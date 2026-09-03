#!/usr/bin/env python3
"""オープニング映像を作る。
   立ち絵が下からせり上がり、チャンネル名がポップし、最後に白く飛ばして本編へつなぐ。
   ナレーションはずんだもんで、口パクも本編と同じ仕組みで動かす。"""
__VERSION__ = "2026-09-03a"
import json, math, os, subprocess, urllib.parse, urllib.request, wave

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "assets", "frames")
W, H, FPS = 1920, 1080, 30
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

BG1, BG2 = (26, 62, 30), (12, 30, 16)
ACC, GOLD, INK = (140, 214, 108), (250, 216, 96), (255, 255, 255)


def ease_out(t):   return 1 - (1 - t) ** 3
def ease_back(t):                       # 少し行き過ぎて戻る
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _synth(base, text, speaker, path):
    q = json.loads(urllib.request.urlopen(
        base + "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": speaker}),
        data=b"", timeout=90).read())
    wav = urllib.request.urlopen(urllib.request.Request(
        base + f"/synthesis?speaker={speaker}", data=json.dumps(q).encode(),
        headers={"Content-Type": "application/json"}), timeout=300).read()
    open(path, "wb").write(wav)
    with wave.open(path) as w:
        return q, w.getnframes() / w.getframerate()


VOWEL = {"a": "a", "A": "a", "i": "i", "I": "i", "u": "u",
         "U": "u", "e": "e", "E": "e", "o": "o", "O": "o"}


def _mouth_at(q, t):
    """時刻tでの口の形"""
    cur = q.get("prePhonemeLength", 0.1)
    if t < cur:
        return "x"
    for ap in q["accent_phrases"]:
        for mo in ap["moras"]:
            d = (mo.get("consonant_length") or 0) + mo["vowel_length"]
            if t < cur + d:
                return VOWEL.get(mo["vowel"], "x")
            cur += d
        pm = ap.get("pause_mora")
        if pm:
            cur += (pm.get("consonant_length") or 0) + pm["vowel_length"]
    return "x"


def _background():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    y = np.linspace(0, 1, H)[:, None]; x = np.linspace(0, 1, W)[None, :]
    t = y * 0.7 + x * 0.3
    a, b = np.array(BG1, float), np.array(BG2, float)
    img = Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8)).convert("RGBA")
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(rays)
    for i in range(30):
        a0 = i * 2 * math.pi / 30; a1 = a0 + math.pi / 30 * 0.8; R = 2200
        d.polygon([(760, 470), (760 + R*math.cos(a0), 470 + R*math.sin(a0)),
                   (760 + R*math.cos(a1), 470 + R*math.sin(a1))], fill=ACC + (26,))
    img = Image.alpha_composite(img, rays)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([1180, 120, 1980, 920], fill=ACC + (60,))
    return Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90))).convert("RGB")


