#!/usr/bin/env python3
"""
ずんだもん解説動画パイプライン v2

改良点:
  - ずんだもんの立ち絵を合成(表情はシーンごとに指定)
  - 母音に合わせた口パク(VOICEVOXのモーラ長を使用)
  - ASS字幕による本格テロップ(フレーズ単位・キーワード強調・ポップイン)
"""
__VERSION__ = "2026-09-08d"
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

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

def bg_images():
    """用意された背景画像を集める。ファイル名が bg で始まるものを拾う"""
    import glob
    out, seen = [], set()
    for d in (os.path.join(ROOT, "assets", "bg"), os.path.join(ROOT, "assets"),
              ROOT, os.path.dirname(ROOT)):
        for q in sorted(glob.glob(os.path.join(d, "*"))):
            b = os.path.basename(q).lower()
            if os.path.isdir(q) or os.path.splitext(b)[1] not in IMG_EXT:
                continue
            if not b.startswith("bg"):
                continue
            key = re.sub(r"[\s(]\d+\)?", "", os.path.splitext(b)[0]).strip()
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out


def _photo_background(path):
    """写真の背景を、文字が読めるようにやわらげて敷く"""
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    im = Image.open(path).convert("RGB")
    # 画面いっぱいに切り出す
    k = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    ox, oy = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((ox, oy, ox + W, oy + H))
    im = im.filter(ImageFilter.GaussianBlur(5))
    im = ImageEnhance.Color(im).enhance(0.72)
    im = im.convert("RGBA")

    # 全体を白でうすめて、本文側はさらに明るくする
    veil = Image.new("RGBA", (W, H), (255, 255, 255, 96))
    im = Image.alpha_composite(im, veil)
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(wash).ellipse([-420, -260, 1330, 1040], fill=(255, 255, 255, 150))
    im = Image.alpha_composite(im, wash.filter(ImageFilter.GaussianBlur(110)))

    # 立ち絵まわりに白いハロー
    hl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse([1360, 130, 1900, 880], fill=(255, 255, 255, 92))
    im = Image.alpha_composite(im, hl.filter(ImageFilter.GaussianBlur(80)))
    return im.convert("RGB")


