#!/usr/bin/env python3
"""タイトル候補と概要欄の生成。

参考にした定石:
  タイトルは30字以内・検索語は前半へ
  概要欄は冒頭1〜2行にキーワード / 本文300字前後
  チャプターは 0:00 から始める / ハッシュタグは3〜5個
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from video import to_digits

TITLE_MAX = 30
TAG_MAX   = 5

DEFAULT_NOTICE = (
    "動画の内容は制作時点で確認できた情報にもとづいています。制度や条件、価格などは\n"
    "変わることがあります。実際に手続きや判断をされる際は、公式の案内や最新の情報を\n"
    "ご自身でご確認ください。"
)
# お金や投資を扱う回は、台本の meta.notice に踏み込んだ注意文を書く

# VOICEVOX のクレジットは利用規約上の必須項目なので、必ず入れる
REQUIRED_CREDIT = "音声合成:VOICEVOX:ずんだもん"


def mmss(sec):
    return f"{int(sec)//60}:{int(sec)%60:02d}"


def check_titles(titles):
    out = []
    for t in titles:
        n = len(t)
        note = "OK" if n <= TITLE_MAX else f"{n - TITLE_MAX}字オーバー"
        out.append((t, n, note))
    return out


def build_description(meta, chapters):
    L = []
    L.append(meta["hook"].rstrip())
    L.append("")
    L.append(meta["body"].rstrip())
    L.append("")
    L.append("━━━━━━━━━━━━━━━━")
    L.append("◆ 目次")
    L.append("━━━━━━━━━━━━━━━━")
    for title, start, _ in chapters:
        L.append(f"{mmss(start)} {to_digits(title)}")
    if meta.get("terms"):
        L += ["", "━━━━━━━━━━━━━━━━", "◆ 動画内で出てくる用語", "━━━━━━━━━━━━━━━━"]
        for word, desc in meta["terms"]:
            L.append(f"・{word} … {desc}")
    L += ["", "━━━━━━━━━━━━━━━━", "◆ ご注意", "━━━━━━━━━━━━━━━━",
          meta.get("notice", DEFAULT_NOTICE).rstrip()]
    credits = list(meta.get("credits", []))
    if not any("VOICEVOX" in c for c in credits):
        credits.insert(0, REQUIRED_CREDIT)
    L += ["", "━━━━━━━━━━━━━━━━", "◆ クレジット", "━━━━━━━━━━━━━━━━"] + credits
    tags = meta.get("hashtags", [])[:TAG_MAX]
    if tags:
        L += ["", " ".join("#" + t for t in tags)]
    return "\n".join(L) + "\n"


def build(meta, chapters, outdir):
    os.makedirs(outdir, exist_ok=True)
    desc = build_description(meta, chapters)
    checked = check_titles(meta.get("titles", []))

    with open(os.path.join(outdir, "description.txt"), "w", encoding="utf-8") as fp:
        fp.write(desc)

    lines = ["# タイトル候補", ""]
    for t, n, note in checked:
        lines.append(f"- [{n:2d}字 / {note}] {t}")
    warn = []
    if len(meta.get("hashtags", [])) > TAG_MAX:
        warn.append(f"ハッシュタグが{len(meta['hashtags'])}個あります。3〜5個に絞ってください。")
    body_len = len(meta["body"].replace("\n", ""))
    if not (200 <= body_len <= 500):
        warn.append(f"本文が{body_len}字です。300字前後が目安です。")
    if warn:
        lines += ["", "## 確認事項", ""] + [f"- {w}" for w in warn]
    lines += ["", "# 概要欄(このまま貼り付け)", "", "```", desc.rstrip(), "```", ""]
    with open(os.path.join(outdir, "title_description.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return checked, warn
