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
        "第一","唯一","同一","統一","単一","均一","万一","一日中","一人ひとり",
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
    def repl(m):
        run, start, end = m.group(0), m.start(), m.end()
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

def draw_slide(scene, idx, total, chapter, path):
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

    # 箇条書き
    for b in scene.get("bullets", []):
        d.rounded_rectangle([259, y + 8, 275, y + 24], radius=4, fill=acc)
        for i, line in enumerate(wrap(to_digits(b), f_body, 960)):
            d.text((310, y), line, font=f_body, fill=INK if i == 0 else INK_SOFT)
            y += 58
        y += 22

    # テロップ帯
    d.rectangle([0, 872, W, H], fill=(252, 253, 248, 232))
    d.rectangle([0, 872, W, 876], fill=acc)
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
    """maxlen付近で助詞などの自然な切れ目を探す"""
    lo = max(5, int(maxlen * 0.5))
    for i in range(min(maxlen, len(s) - 1), lo, -1):
        if s[i - 1] in BREAK_AFTER:
            return i
    return maxlen


def split_chunks(text, maxlen):
    """テロップ1枚ぶんに刻む(句読点優先、長い場合は助詞で切る)"""
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

    # 極端に短い切れ端は前のテロップに吸収させる
    merged = []
    for c in chunks:
        if merged and len(c) <= 4 and len(merged[-1]) + len(c) <= maxlen + 6:
            merged[-1] += c
        else:
            merged.append(c)
    return merged


def align_telops(q, sentence, maxlen=20):
    """原文のチャンクに、実測のモーラ時刻を割り当てる"""
    chunks = split_chunks(sentence, maxlen)
    times  = mora_times(q)
    if not chunks or not times: return []
    counts = [kana_moras(c) for c in chunks]
    tot, N = sum(counts), len(times)
    out, acc, st = [], 0, q.get("prePhonemeLength", 0.1)
    for c, n in zip(chunks, counts):
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

    for i, sc in enumerate(scenes, 1):
        png = f"{workdir}/slide{i:02d}.png"
        draw_slide(sc, i, len(scenes), script.get("chapter", ""), png)
        expr = sc.get("expression", "normal")
        all_kw += sc.get("keywords", [])
        scene_dur = 0.0

        for j, sent in enumerate([s for s in re.split(r"(?<=[。！？])", sc["narration"]) if s.strip()]):
            wav = f"{workdir}/a{i:02d}_{j:02d}.wav"
            q, dur = synth(sent, wav)
            audio_files.append(wav)
            # モーラの母音に合わせて口の形を切り替える(口パク)
            for shape, ln in mouth_track(q):
                if ln > 0.01:
                    mouth_seq.append((chars[(expr, shape)], ln))

            base = clock + scene_dur
            for st, en, tx in align_telops(q, sent, TELOP_MAX):
                telops.append((base + st, base + en, tx))

            scene_dur += dur + GAP

        chapters.append((sc["title"], clock, scene_dur))
        slide_seq.append((png, scene_dur))
        clock += scene_dur
        print(f"  {i:02d}. {scene_dur:6.1f}秒  {sc['title']}", flush=True)

    print(f"\n合計 {clock/60:.1f}分 / テロップ {len(telops)}枚 / 立ち絵 {len(mouth_seq)}コマ", flush=True)

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

    print("エンコード開始...", flush=True)
    subprocess.run([
        "ffmpeg","-y","-v","error",
        "-f","concat","-safe","0","-i",f"{workdir}/v.txt",
        "-f","concat","-safe","0","-i",f"{workdir}/c.txt",
        "-i",f"{workdir}/audio.wav",
        "-filter_complex",
          f"[0:v]scale={W}:{H},fps=30[bg];"
          f"[1:v]scale={CHAR_W}:{CHAR_H},fps=30[ch];"
          f"[bg][ch]overlay={CHAR_X}:{CHAR_Y}:shortest=0[v];"
          f"[v]ass={workdir}/telop.ass,format=yuv420p[vo]",
        "-map","[vo]","-map","2:a",
        "-c:v","libx264","-preset","veryfast","-crf","22",
        "-c:a","aac","-b:a","160k","-shortest", out_path],check=True)
    print(f"完成: {out_path}", flush=True)
    return {"duration": clock, "chapters": chapters, "telops": len(telops)}


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