def make_background(g):
    """やわらかいグラデーション + 光の玉 + うっすら斜めストライプ"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    key = g[0]
    if key in _BG_CACHE:
        return _BG_CACHE[key].copy()
    _, _, c1, c2, acc, blobs = g

    # 用意された背景画像があれば、章ごとに切り替えて使う
    imgs = bg_images()
    if imgs:
        gi = [x[0] for x in GROUPS].index(key) if key in [x[0] for x in GROUPS] else 0
        out = _photo_background(imgs[gi % len(imgs)])
        _BG_CACHE[key] = out
        return out.copy()

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
    """立ち絵素材を読み込む。assets/frames が主役、assets/frames_<名前> が相手役。
    返り値は {(キャラ, 表情, 口の形): パス}"""
    import glob
    made = {}
    for d in sorted(glob.glob(os.path.join(ROOT, "assets", "frames*"))):
        if not os.path.isdir(d):
            continue
        base = os.path.basename(d)
        who  = "zunda" if base == "frames" else base[len("frames_"):]
        for p in glob.glob(f"{d}/*_*.png"):
            expr, tag = os.path.basename(p)[:-4].rsplit("_", 1)
            made[(who, expr, tag)] = p
    # 相棒役は1枚のシート画像でも渡せる(リポジトリに置くファイルを減らすため)
    if not any(k[0] == "guest" for k in made):
        made.update(_sheet_frames("guest"))
    if not any(k[0] == "zunda" for k in made):
        raise SystemExit(f"立ち絵が見つからない: {cache}")
    return made


SHEET_EXPRS = ["normal", "happy", "surprise", "think", "sad"]
SHEET_TAGS  = ["x", "a", "i", "u", "e", "o"]   # 上から順。2段だけの古いシートも読める

def _sheet_frames(who):
    """<who>_sheet.png(表情を横、口の形を縦に並べた1枚絵)を切り出す。
    段数はシートの高さから判断するので、2段でも6段でも読める"""
    import glob
    from PIL import Image
    cand = []
    for d in (os.path.join(ROOT, "assets"), ROOT, os.path.dirname(ROOT)):
        cand += sorted(glob.glob(os.path.join(d, f"{who}_sheet*")))
    cand = [c for c in cand if os.path.splitext(c)[1].lower() in (".png", ".webp")]
    if not cand:
        return {}
    # 古いシートが残っていても、口の形が多い(縦に長い)ほうを選ぶ
    def rows_of(q):
        try:
            w, h = Image.open(q).size
            return h / max(1, w)
        except Exception:
            return 0
    cand.sort(key=rows_of, reverse=True)
    sheet = Image.open(cand[0]).convert("RGBA")
    cw   = sheet.width // len(SHEET_EXPRS)
    rows = max(1, min(len(SHEET_TAGS), round(sheet.height / (cw * 900 / 478))))
    chh  = sheet.height // rows
    out  = os.path.join(ROOT, "assets", f"frames_{who}")
    os.makedirs(out, exist_ok=True)
    made = {}
    for i, e in enumerate(SHEET_EXPRS):
        for j, tag in enumerate(SHEET_TAGS[:rows]):
            path = os.path.join(out, f"{e}_{tag}.png")
            if not os.path.exists(path):
                sheet.crop((i*cw, j*chh, (i+1)*cw, (j+1)*chh)).save(path)
            made[(who, e, tag)] = path
    print(f"  相棒の立ち絵: {os.path.basename(cand[0])} から{len(made)}枚"
          f"(口の形{rows}種)", flush=True)
    return made


def q_span(q):
    """クエリ上の合計秒数。speedScale を掛けた実尺とはずれるので補正に使う"""
    t = q.get("prePhonemeLength", 0.1) + q.get("postPhonemeLength", 0.1)
    for ap in q["accent_phrases"]:
        for mo in ap["moras"]:
            t += (mo.get("consonant_length") or 0.0) + mo["vowel_length"]
        pm = ap.get("pause_mora")
        if pm:
            t += (pm.get("consonant_length") or 0.0) + pm["vowel_length"]
    return t or 1.0


def mouth_frames(chars, who, expr, q, dur=None):
    """その人の口パクのコマ列 [(画像パス, 秒)] を作る。
    母音5種がそろっていない素材は、開く/閉じるの2枚でパクパクさせる"""
    two = (who, expr, "o") not in chars and (who, "normal", "o") not in chars
    k = 1.0 if dur is None else dur / q_span(q)   # 話す速さの調整ぶんを補正
    out = []
    if not two:
        for shape, ln in mouth_track(q):
            if ln > 0.01:
                out.append((pick_frame(chars, who, expr, shape), ln * k))
        return out
    op = pick_frame(chars, who, expr, "a")
    cl = pick_frame(chars, who, expr, "x")
    for shape, ln in mouth_track(q):
        if ln <= 0.01:
            continue
        ln *= k
        if shape == "x":
            out.append((cl, ln))
        else:                       # 1モーラのうち前を開け、後ろを閉じる
            out.append((op, ln * 0.62))
            out.append((cl, ln * 0.38))
    return out


def pick_frame(chars, who, expr, shape):
    """その人の立ち絵を探す。無ければ主役の口を閉じた絵で代用する"""
    for k in ((who, expr, shape), (who, "normal", shape),
              ("zunda", expr, "x"), ("zunda", "normal", "x")):
        if k in chars:
            return chars[k]
    return next(iter(chars.values()))


# 会話形式の登場人物。script["cast"] で上書きできる
# styles: 表情ごとの話者ID。VOICEVOXは同じキャラの感情違いが別IDになっている
CAST = {
    # badge: 名札の地色。立ち絵の髪の色から取って、白文字が読める濃さまで落としたもの
    "zunda": {"speaker": 3, "name": "ずんだもん", "color": "&H001B2C14",
              "badge": (56, 138, 82),
              "styles": {"normal": 3, "happy": 1, "surprise": 7,
                         "think": 3, "sad": 76}},
    # pitch: その人の声の高さの補正。めたんは少し低めにする
    "guest": {"speaker": 2, "name": "四国めたん", "color": "&H00603480",
              "badge": (230, 62, 130),          # めたんの桃色。緑や紫と間違えない鮮やかさにする
              "pitch": -0.06,
              "styles": {"normal": 2, "happy": 0, "surprise": 6,
                         "think": 2, "sad": 2}},
}

# 表情ごとの読み上げの味つけ(速さ・抑揚・高さ)
TUNE = {
    "normal":   {"speedScale": 1.00, "intonationScale": 1.00, "pitchScale": 0.00},
    "happy":    {"speedScale": 1.04, "intonationScale": 1.15, "pitchScale": 0.01},
    "surprise": {"speedScale": 1.06, "intonationScale": 1.30, "pitchScale": 0.02},
    "think":    {"speedScale": 0.94, "intonationScale": 0.92, "pitchScale": -0.01},
    "sad":      {"speedScale": 0.92, "intonationScale": 0.95, "pitchScale": -0.02},
}

def ass_rgb(c):
    """ASSの色指定 &HAABBGGRR を (R,G,B) にする"""
    h = str(c).lstrip("&Hh").rjust(8, "0")[-8:]
    return (int(h[6:8], 16), int(h[4:6], 16), int(h[2:4], 16))


def badge_rgb(who_conf):
    """名札の地色。話者ごとのテロップ色から作る(白文字が読める明るさまで持ち上げる)。
    章ごとのアクセント色を使うと、めたんの名札まで緑になってしまうため"""
    if who_conf.get("badge"):
        return tuple(who_conf["badge"])
    r, g, b = ass_rgb(who_conf.get("color", "&H00000000"))
    m = max(r, g, b)
    if not m:
        return (90, 90, 90)
    k = 152 / m
    return tuple(min(255, int(v * k)) for v in (r, g, b))


def cast_of(script):
    c = {k: dict(v) for k, v in CAST.items()}
    for k, v in (script.get("cast") or {}).items():
        c.setdefault(k, dict(CAST["guest"]))
        c[k].update(v)
    return c


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
        "十五夜","十三夜","十日夜","十三参り","七五三","二十歳","八百屋",
        "数百","数千","十数","一石二鳥","二者択一","三脚","五感","七夕",
        # 四字熟語・慣用句(数の字が入るが数ではない)
        "十人十色","十人一色","十人並み","五分五分","十中八九","一日千秋","三日坊主",
        "一日一善","三日三晩","一問一答","一言一句","一喜一憂","一進一退","一長一短",
        "千差万別","二束三文","三三五五","四苦八苦","七転八倒","一朝一夕","三寒四温",
        "八方美人","百発百中","千載一遇","一部始終","一挙両得","二重人格","四面楚歌",
        "五里霧中","十把一絡げ","一切合切","千客万来","百戦錬磨","千変万化","四六時中",
        "二の次","二の舞","一辺倒","九分九厘","二人三脚","九九",
        # 読みが変わる語・暦
        "三日月","五月雨","五月晴れ","十六夜","四十九日","二十四節気","八十八夜",
        "二百十日","二日酔い","四つ角","五分刈り","十二単","三が日",
        # 固有名詞・そのままの語
        "万年筆","億万長者","六本木","二子玉川","三軒茶屋","五反田","八王子","九段下",
        "七十七銀行","八十二銀行","十六銀行","百五銀行","百十四銀行","三十三銀行",
        "十八親和","第四北越","七味","九州","十字架","千鳥","万葉集","三権分立",
        "五重塔","四天王","七福神","千里眼","一世一代","第三者","第二","第三"]

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
    # 位を表す字が1つも無いのに一桁字が2つ以上続くものは数ではない。
    # 「三三五五」「四六時中」「九九」「二三日」など。_small だと最後の1字しか
    # 残らず文字が消えてしまうので、そのまま返す
    if len(run) >= 2 and not any(c in run for c in "十百千万億兆〇"):
        return run
    out, rest = "", run
    for unit in ("億", "万"):
        if unit in rest:
            head, rest = rest.split(unit, 1)
            out += f"{_small(head) if head else 1}{unit}"
    tail = _small(rest) if rest else 0
    if tail or not out:
        out += str(tail)
    return out


# KEEPの語でも、この形で出てきたときは数として扱う(退避しない)
#   「一時」は普通は退避したいが「一時間」は1時間
#   「十分」も同じで「十分間」は10分間
KEEP_EXCEPT = {
    "一時": "間半",
    "十分": "間",
}


def to_digits(text):
    # 1) 数として扱わない語を退避。ただし
    #    ・直前が漢数字のとき(三十分の「十分」など)は数の一部なので退避しない
    #    ・KEEP_EXCEPT の字が続くとき(一時間・十分間)も退避しない
    holes = {}
    for i, w in enumerate(KEEP):
        if w not in text:
            continue
        key = f"\x00{i}\x00"
        nxt = KEEP_EXCEPT.get(w, "")
        out, p = [], 0
        while True:
            j = text.find(w, p)
            if j < 0:
                out.append(text[p:]); break
            after = text[j + len(w): j + len(w) + 1]
            prev  = text[j - 1] if j else ""
            if (prev and prev in NUMCH) or (nxt and after and after in nxt):
                out.append(text[p:j + len(w)])       # 数の一部なので退避しない
            else:
                out.append(text[p:j]); out.append(key)
                holes[key] = w
            p = j + len(w)
        text = "".join(out)

    # 1-b) 「数十」「何百」などの概数の直後に続く「万・億・兆」も一緒に退避する。
    #      これをしないと「数十万円」が「数十1万円」に壊れる
    VAGUE_END = set(NUMCH) | set("数何")
    def _absorb(m):
        key, tail = m.group(1), m.group(2)
        w = holes.get(key, "")
        if not w or w[-1] not in VAGUE_END:
            return m.group(0)
        k2 = f"\x00v{len(holes)}\x00"
        holes[k2] = w + tail
        return k2
    if holes:
        text = re.sub(r"(\x00\d+\x00)([万億兆]+)", _absorb, text)

    # 2) 漢数字の並びを見つけて変換
    DIGITS = "0123456789０１２３４５６７８９"

    def repl(m):
        run, start, end = m.group(0), m.start(), m.end()
        # すでに算用数字で書かれている場合の「万」「億」は単位なので触らない
        # (これを変換すると 193万円 → 1931万円 のように壊れる)
        if start > 0 and text[start - 1] in DIGITS:
            return run
        # 「数万人」「何億円」のような概数。数として書き換えない
        if start > 0 and text[start - 1] in "数何":
            return run
        after = text[end:end + 6]
        before = text[max(0, start - 2):start]
        is_num = (re.match(UNIT, after) or len(run) >= 2
                  or before.endswith(("その", "第", "計", "約", "分の")))
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

def _lighten(c, k=0.55):
    return tuple(int(v * (1 - k) + 255 * k) for v in c)


def figure_spec(scene):
    """シーンから図解の指定を取り出す。chart は棒グラフの別名"""
    f = scene.get("figure")
    if not f and scene.get("chart"):
        f = dict(scene["chart"])
        f.setdefault("type", "bar")
    if not f:
        return None
    f = dict(f)
    f.setdefault("type", "bar")
    if f["type"] in ("bar", "ratio", "steps", "timeline") and not f.get("items"):
        return None
    if f["type"] == "table" and not f.get("rows"):
        return None
    # 形が違うとビルドの途中で落ちるので、ここで弾いて図解なしとして続行する
    #   bar / ratio … [ラベル, 数値] の組
    #   timeline    … [いつ, なに] の組
    #   steps       … 文字列
    #   table       … 行が list
    try:
        it = f.get("items") or []
        if f["type"] in ("bar", "ratio", "timeline"):
            if not all(isinstance(v, (list, tuple)) and len(v) == 2 for v in it):
                raise ValueError(f'{f["type"]} の items は [ラベル, 値] の組にする')
            if f["type"] in ("bar", "ratio"):
                for _, v in it:
                    float(v)
        if f["type"] == "steps" and not all(isinstance(v, str) for v in it):
            raise ValueError("steps の items は文字列にする")
        if f["type"] == "table":
            if not all(isinstance(r, (list, tuple)) for r in f["rows"]):
                raise ValueError("table の rows は list にする")
    except Exception as e:
        print(f"  ! 図解の指定が正しくないので飛ばしたのだ({f.get('type')}): {e}")
        return None
    return f


def figure_height(spec, sc=1.0, w=1120):
    """図解が縦に何ピクセル要るか(scは拡大率、wは使える横幅)"""
    t = spec["type"]
    n = len(spec.get("items", []))
    if t == "bar":
        return int(n * ((52 + 26) if n <= 3 else (44 + 20)) * sc)
    if t == "ratio":
        rows = 1 + max(0, (n - 1) // 3)      # 凡例が折り返す想定
        return int((116 + 60 * rows) * sc)
    if t == "timeline":
        return _timeline_layout(spec, w, sc)[5]
    if t == "steps":
        if n > 4:
            return int(n * 74 * sc)
        return _steps_layout(spec, w, sc)[2]
    if t == "table":
        return _table_layout(spec, w, sc)[3]
    return 0


def draw_figure(d, spec, x, y, w, acc, sc=1.0):
    """図解を描く。数字や手順はこれがあると理解が段違いに速い"""
    fn = {"bar": _fig_bar, "ratio": _fig_ratio, "steps": _fig_steps,
          "timeline": _fig_timeline, "table": _fig_table}.get(spec["type"])
    if fn:
        fn(d, spec, x, y, w, acc, sc)


def _f(path, size, sc):
    from PIL import ImageFont
    return ImageFont.truetype(path, max(12, int(size * sc)))


def _fig_bar(d, spec, x, y, w, acc, sc=1.0):
    items = spec["items"]
    unit  = spec.get("unit", "")
    n     = len(items)
    bh, gap = (int(52*sc), int(26*sc)) if n <= 3 else (int(44*sc), int(20*sc))
    vmax  = max(abs(v) for _, v in items) or 1
    vtxt  = lambda v: f"{v:,}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"
    # ラベルと数字が長いと棒の置き場が無くなり、右へはみ出して立ち絵に重なる。
    # 収まるまで文字を小さくしてから組む
    for k in (1.0, 0.92, 0.84, 0.76, 0.68, 0.60, 0.52):
        f_lab = _f(FONT_R, int(34 * k), sc)
        f_val = _f(FONT_B, int(40 * k), sc)
        labw  = max(f_lab.getlength(to_digits(str(l))) for l, _ in items) + 24 * sc
        vw    = max(f_val.getlength(vtxt(v)) for _, v in items) + 30 * sc
        barw  = w - labw - vw
        if barw >= 200:
            break
    barw  = max(120, barw)
    barx  = x + labw
    for i, (label, val) in enumerate(items):
        cy = y + i * (bh + gap)
        d.text((x, cy + (bh - f_lab.size) // 2), to_digits(str(label)), font=f_lab, fill=INK_SOFT)
        d.rounded_rectangle([barx, cy, barx + barw, cy + bh], radius=int(8*sc),
                            fill=(255, 255, 255, 150))
        L = max(10, int(barw * abs(val) / vmax))
        col = acc if i == n - 1 else _lighten(acc)      # 最後の項目=結論を濃く
        d.rounded_rectangle([barx, cy, barx + L, cy + bh], radius=int(8*sc), fill=col)
        # 数字が右端(=立ち絵の手前)を越えないように寄せる
        vx = min(barx + L + 18 * sc, x + w - f_val.getlength(vtxt(val)))
        d.text((vx, cy + (bh - f_val.size) // 2), vtxt(val), font=f_val, fill=INK)


def _fig_ratio(d, spec, x, y, w, acc, sc=1.0):
    """割合を1本の帯で見せる"""
    items = spec["items"]
    f_num = _f(FONT_B, 38, sc)
    f_lab = _f(FONT_R, 32, sc)
    tot   = sum(abs(v) for _, v in items) or 1
    bh    = int(76 * sc)
    cx    = x
    shades = [acc if i == 0 else _lighten(acc, 0.28 + 0.22 * i) for i in range(len(items))]
    for i, (label, val) in enumerate(items):
        seg = int(w * abs(val) / tot)
        if i == len(items) - 1:
            seg = x + w - cx
        d.rectangle([cx, y, cx + seg, y + bh], fill=shades[i])
        pct = f"{round(100 * abs(val) / tot)}%"
        tw = f_num.getlength(pct)
        if seg > tw + 20:
            d.text((cx + (seg - tw) / 2, y + (bh - f_num.size) / 2), pct, font=f_num,
                   fill=(255, 255, 255) if i == 0 else INK)
        cx += seg
    # 凡例。横に並べきれなくなったら折り返す(立ち絵に重なって切れるのを防ぐ)
    lx, ly = x, y + bh + int(28 * sc)
    box  = int(26 * sc)
    step = int(f_lab.size * 1.5)
    for i, (label, _) in enumerate(items):
        txt = to_digits(str(label))
        need = box + 14 * sc + f_lab.getlength(txt) + 46 * sc
        if lx > x and lx + need > x + w:
            lx, ly = x, ly + step
        d.rounded_rectangle([lx, ly + 6, lx + box, ly + 6 + box], radius=int(5*sc), fill=shades[i])
        d.text((lx + box + 14 * sc, ly), txt, font=f_lab, fill=INK_SOFT)
        lx += need


def _steps_layout(spec, w, sc):
    """手順の箱の幅・高さ・文字サイズを決める"""
    items = [to_digits(str(v)) for v in spec["items"]]
    n     = max(1, len(items))
    gapw  = int(46 * sc)
    bw    = (w - gapw * (n - 1)) // n
    inner = bw - int(44 * sc)
    sz    = int(40 * sc)
    while sz > 20:
        f = _f(FONT_R, sz, 1.0)
        rows = [wrap(t, f, inner) for t in items]
        if max(len(r) for r in rows) <= 3:
            break
        sz -= 2
    f    = _f(FONT_R, sz, 1.0)
    rows = [wrap(t, f, inner) for t in items]
    lines = max(len(r) for r in rows)
    bh   = int(58 * sc) + 2 * int(22 * sc) + int(lines * sz * 1.3) + int(18 * sc)
    return bw, gapw, bh, sz, rows


def _fig_steps(d, spec, x, y, w, acc, sc=1.0):
    """手順を1→2→3と横に並べる"""
    items = [to_digits(str(v)) for v in spec["items"]]
    n = len(items)
    if n <= 4:
        bw, gapw, bh, sz, rows = _steps_layout(spec, w, sc)
        r    = int(22 * sc)
        f_no = _f(FONT_B, 34, sc)
        f_tx = _f(FONT_R, sz, 1.0)
        for i, lines in enumerate(rows):
            bx = x + i * (bw + gapw)
            d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=int(16*sc),
                                fill=(255, 255, 255, 195), outline=_lighten(acc, 0.3),
                                width=max(2, int(3*sc)))
            ccx, ccy = bx + int(20*sc) + r, y + int(18*sc) + r
            d.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=acc)
            d.text((ccx, ccy), str(i + 1), font=f_no, fill=(255, 255, 255), anchor="mm")
            ty = y + int(58 * sc) + 2 * int(22 * sc)
            for line in lines:
                d.text((bx + int(22*sc), ty), line, font=f_tx, fill=INK)
                ty += int(sz * 1.3)
            if i < n - 1:
                ax = bx + bw + gapw // 2
                a  = int(12 * sc)
                d.polygon([(ax - a, y + bh//2 - a), (ax + a, y + bh//2), (ax - a, y + bh//2 + a)],
                          fill=acc)
    else:
        f_no = _f(FONT_B, 30, sc)
        f_tx = _f(FONT_R, 38, sc)
        r    = int(22 * sc)
        for i, t in enumerate(items):
            cy = y + int(i * 74 * sc)
            d.ellipse([x, cy + 4, x + 2*r, cy + 4 + 2*r], fill=acc)
            d.text((x + r, cy + 4 + r), str(i + 1), font=f_no, fill=(255, 255, 255), anchor="mm")
            d.text((x + 2*r + int(22*sc), cy + 4), t, font=f_tx, fill=INK)


def _timeline_layout(spec, w, sc):
    """時期と内容が右へはみ出さないように、文字の大きさと折り返しを決める"""
    items = spec["items"]
    for k in (1.0, 0.92, 0.84, 0.76, 0.68, 0.60):
        f_when = _f(FONT_B, int(36 * k), sc)
        f_what = _f(FONT_R, int(36 * k), sc)
        ww   = max(f_when.getlength(to_digits(str(a))) for a, _ in items) + 40 * sc
        left = int(52 * sc) + ww
        avail = w - left
        if avail < 160:
            continue
        rows = [wrap(to_digits(str(b)), f_what, avail) for _, b in items]
        if max(len(r) for r in rows) <= 1:
            break
    else:
        rows = [wrap(to_digits(str(b)), f_what, max(160, w - int(52*sc) - ww))
                for _, b in items]
    lines = max(1, max(len(r) for r in rows))
    step  = int((84 if lines == 1 else 84 + 46 * (lines - 1)) * sc)
    return f_when, f_what, ww, rows, step, step * len(items)


def _fig_timeline(d, spec, x, y, w, acc, sc=1.0):
    """いつ何が変わるかを縦に並べる"""
    items = spec["items"]
    f_when, f_what, ww, rows, step, _ = _timeline_layout(spec, w, sc)
    r    = int(13 * sc)
    rail = x + int(22 * sc)
    d.line([(rail, y + step * 0.3), (rail, y + (len(items) - 1) * step + step * 0.34)],
           fill=_lighten(acc, 0.4), width=max(3, int(5*sc)))
    for i, (when, what) in enumerate(items):
        cy = y + i * step
        d.ellipse([rail - r, cy + step*0.16, rail + r, cy + step*0.16 + 2*r], fill=acc)
        d.text((x + int(52*sc), cy), to_digits(str(when)), font=f_when, fill=acc)
        wy = cy
        for line in rows[i]:
            d.text((x + int(52*sc) + ww, wy), line, font=f_what, fill=INK)
            wy += int(f_what.size * 1.28)


def _table_layout(spec, w, sc):
    """表の列幅・文字サイズ・行の高さ・全体の高さを決める。
    列幅は中身の長さに応じて配分する(等分にすると、長い列に引きずられて
    表全体の文字が小さくなってしまう)"""
    cols = spec.get("cols") or []
    rows = spec["rows"]
    nc   = max(max((len(r) for r in rows), default=0), len(cols))
    if nc == 0:
        return [], 20, 0, 0, nc
    cells = [[str(c) for c in cols]] + [[str(c) for c in r] for r in rows]
    f0 = _f(FONT_B, 40, 1.0)
    need = []
    for j in range(nc):
        wmax = max((f0.getlength(to_digits(row[j])) for row in cells if j < len(row)),
                   default=1.0)
        need.append(wmax + 70)          # 左右の余白ぶん
    tot = sum(need) or 1
    cw = [max(140, int(w * n / tot)) for n in need]
    over = sum(cw) - w
    if over > 0:                        # 下限で膨らんだぶんは一番広い列から削る
        cw[cw.index(max(cw))] -= over
    sz = int(42 * sc)
    while sz > 22:
        f = _f(FONT_B, sz, 1.0)
        if all(f.getlength(to_digits(row[j])) <= cw[j] - 30
               for row in cells for j in range(min(len(row), nc))):
            break
        sz -= 2
    rh = int(sz * 1.85)
    h  = rh * (len(rows) + (1 if cols else 0))
    return cw, sz, rh, h, nc


def _fig_table(d, spec, x, y, w, acc, sc=1.0):
    """現行と改正後のような比較表"""
    cols = spec.get("cols") or []
    rows = spec["rows"]
    cw, sz, rh, _, nc = _table_layout(spec, w, sc)
    if nc == 0:
        return
    f_h = _f(FONT_B, sz, 1.0)
    f_c = _f(FONT_R, sz, 1.0)
    pad = 18
    ry  = y
    if cols:
        cx = x
        for j in range(nc):
            d.rectangle([cx, ry, cx + cw[j], ry + rh], fill=_lighten(acc, 0.22))
            t = to_digits(str(cols[j])) if j < len(cols) else ""
            d.text((cx + pad, ry + (rh - sz) // 2), t, font=f_h, fill=(255, 255, 255))
            cx += cw[j]
        ry += rh
    for i, row in enumerate(rows):
        cx = x
        bg = (255, 255, 255, 155) if i % 2 == 0 else (255, 255, 255, 96)
        for j in range(nc):
            d.rectangle([cx, ry, cx + cw[j], ry + rh], fill=bg)
            t = to_digits(str(row[j])) if j < len(row) else ""
            d.text((cx + pad, ry + (rh - sz) // 2), t, font=f_h if j == 0 else f_c,
                   fill=INK_SOFT if j == 0 else INK)
            cx += cw[j]
        ry += rh
    if nc >= 2:                                   # 右端(改正後)を枠で強調
        rx = x + sum(cw[:nc - 1])
        d.rectangle([rx, y, rx + cw[-1], ry], outline=acc, width=max(3, int(4*sc)))


def _chrome(d, acc, chapter, idx, total, progress):
    """どのスライドにも共通の枠(上帯・テロップ帯・進捗バー)"""
    from PIL import ImageFont
    f_ch = ImageFont.truetype(FONT_R, 28)
    d.rectangle([0, 0, W, 9], fill=acc)
    d.rectangle([0, 9, W, 80], fill=(255, 255, 255, 150))
    d.text((90, 28), chapter, font=f_ch, fill=INK_SOFT)
    d.text((W - 90, 28), f"{idx} / {total}", font=f_ch, fill=acc, anchor="ra")
    d.rectangle([0, 872, W, H], fill=(252, 253, 248, 232))
    d.rectangle([0, 872, W, 876], fill=acc)
    d.rectangle([0, H - 7, W, H], fill=(0, 0, 0, 26))
    d.rectangle([0, H - 7, int(W * max(0.0, min(1.0, progress))), H], fill=acc)


def draw_chapter_card(scene, idx, total, chapter, path, part, nparts, progress=0.0):
    """章の変わり目に出す扉。同じ画づらが続く単調さをここで切る"""
    from PIL import ImageDraw, ImageFont
    g   = group_of(idx)
    acc = g[4]
    img = make_background(g)
    d   = ImageDraw.Draw(img, "RGBA")
    _chrome(d, acc, chapter, idx, total, progress)

    L, R, T, B = 150, 1330, 250, 720
    d.rounded_rectangle([L, T, R, B], radius=28, fill=(255, 255, 255, 178))
    d.rectangle([L, T, L + 12, B], fill=acc)

    # 右端に大きな章番号(飾り)
    f_big = ImageFont.truetype(FONT_B, 250)
    d.text((R - 56, (T + B) // 2), str(part), font=f_big, fill=acc + (40,), anchor="rm")

    f_kick = ImageFont.truetype(FONT_B, 40)
    d.text((L + 64, T + 50), f"第{part}章 / 全{nparts}章", font=f_kick, fill=acc)

    # 「このあと何が分かるか」を1行そえて、ここで離脱させない
    kick = to_digits(str(scene.get("kicker", "")))[:34]
    if kick:
        f_k2 = ImageFont.truetype(FONT_R, 34)
        d.text((L + 64, B - 78), kick, font=f_k2, fill=INK_SOFT)

    # 見出しは2行に収まる大きさを選ぶ
    title = to_digits(scene["title"])
    TW = 900
    for sz in (92, 82, 74, 66, 58, 50):
        f_ttl = ImageFont.truetype(FONT_B, sz)
        lines = wrap(title, f_ttl, TW)
        if len(lines) <= 2:
            break
    lh = int(sz * 1.26)
    y  = (T + B) // 2 - (len(lines) * lh) // 2 + 10
    for line in lines:
        d.text((L + 64, y), line, font=f_ttl, fill=INK)
        y += lh
    d.rectangle([L + 64, min(y + 16, B - 40), L + 234, min(y + 22, B - 34)], fill=acc)
    img.save(path)


def _trim_figure(spec, avail, w):
    """縮小しても入りきらない図解は、行(項目)を減らして必ず収める。
    減らさないと立ち絵や名札、箇条書きに重なる"""
    if figure_height(spec, 0.55, w) <= avail:
        return spec
    key = "rows" if spec["type"] == "table" else "items"
    seq = list(spec.get(key) or [])
    while len(seq) > 2:
        seq = seq[:-1]
        cand = dict(spec); cand[key] = seq
        if figure_height(cand, 0.55, w) <= avail:
            print(f"  ! 図解が入りきらないので{key}を{len(spec.get(key))}→{len(seq)}に減らしたのだ")
            return cand
    out = dict(spec); out[key] = seq
    print(f"  ! 図解が入りきらないので{key}を{len(spec.get(key))}→{len(seq)}に減らしたのだ")
    return out


def draw_slide(scene, idx, total, chapter, path, shown=None, progress=0.0,
               speaker=None, badge=None):
    """shown: 表示する箇条書きの数(Noneなら全部) / progress: 全体の進み具合 0〜1"""
    from PIL import Image, ImageDraw, ImageFont
    g   = group_of(idx)
    acc = g[4]
    img = make_background(g)
    d   = ImageDraw.Draw(img, "RGBA")
    _chrome(d, acc, chapter, idx, total, progress)

    f_num  = ImageFont.truetype(FONT_B, 116)

    # 章番号(背景の飾り)
    d.text((84, 122), f"{idx:02d}", font=f_num, fill=acc + (58,))

    # タイトル。3行になると図解の場所が無くなるので、2行に収まる大きさまで落とす
    ttl = to_digits(scene["title"])
    for tsz in (72, 66, 60, 54, 48):
        f_ttl = ImageFont.truetype(FONT_B, tsz)
        tlines = wrap(ttl, f_ttl, 1120)
        if len(tlines) <= 2:
            break
    lh_t = int(tsz * 1.28)
    y = 152
    for line in tlines:
        d.text((256, y), line, font=f_ttl, fill=INK); y += lh_t
    y += 18
    d.rectangle([259, y, 369, y + 5], fill=acc); y += 52
    TOP = y            # 見出しの下端。図解も箇条書きもここより下に置く

    # 箇条書き(ナレーションの進みに合わせて1つずつ増える)
    bullets = [to_digits(b) for b in scene.get("bullets", [])]
    n = len(bullets) if shown is None else max(0, min(shown, len(bullets)))
    fig  = figure_spec(scene)
    # 立ち絵は x=1430 から始まる。図解は x=268 起点なので、
    # 右端が 1384(立ち絵の46px手前)を越えない幅にする
    FIGW = 1116 if not bullets else 1060
    # 会話形式の回は左下に名札(y=806〜856)が出るので、図解はその上で止める
    LIMIT = 792 if speaker else 848
    fsc  = 1.0
    if fig:
        # 箇条書きが無いシーンでは余白いっぱいまで大きくする。
        # 見出しが2行になることがあるので、上端は決め打ちにせず TOP から測る。
        # 箇条書きと同居するときは、その行数ぶんを先に取り分ける
        if bullets:
            avail = max(120, LIMIT - TOP - (len(bullets) * 66 + 24))
            hi = 1.0
        else:
            avail = max(120, LIMIT - TOP - 24)
            hi = 1.75
        fig = _trim_figure(fig, avail, FIGW)
        nat = figure_height(fig, 1.0, FIGW) or 1
        # 拡大は1.75倍まで、縮小は0.55倍まで。これ以上小さいと読めない
        fsc = max(0.55, min(hi, avail / nat))
    fh   = figure_height(fig, fsc, FIGW) if fig else 0
    BOTTOM = LIMIT - (fh + 40 if fh else 0)   # 箇条書きが使ってよい下端
    BOTTOM = max(BOTTOM, TOP + 60)            # 見出しの下に食い込ませない
    fig_y  = BOTTOM + 28

    if bullets:
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
        if not fig:                        # 図解が無いときは縦方向に中央寄せ
            y += max(0, min(120, (BOTTOM - y - block) // 2))

        for k, b in enumerate(bullets[:n]):
            fresh = (k == n - 1)           # 出たばかりの行は少し目立たせる
            ms = max(14, int(size * 0.32))
            my = y + int(lh * 0.32)
            d.rounded_rectangle([259, my, 259 + ms, my + ms], radius=4,
                                fill=acc if fresh else acc + (150,))
            for i, line in enumerate(rows[k]):
                d.text((310, y), line, font=f_body,
                       fill=INK if (i == 0 or fresh) else INK_SOFT)
                y += lh
            y += pad
    else:
        # 箇条書きが無いシーンは図解を真ん中に置く。ただし見出しには絶対にかぶせない
        fig_y = max(TOP + 24, (LIMIT + TOP - fh) // 2)

    # 図解(箇条書きが出そろってから)
    if fig and n >= len(bullets):
        fig_y = min(max(fig_y, TOP + 12), max(TOP + 12, LIMIT - fh))
        draw_figure(d, fig, 268, fig_y, FIGW, acc, fsc)

    # 会話形式のとき、いま誰が話しているかを示す
    if speaker:
        f_sp = ImageFont.truetype(FONT_B, 30)
        tw = f_sp.getlength(speaker)
        col = tuple(badge) if badge else acc
        # 背景から浮かせるために白いふちを付ける。色の違いが遠目にも分かる
        d.rounded_rectangle([86, 802, 94 + tw + 44, 860], radius=29,
                            fill=(255, 255, 255, 235))
        d.rounded_rectangle([90, 806, 90 + tw + 40, 856], radius=25, fill=col)
        d.text((110, 815), speaker, font=f_sp, fill=(255, 255, 255))

    img.save(path)


# ============ 音声合成 + モーラ取得 ============
CACHE = os.path.join(ROOT, ".cache", "voice")

# ─────────────────────────────────────────────────────────
# 読みの上書き(VOICEVOXのユーザー辞書)
#   surface はそのまま画面に出て、読みだけが変わる。テロップと口パクの
#   時刻合わせは元のテキストのままで済むので、置換方式より安全。
#   priority は必ず高くすること。既定の5ではOpenJTalk側の解析に負けて効かない
# ─────────────────────────────────────────────────────────
READINGS = [
    # (表記, 読み, アクセント核の位置。0は平板)
    ("iDeCo",   "イデコ",              0),   # 既定は「アイディイイイシイオオ」
    ("お得",    "オトク",              0),   # 既定は「オ'トク」で頭が高く不自然
    ("首都高",  "シュトコー",           0),   # 既定は「シュトダカ」
    ("NISA",    "ニーサ",              1),   # 既定は「エヌアイエスエー」
    ("PayPay",  "ペイペイ",            1),   # 既定は「ピイエエワイピイエエワイ」
    ("ChatGPT", "チャットジーピーティー",  0),
    ("eTax",    "イータックス",         0),
    ("生鮮品",  "セイセンヒン",         0),   # 既定は「セイセンシナ」
    ("取引所",  "トリヒキジョ",         5),   # 既定は「トリヒキショ」
    ("前と後",  "マエトアト",           1),   # 既定は「ゼントゴ」(前後の音読みになる)
    ("中と外",  "ナカトソト",           5),   # 既定は「チュウトガイ」
    ("線引き",  "センビキ",             0),   # 既定は「センヒキ」(連濁しない)
    ("放って",  "ホウッテ",             1),   # 「放っておく」が「ハナッテおく」になる
    ("食べ放題", "タベホウダイ",         0),   # 「タベ・ホーダイ」と切れる
    ("使い放題", "ツカイホウダイ",       0),
    # 「〜どき」は連濁せず「〜ジ」と読まれるか、途中で切れてしまう
    ("買い時",  "カイドキ",             0),
    ("売り時",  "ウリドキ",             0),
    ("使い時",  "ツカイドキ",           0),
    ("やめ時",  "ヤメドキ",             0),
    ("始め時",  "ハジメドキ",           0),
    ("食べ時",  "タベドキ",             0),
    ("見直し時", "ミナオシドキ",         0),
    # 「〜車」がクルマと読まれてしまう語(小型車・救急車などは正しく読める)
    ("高級車",  "コウキュウシャ",       0),   # 既定は「コオキュウ・クルマ」
    ("普通車",  "フツウシャ",           0),   # 既定は「フツウ・クルマ」
    ("代車",    "ダイシャ",             0),   # 既定は「ダイクルマ」
    # 「更新月」の更が単独で「サラ」と読まれてしまう
    ("更新月",  "コウシンヅキ",         0),   # 既定は「サラ・シンゲツ」
    ("新事実",  "シンジジツ",           1),   # 既定は「シン」で切れる
    # 「〜通り」は連濁して「〜ドオリ」。名詞のあと(予定通り・時間通り)は正しく読めるが、
    # 「いつも」「今まで」のような副詞句のあとだと切れて「トオリ」になる
    ("いつも通り",   "イツモドオリ",     0),
    ("今まで通り",   "イママデドオリ",   0),
    ("これまで通り", "コレマデドオリ",   0),
    ("それまで通り", "ソレマデドオリ",   0),
    # 「〜人」は辞書に無い複合語だと全部「ジン」になる(正しくはニン)
    ("名義人",     "メイギニン",       0),
    ("相続人",     "ソウゾクニン",     0),
    ("被相続人",   "ヒソウゾクニン",   0),
    ("受取人",     "ウケトリニン",     0),
    ("同居人",     "ドウキョニン",     0),
    ("賃借人",     "チンシャクニン",   0),
    ("賃貸人",     "チンタイニン",     0),
    ("譲渡人",     "ジョウトニン",     0),
    ("差出人",     "サシダシニン",     0),
    # 「〜主」は「オモ」になることがある(正しくはヌシ)
    ("世帯主",     "セタイヌシ",       0),
    ("事業主",     "ジギョウヌシ",     0),
    # そのほか
    ("金地金",     "キンジガネ",       0),   # 既定は「キンジキン」
    ("一対",       "イッツイ",         0),   # 既定は「イチタイ」
    ("河原",       "カワラ",           0),   # 既定は「カワハラ」(名字)
    ("1日中",      "イチニチジュウ",   4),   # 既定は「イチニチチュウ」
    ("一日中",     "イチニチジュウ",   4),
    # 単漢字の読み分け。文脈まで含めて登録しないと他の言い方が壊れる
    ("時間が空く", "ジカンガアク",     4),   # 既定は「ジカンガスク」
    ("席が空く",   "セキガアク",       3),
    ("角を曲がる", "カドオマガル",     3),   # 既定は「カクオマガル」
    ("角を曲がっ", "カドオマガッ",     3),   # 「角を曲がって」の形
    ("曲がり角",   "マガリカド",       3),
    ("表に出る",   "オモテニデル",     3),   # 既定は「ヒョウニデル」
    ("表に出て",   "オモテニデテ",     3),   # 活用形は別に登録しないと効かない
    ("表に出た",   "オモテニデタ",     3),
    ("表に出ない", "オモテニデナイ",   4),
    ("表に出なく", "オモテニデナク",   4),
    ("表に出す",   "オモテニダス",     3),
    # 「〜薬」がヤクになる(正しくはグスリ)。胃薬・目薬・塗り薬は正しく読める
    ("風邪薬",     "カゼグスリ",       3),
    ("飲み薬",     "ノミグスリ",       3),
    ("粉薬",       "コナグスリ",       3),
    ("払拭",       "フッショク",       0),   # 既定は「フッシキ」
    ("農作物",     "ノウサクブツ",     4),   # 既定は「ノウサクモツ」
    # 「〜所」が連濁せず「ショ」になる(取引所と同じ型)
    ("料金所",     "リョウキンジョ",   0),
    ("診療所",     "シンリョウジョ",   0),
    ("集会所",     "シュウカイジョ",   0),
    ("宿泊所",     "シュクハクジョ",   0),
    ("追納",       "ツイノウ",         0),   # 既定は「ツイオサメ」
    # 辞書に無い「〜口」は全部「コウ」になる(窓口・入口・改札口は元から正しい)
    ("受付口",     "ウケツケグチ",     4),
    ("相談口",     "ソウダングチ",     4),
    ("支払口",     "シハライグチ",     4),
    ("申込口",     "モウシコミグチ",   5),
    ("返却口",     "ヘンキャクグチ",   4),
    ("投入口",     "トウニュウグチ",   5),
    ("取出口",     "トリダシグチ",     4),
    ("正面口",     "ショウメングチ",   4),
    ("高止まり",   "タカドマリ",       3),   # 既定は「コウトマリ」
    ("高買い",     "タカガイ",         3),
    ("使い勝手",   "ツカイガッテ",     3),   # 既定は「ツカイカッテ」
    ("地代",       "チダイ",           0),   # 既定は「ジダイ」(時代と同じ音になる)
    ("地代家賃",   "チダイヤチン",     0),
    ("立ち行かない", "タチイカナイ",   0),   # 既定は「タチユカナイ」
    ("垂れる",     "タレル",           2),   # 既定は「シダレル」
    ("鍛冶",       "カジ",             1),   # 既定は「タンヤ」
    ("所々",       "トコロドコロ",     4),   # 既定は「ショショ」
    ("実のところ", "ジツノトコロ",     1),   # 既定は「ミノトコロ」
    ("奥深い",     "オクブカイ",       4),   # 既定は「オクフカイ」
    # 範囲の「〜」は読み飛ばされる。「50〜60代」が「5060代」に聞こえていた。
    # 辞書に入れれば画面の表記は「〜」のまま、読みだけ「から」になる
    ("〜",         "カラ",             0),
    ("年に",       "ネンニ",           1),   # 「年に2回」が「トシニ2回」になる
    ("かつては",   "カツテワ",         1),   # 助詞の「は」がハのまま読まれる
    ("1世帯",     "イッセタイ",       4),   # 既定は「イチセタイ」
    ("SIM",       "シム",             1),   # 既定は「エスアイエム」
    ("5G",        "ファイブジー",     4),   # 既定は「ゴジー」
    # 投資まわり。「〜買い」が連濁せず「カイ」になる型
    ("信用買い",   "シンヨウガイ",     5),
    ("現物買い",   "ゲンブツガイ",     5),
    ("成行買い",   "ナリユキガイ",     5),
    ("押し目買い", "オシメガイ",       4),
    ("先物買い",   "サキモノガイ",     5),
    ("自社株買い", "ジシャカブガイ",   5),
    ("含み損",     "フクミゾン",       0),   # 既定は「フクミソン」
    ("成行",       "ナリユキ",         0),   # 既定は「シゲユキ」(人名)
    ("歩み値",     "アユミネ",         3),   # 既定は「アユミチ」
    ("逆張り",     "ギャクバリ",       0),   # 既定は「ギャクハリ」
    ("順張り",     "ジュンバリ",       0),
]

# 分数。「3分の1」の分をVOICEVOXは「プン(時間の分)」と読んでしまうので、
# 「分の」+数字 のときだけ「ブンノ」に直す。「30分の休憩」は数字が続かないので影響しない
_FRAC = {"1": "イチ", "2": "ニ", "3": "サン", "4": "ヨン", "5": "ゴ",
         "6": "ロク", "7": "ナナ", "8": "ハチ", "9": "キュウ"}
READINGS += [(f"分の{d}", "ブンノ" + y, 0) for d, y in _FRAC.items()]


def readings_tag():
    """辞書の中身が変わったら音声キャッシュを作り直すための印"""
    import hashlib
    return hashlib.md5(repr(READINGS).encode()).hexdigest()[:8]


def register_readings():
    """ユーザー辞書に READINGS を入れ直す。エンジンは毎回まっさらなので都度呼ぶ"""
    import unicodedata
    def norm(t):
        return unicodedata.normalize("NFKC", str(t)).lower()
    try:
        cur = json.loads(urllib.request.urlopen(VOICEVOX + "/user_dict", timeout=30).read())
    except Exception as e:
        print(f"  読み辞書を読めなかったので既定の読みで続行: {type(e).__name__}")
        return 0
    want = {norm(su) for su, _, _ in READINGS}
    for uid, w in cur.items():                     # 同じ語の古い登録は消す
        if norm(w.get("surface", "")) in want:
            try:
                urllib.request.urlopen(urllib.request.Request(
                    VOICEVOX + "/user_dict_word/" + uid, method="DELETE"), timeout=30).read()
            except Exception:
                pass
    n = 0
    for su, yomi, acc in READINGS:
        q = urllib.parse.urlencode({"surface": su, "pronunciation": yomi,
                                    "accent_type": acc, "priority": 10})
        try:
            urllib.request.urlopen(urllib.request.Request(
                VOICEVOX + "/user_dict_word?" + q, data=b"", method="POST"), timeout=30).read()
            n += 1
        except Exception as e:
            print(f"  読みの登録に失敗 {su}: {type(e).__name__}")
    print(f"  読み辞書 {n}語を登録(" +
          "/".join(su for su, _, _ in READINGS[:7]) + " ほか)")
    return n


_READY = {"dict": False}


def synth(text, path, speaker=None, tune=None):
    """合成結果をテキスト単位でキャッシュし、再実行時は使い回す"""
    import hashlib, shutil
    if not _READY["dict"]:
        _READY["dict"] = True
        register_readings()
    speaker = SPEAKER if speaker is None else speaker
    tag = "" if not tune else ":" + ",".join(f"{k}={v}" for k, v in sorted(tune.items()))
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(f"{speaker}:{text}{tag}:{readings_tag()}:num2".encode()).hexdigest()
    cw, cq = f"{CACHE}/{key}.wav", f"{CACHE}/{key}.json"
    if os.path.exists(cw) and os.path.exists(cq):
        shutil.copyfile(cw, path)
        with wave.open(path) as w:
            return json.load(open(cq, encoding="utf-8")), w.getnframes() / w.getframerate()
    q, dur = _synth_remote(text, path, speaker, tune)
    shutil.copyfile(path, cw)
    json.dump(q, open(cq, "w", encoding="utf-8"), ensure_ascii=False)
    return q, dur


# 数の読みだけでできているアクセント句のかたまり。これ単独で語になることはない
_NUMKANA = ("イチ","ニ","サン","ヨン","シ","ゴ","ロク","ナナ","シチ","ハチ","キュウ","ク",
            "ジュウ","ジュッ","ジュ","ヒャク","ビャク","ピャク","セン","ゼン","マン","オク",
            "チョウ","ゼロ","レイ","テン","ッ")   # テンは小数点


def _phrase_kana(ap):
    return "".join(m["text"] for m in ap["moras"])


def _is_number_only(kana):
    """「ニセン」「ニジュウ」のように数の読みだけでできているか"""
    i, n = 0, len(kana)
    if not n:
        return False
    while i < n:
        for w in sorted(_NUMKANA, key=len, reverse=True):
            if kana.startswith(w, i):
                i += len(w); break
        else:
            return False
    return True


# 大きい位。前の句の数につながっていないと数として成立しない
_BIGUNIT = ("マン", "オク", "チョウ", "セン", "ゼン", "ビャク", "ピャク", "ヒャク")


def _ends_with_number(kana):
    """句の終わりが数の読みで終わっているか。「ツキヒャク」「ネンシュウヒャク」など、
    前の名詞とくっついてしまった数を見つけるのに使う"""
    for w in sorted(_NUMKANA, key=len, reverse=True):
        if kana.endswith(w) and len(kana) > len(w):
            return True
    return _is_number_only(kana)


def _starts_with_bigunit(kana):
    return any(kana.startswith(w) for w in _BIGUNIT)


def _starts_with_number(kana):
    return any(kana.startswith(w) for w in _NUMKANA)


def merge_number_phrases(q):
    """「2026年」がニセン/ニジュウ/ロクネンの3つに割れて、区切るたびに音の高さが
    リセットされるため「2000、20、6年」のように聞こえる。数の読みだけの句は
    単独では語にならないので、次の句とつないで1つの抑揚にする。

    さらに「月100万円」は OpenJTalk が「ツキヒャク / マンエン」と切ってしまい、
    100万が「百」と「万」に分かれて聞こえる(年収103万円が「百・三万円」になる)。
    後ろの句が万・億・兆で始まり、前の句が数で終わっているときもつなぐ"""
    aps = q.get("accent_phrases") or []
    out = []
    for ap in aps:
        join = False
        if out and not out[-1].get("pause_mora"):
            pk = _phrase_kana(out[-1])
            ck = _phrase_kana(ap)
            join = (_is_number_only(pk)
                    # 数の途中で切れている。「ネンシュウヒャク / サンマンエン」を
                    # つながないと 103万が「百・三万」に聞こえてしまう
                    or (_starts_with_number(ck) and _ends_with_number(pk)))
        if join:
            prev = out.pop()
            k = len(prev["moras"])
            ap = dict(ap)
            ap["moras"] = prev["moras"] + ap["moras"]
            # 後ろの句の山の位置を、前につないだぶんだけ後ろへずらす。
            # 平板(0)はそのまま平板にしておく
            acc = ap.get("accent") or 0
            ap["accent"] = acc + k if acc else 0
        out.append(ap)
    q["accent_phrases"] = out
    return q


def _synth_remote(text, path, speaker=None, tune=None):
    speaker = SPEAKER if speaker is None else speaker
    q = json.loads(urllib.request.urlopen(
        VOICEVOX + "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": speaker}),
        data=b"", timeout=90).read())
    merge_number_phrases(q)                 # 数字が細切れに聞こえるのを直す
    for k, v in (tune or {}).items():       # 速さ・抑揚・高さの味つけ
        q[k] = v
    wav = urllib.request.urlopen(urllib.request.Request(
        VOICEVOX + f"/synthesis?speaker={speaker}",
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
    """日本語の文からモーラ数を数える。READINGS で読みを上書きした語は
    pyopenjtalk が知らないので、先にカタカナに置き換えてから数える"""
    import pyopenjtalk
    for su, yomi, _ in READINGS:
        if su and su in s:
            s = s.replace(su, yomi)
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
    return _apply_readings(text, spans)


def yomi_moras(yomi):
    """カタカナの読みそのものからモーラ数を数える(小さいャュョは前の字と1モーラ)。
    上の kana_moras と違い、日本語文ではなく READINGS のカタカナを渡すこと"""
    return sum(1 for c in yomi if c not in SMALL)


def _apply_readings(text, spans):
    """ユーザー辞書で読みを変えた語は、pyopenjtalk側のモーラ数と食い違う。
    (例: NISA は解析上8モーラだが、実際は「ニーサ」で3モーラ)
    テロップが後ろにずれるので、その語の範囲だけモーラ数を差し替える"""
    import unicodedata
    low = unicodedata.normalize("NFKC", text).lower()
    if len(low) != len(text):
        return spans                     # 正規化で長さが変わったら触らない
    out = list(spans)
    for su, yomi, _ in READINGS:
        key = unicodedata.normalize("NFKC", su).lower()
        if not key:
            continue
        want, i = yomi_moras(yomi), low.find(key)
        while i >= 0:
            j = i + len(key)
            hit = [k for k, (a, b, _, _) in enumerate(out) if a < j and b > i]
            if hit:
                first = hit[0]
                for k in hit:
                    a, b, m, pos = out[k]
                    out[k] = (a, b, want if k == first else 0, pos)
            i = low.find(key, j)
    return out


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


def align_telops(q, sentence, maxlen=20, dur=None):
    """原文のチャンクに、実測のモーラ時刻を割り当てる"""
    chunks = split_chunks(sentence, maxlen)
    times  = mora_times(q)
    if dur is not None and times:
        k = dur / q_span(q)                        # 話す速さの調整ぶんを補正
        times = [t * k for t in times]
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
Style: Telop,Noto Sans CJK JP,80,&H001B2C14,&H000000FF,&H00FAFCF6,&H00FFFFFF,-1,0,0,0,100,100,1,0,1,9,0,2,90,640,84,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""

def esc(t):
    return t.replace("\\", "").replace("{", "").replace("}", "")

# テロップの表示幅。左90/右640のマージンの内側に収める必要がある。
# libassは指定サイズより小さく描くので、実測した倍率で見積もる。
TELOP_BOX   = 1180
TELOP_SIZE  = 80
ASS_RATIO   = 0.72


def telop_scale(text, box=None):
    """長すぎるテロップが画面の外に出ないよう、縮める割合を返す"""
    from PIL import ImageFont
    box = box or TELOP_BOX
    w = ImageFont.truetype(FONT_B, TELOP_SIZE).getlength(text) * ASS_RATIO
    if w <= box:
        return 100
    return max(50, int(100 * box / w))


# 字幕の出方。どれも「1回だけのなめらかな変化」にして、点滅や往復は作らない。
# 文ごとに切り替える(1文は3〜5秒あるので、ちかちかしない)
TELOP_FX = ("pop", "rise", "open", "soft", "blur", "track",
            "settle", "glow", "lean", "wide")


def telop_anim(sc, fx="pop"):
    """どれも「一方向に1回だけ」動いて終わる。行ったり来たりさせないので点滅しない"""
    s = max(10, int(sc))
    if fx == "rise":      # 下から立ち上がるように縦へ伸びる
        return f"{{\\fad(80,70)\\fscx{s}\\fscy{int(s*0.86)}\\t(0,150,\\fscy{s})}}"
    if fx == "open":      # 横にすっと開く
        return f"{{\\fad(80,70)\\fscx{int(s*0.94)}\\fscy{s}\\t(0,140,\\fscx{s})}}"
    if fx == "soft":      # ゆっくり浮かび上がるだけ
        return f"{{\\fad(170,120)\\fscx{s}\\fscy{s}}}"
    if fx == "blur":      # ぼけからピントが合う
        return f"{{\\fad(90,80)\\fscx{s}\\fscy{s}\\blur2.6\\t(0,180,\\blur0)}}"
    if fx == "track":     # 字間がすっと詰まる
        return f"{{\\fad(90,80)\\fscx{s}\\fscy{s}\\fsp5\\t(0,190,\\fsp1)}}"
    if fx == "settle":    # 少し大きめから、すっと落ち着く
        return (f"{{\\fad(80,70)\\fscx{int(s*1.06)}\\fscy{int(s*1.06)}"
                f"\\t(0,160,\\fscx{s}\\fscy{s})}}")
    if fx == "glow":      # 白フチがあとから締まる
        return f"{{\\fad(90,80)\\fscx{s}\\fscy{s}\\3a&HB4&\\t(0,220,\\3a&H00&)}}"
    if fx == "lean":      # わずかな傾きがまっすぐになる
        return f"{{\\fad(90,80)\\fscx{s}\\fscy{s}\\fax0.10\\t(0,180,\\fax0)}}"
    if fx == "wide":      # 横に少し広い状態から締まる
        return f"{{\\fad(80,70)\\fscx{int(s*1.07)}\\fscy{s}\\t(0,160,\\fscx{s})}}"
    return (f"{{\\fad(70,60)\\fscx{int(s*0.92)}\\fscy{int(s*0.92)}"
            f"\\t(0,110,\\fscx{s}\\fscy{s})}}")


def build_telops(entries, keywords, path, head=None, box=None):
    """entries: (start, end, text) / keywords: 強調する語のリスト"""
    kws = sorted({to_digits(k) for k in keywords}, key=len, reverse=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(head or ASS_HEAD)
        for e in entries:
            st, en, tx = e[0], e[1], e[2]
            col = e[3] if len(e) > 3 else "&H001B2C14"
            body = to_digits(esc(tx))
            sc   = telop_scale(body, box)
            for k in kws:
                if k and k in body:
                    body = body.replace(k, "\x01" + k + "\x02")
            body = (body.replace("\x01", r"{\c&H2A7A1E&\b1}")
                        .replace("\x02", "{\\c" + col + "\\b1}"))
            if col != "&H001B2C14":
                body = "{\\c" + col + "}" + body
            anim = telop_anim(sc, e[4] if len(e) > 4 else "pop")
            f.write(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Telop,,0,0,0,,{anim}{body}\n")

# ============ 台本の書き間違いを直す ============
# 読み上げも字幕も同じ文字列から作るので、読み込んだ直後にここを1回通す。
# 実際に動画で起きた誤りを見つけたら、この表に足していく。
TYPOS = [
    (r"こんにちわ",                      "こんにちは"),
    (r"こんばんわ",                      "こんばんは"),
    # 「こんにちなのだ」のように「は」が抜けた挨拶
    (r"こんにち(?=[なだ、。!?！？]|$)",   "こんにちは"),
    (r"こんばん(?=[なだ、。!?！？]|$)",   "こんばんは"),
    (r"おはよ(?=[なだ、。!?！？]|$)",     "おはよう"),
    # 語尾の重複
    (r"なのだのだ",                      "なのだ"),
    (r"のだのだ",                        "のだ"),
    (r"ですのだ",                        "なのだ"),
    # 全角・半角のゆれ
    (r"！！+",                           "！"),
    (r"。。+",                           "。"),
]

# 「直」と「治」の取り違え。病気・けがは「治」、それ以外は「直」
_CURE = ("(病気|風邪|かぜ|カゼ|けが|ケガ|怪我|傷|症状|痛み|体調|持病|虫歯|"
         "花粉症|不調|むし歯|やけど|骨折|捻挫|うつ|めまい|しびれ|かゆみ|腰痛|頭痛)")
_THING = ("(誤り|間違い|まちがい|ミス|故障|不具合|バグ|設定|文章|文字|字|"
          "くせ|癖|クセ|時計|パソコン|スマホ|データ|表|グラフ|書類|申告|申請|"
          "名前|住所|向き|位置|軌道|やり方|方法|手順|制度|ルール|遅れ|ずれ|"
          "誤字|脱字|配線|屋根|壁|道|レイアウト|数字|金額|条件)")
TYPOS += [
    # 病気・けがなのに「直」を使っている
    (_CURE + r"(が|は|も|を)直",                       r"\1\2治"),
    (r"直(療|癒|安|(?=まる思))",                        r"治\1"),
    # もの・誤りなのに「治」を使っている
    (_THING + r"(が|は|も|を)治",                      r"\1\2直"),
    # 複合動詞は必ず「直」
    (r"(見|立て|建て|組み|やり|作り|練り|問い|出|仕切り|思い|考え|"
     r"書き|読み|言い|やり|取り|し|とらえ|捉え|結び|やり)治(す|し|さ|そ|せ|る|り|っ|ら|れ)",
     r"\1直\2"),
    # 「〜が治す」ではなく「〜を治す」など単純な取り違えの残り
    (r"治接",                                          "直接"),
    (r"正治",                                          "正直"),
    (r"素治",                                          "素直"),
    (r"直療",                                          "治療"),
    (r"直安",                                          "治安"),
    (r"政直",                                          "政治"),
    (r"自直体",                                        "自治体"),
    (r"完直",                                          "完治"),
    (r"直外法権",                                      "治外法権"),
    # 「年100万円」「年2回」の年は「トシ」と読まれる。年間に直せばネンカンで読める。
    # 直前が数字か漢字のとき(2026年10月・昨年10月・今年3月)は年号や熟語なので触らない
    (r"(?<![0-9０-９々一-鿿])年(?=[0-9０-９])",         "年間"),
    (r"℃",                                            "度"),   # 「25℃」が「25ドシー」になる
    # 範囲の波ダッシュ。辞書で「カラ」と読ませているが、「4月〜9月」「月曜〜金曜」のように
    # 直前が漢字だと辞書が効かず読み飛ばされて「4月9月」に聞こえる。文字ごと直すのが確実
    (r"[〜～]",                                        "から"),
    # 読み飛ばされる記号。そのままだと数字だけが残って意味が変わる
    (r"(\d{4})\s*[/／.]\s*(\d{1,2})\s*[/／.]\s*(\d{1,2})", r"\1年\2月\3日"),
    (r"㎡", "平方メートル"), (r"㎥", "立方メートル"), (r"㎞", "キロメートル"),
    (r"㎏", "キログラム"), (r"㎝", "センチメートル"), (r"㎜", "ミリメートル"),
    (r"㍑", "リットル"), (r"㈱", "株式会社"), (r"№", "ナンバー"),
    (r"[▲△](?=\d)",                                  "マイナス"),   # 決算の▲5%が「5%」になる
    (r"[−–—-](?=\d+(?:\.\d+)?\s*[%％円ポ])",           "マイナス"),
    (r"¥\s*(\d[\d,]*)",                              r"\1円"),
    (r"[$＄]\s*(\d[\d,]*)",                           r"\1ドル"),
]
# 丸数字は読み飛ばされるので算用数字に開く
TYPOS += [(chr(0x2460 + i), str(i + 1)) for i in range(20)]



def fix_text(t):
    """台本のよくある書き間違いを直して返す"""
    if not isinstance(t, str):
        return t
    for pat, rep in TYPOS:
        t = re.sub(pat, rep, t)
    return t


def fix_script(script):
    """台本まるごとに fix_text をかけ、直した箇所の件数を返す"""
    hits = []
    def fx(v):
        w = fix_text(v)
        if w != v:
            hits.append((v, w))
        return w
    for sc in script.get("scenes", []):
        for k in ("title", "narration", "kicker"):
            if sc.get(k):
                sc[k] = fx(sc[k])
        if sc.get("bullets"):
            sc["bullets"] = [fx(b) for b in sc["bullets"]]
        # 会話形式のセリフ。合成のときにも fix_text は通るが、ここで直しておくと
        # 何をどう直したかがログに残る
        for ln in sc.get("lines") or []:
            if isinstance(ln, dict) and ln.get("text"):
                ln["text"] = fx(ln["text"])
            elif isinstance(ln, (list, tuple)) and len(ln) > 1 and isinstance(ln[1], str):
                ln[1] = fx(ln[1])
    # フックとショートは fix_script を通っていなかったので、ここで一緒に直す
    meta = script.get("meta") or {}
    if meta.get("hook_say"):
        meta["hook_say"] = fx(meta["hook_say"])
    if meta.get("hook_big"):
        meta["hook_big"] = [fx(x) if isinstance(x, str) else x for x in meta["hook_big"]]
    sh = script.get("short") or {}
    for k in ("title", "narration"):
        if isinstance(sh.get(k), str) and sh.get(k):
            sh[k] = fx(sh[k])
    if sh.get("bullets"):
        sh["bullets"] = [fx(b) if isinstance(b, str) else b for b in sh["bullets"]]
    for a, b in hits:
        print(f"  台本を修正: {a[:24]} -> {b[:24]}", flush=True)
    # 「10/1」「1/2」のスラッシュは読み飛ばされる(10月1日なのか2分の1なのか決められない)。
    # 直さずに知らせるだけにして、台本の書き方で避けてもらう
    import json as _json
    for m in set(re.findall(r"\d+\s*[/／]\s*\d+", _json.dumps(script, ensure_ascii=False))):
        print(f"  ⚠ 「{m}」のスラッシュは読み上げで消えるのだ。"
              f"「10月1日」「2分の1」のように書いてほしいのだ", flush=True)
    return len(hits)


# ============ 表情の自動切り替え ============
ASK  = ("？", "?", "だろうか", "のかな", "どうなる", "なぜ", "どうして", "いくら")
BANG = ("！", "!", "注意", "危険", "損", "落とし穴", "びっくり", "大事", "気をつけ", "禁止")
GOOD = ("お得", "うれしい", "便利", "安心", "おすすめ", "うまく", "できる", "覚えて")

def sentence_expr(default, sent, available, who="zunda"):
    """文の内容から表情を選ぶ。素材に無い表情は既定に戻す"""
    pick = default
    if any(k in sent for k in BANG):
        pick = "surprise"
    elif any(k in sent for k in ASK):
        pick = "think"
    elif any(k in sent for k in GOOD):
        pick = "happy"
    return pick if (who, pick, "a") in available else default


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


def _sfx(kind, sr):
    """効果音を1つ作る。すべてその場で合成しているので権利の心配がない"""
    import numpy as np

    def tone(freqs, dur, decay, amp, sweep=0.0):
        t = np.arange(int(dur * sr)) / sr
        y = np.zeros(len(t))
        for k, f in enumerate(freqs):
            ff = f * (1.0 + sweep * t / max(dur, 1e-6))
            y += np.sin(2*np.pi*ff*t) * (0.9 ** k)
        return y * np.exp(-t / decay) * amp

    if kind == "chime":        # 章の切り替わり(レ→ソ)
        return tone([1174.66, 1567.98], 0.50, 0.11, 0.20)
    if kind == "chime2":       # 同じ役割の別の音(ミ→シ)。同じ音が続く単調さを避ける
        return tone([1318.51, 1975.53], 0.46, 0.10, 0.18)
    if kind == "chime3":       # 3つ目(ソ→レ)
        return tone([1567.98, 2349.32], 0.44, 0.10, 0.16)
    if kind == "ding":         # 話が切り替わる合図(オクターブ)
        return tone([1046.50, 2093.00], 0.44, 0.12, 0.17)
    if kind == "ding2":        # もう1種類(5度)
        return tone([880.00, 1318.51], 0.42, 0.11, 0.16)
    if kind == "note":         # 語が出てくるときの、木琴のような柔らかい1音
        return tone([1174.66, 2349.32], 0.26, 0.055, 0.075)
    if kind == "okay":         # 納得・肯定(上がる3度)
        return tone([784.00, 987.77], 0.30, 0.075, 0.10, sweep=0.03)
    if kind == "warn":         # 注意を促す(低めの2音)
        return tone([311.13, 415.30], 0.34, 0.085, 0.13)
    if kind == "airy":         # シーンの終わりの、息を抜くような音
        t = np.arange(int(0.34 * sr)) / sr
        rng = np.random.default_rng(31)
        noise = np.convolve(rng.normal(0, 1, len(t)), np.ones(9) / 9, mode="same")
        return noise * np.exp(-t / 0.09) * 0.05
    if kind == "clack":        # 拍子木のような短い音
        t = np.arange(int(0.12 * sr)) / sr
        rng = np.random.default_rng(37)
        y = np.sin(2*np.pi*760*t) * 0.5 + rng.normal(0, 1, len(t)) * 0.2
        return y * np.exp(-t / 0.016) * 0.10
    if kind == "swipe":        # 画面が切り替わる感じの短い風切り
        t = np.arange(int(0.22 * sr)) / sr
        rng = np.random.default_rng(41)
        noise = rng.normal(0, 1, len(t))
        k = np.exp(-((t - 0.07) ** 2) / 0.0022)
        return noise * k * np.exp(-t / 0.10) * 0.075
    if kind.startswith("pop"):
        # 箇条書きが1つ出る。1つ目→2つ目→…で少しずつ高くして、並んでいく感じを出す
        f = {"pop1": 784.0, "pop2": 880.0, "pop3": 987.77,
             "pop4": 1108.73, "pop5": 1244.51}.get(kind, 880.0)
        return tone([f], 0.13, 0.030, 0.16, sweep=0.45)
    if kind == "tick":         # 数字や条件を1つ挙げるとき
        return tone([1396.91], 0.09, 0.018, 0.13, sweep=-0.20)
    if kind == "tick2":        # 割合やパーセントのとき(少し低い)
        return tone([1046.50], 0.09, 0.018, 0.11, sweep=-0.18)
    if kind == "sparkle2":     # 図解のもう1種類(下から上へ)
        y = np.zeros(int(0.50 * sr))
        for i, f in enumerate((1318, 1760, 2349, 2793)):
            seg = tone([f], 0.24, 0.055, 0.075)
            o = int(i * 0.042 * sr)
            y[o:o+len(seg)] += seg[:len(y)-o]
        return y
    if kind == "coin":         # 金額が出てくるとき(小さく2音)
        y = np.zeros(int(0.30 * sr))
        for i, f in enumerate((1760.0, 2637.0)):
            seg = tone([f], 0.16, 0.035, 0.075)
            o = int(i * 0.045 * sr)
            y[o:o+len(seg)] += seg[:len(y)-o]
        return y
    if kind == "coin2":        # 大きい金額のとき(3音)
        y = np.zeros(int(0.40 * sr))
        for i, f in enumerate((1318.5, 1975.5, 2637.0)):
            seg = tone([f], 0.18, 0.040, 0.070)
            o = int(i * 0.050 * sr)
            y[o:o+len(seg)] += seg[:len(y)-o]
        return y
    if kind == "blip":         # 話し手が入れ替わるとき。ごく小さく
        return tone([1046.50], 0.08, 0.020, 0.055, sweep=0.25)
    if kind == "wood":         # 一区切りついたとき。木を打つような短い音
        t = np.arange(int(0.16 * sr)) / sr
        rng = np.random.default_rng(23)
        y = np.sin(2*np.pi*520*t) * 0.6 + rng.normal(0, 1, len(t)) * 0.25
        return y * np.exp(-t / 0.022) * 0.12
    if kind == "bell":         # まとめに入るとき
        y = np.zeros(int(0.90 * sr))
        for i, f in enumerate((1046.50, 1318.51, 1567.98)):
            seg = tone([f], 0.60, 0.16, 0.10)
            o = int(i * 0.10 * sr)
            y[o:o+len(seg)] += seg[:len(y)-o]
        return y
    if kind == "question":     # 疑問を投げかけるところ(上がる2音)
        return tone([659.26, 987.77], 0.34, 0.09, 0.14, sweep=0.05)
    if kind == "swell":        # やわらかく場面が開く
        t = np.arange(int(0.55 * sr)) / sr
        env = np.minimum(t / 0.22, 1.0) * np.exp(-np.maximum(t - 0.22, 0) / 0.16)
        y = np.zeros(len(t))
        for k, f in enumerate((392.0, 587.33, 784.0)):
            y += np.sin(2*np.pi*f*t) * (0.7 ** k)
        return y * env * 0.075
    if kind == "sparkle":      # 図解が出る
        y = np.zeros(int(0.55 * sr))
        for i, f in enumerate((1568, 2093, 2637)):
            seg = tone([f], 0.30, 0.070, 0.11)
            o = int(i * 0.055 * sr)
            y[o:o+len(seg)] += seg[:len(y)-o]
        return y
    if kind == "whoosh":       # 章の扉
        t = np.arange(int(0.42 * sr)) / sr
        rng = np.random.default_rng(7)
        noise = rng.normal(0, 1, len(t))
        k = np.exp(-((t - 0.12) ** 2) / 0.006)          # さっと通り過ぎる感じ
        return noise * k * np.exp(-t / 0.18) * 0.10
    if kind == "page":         # 章の扉のもう一種類。紙をめくるような短い音
        t = np.arange(int(0.26 * sr)) / sr
        rng = np.random.default_rng(11)
        noise = rng.normal(0, 1, len(t))
        noise = np.convolve(noise, np.ones(5) / 5, mode="same")   # 高域を少し丸める
        return noise * np.exp(-t / 0.055) * 0.085
    if kind == "thud":         # ここ大事、という強調
        return tone([146.83, 220.0], 0.42, 0.10, 0.15)
    return np.zeros(1)


def make_sfx_track(total, sfx, path, sr=24000):
    """効果音だけを並べた1本のwav。BGMと違ってナレーション中も絞らないので、
    箇条書きが出た瞬間などにちゃんと聞こえる"""
    import numpy as np
    n = int(total * sr) + sr
    out = np.zeros(n, dtype=np.float32)
    cache = {}
    for m in sfx:
        at, kind = m if isinstance(m, (tuple, list)) else (m, "chime")
        s0 = int(at * sr)
        if s0 <= 0 or s0 >= n:
            continue
        if kind not in cache:
            cache[kind] = _sfx(kind, sr)
        y = cache[kind]
        s1 = min(n, s0 + len(y))
        out[s0:s1] += y[:s1 - s0]
    peak = float(np.max(np.abs(out)))
    if peak > 0.95:
        out = out / peak * 0.95
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((out * 32767).astype(np.int16).tobytes())
    return path


def _finish_bed(out, marks, path, sr, normalize):
    """効果音を重ね、前後をフェードして書き出す。
    marks は (秒, 種類) の並び。秒だけ渡された場合は章の切り替わりとして扱う"""
    import numpy as np
    n = len(out)
    cache = {}
    for m in marks:
        at, kind = m if isinstance(m, (tuple, list)) else (m, "chime")
        s0 = int(at * sr)
        if s0 <= 0 or s0 >= n:
            continue
        if kind not in cache:
            cache[kind] = _sfx(kind, sr)
        y = cache[kind]
        s1 = min(n, s0 + len(y))
        out[s0:s1] += y[:s1 - s0]

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
    fix_script(script)
    scenes = script["scenes"]
    chars  = render_character_frames()

    TELOP_MAX = 22      # テロップ1枚の最大文字数
    GAP       = 0.34    # 文と文のあいだ

    clock = 0.0
    telops, mouth_seq, slide_seq, audio_files, chapters = [], [], [], [], []
    all_kw, sfx = [], []          # sfx: (秒, 効果音の種類)
    fx_no = [0]                   # 字幕の出方を文ごとに回すための番号
    last_sfx, prev_who = [-9.0], [None]   # 効果音が近づきすぎないようにする

    cast     = cast_of(script)
    dialogue = any(sc.get("lines") for sc in scenes)

    def scene_lines(sc):
        """シーンを (話者キー, 一文) の並びにほぐす"""
        out = []
        if sc.get("lines"):
            for ln in sc["lines"]:
                if isinstance(ln, (list, tuple)):
                    who, text = ln[0], ln[1]
                else:
                    who, text = ln.get("who", "zunda"), ln.get("text", "")
                who = who if who in cast else "guest"
                for x in re.split(r"(?<=[。！？])", fix_text(text)):
                    if x.strip():
                        out.append((who, x))
        else:
            for x in re.split(r"(?<=[。！？])", sc.get("narration", "")):
                if x.strip():
                    out.append(("zunda", x))
        if not out:
            # キー名を間違えると、何も言わない0秒のシーンが静かにできてしまう
            print(f'  ⚠ セリフが空のシーンがあるのだ: 「{sc.get("title", "(無題)")}」'
                  f' … lines か narration を入れてほしいのだ'
                  f'(使われたキー: {", ".join(sc.keys())})')
        return out

    # まず全シーンの尺を出す(進捗バーに全体の長さが要るため)
    plan = []            # [(scene, [(who, 表情, sent, wav, q, dur), ...], scene_dur)]
    for i, sc in enumerate(scenes, 1):
        items, scene_dur = [], 0.0
        base_expr = sc.get("expression", "normal")
        for j, (who, sent) in enumerate(scene_lines(sc)):
            wav = f"{workdir}/a{i:02d}_{j:02d}.wav"
            # 文の中身から表情を決め、声も同じ表情に合わせる
            e2 = sentence_expr(base_expr, sent, chars, who)
            c  = cast[who]
            spk = (c.get("styles") or {}).get(e2, c["speaker"])
            tune = dict(TUNE.get(e2, {}))
            tune["pitchScale"] = round(tune.get("pitchScale", 0.0) + c.get("pitch", 0.0), 3)
            q, dur = synth(sent, wav, spk, tune)
            items.append((who, e2, sent, wav, q, dur))
            scene_dur += dur + GAP
        plan.append((sc, items, scene_dur))
        print(f"  {i:02d}. {scene_dur:6.1f}秒  {sc['title']}", flush=True)
    total_dur = sum(p[2] for p in plan) or 1.0

    # 章(背景パレットのまとまり)の先頭シーンを覚えておく
    card_at, nparts, seen = {}, 0, set()
    for i in range(1, len(plan) + 1):
        key = group_of(i)[0]
        if key not in seen:
            seen.add(key)
            nparts += 1
            if i > 1 or len(plan) > 4:     # 1本目から扉を出す
                card_at[i] = nparts
    nparts = max(nparts, 1)

    for i, (sc, items, scene_dur) in enumerate(plan, 1):
        all_kw += sc.get("keywords", [])
        nb = len(sc.get("bullets", []))
        scene_expr = sc.get("expression", "normal")
        sent_dur, prev_shown = 0.0, -1

        for j, (who, e2, sent, wav, q, dur) in enumerate(items):
            audio_files.append(wav)
            # 立ち絵はシーンの表情のまま動かさない(体ごと切り替わると落ち着かない)
            vis = scene_expr if (who, scene_expr, "x") in chars else "normal"
            mouth_seq += mouth_frames(chars, who, vis, q, dur)
            # 文と文のあいだの無音ぶんも口を閉じたまま埋める。
            # これを入れないと立ち絵だけ短くなって口パクが少しずつずれる
            mouth_seq.append((pick_frame(chars, who, vis, "x"), GAP))

            base = clock + sent_dur
            col  = cast[who]["color"]
            # 出方は文ごとに変える。1文のなかでは同じにして落ち着かせる
            fx   = TELOP_FX[fx_no[0] % len(TELOP_FX)]
            fx_no[0] += 1
            for st, en, tx in align_telops(q, sent, TELOP_MAX, dur):
                telops.append((base + st, base + en, tx, col, fx))

            # 文が進むごとに箇条書きを1つずつ出す
            shown = nb if len(items) <= 1 else min(nb, j)
            png = f"{workdir}/s{i:02d}_{j:02d}.png"
            prog = (clock + sent_dur) / total_dur
            at = clock + sent_dur
            last_scene = (i == len(scenes))
            spk2 = "sparkle" if i % 2 == 0 else "sparkle2"
            if j == 0 and i in card_at:
                # 章の扉。3種類を順に回して、同じ音の繰り返しにしない
                sfx.append((at, ("whoosh", "page", "swipe")[i % 3]))
            elif j == 0:
                if last_scene:
                    sfx.append((at, "bell"))         # まとめに入る
                elif sc.get("expression") == "surprise":
                    sfx.append((at, "thud"))         # 注意を促すシーン
                elif sc.get("expression") == "think":
                    sfx.append((at, "question"))     # 問いを立てるシーン
                else:
                    sfx.append((at, ("chime", "chime2", "ding",
                                     "chime3", "ding2")[i % 5]))
                if nb == 0 and figure_spec(sc):
                    sfx.append((at + 0.35, spk2))    # 箇条書きの無い図解シーン
            elif 1 <= shown <= nb and shown != prev_shown:
                # 1つ目→2つ目→…と音を上げていく
                sfx.append((at, f"pop{min(5, shown)}"))
                if shown == nb and figure_spec(sc):
                    sfx.append((at + 0.12, spk2))    # 図解が出る
            prev_shown = shown

            # 文の中身に応じた差し込み。近すぎる音は捨てるので、うるさくはならない
            last_sfx[0] = max((x[0] for x in sfx), default=-9.0)

            def _add(t, kind, gap=0.45):
                if t - last_sfx[0] >= gap:
                    sfx.append((t, kind))
                    last_sfx[0] = t

            cands = []
            if j > 0 and who != prev_who[0]:
                cands.append((at + 0.02, "blip"))                  # 話し手が交代
            if re.search(r"注意|気をつけ|危険|間違|うっかり|落とし穴|忘れ", sent):
                cands.append((at + dur * 0.24, "warn"))            # 注意を促す
            if re.search(r"そうなのだ|そのとおり|正解|そのはず|できるのだ", sent):
                cands.append((at + dur * 0.30, "okay"))            # 納得・肯定
            if re.search(r"[0-9]", sent):
                if "円" in sent:
                    big = re.search(r"[0-9]{6,}|[0-9]\s*[万億兆]", sent)
                    cands.append((at + dur * 0.42, "coin2" if big else "coin"))
                elif re.search(r"[%％]|割", sent):
                    cands.append((at + dur * 0.42, "tick2"))
                else:
                    cands.append((at + dur * 0.42, "tick"))
            if any(k and str(k) in sent for k in (sc.get("keywords") or [])):
                cands.append((at + dur * 0.64, "note"))            # 強調する語が出た
            elif re.search(r"つまり|実は|ところが|だから|なぜなら", sent):
                cands.append((at + dur * 0.20, "note"))            # 話の切り替え
            if re.search(r"^まず|次に|最後に|1つ目|2つ目|3つ目|ここが", sent):
                cands.append((at + dur * 0.12, "clack"))           # 順番に挙げる
            tail = sent.rstrip()
            if tail.endswith(("!", "！")):
                cands.append((at + dur * 0.88, "wood"))
            elif tail.endswith(("?", "？")) or tail.endswith(("かしら。", "のかな。", "だろうか。")):
                cands.append((at + dur * 0.88, "question"))
            if j == len(items) - 1 and not last_scene:
                cands.append((at + dur + GAP * 0.4, "airy"))       # シーンの締め
            for t2, k2 in sorted(cands):
                _add(t2, k2)
            prev_who[0] = who
            if j == 0 and i in card_at:
                # 章の変わり目は扉を1文だけ挟んで、同じ画づらが続く単調さを切る
                draw_chapter_card(sc, i, len(scenes), script.get("chapter", ""), png,
                                  card_at[i], nparts, progress=prog)
            else:
                draw_slide(sc, i, len(scenes), script.get("chapter", ""), png,
                           shown=shown, progress=prog,
                           speaker=cast[who]["name"] if dialogue else None,
                           badge=badge_rgb(cast[who]) if dialogue else None)
            slide_seq.append((png, dur + GAP))
            sent_dur += dur + GAP

        chapters.append((sc["title"], clock, scene_dur))
        clock += scene_dur

    # 1フレームに満たないコマは前にまとめる。
    # 切り上げていると全体が伸びて口パクがずれるため
    merged = []
    for pth, dd in mouth_seq:
        if merged and dd < 0.034:
            merged[-1] = (merged[-1][0], merged[-1][1] + dd)
        else:
            merged.append((pth, dd))
    mouth_seq = merged

    m_tot = sum(d for _, d in mouth_seq)
    v_tot = sum(d for _, d in slide_seq)
    print(f"\n合計 {clock/60:.1f}分 / テロップ {len(telops)}枚 / スライド {len(slide_seq)}枚 / 立ち絵 {len(mouth_seq)}コマ", flush=True)
    if abs(m_tot - v_tot) > 1.5:
        print(f"  ⚠ 立ち絵とスライドの長さがずれている: {m_tot:.1f}秒 vs {v_tot:.1f}秒", flush=True)

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
    bed = sfx_wav = None
    if script.get("bgm", True):
        try:
            adur = wav_duration(f"{workdir}/audio.wav")
            bed = make_audio_bed(adur, [], f"{workdir}/bed.wav")
            sfx_wav = make_sfx_track(adur, sfx, f"{workdir}/sfx.wav")
            print(f"  効果音 {len(sfx)}か所", flush=True)
            print("  BGMを用意したのだ", flush=True)
        except Exception as e:
            bed = sfx_wav = None
            print(f"  BGMなしで続行: {type(e).__name__}: {e}", flush=True)

    vfilter = (f"[0:v]scale={W}:{H},fps=30[bg];"
               f"[1:v]scale={CHAR_W}:{CHAR_H},fps=30[ch];"
               f"[bg][ch]overlay={CHAR_X}:{CHAR_Y}:shortest=0[v];"
               f"[v]ass={workdir}/telop.ass,format=yuv420p[vo]")

    # YouTubeの基準(-14 LUFS)に合わせる。これをしないと他チャンネルより音が小さい
    MONO = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
    NORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=24000"

    # ナレーションが鳴っているあいだBGMを自動で下げる(サイドチェイン)
    # [3]=BGM(ナレーション中は自動で下がる) [4]=効果音(下げない)
    AF_DUCK = (f"[2:a]{MONO},asplit=2[na][sc];"
               f"[3:a]{MONO},volume=0.15[bd];"
               f"[4:a]{MONO},volume=0.55[sx];"
               f"[bd][sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350[bdd];"
               f"[na][bdd][sx]amix=inputs=3:duration=first:normalize=0,{NORM}[ao]")
    AF_FLAT = (f"[2:a]{MONO}[na];[3:a]{MONO},volume=0.055[bd];"
               f"[4:a]{MONO},volume=0.5[sx];"
               f"[na][bd][sx]amix=inputs=3:duration=first:normalize=0,{NORM}[ao]")
    AF_BARE = f"[2:a]{MONO},{NORM}[ao]"

    def encode(afilter, with_bed):
        cmd = ["ffmpeg","-y","-v","error",
               "-f","concat","-safe","0","-i",f"{workdir}/v.txt",
               "-f","concat","-safe","0","-i",f"{workdir}/c.txt",
               "-i",f"{workdir}/audio.wav"]
        if with_bed:
            cmd += ["-i", bed, "-i", sfx_wav]
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


# ============ ショート動画(縦) ============
SW, SH = 1080, 1920
# 2026-09-06の実測で、26秒・速い読み・間0.10秒に変えたショートは
# 平均視聴が7.4秒→4.6秒、維持率21.0%→16.3%と下がった。速さと短さは効かなかったので戻す。
# よく見られた回は28〜39秒・ふつうの速さだった(106万円の壁29秒で維持35.8%など)
SHORT_MAX    = 40.0       # ここを超えたら打ち切る
SHORT_TARGET = 32.0       # 狙う尺
SHORT_GAP    = 0.18       # 文と文の間
SHORT_SPEED  = 1.00       # 速さは本編と同じ
SHORT_LOOP   = 0.85       # 末尾に冒頭の絵を戻してループを自然につなぐ秒数

SHORT_ASS = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SW}
PlayResY: {SH}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Telop,Noto Sans CJK JP,72,&H00FFFFFF,&H000000FF,&H00203010,&H00FFFFFF,-1,0,0,0,100,100,1,0,1,10,0,2,50,50,118,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


def short_spec(script):
    """ショートに使う中身を決める。script["short"] があればそれを使い、
    無ければ本編のフックとまとめから組み立てる"""
    sp = dict(script.get("short") or {})
    meta = script.get("meta", {})
    scenes = script.get("scenes", [])
    if not sp.get("narration"):
        # まとめではなくフックを軸にする。まとめから作ると「振り返り」になって
        # 冒頭で切られるため、結論→理由→ひとこと の順に組む
        say = meta.get("hook_say", "")
        pool = say + "".join(scene_text(sc) for sc in scenes[1:4])
        out = ""
        for sent in re.split(r"(?<=[。！？])", pool):
            if not sent.strip():
                continue
            if len(out) + len(sent) > 190:   # 文の途中で切らない
                break
            out += sent
        sp["narration"] = out or pool[:190]
    if not sp.get("title"):
        sp["title"] = (meta.get("hook_big") or [None])[0] or script.get("chapter", "")
    if not sp.get("bullets"):
        # 最後のまとめより、本編前半の要点のほうが結論として強い
        for sc in scenes[1:]:
            if sc.get("bullets"):
                sp["bullets"] = sc["bullets"]
                break
        sp.setdefault("bullets", (scenes[-1].get("bullets") if scenes else []) or [])
    return sp


def scene_text(sc):
    """シーンの読み上げ文をつなげて返す(会話形式にも対応)"""
    if sc.get("lines"):
        return "".join(str(x.get("text", "")) for x in sc["lines"])
    return str(sc.get("narration", ""))


def draw_short_slide(sp, chapter, path, shown, progress, acc, remain=None):
    """縦画面の1枚。上に見出し、真ん中に要点、下は立ち絵とテロップ。
       remain は残り秒数。残り時間バーは出さない(残りが見えると離脱するため)"""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    imgs = bg_images()
    if imgs:
        src = Image.open(imgs[0]).convert("RGB")
        k = max(SW / src.width, SH / src.height)
        src = src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS)
        ox, oy = (src.width - SW) // 2, (src.height - SH) // 2
        img = src.crop((ox, oy, ox + SW, oy + SH)).filter(ImageFilter.GaussianBlur(7))
        img = Image.alpha_composite(img.convert("RGBA"),
                                    Image.new("RGBA", (SW, SH), (255, 255, 255, 120)))
    else:
        img = Image.new("RGBA", (SW, SH), (244, 249, 238, 255))
    d = ImageDraw.Draw(img, "RGBA")

    # 上の帯
    d.rectangle([0, 0, SW, 14], fill=acc)
    d.rectangle([0, 14, SW, 104], fill=(255, 255, 255, 190))
    d.text((44, 40), chapter[:22], font=ImageFont.truetype(FONT_R, 34), fill=INK_SOFT)

    # 「結論」のしるし(1コマ目から見えるようにする)
    f_chip = ImageFont.truetype(FONT_B, 34)
    cw = int(d.textlength("結論", font=f_chip)) + 44
    d.rounded_rectangle([55, 124, 55 + cw, 124 + 52], radius=12, fill=acc)
    d.text((55 + cw // 2, 150), "結論", font=f_chip, fill=(255, 255, 255), anchor="mm")

    # 見出し
    title = " ".join(to_digits(str(sp.get("title", ""))).split())
    lines, f_t, sz = None, None, 54
    for want in (2, 3):
        for sz in (82, 74, 68, 62, 56, 50):
            f_t = ImageFont.truetype(FONT_B, sz)
            lines = wrap(title, f_t, SW - 110)
            if len(lines) <= want:
                break
        if len(lines) <= want:
            break
    y = 200
    for ln in lines:
        d.text((55, y), ln, font=f_t, fill=INK)
        y += int(sz * 1.24)
    y += 10
    d.rectangle([55, y, 205, y + 8], fill=acc)
    y += 60

    # 要点(読み上げに合わせて1つずつ)
    bl = [to_digits(b) for b in sp.get("bullets", [])][:4]
    n  = len(bl) if shown is None else max(0, min(shown, len(bl)))
    for sz in (52, 46, 42, 38):
        f_b = ImageFont.truetype(FONT_R, sz)
        rows = [wrap(b, f_b, SW - 190) for b in bl]
        if sum(len(r) for r in rows) * int(sz * 1.34) + len(rows) * 30 <= 1180 - y:
            break
    for k2, b in enumerate(bl[:n]):
        fresh = (k2 == n - 1)
        d.rounded_rectangle([58, y + 12, 58 + int(sz*0.34), y + 12 + int(sz*0.34)],
                            radius=5, fill=acc if fresh else acc + (150,))
        for ln in rows[k2]:
            d.text((110, y), ln, font=f_b, fill=INK if fresh else INK_SOFT)
            y += int(sz * 1.34)
        y += 30

    # 終わりぎわに登録の誘導(ショートは登録につながりにくいので明示する)
    if remain is not None and remain <= 3.4:
        a = int(235 * min(1.0, (3.4 - remain) / 0.8))
        # 立ち絵は右下(x=590〜)に重なるので、左側の空きに置く
        t = "登録で毎日届くのだ"
        for cs in (46, 42, 38, 34, 30):
            f_cta = ImageFont.truetype(FONT_B, cs)
            tw = d.textlength(t, font=f_cta)
            if tw <= 460:
                break
        bw, bh = int(tw) + 64, int(cs * 2.1)
        bx, by = 40, SH - 620
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=acc + (a,))
        d.text((bx + bw // 2, by + bh // 2), t, font=f_cta,
               fill=(255, 255, 255, a), anchor="mm")

    # 下のテロップ帯
    d.rectangle([0, SH - 290, SW, SH], fill=(24, 44, 22, 214))
    d.rectangle([0, SH - 294, SW, SH - 286], fill=acc)
    # 残り時間バーは出さない。あと何秒あるかが見えると、そこで離脱されるため
    img.convert("RGB").save(path)


def build_short(script_path, out_path, workdir=None):
    """本編と同じ台本から、縦型のショート動画を1本作る"""
    workdir = workdir or os.path.join(ROOT, ".cache", "short")
    os.makedirs(workdir, exist_ok=True)
    script = json.load(open(script_path, encoding="utf-8"))
    fix_script(script)
    sp    = short_spec(script)
    cast  = cast_of(script)
    chars = render_character_frames()
    acc   = GROUPS[0][4]
    chapter = script.get("chapter", "")
    GAP = SHORT_GAP

    sents = [x for x in re.split(r"(?<=[。！？])", sp["narration"]) if x.strip()]
    items, clock = [], 0.0
    for j, sent in enumerate(sents):
        wav = f"{workdir}/s{j:02d}.wav"
        e2  = sentence_expr("normal", sent, chars, "zunda")
        spk = CAST["zunda"]["styles"].get(e2, 3)
        tn  = dict(TUNE.get(e2) or {})
        tn["speedScale"] = tn.get("speedScale", 1.0) * SHORT_SPEED
        q, dur = synth(sent, wav, spk, tn)
        # 狙いは SHORT_TARGET 秒。1文目だけは SHORT_MAX まで許して空を防ぐ
        cap = SHORT_TARGET if items else SHORT_MAX
        if clock + dur + GAP > cap:
            break
        items.append((e2, sent, wav, q, dur))
        clock += dur + GAP
    if not items:
        raise RuntimeError("ショートに入れる文がない")
    if len(items) < len(sents):
        print(f"  ナレーションが長いので{len(items)}/{len(sents)}文で打ち切り "
              f"({clock:.1f}秒)。台本の short.narration は"
              f"{int(SHORT_TARGET)}秒(150字前後)に収めるとよい")

    telops, mouth_seq, slide_seq, audio, t = [], [], [], 0.0, 0.0
    nb = len(sp.get("bullets", [])[:4])
    for j, (e2, sent, wav, q, dur) in enumerate(items):
        audio_f = wav
        mouth_seq += mouth_frames(chars, "zunda", e2, q, dur)
        mouth_seq.append((pick_frame(chars, "zunda", e2, "x"), GAP))
        fx = TELOP_FX[j % len(TELOP_FX)]
        for st, en, tx in align_telops(q, sent, 16, dur):
            telops.append((t + st, t + en, tx, "&H00FFFFFF", fx))
        png = f"{workdir}/f{j:02d}.png"
        shown = nb if len(items) <= 1 else min(nb, j)
        draw_short_slide(sp, chapter, png, shown, (t + dur) / clock, acc,
                         remain=clock - (t + dur))
        slide_seq.append((png, dur + GAP))
        t += dur + GAP

    # 末尾に1コマ目を戻す。ループ再生でつながって見えるので2周目に入りやすい
    loop_png = f"{workdir}/floop.png"
    draw_short_slide(sp, chapter, loop_png, 0, 0.0, acc, remain=99)
    slide_seq.append((loop_png, SHORT_LOOP))
    mouth_seq.append((pick_frame(chars, "zunda", "normal", "x"), SHORT_LOOP))
    clock += SHORT_LOOP

    sil = f"{workdir}/sil.wav"
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","anullsrc=r=24000:cl=mono",
                    "-t",str(GAP),sil],check=True)
    sil2 = f"{workdir}/sil_loop.wav"
    subprocess.run(["ffmpeg","-y","-v","error","-f","lavfi","-i","anullsrc=r=24000:cl=mono",
                    "-t",str(SHORT_LOOP),sil2],check=True)
    with open(f"{workdir}/a.txt","w") as f:
        for _, _, w2, _, _ in items:
            f.write(f"file '{w2}'\nfile '{sil}'\n")
        f.write(f"file '{sil2}'\n")
    subprocess.run(["ffmpeg","-y","-v","error","-f","concat","-safe","0",
                    "-i",f"{workdir}/a.txt",f"{workdir}/audio.wav"],check=True)
    with open(f"{workdir}/v.txt","w") as f:
        for p2,d2 in slide_seq: f.write(f"file '{p2}'\nduration {d2:.3f}\n")
        f.write(f"file '{slide_seq[-1][0]}'\n")
    with open(f"{workdir}/c.txt","w") as f:
        for p2,d2 in mouth_seq: f.write(f"file '{p2}'\nduration {max(d2,0.02):.3f}\n")
        f.write(f"file '{mouth_seq[-1][0]}'\n")
    build_telops(telops, [], f"{workdir}/telop.ass", head=SHORT_ASS, box=980)

    bed = None
    try:
        bed = make_audio_bed(wav_duration(f"{workdir}/audio.wav"), [], f"{workdir}/bed.wav")
    except Exception:
        bed = None

    CW2, CH2 = 470, 884
    vf = (f"[0:v]scale={SW}:{SH},fps=30[bg];"
          f"[1:v]scale={CW2}:{CH2},fps=30[ch];"
          f"[bg][ch]overlay={SW-CW2-20}:{SH-CH2-210}:shortest=0[v];"
          f"[v]ass={workdir}/telop.ass,format=yuv420p[vo]")
    MONO = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
    NORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=24000"
    cmd = ["ffmpeg","-y","-v","error",
           "-f","concat","-safe","0","-i",f"{workdir}/v.txt",
           "-f","concat","-safe","0","-i",f"{workdir}/c.txt",
           "-i",f"{workdir}/audio.wav"]
    if bed:
        cmd += ["-i", bed, "-filter_complex", vf + ";" +
                f"[2:a]{MONO}[na];[3:a]{MONO},volume=0.10[bd];"
                f"[na][bd]amix=inputs=2:duration=first:normalize=0,{NORM}[ao]"]
    else:
        cmd += ["-filter_complex", vf + f";[2:a]{MONO},{NORM}[ao]"]
    cmd += ["-map","[vo]","-map","[ao]",
            "-c:v","libx264","-preset","veryfast","-crf","22",
            "-c:a","aac","-b:a","160k","-ar","24000","-ac","1","-shortest", out_path]
    subprocess.run(cmd, check=True)
    return clock
