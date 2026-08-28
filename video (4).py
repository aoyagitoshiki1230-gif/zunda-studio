#!/usr/bin/env python3
"""
ずんだもん解説動画パイプライン v2

改良点:
  - ずんだもんの立ち絵を合成(表情はシーンごとに指定)
  - 母音に合わせた口パク(VOICEVOXのモーラ長を使用)
  - ASS字幕による本格テロップ(フレーズ単位・キーワード強調・ポップイン)
"""
import json, os, re, subprocess, sys, urllib.parse, urllib.request, wave

VOICEVOX = "http://127.0.0.1:50021"
SPEAKER  = 3
W, H     = 1920, 1080
FONT_R   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_B   = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

INK       = (32, 44, 27)
INK_SOFT  = (99, 116, 92)

# 章のまとまりごとの背景パレット
# (開始シーン, 終了シーン, 上の色, 下の色, アクセント, 光の玉の色)
GROUPS = [
    (1,  2,  (245,249,234), (216,233,201), ( 98,158, 58), [(168,206,128),(238,226,158)]),
    (3,  5,  (238,247,234), (205,230,200), ( 74,152, 78), [(150,205,150),(190,222,170)]),
    (6,  9,  (233,245,243), (196,224,219), ( 42,138,130), [(140,204,196),(176,218,200)]),
    (10, 12, (235,242,250), (200,219,240), ( 56,120,180), [(150,186,226),(180,206,232)]),
    (13, 15, (251,243,230), (240,222,196), (192,126, 40), [(232,196,140),(226,214,160)]),
    (16, 17, (239,248,234), (208,231,199), ( 74,152, 78), [(154,206,152),(196,226,172)]),
]

def group_of(idx):
    for g in GROUPS:
        if g[0] <= idx <= g[1]:
            return g
    return GROUPS[-1]

_BG_CACHE = {}