def build(out_path, channel_name="ずんだもん解説", tagline="気になるあれこれを10分で",
          narration=None, speaker=3, voicevox="http://127.0.0.1:50021", workdir=None):
    from PIL import Image, ImageDraw, ImageFont
    workdir = workdir or os.path.join(ROOT, ".cache", "op")
    os.makedirs(workdir, exist_ok=True)
    narration = narration or f"{channel_name}なのだ。{tagline}お届けするのだ。"

    wav = os.path.join(workdir, "op.wav")
    q, vdur = _synth(voicevox, narration, speaker, wav)
    dur = max(4.2, vdur + 0.9)
    n = int(dur * FPS)

    bg = _background()
    mouths = {v: Image.open(os.path.join(FRAMES, f"happy_{v}.png")).convert("RGBA")
              for v in ("a", "i", "u", "e", "o", "x")}
    cw = 520
    ch = int(mouths["x"].height * cw / mouths["x"].width)
    mouths = {k: v.resize((cw, ch), Image.LANCZOS) for k, v in mouths.items()}

    # チャンネル名が長いときは立ち絵にかからないよう自動で縮める
    MAXW = 1120
    base_sz = 150
    while base_sz > 60 and ImageFont.truetype(FB, base_sz).getlength(channel_name) > MAXW:
        base_sz -= 4
    f_name = ImageFont.truetype(FB, base_sz)
    f_tag  = ImageFont.truetype(FM, 54)
    f_sub  = ImageFont.truetype(FM, 34)

    for i in range(n):
        t = i / FPS
        fr = bg.copy()

        # 立ち絵: 下からせり上がって少し弾む
        p = ease_back(min(1.0, max(0.0, (t - 0.35) / 0.85)))
        cy = int(H - ch * p) + 40
        m = _mouth_at(q, max(0.0, t - 0.45))
        fr.paste(mouths[m], (1310, cy), mouths[m])

        d = ImageDraw.Draw(fr, "RGBA")

        # 斜めのアクセント帯
        p2 = ease_out(min(1.0, t / 0.55))
        d.polygon([(-200, 300), (-200 + 1500*p2, 300), (-320 + 1500*p2, 470), (-320, 470)],
                  fill=ACC + (34,))

        # チャンネル名: 拡大しながら現れる
        if t > 0.7:
            p3 = ease_back(min(1.0, (t - 0.7) / 0.6))
            sz = int(base_sz * (0.72 + 0.28 * p3))
            fo = ImageFont.truetype(FB, max(20, sz))
            al = int(255 * min(1.0, (t - 0.7) / 0.35))
            tw = d.textlength(channel_name, font=fo)
            ty = 330 + int((base_sz - sz) * 0.55)      # 拡大の中心を揃える
            d.text((150 + (f_name.getlength(channel_name) - tw) / 2, ty),
                   channel_name, font=fo, fill=INK + (al,),
                   stroke_width=max(6, sz // 11), stroke_fill=(14, 32, 16, al))

        # タグライン: 左からスライド
        if t > 1.15:
            p4 = ease_out(min(1.0, (t - 1.15) / 0.5))
            al = int(255 * p4)
            yb = 378 + base_sz
            d.rectangle([150, yb, 150 + int(180 * p4), yb + 10], fill=GOLD + (al,))
            d.text((150 - 60 + int(60 * p4), yb + 38), tagline, font=f_tag,
                   fill=GOLD + (al,), stroke_width=5, stroke_fill=(14, 32, 16, al))

        if t > 1.7:
            al = int(200 * ease_out(min(1.0, (t - 1.7) / 0.5)))
            d.text((152, 378 + base_sz + 128), "VOICEVOX:ずんだもん", font=f_sub, fill=(206, 226, 200, al))

        # 最後に白く飛ばして本編へ
        rest = dur - t
        if rest < 0.45:
            k = int(255 * (1 - rest / 0.45) ** 1.6)
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, k))

        fr.save(f"{workdir}/f{i:04d}.png")

    # OPにも短いジングルを重ね、本編と同じ音量基準にそろえる
    MONO = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
    NORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=24000"
    bed = None
    try:
        import video as V
        op = V.bgm_tracks(opening=True)
        if op:
            import numpy as np
            a = V.load_bgm(op[0], dur + 0.5, 24000, f"{workdir}/op_src.wav")
            bed = V._finish_bed(a, [], f"{workdir}/op_bed.wav", 24000, normalize=False)
        else:
            bed = V.make_audio_bed(dur, [0.15], f"{workdir}/op_bed.wav")
    except Exception as e:
        print(f"  OPのBGMなしで続行: {type(e).__name__}: {e}", flush=True)
        bed = None

    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
           "-i", f"{workdir}/f%04d.png", "-i", wav]
    if bed:
        cmd += ["-i", bed, "-filter_complex",
                f"[1:a]{MONO},apad=whole_dur={dur}[a];"
                f"[2:a]{MONO},volume=0.12[b];"
                f"[a][b]amix=inputs=2:duration=first:normalize=0,{NORM}[ao]"]
    else:
        cmd += ["-filter_complex", f"[1:a]{MONO},apad=whole_dur={dur},{NORM}[ao]"]
    cmd += ["-map", "0:v", "-map", "[ao]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "24000", "-ac", "1",
            "-t", str(dur), out_path]
    subprocess.run(cmd, check=True)
    for f in os.listdir(workdir):
        if f.startswith("f") and f.endswith(".png"):
            os.remove(os.path.join(workdir, f))
    return dur


