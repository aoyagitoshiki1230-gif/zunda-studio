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
SHORT_TITLE_MAX = 22      # ショートはスマホで2行に収まる長さに
TAG_MAX   = 5
__VERSION__ = "2026-09-05a"

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


def _lines(v):
    """文字列でもリストでも受ける。台本によってどちらでも来るため"""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x) for x in v).rstrip()
    return str(v).rstrip()


def build_description(meta, chapters):
    L = []
    L.append(_lines(meta.get("hook")))
    L.append("")
    L.append(_lines(meta.get("body")))
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
    # 台本が「#税」のように#付きで書いてくることがある。二重に付けない
    tags = [str(t).lstrip("#＃").strip() for t in meta.get("hashtags", [])[:TAG_MAX]]
    tags = [t for t in tags if t]
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
    body_len = len(_lines(meta.get("body")).replace("\n", ""))
    if not (200 <= body_len <= 500):
        warn.append(f"本文が{body_len}字です。300字前後が目安です。")
    if warn:
        lines += ["", "## 確認事項", ""] + [f"- {w}" for w in warn]
    lines += ["", "# 概要欄(このまま貼り付け)", "", "```", desc.rstrip(), "```", ""]
    with open(os.path.join(outdir, "title_description.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return checked, warn


# ─────────────────────────────────────────────────────────
# ショート用のメタと、登録につなげる仕掛け
# 実測(2026-09-03)で分かったこと:
#   ・ショートと長編でタイトルが完全に同じだと、検索でも関連でも共食いする。
#     何よりショートを見た人が長編を「見たやつだ」と思ってスキップする
#   ・再生14,452回に対して登録7人(0.05%)。導線が無いのが原因
# ─────────────────────────────────────────────────────────

def _norm(t):
    return "".join(str(t).split()).replace("!", "").replace("！", "") \
                                  .replace("?", "").replace("？", "")


def short_titles(meta, short):
    """ショート用のタイトル候補。長編と同じ文言は落とす"""
    long_t = [_norm(t) for t in meta.get("titles", [])]
    cands  = list(short.get("titles") or [])
    if not cands:
        base = to_digits(short.get("title", "")) or (meta.get("hook_big") or [""])[0]
        base = base.strip()
        if base:
            cands = [base, base + "【1分で】"]
    out = []
    for t in cands:
        if _norm(t) in long_t:
            continue          # 長編と同じタイトルは使わない
        if t not in out:
            out.append(t)
    return out


def build_short_meta(meta, short, long_title, outdir):
    """ショートの説明欄と、長編の固定コメントを書き出す"""
    cands = short_titles(meta, short)
    L = ["# ショート(縦動画)用", ""]
    if cands:
        L.append("## タイトル候補 ── 長編と必ず変える")
        for t in cands:
            n = len(t)
            note = "OK" if n <= SHORT_TITLE_MAX else f"{n - SHORT_TITLE_MAX}字オーバー"
            L.append(f"- [{n:2d}字 / {note}] {t}")
    else:
        L.append("## ⚠ ショートのタイトル候補が作れませんでした")
        L.append("台本の short.titles に、長編とは別の切り口のタイトルを2案入れてください。")
    sdesc = (f"くわしくは長編で解説しています。\n"
             f"▶ {long_title}\n"
             f"（チャンネルの動画一覧から見られます）\n\n"
             f"#Shorts #" + " #".join(meta.get("hashtags", [])[:3]))
    L += ["", "## 説明欄(このまま貼り付け)", "", "```", sdesc, "```", ""]
    L += ["## ショートの固定コメント", "", "```",
          "この話の続き（なぜそうなるのか）は長編にまとめました。\n"
          "気になった人はチャンネルの動画一覧からどうぞなのだ。", "```", ""]

    head = (_lines(meta.get("hook")).strip().splitlines() or [""])[0]
    L += ["# 長編の固定コメント(投稿したらすぐ固定する)", "", "```",
          (head + "\n\n" if head else "") +
          "ずんだもんと四国めたんの会話でまとめたのだ。\n"
          "「知らないと損する生活のお金と制度」を毎日出しているので、\n"
          "役に立ったらチャンネル登録してもらえるとうれしいのだ。\n\n"
          "気になることや、次に取り上げてほしいテーマがあれば\n"
          "コメントで教えてほしいのだ。",
          "```", ""]
    L += ["# 終了画面(YouTube Studioで設定)", "",
          "- 最後の11秒はエンディング映像なので、そこに終了画面を置く",
          "- 左に「チャンネル登録」、右に「最新の動画」の2つだけにする", ""]
    with open(os.path.join(outdir, "short_meta.md"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(L))
    return cands