def make_background(g):
    """やわらかいグラデーション + 光の玉 + うっすら斜めストライプ"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    key = g[0]
    if key in _BG_CACHE:
        return _BG_CACHE[key].copy()
    _, _, c1, c2, acc, blobs = g

    ys = np.linspace(0, 1, H)[:, None]
    xs = np.linspace(0, 1, W)[None, :]
    t = (ys * 0.78 + xs * 0.22)
    a, b = np.array(c1, float), np.array(c2, float)
    img = Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8)).convert("RGBA")

    # 光の玉
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    spots = [(1610, 470, 470, blobs[0], 96), (250, 900, 380, blobs[1], 74),
             (700, 120, 300, blobs[0], 56), (1200, 980, 300, blobs[1], 66)]
    for cx, cy, r, col, op in spots:
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=col + (op,))
    img = Image.alpha_composite(img, lay.filter(ImageFilter.GaussianBlur(95)))

    # 斜めストライプ(ごく薄く)
    st = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(st)
    for i in range(-10, 36):
        d.line([(i*92, 0), (i*92+270, H)], fill=(255, 255, 255, 46), width=30)
    img = Image.alpha_composite(img, st.filter(ImageFilter.GaussianBlur(3)))

    # 立ち絵まわり: 白いハロー + 足元の影
    hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(hl)
    d.ellipse([1360, 130, 1900, 880], fill=(255, 255, 255, 96))
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(80)))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.ellipse([1520, 848, 1800, 886], fill=(70, 92, 62, 56))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(26)))

    # 本文側をわずかに明るくして可読性を上げる
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(wash)
    d.ellipse([-360, -220, 1240, 1000], fill=(255, 255, 255, 76))
    img = Image.alpha_composite(img, wash.filter(ImageFilter.GaussianBlur(120)))

    out = img.convert("RGB")
    _BG_CACHE[key] = out
    return out.copy()


CHAR_W, CHAR_H = 425, 800
CHAR_X, CHAR_Y = 1430, 84

# ============ 立ち絵の事前レンダリング ============
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "assets", "frames")

def render_character_frames(cache=FRAMES):
    """提供された立ち絵素材(表情ごと・揺れ2枚)を読み込む"""
    import glob
    made = {}
    for p in glob.glob(f"{cache}/*_*.png"):
        expr, tag = os.path.basename(p)[:-4].rsplit("_", 1)
        made[(expr, tag)] = p
    if not made:
        raise SystemExit(f"立ち絵が見つからない: {cache}")
    return made


# ============ 背景スライド ============
import re

DIG = {"〇":0,"零":0,"一":1,"二":2,"三":3,"四":4,"五":5,
       "六":6,"七":7,"八":8,"九":9}
NUMCH = "〇零一二三四五六七八九十百千万億兆"

# 数ではない語(ここに入る語はそのまま残す)
KEEP = ["一般","一番","一致","一部","一連","一方","一時","一緒","一気","一応",
        "一切","一定","一律","一括","一覧","一環","一種","一見","一体","一斉",
        "一員","一因","一助","一新","一任","一挙","一様","一目","一言","一歩",
        "万が一","第一","唯一","同一","統一","単一","均一","万一","一日中","一人ひとり",
        "二次","二重","二度と","三角","三菱","四角","四国","四季","五輪",
        "十分","十字","百科","百貨","千葉","万全","万能","億劫","何十","数十",
        "数百","数千","十数","一石二鳥","二者択一","三脚","五感","七夕"]

# この語が続くときは数として扱う
UNIT = ("円|株|割|年|月|日間|日|時間|時|分間|分|秒|個|人|回|倍|歳|才|件|種類|"
        "つ|番目|番|段階|位|点|階|冊|枚|台|本|杯|度|%|パーセント|ヶ月|か月|カ月|"
        "箇月|週間|年間|ポイント|営業日|万円|億円|文字|問|択|色|面|部屋|品|袋|"
        "gram|キロ|メートル|センチ|リットル")


def _small(s):
    """千百十までを数値にする"""
    total = cur = 0
    for ch in s:
        if ch in DIG:
            cur = DIG[ch]
        elif ch == "十":
            total += (cur or 1) * 10; cur = 0
        elif ch == "百":
            total += (cur or 1) * 100; cur = 0
        elif ch == "千":
            total += (cur or 1) * 1000; cur = 0
    return total + cur


def _convert(run):
    """漢数字の並びを算用数字の文字列にする。万・億はそのまま残す"""
    if "〇" in run and not any(c in run for c in "十百千万億兆"):
        return "".join(str(DIG[c]) for c in run)      # 一〇三 のような位取り
    out, rest = "", run
    for unit in ("億", "万"):
        if unit in rest:
            head, rest = rest.split(unit, 1)
            out += f"{_small(head) if head else 1}{unit}"
    tail = _small(rest) if rest else 0
    if tail or not out:
        out += str(tail)
    return out


def to_digits(text):
    # 1) 数として扱わない語を退避
    holes = {}
    for i, w in enumerate(KEEP):
        if w in text:
            key = f"\x00{i}\x00"
            holes[key] = w
            text = text.replace(w, key)

    # 2) 漢数字の並びを見つけて変換
    DIGITS = "0123456789０１２３４５６７８９"

    def repl(m):
        run, start, end = m.group(0), m.start(), m.end()
        # すでに算用数字で書かれている場合の「万」「億」は単位なので触らない
        # (これを変換すると 193万円 → 1931万円 のように壊れる)
        if start > 0 and text[start - 1] in DIGITS:
            return run
        after = text[end:end + 6]
        before = text[max(0, start - 2):start]
        is_num = (re.match(UNIT, after) or len(run) >= 2
                  or before.endswith(("その", "第", "計", "約")))
        return _convert(run) if is_num else run

    text = re.sub(f"[{NUMCH}]+", repl, text)

    # 3) 退避した語を戻す
    for key, w in holes.items():
        text = text.replace(key, w)
    return text


def wrap(text, font, maxw):
    lines, cur = [], ""
    for ch in text:
        if font.getlength(cur + ch) > maxw and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur: lines.append(cur)
    return lines

def chart_metrics(spec):
    n = len(spec.get("items", []))
    if not n:
        return 0, 0, 0
    bh, gap = (52, 26) if n <= 3 else (44, 20)
    return n * (bh + gap), bh, gap


def draw_chart(d, spec, x, y, w, acc):
    """棒グラフを描く。数字の比較はこれがあると理解が段違いに速い"""
    from PIL import ImageFont
    items = spec.get("items", [])
    if not items:
        return y
    unit  = spec.get("unit", "")
    f_lab = ImageFont.truetype(FONT_R, 34)
    f_val = ImageFont.truetype(FONT_B, 40)
    vmax  = max(abs(v) for _, v in items) or 1
    labw  = max(f_lab.getlength(to_digits(str(l))) for l, _ in items) + 24
    barx  = x + labw
    barw  = w - labw - 210
    _, bh, gap = chart_metrics(spec)

    for i, (label, val) in enumerate(items):
        cy = y + i * (bh + gap)
        d.text((x, cy + 8), to_digits(str(label)), font=f_lab, fill=INK_SOFT)
        d.rounded_rectangle([barx, cy, barx + barw, cy + bh], radius=8,
                            fill=(255, 255, 255, 150))
        L = max(10, int(barw * abs(val) / vmax))
        # 最後の項目だけ濃くして「結論」を示す
        col = acc if i == len(items) - 1 else tuple(int(c * 0.45 + 255 * 0.55) for c in acc)
        d.rounded_rectangle([barx, cy, barx + L, cy + bh], radius=8, fill=col)
        txt = f"{val:,}{unit}" if isinstance(val, (int, float)) else f"{val}{unit}"
        d.text((barx + L + 18, cy + 4), txt, font=f_val, fill=INK)
    return y + len(items) * (bh + gap)


def draw_slide(scene, idx, total, chapter, path, shown=None, progress=0.0):
    """shown: 表示する箇条書きの数(Noneなら全部) / progress: 全体の進み具合 0〜1"""
    from PIL import Image, ImageDraw, ImageFont
    g   = group_of(idx)
    acc = g[4]
    img = make_background(g)
    d   = ImageDraw.Draw(img, "RGBA")

    f_ch   = ImageFont.truetype(FONT_R, 28)
    f_num  = ImageFont.truetype(FONT_B, 116)
    f_ttl  = ImageFont.truetype(FONT_B, 72)
    f_body = ImageFont.truetype(FONT_R, 42)

    # 上部の帯
    d.rectangle([0, 0, W, 9], fill=acc)
    d.rectangle([0, 9, W, 80], fill=(255, 255, 255, 150))
    d.text((90, 28), chapter, font=f_ch, fill=INK_SOFT)
    d.text((W - 90, 28), f"{idx} / {total}", font=f_ch, fill=acc, anchor="ra")

    # 章番号(背景の飾り)
    d.text((84, 122), f"{idx:02d}", font=f_num, fill=acc + (58,))

    # タイトル
    y = 152
    for line in wrap(to_digits(scene["title"]), f_ttl, 1120):
        d.text((256, y), line, font=f_ttl, fill=INK); y += 92
    y += 18
    d.rectangle([259, y, 369, y + 5], fill=acc); y += 52

    # 箇条書き(ナレーションの進みに合わせて1つずつ増える)
    bullets = [to_digits(b) for b in scene.get("bullets", [])]
    n = len(bullets) if shown is None else max(0, min(shown, len(bullets)))
    has_chart = bool(scene.get("chart"))
    ch_h = chart_metrics(scene["chart"])[0] if has_chart else 0
    BOTTOM = 840 - (ch_h + 40 if ch_h else 0)   # 使ってよい下端
    chart_y = BOTTOM + 28

    # 余白が空きすぎないよう、収まる範囲でいちばん大きい文字を選ぶ。
    # 途中で折り返すと読みにくいので、1行に収まる大きさを優先する。
    def try_sizes(sizes, maxlines):
        for sz in sizes:
            f = ImageFont.truetype(FONT_R, sz)
            lh, pad = int(sz * 1.38), int(sz * 0.55)
            rows = [wrap(b, f, 990) for b in bullets]
            hh = sum(len(r) * lh + pad for r in rows)
            ok = all(len(r) <= maxlines and (len(r) < 2 or len(r[-1]) >= 5)
                     for r in rows)
            if hh <= BOTTOM - y and ok:
                return (rows, lh, pad), sz, f
        return None

    got = (try_sizes((58, 54, 50, 46, 42), 1)
           or try_sizes((50, 46, 42, 38), 2)
           or try_sizes((38, 34), 3))
    if got:
        layout, size, f_body = got
    else:
        size, f_body = 34, ImageFont.truetype(FONT_R, 34)
        layout = ([wrap(b, f_body, 990) for b in bullets], 48, 18)

    rows, lh, pad = layout
    block = sum(len(r) * lh + pad for r in rows)
    if not has_chart:                      # 図解が無いときは縦方向に中央寄せ
        y += max(0, min(120, (BOTTOM - y - block) // 2))

    for k, b in enumerate(bullets[:n]):
        fresh = (k == n - 1)               # 出たばかりの行は少し目立たせる
        ms = max(14, int(size * 0.32))
        my = y + int(lh * 0.32)
        d.rounded_rectangle([259, my, 259 + ms, my + ms], radius=4,
                            fill=acc if fresh else acc + (150,))
        for i, line in enumerate(rows[k]):
            d.text((310, y), line, font=f_body,
                   fill=INK if (i == 0 or fresh) else INK_SOFT)
            y += lh
        y += pad

    # 図解(あれば箇条書きの下に)
    if has_chart and n >= len(bullets):
        draw_chart(d, scene["chart"], 268, chart_y, 980, acc)

    # テロップ帯
    d.rectangle([0, 872, W, H], fill=(252, 253, 248, 232))
    d.rectangle([0, 872, W, 876], fill=acc)

    # 進捗バー(いまどのあたりかが分かる)
    d.rectangle([0, H - 7, W, H], fill=(0, 0, 0, 26))
    d.rectangle([0, H - 7, int(W * max(0.0, min(1.0, progress))), H], fill=acc)
    img.save(path)


# ============ 音声合成 + モーラ取得 ============
CACHE = os.path.join(ROOT, ".cache", "voice")

def synth(text, path):
    """合成結果をテキスト単位でキャッシュし、再実行時は使い回す"""
    import hashlib, shutil
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(f"{SPEAKER}:{text}".encode()).hexdigest()
    cw, cq = f"{CACHE}/{key}.wav", f"{CACHE}/{key}.json"
    if os.path.exists(cw) and os.path.exists(cq):
        shutil.copyfile(cw, path)
        with wave.open(path) as w:
            return json.load(open(cq, encoding="utf-8")), w.getnframes() / w.getframerate()
    q, dur = _synth_remote(text, path)
    shutil.copyfile(path, cw)
    json.dump(q, open(cq, "w", encoding="utf-8"), ensure_ascii=False)
    return q, dur


def _synth_remote(text, path):
    q = json.loads(urllib.request.urlopen(
        VOICEVOX + "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": SPEAKER}),
        data=b"", timeout=90).read())
    wav = urllib.request.urlopen(urllib.request.Request(
        VOICEVOX + f"/synthesis?speaker={SPEAKER}",
        data=json.dumps(q).encode(), headers={"Content-Type": "application/json"}),
        timeout=300).read()
    open(path, "wb").write(wav)
    with wave.open(path) as w:
        dur = w.getnframes() / w.getframerate()
    return q, dur

OPEN_V  = {"a", "o", "A", "O"}
HALF_V  = {"i", "u", "e", "I", "U", "E"}

VOWEL = {"a":"a","A":"a","i":"i","I":"i","u":"u","U":"u",
         "e":"e","E":"e","o":"o","O":"o"}

def mouth_track(q):
    """モーラの母音に応じた口の形と長さの列。子音は続く母音と同じ形にして滑らかにする"""
    mouth = [("x", q.get("prePhonemeLength", 0.1))]
    for ap in q["accent_phrases"]:
        for mo in ap["moras"]:
            c = mo.get("consonant_length") or 0.0
            shape = VOWEL.get(mo["vowel"], "x")
            mouth.append((shape, c + mo["vowel_length"]))
        pm = ap.get("pause_mora")
        if pm:
            mouth.append(("x", (pm.get("consonant_length") or 0) + pm["vowel_length"]))
    mouth.append(("x", q.get("postPhonemeLength", 0.1)))
    return mouth


def mora_times(q):
    """モーラごとの終了時刻の列"""
    times, t = [], q.get("prePhonemeLength", 0.1)
    for ap in q["accent_phrases"]:
        for mo in ap["moras"]:
            t += (mo.get("consonant_length") or 0) + mo["vowel_length"]
            times.append(t)
        pm = ap.get("pause_mora")
        if pm:
            t += (pm.get("consonant_length") or 0) + pm["vowel_length"]
            if times: times[-1] = t
    return times


SMALL = "ャュョァィゥェォ"

def kana_moras(s):
    import pyopenjtalk
    k = pyopenjtalk.g2p(s, kana=True)
    return max(1, len([c for c in k if c not in SMALL and c not in "、。！？"]))


BREAK_AFTER = set("はがをにでともやのへらてだ、")

def _find_break(s, maxlen):
    """maxlen付近で助詞などの自然な切れ目を探す(形態素解析が使えないときの保険)"""
    lo = max(5, int(maxlen * 0.5))
    for i in range(min(maxlen, len(s) - 1), lo, -1):
        if s[i - 1] in BREAK_AFTER:
            return i
    return maxlen


def _chunks_fallback(text, maxlen):
    parts = [p for p in re.split(r"(?<=[、。！？])", text) if p.strip()]
    chunks, cur = [], ""
    for p in parts:
        while len(p) > maxlen:
            if cur: chunks.append(cur); cur = ""
            b = _find_break(p, maxlen)
            chunks.append(p[:b]); p = p[b:]
        if len(cur) + len(p) <= maxlen:
            cur += p
        else:
            if cur: chunks.append(cur)
            cur = p
    if cur: chunks.append(cur)
    chunks = [c for c in (x.strip("、。！？ ") for x in chunks) if c]
    merged = []
    for c in chunks:
        if merged and len(c) <= 4 and len(merged[-1]) + len(c) <= maxlen + 6:
            merged[-1] += c
        else:
            merged.append(c)
    return [(c, kana_moras(c)) for c in merged]


def morph_spans(text):
    """原文を形態素の区切りに分け (開始, 終了, モーラ数, 品詞) を返す。
    OpenJTalkが表記を正規化して長さが変わる場合(算用数字など)は None"""
    import pyopenjtalk
    try:
        toks = pyopenjtalk.run_frontend(text)
    except Exception:
        return None
    if not toks or sum(len(t.get("string", "")) for t in toks) != len(text):
        return None
    spans, p = [], 0
    for t in toks:
        n = len(t.get("string", ""))
        spans.append((p, p + n, int(t.get("mora_size", 0) or 0), t.get("pos", "")))
        p += n
    return spans


GLUE = ("助詞", "助動詞", "記号")   # 直前の語にくっつけたい品詞

def split_chunks(text, maxlen):
    """テロップ1枚ぶんに刻む。形態素の途中では絶対に切らない。
    返り値は [(表示する文字列, モーラ数)]"""
    spans = morph_spans(text)
    if spans is None:
        return _chunks_fallback(text, maxlen)

    chunks, st, mo = [], 0, 0
    for a, b, m, pos in spans:
        w = text[a:b]
        if st < a:
            over = (b - st) > maxlen
            hard = (b - st) > maxlen + 4
            if hard or (over and pos not in GLUE):
                chunks.append((text[st:a], mo)); st, mo = a, 0
        mo += m
        if w in "、。！？" and (b - st) >= max(7, maxlen * 0.35):
            chunks.append((text[st:b], mo)); st, mo = b, 0
    if st < len(text):
        chunks.append((text[st:], mo))

    out = []
    for c, m in chunks:
        c2 = c.strip("、。！？ 　")
        if not c2:
            if out: out[-1] = (out[-1][0], out[-1][1] + m)
            continue
        out.append((c2, max(1, m)))

    merged = []
    for c, m in out:
        if merged and len(c) <= 4 and len(merged[-1][0]) + len(c) <= maxlen + 6:
            merged[-1] = (merged[-1][0] + c, merged[-1][1] + m)
        else:
            merged.append((c, m))
    return merged


def align_telops(q, sentence, maxlen=20):
    """原文のチャンクに、実測のモーラ時刻を割り当てる"""
    chunks = split_chunks(sentence, maxlen)
    times  = mora_times(q)
    if not chunks or not times: return []
    counts = [max(1, m) for _, m in chunks]
    tot, N = sum(counts), len(times)
    out, acc, st = [], 0, q.get("prePhonemeLength", 0.1)
    for (c, _), n in zip(chunks, counts):
        acc += n
        i = min(N - 1, max(0, round(acc / tot * N) - 1))
        en = times[i]
        if en <= st: en = st + 0.25
        out.append((st, en, c))
        st = en
    return out


# ============ ASSテロップ ============
def ass_time(s):
    h, r = divmod(s, 3600); m, sec = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"

ASS_HEAD = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Telop,Noto Sans CJK JP,72,&H001B2C14,&H000000FF,&H00FAFCF6,&H00FFFFFF,-1,0,0,0,100,100,1,0,1,8,0,2,90,640,86,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

def esc(t):
    return t.replace("\\", "").replace("{", "").replace("}", "")

def build_telops(entries, keywords, path):
    """entries: (start, end, text) / keywords: 強調する語のリスト"""
    kws = sorted({to_digits(k) for k in keywords}, key=len, reverse=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEAD)
        for st, en, tx in entries:
            body = to_digits(esc(tx))
            for k in kws:
                if k and k in body:
                    body = body.replace(k, "\x01" + k + "\x02")
            body = (body.replace("\x01", r"{\c&H2A7A1E&\b1}")
                        .replace("\x02", r"{\c&H1B2C14&\b1}"))
            anim = r"{\fad(70,60)\fscx92\fscy92\t(0,110,\fscx100\fscy100)}"
            f.write(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Telop,,0,0,0,,{anim}{body}\n")

# ============ 表情の自動切り替え ============
ASK  = ("？", "?", "だろうか", "のかな", "どうなる", "なぜ", "どうして", "いくら")
BANG = ("！", "!", "注意", "危険", "損", "落とし穴", "びっくり", "大事", "気をつけ", "禁止")
GOOD = ("お得", "うれしい", "便利", "安心", "おすすめ", "うまく", "できる", "覚えて")

def sentence_expr(default, sent, available):
    """文の内容から表情を選ぶ。素材に無い表情は既定に戻す"""
    pick = default
    if any(k in sent for k in BANG):
        pick = "surprise"
    elif any(k in sent for k in ASK):
        pick = "think"
    elif any(k in sent for k in GOOD):
        pick = "happy"
    return pick if (pick, "a") in available else default


# ============ BGM・効果音 ============
BGM_DIR  = os.path.join(ROOT, "assets", "bgm")
BGM_EXT  = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac")
BGM_RMS  = 0.10          # 曲ごとの音量差をここでそろえる


# 曲を探す場所。リポジトリ直下に置かれてもそのまま拾えるようにしてある
BGM_DIRS = [BGM_DIR,
            os.path.join(ROOT, "assets"),
            ROOT,
            os.path.dirname(ROOT)]


def bgm_tracks(opening=False):
    """使える曲を集める。opening=True なら OP用(名前に opening を含むもの)だけ"""
    import glob
    out, seen = [], set()
    for d in BGM_DIRS:
        for p in sorted(glob.glob(os.path.join(d, "*"))):
            if os.path.isdir(p) or os.path.splitext(p)[1].lower() not in BGM_EXT:
                continue
            base = os.path.basename(p).lower()
            if not base.startswith("bgm"):
                continue
            # 「bgm_normal (1).mp3」のような重複を1つにまとめる
            key = re.sub(r"[\s(]\d+\)?", "", os.path.splitext(base)[0]).strip()
            if key in seen:
                continue
            if ("opening" in base) == bool(opening):
                seen.add(key)
                out.append(p)
    return out


def load_bgm(src, total, sr, tmp):
    """曲を必要な長さまでループして numpy 配列で返す。音量はRMSでそろえる"""
    import numpy as np
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", src,
                    "-t", f"{total:.3f}", "-ac", "1", "-ar", str(sr), tmp], check=True)
    with wave.open(tmp) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    try:
        os.remove(tmp)
    except OSError:
        pass
    rms = float(np.sqrt((a ** 2).mean()))
    if rms > 1e-6:
        a = a * (BGM_RMS / rms)
    return a


def make_audio_bed(total, marks, path, sr=24000):
    """やわらかいBGM(コード進行)とシーン切り替えの効果音を1本のwavにする。
    著作権の問題が出ないよう、音そのものをその場で合成している。"""
    import numpy as np, random
    n = int(total * sr) + sr
    out = np.zeros(n, dtype=np.float32)

    # 用意された曲があればそれを使う(毎回ちがう曲になるよう1本選ぶ)
    picked = bgm_tracks()
    if picked:
        src = random.choice(picked)
        try:
            a = load_bgm(src, total + 1.0, sr, path + ".src.wav")
            out[:min(n, len(a))] += a[:n]
            print(f"  BGM: {os.path.basename(src)}", flush=True)
            return _finish_bed(out, marks, path, sr, normalize=False)
        except Exception as e:
            print(f"  曲を読めなかったので合成BGMにするのだ: {type(e).__name__}: {e}", flush=True)
            out[:] = 0.0

    print("  BGM: 用意された曲が見つからないので合成BGMを使うのだ", flush=True)
    BAR = 3.2                       # コード1つの長さ(秒)
    PROG_A = [(0,4,7,12), (7,11,14,19), (9,12,16,21), (5,9,12,17)]   # C G Am F
    PROG_B = [(5,9,12,17), (7,11,14,19), (0,4,7,12), (9,12,16,21)]   # F G C Am
    hz = lambda semi: 261.63 * 2.0 ** (semi / 12.0)

    # 12小節ごとに転調して、長い動画でも飽きにくくする
    KEYS = [0, 2, -3, 5, -5, 3]

    nbar = int(total / BAR) + 2
    for bar in range(nbar):
        prog = PROG_A if (bar // 4) % 2 == 0 else PROG_B
        key = KEYS[(bar // 12) % len(KEYS)]
        chord = tuple(c + key for c in prog[bar % 4])
        s0 = int(bar * BAR * sr)
        if s0 >= n:
            break
        s1 = min(n, s0 + int((BAR + 0.7) * sr))
        lt = np.arange(s1 - s0) / sr

        # パッド(ゆっくり立ち上がる和音)
        env = np.minimum(lt / 0.9, 1.0) * np.exp(-lt / (BAR * 0.95))
        pad = np.zeros(s1 - s0, dtype=np.float32)
        for k, semi in enumerate(chord):
            f = hz(semi - 12)
            pad += (np.sin(2*np.pi*f*lt) * 0.55 + np.sin(2*np.pi*f*2*lt) * 0.15) * (0.88 ** k)
        out[s0:s1] += pad * env * 0.16

        # アルペジオ(4小節に3回だけ鳴らして単調さを避ける)
        if bar % 4 != 3:
            for k, semi in enumerate(chord):
                a0 = s0 + int((k * BAR / 4.0) * sr)
                if a0 >= n:
                    break
                a1 = min(n, a0 + int(0.9 * sr))
                at = np.arange(a1 - a0) / sr
                f = hz(semi + 12)
                out[a0:a1] += (np.sin(2*np.pi*f*at) + 0.28*np.sin(2*np.pi*f*2*at)) \
                              * np.exp(-at / 0.20) * 0.05

    return _finish_bed(out, marks, path, sr, normalize=True)


def _finish_bed(out, marks, path, sr, normalize):
    """シーン切り替えのチャイムを足し、前後をフェードして書き出す"""
    import numpy as np
    n = len(out)
    for m in marks:
        s0 = int(m * sr)
        if s0 <= sr or s0 >= n:
            continue
        s1 = min(n, s0 + int(0.5 * sr))
        lt = np.arange(s1 - s0) / sr
        e = np.exp(-lt / 0.11)
        out[s0:s1] += (np.sin(2*np.pi*1174.66*lt) * 0.6
                       + np.sin(2*np.pi*1567.98*lt) * 0.4) * e * 0.20

    fi, fo = int(2.5 * sr), int(4.0 * sr)
    out[:fi] *= np.linspace(0, 1, fi)
    if n > fo:
        out[-fo:] *= np.linspace(1, 0, fo)

    peak = float(np.max(np.abs(out))) or 1.0
    if normalize:
        out = out / peak * 0.85
    elif peak > 0.95:
        out = out / peak * 0.95
    pcm = (out * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def wav_duration(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


# ============ 本体 ============
def main(script_path, out_path, workdir=None):
    workdir = workdir or os.path.join(ROOT, ".cache", "work")
    os.makedirs(workdir, exist_ok=True)
    script = json.load(open(script_path, encoding="utf-8"))
    scenes = script["scenes"]
    chars  = render_character_frames()

    TELOP_MAX = 22      # テロップ1枚の最大文字数
    GAP       = 0.34    # 文と文のあいだ

    clock = 0.0
    telops, mouth_seq, slide_seq, audio_files, chapters = [], [], [], [], []
    all_kw = []

    # まず全シーンの尺を出す(進捗バーに全体の長さが要るため)
    plan = []            # [(scene, [(sent, wav, q, dur), ...], scene_dur)]
    for i, sc in enumerate(scenes, 1):
        sents = [x for x in re.split(r"(?<=[。！？])", sc["narration"]) if x.strip()]
        items, scene_dur = [], 0.0
        for j, sent in enumerate(sents):
            wav = f"{workdir}/a{i:02d}_{j:02d}.wav"
            q, dur = synth(sent, wav)
            items.append((sent, wav, q, dur))
            scene_dur += dur + GAP
        plan.append((sc, items, scene_dur))
        print(f"  {i:02d}. {scene_dur:6.1f}秒  {sc['title']}", flush=True)
    total_dur = sum(p[2] for p in plan) or 1.0

    for i, (sc, items, scene_dur) in enumerate(plan, 1):
        expr = sc.get("expression", "normal")
        all_kw += sc.get("keywords", [])
        nb = len(sc.get("bullets", []))
        sent_dur = 0.0

        for j, (sent, wav, q, dur) in enumerate(items):
            audio_files.append(wav)
            e2 = sentence_expr(expr, sent, chars)
            for shape, ln in mouth_track(q):
                if ln > 0.01:
                    mouth_seq.append((chars[(e2, shape)], ln))

            base = clock + sent_dur
            for st, en, tx in align_telops(q, sent, TELOP_MAX):
                telops.append((base + st, base + en, tx))

            # 文が進むごとに箇条書きを1つずつ出す
            shown = nb if len(items) <= 1 else min(nb, j)
            png = f"{workdir}/s{i:02d}_{j:02d}.png"
            draw_slide(sc, i, len(scenes), script.get("chapter", ""), png,
                       shown=shown, progress=(clock + sent_dur) / total_dur)
            slide_seq.append((png, dur + GAP))
            sent_dur += dur + GAP

        chapters.append((sc["title"], clock, scene_dur))
        clock += scene_dur

    print(f"\n合計 {clock/60:.1f}分 / テロップ {len(telops)}枚 / スライド {len(slide_seq)}枚 / 立ち絵 {len(mouth_seq)}コマ", flush=True)

    # --- 音声連結 ---
    sil = f"{workdir}/sil.wav"
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","anullsrc=r=24000:cl=mono",
                    "-t",str(GAP),sil],check=True)
    with open(f"{workdir}/a.txt","w") as f:
        for w in audio_files: f.write(f"file '{w}'\nfile '{sil}'\n")
    subprocess.run(["ffmpeg","-y","-v","error","-f","concat","-safe","0",
                    "-i",f"{workdir}/a.txt",f"{workdir}/audio.wav"],check=True)

    # --- スライド列 ---
    with open(f"{workdir}/v.txt","w") as f:
        for p,d in slide_seq: f.write(f"file '{p}'\nduration {d:.3f}\n")
        f.write(f"file '{slide_seq[-1][0]}'\n")

    # --- 口パク列 ---
    with open(f"{workdir}/c.txt","w") as f:
        for p,d in mouth_seq: f.write(f"file '{p}'\nduration {max(d,0.02):.3f}\n")
        f.write(f"file '{mouth_seq[-1][0]}'\n")

    build_telops(telops, all_kw, f"{workdir}/telop.ass")

    # --- BGMと効果音の下敷き ---
    bed = None
    if script.get("bgm", True):
        try:
            bed = make_audio_bed(wav_duration(f"{workdir}/audio.wav"),
                                 [c[1] for c in chapters], f"{workdir}/bed.wav")
            print("  BGMを用意したのだ", flush=True)
        except Exception as e:
            bed = None
            print(f"  BGMなしで続行: {type(e).__name__}: {e}", flush=True)

    vfilter = (f"[0:v]scale={W}:{H},fps=30[bg];"
               f"[1:v]scale={CHAR_W}:{CHAR_H},fps=30[ch];"
               f"[bg][ch]overlay=x='{CHAR_X}+4*sin(2*PI*t/5.1)'"
               f":y='{CHAR_Y}+2*sin(2*PI*t/3.6)':eval=frame:shortest=0[v];"
               f"[v]ass={workdir}/telop.ass,format=yuv420p[vo]")

    # YouTubeの基準(-14 LUFS)に合わせる。これをしないと他チャンネルより音が小さい
    MONO = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
    NORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=24000"

    # ナレーションが鳴っているあいだBGMを自動で下げる(サイドチェイン)
    AF_DUCK = (f"[2:a]{MONO},asplit=2[na][sc];"
               f"[3:a]{MONO},volume=0.15[bd];"
               f"[bd][sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350[bdd];"
               f"[na][bdd]amix=inputs=2:duration=first:normalize=0,{NORM}[ao]")
    AF_FLAT = (f"[2:a]{MONO}[na];[3:a]{MONO},volume=0.055[bd];"
               f"[na][bd]amix=inputs=2:duration=first:normalize=0,{NORM}[ao]")
    AF_BARE = f"[2:a]{MONO},{NORM}[ao]"

    def encode(afilter, with_bed):
        cmd = ["ffmpeg","-y","-v","error",
               "-f","concat","-safe","0","-i",f"{workdir}/v.txt",
               "-f","concat","-safe","0","-i",f"{workdir}/c.txt",
               "-i",f"{workdir}/audio.wav"]
        if with_bed:
            cmd += ["-i", bed]
        cmd += ["-filter_complex", vfilter + ";" + afilter,
                "-map","[vo]","-map","[ao]",
                "-c:v","libx264","-preset","veryfast","-crf","22",
                "-c:a","aac","-b:a","160k","-ar","24000","-ac","1","-shortest", out_path]
        subprocess.run(cmd, check=True)

    print("エンコード開始...", flush=True)
    plans = ([(AF_DUCK,True),(AF_FLAT,True),(AF_BARE,False)] if bed
             else [(AF_BARE,False)])
    for af, wb in plans:
        try:
            encode(af, wb)
            break
        except subprocess.CalledProcessError as e:
            print(f"  音声ミックスを簡素化して再試行するのだ ({e})", flush=True)
    else:
        raise RuntimeError("エンコードに失敗したのだ")
    print(f"完成: {out_path}", flush=True)
    return {"duration": clock, "chapters": chapters, "telops": len(telops)}


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