# ============ エンディング ============
def build_ending(out_path, channel_name="ずんだもん生活の知恵",
                 next_hint="気になるあれこれを10分で",
                 narration=None, speaker=3,
                 voicevox="http://127.0.0.1:50021", workdir=None):
    """最後に付ける見送りカード。チャンネル登録と次の動画へつなぐ。
    戻り値は尺(秒)"""
    from PIL import Image, ImageDraw, ImageFont
    workdir = workdir or os.path.join(ROOT, ".cache", "ed")
    os.makedirs(workdir, exist_ok=True)
    narration = narration or (
        "最後まで見てくれてありがとうなのだ。"
        "役に立ったらチャンネル登録と高評価をお願いするのだ。"
        "また次の動画で会おうなのだ。")

    wav = os.path.join(workdir, "ed.wav")
    q, vdur = _synth(voicevox, narration, speaker, wav)
    dur = max(6.0, vdur + 1.2)
    n   = int(dur * FPS)

    bg = _background()
    mouths = {v: Image.open(os.path.join(FRAMES, f"happy_{v}.png")).convert("RGBA")
              for v in ("a", "i", "u", "e", "o", "x")}
    cw = 480
    ch = int(mouths["x"].height * cw / mouths["x"].width)
    mouths = {k: v.resize((cw, ch), Image.LANCZOS) for k, v in mouths.items()}

    MAXW = 1040
    sz_name = 96
    while sz_name > 44 and ImageFont.truetype(FB, sz_name).getlength(channel_name) > MAXW:
        sz_name -= 3
    f_name = ImageFont.truetype(FB, sz_name)
    f_big  = ImageFont.truetype(FB, 78)
    f_card = ImageFont.truetype(FM, 42)
    f_sub  = ImageFont.truetype(FM, 36)

    CARDS = [("チャンネル登録", GOLD), ("高評価", ACC), ("コメント", (150, 206, 232))]

    for i in range(n):
        t  = i / FPS
        fr = bg.copy()

        m = _mouth_at(q, max(0.0, t - 0.3))
        fr.paste(mouths[m], (1360, H - ch + 30), mouths[m])

        d = ImageDraw.Draw(fr, "RGBA")

        # ありがとう
        p1 = ease_back(min(1.0, max(0.0, t / 0.7)))
        al = int(255 * min(1.0, t / 0.4))
        d.text((150, 150 + int(40 * (1 - p1))), "見てくれてありがとう", font=f_big,
               fill=INK + (al,), stroke_width=8, stroke_fill=(14, 32, 16, al))

        # チャンネル名
        if t > 0.5:
            a2 = int(255 * ease_out(min(1.0, (t - 0.5) / 0.45)))
            d.text((150, 268), channel_name, font=f_name, fill=GOLD + (a2,),
                   stroke_width=7, stroke_fill=(14, 32, 16, a2))

        # 3つのカードが順に出る
        for k, (label, col) in enumerate(CARDS):
            t0 = 1.1 + k * 0.32
            if t < t0:
                continue
            p = ease_back(min(1.0, (t - t0) / 0.5))
            a3 = int(255 * min(1.0, (t - t0) / 0.3))
            bw, bh = 350, 128
            bx = 150 + k * (bw + 30)
            by = 470 + int(46 * (1 - p))
            d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=20,
                                fill=col + (int(a3 * 0.9),))
            tw = d.textlength(label, font=f_card)
            d.text((bx + (bw - tw) / 2, by + bh / 2 - 26), label, font=f_card,
                   fill=(16, 34, 18, a3))

        if t > 2.4:
            a4 = int(210 * ease_out(min(1.0, (t - 2.4) / 0.5)))
            d.text((152, 680), next_hint, font=f_sub, fill=(214, 232, 208, a4))
            d.text((152, 740), "音声合成:VOICEVOX:ずんだもん", font=f_sub,
                   fill=(178, 202, 176, a4))

        # 頭は白から、終わりは黒へ
        if t < 0.4:
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, int(255 * (1 - t / 0.4))))
        rest = dur - t
        if rest < 0.8:
            d.rectangle([0, 0, W, H], fill=(0, 0, 0, int(255 * (1 - rest / 0.8) ** 1.4)))

        fr.save(f"{workdir}/f{i:04d}.png")

    _encode_seq(workdir, wav, dur, out_path, opening=False)
    return dur


def _encode_seq(workdir, wav, dur, out_path, opening=True):
    """連番PNG + 音声 を、本編と同じ規格のmp4にする"""
    MONO = "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
    NORM = "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=24000"
    bed = None
    try:
        import video as V
        op = V.bgm_tracks(opening=True)
        if op:
            a = V.load_bgm(op[0], dur + 0.5, 24000, f"{workdir}/bed_src.wav")
            bed = V._finish_bed(a, [], f"{workdir}/bed.wav", 24000, normalize=False)
        else:
            bed = V.make_audio_bed(dur, [0.15], f"{workdir}/bed.wav")
    except Exception as e:
        print(f"  BGMなしで続行: {type(e).__name__}: {e}", flush=True)
        bed = None

    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
           "-i", f"{workdir}/f%04d.png", "-i", wav]
    if bed:
        cmd += ["-i", bed, "-filter_complex",
                f"[1:a]{MONO},apad=whole_dur={dur}[a];"
                f"[2:a]{MONO},volume=0.12[b];"
                f"[a][b]amix=inputs=2:duration=first:normalize=0,{NORM}[ao]"]
    else:
        cmd += ["-filter_complex", f"[1:a]{MONO},apad=whole_dur={dur},{NORM}[ao]"]
    cmd += ["-map", "0:v", "-map", "[ao]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "24000", "-ac", "1",
            "-t", str(dur), out_path]
    subprocess.run(cmd, check=True)
    for f in os.listdir(workdir):
        if f.startswith("f") and f.endswith(".png"):
            os.remove(os.path.join(workdir, f))


# ============ 冒頭のフック ============
def build_hook(out_path, say, big_lines, speaker=3,
               voicevox="http://127.0.0.1:50021", workdir=None):
    """OPの前に置く、結論を先に見せる数秒。ここで続きが気にならないと離脱される。
    say: 読み上げる1〜2文 / big_lines: 画面に大きく出す短い行(2〜3本)"""
    from PIL import Image, ImageDraw, ImageFont
    workdir = workdir or os.path.join(ROOT, ".cache", "hook")
    os.makedirs(workdir, exist_ok=True)
    big_lines = [t for t in (big_lines or []) if str(t).strip()][:4]
    if not say or not big_lines:
        raise ValueError("フックの文言がない")

    wav = os.path.join(workdir, "hook.wav")
    q, vdur = _synth(voicevox, say, speaker, wav)
    dur = max(5.0, vdur + 0.8)
    n   = int(dur * FPS)

    bg = _background()
    mouths = {v: Image.open(os.path.join(FRAMES, f"surprise_{v}.png")).convert("RGBA")
              for v in ("a", "i", "u", "e", "o", "x")}
    cw = 470
    ch = int(mouths["x"].height * cw / mouths["x"].width)
    mouths = {k: v.resize((cw, ch), Image.LANCZOS) for k, v in mouths.items()}

    # 3行が枠に収まる大きさを選ぶ
    MAXW = 1180
    sizes = []
    top  = 150 if len(big_lines) <= 3 else 118   # 4行のときは少し小さく
    for t in big_lines:
        sz = top
        while sz > 52 and ImageFont.truetype(FB, sz).getlength(str(t)) > MAXW:
            sz -= 4
        sizes.append(sz)
    total_h = sum(int(s * 1.26) for s in sizes)
    y0 = (H - total_h) // 2 - 40

    # 行が出るタイミングを、読み上げの長さで割りふる
    starts = [0.25 + i * (vdur * 0.55 / max(1, len(big_lines))) for i in range(len(big_lines))]

    for i in range(n):
        t  = i / FPS
        fr = bg.copy()
        m  = _mouth_at(q, max(0.0, t - 0.2))
        fr.paste(mouths[m], (1330, H - ch + 40), mouths[m])
        d = ImageDraw.Draw(fr, "RGBA")

        y = y0
        for k, (line, sz) in enumerate(zip(big_lines, sizes)):
            lh = int(sz * 1.26)
            if t >= starts[k]:
                p = ease_back(min(1.0, (t - starts[k]) / 0.42))
                al = int(255 * min(1.0, (t - starts[k]) / 0.25))
                cur = max(20, int(sz * (0.74 + 0.26 * p)))
                fo  = ImageFont.truetype(FB, cur)
                col = GOLD if k == len(big_lines) - 1 else INK
                d.text((150, y + (sz - cur) // 2), str(line), font=fo,
                       fill=col + (al,), stroke_width=max(7, cur // 12),
                       stroke_fill=(12, 28, 14, al))
            y += lh

        # 下に細い進行ライン(勢いを出す)
        d.rectangle([0, H - 14, int(W * min(1.0, t / dur)), H], fill=ACC + (200,))

        rest = dur - t
        if rest < 0.35:
            k = int(255 * (1 - rest / 0.35) ** 1.5)
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, k))

        fr.save(f"{workdir}/f{i:04d}.png")

    _encode_seq(workdir, wav, dur, out_path, opening=True)
    return dur
