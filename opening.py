#!/usr/bin/env python3
"""オープニング映像を作る。
   立ち絵が下からせり上がり、チャンネル名がポップし、最後に白く飛ばして本編へつなぐ。
   ナレーションはずんだもんで、口パクも本編と同じ仕組みで動かす。"""
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

    f_name = ImageFont.truetype(FB, 150)
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
            sz = int(150 * (0.72 + 0.28 * p3))
            fo = ImageFont.truetype(FB, max(20, sz))
            al = int(255 * min(1.0, (t - 0.7) / 0.35))
            tw = d.textlength(channel_name, font=fo)
            d.text((150 + (int(d.textlength(channel_name, font=f_name)) - tw) / 2, 330),
                   channel_name, font=fo, fill=INK + (al,),
                   stroke_width=max(6, sz // 11), stroke_fill=(14, 32, 16, al))

        # タグライン: 左からスライド
        if t > 1.15:
            p4 = ease_out(min(1.0, (t - 1.15) / 0.5))
            al = int(255 * p4)
            d.rectangle([150, 528, 150 + int(180 * p4), 538], fill=GOLD + (al,))
            d.text((150 - 60 + int(60 * p4), 566), tagline, font=f_tag,
                   fill=GOLD + (al,), stroke_width=5, stroke_fill=(14, 32, 16, al))

        if t > 1.7:
            al = int(200 * ease_out(min(1.0, (t - 1.7) / 0.5)))
            d.text((152, 656), "VOICEVOX:ずんだもん", font=f_sub, fill=(206, 226, 200, al))

        # 最後に白く飛ばして本編へ
        rest = dur - t
        if rest < 0.45:
            k = int(255 * (1 - rest / 0.45) ** 1.6)
            d.rectangle([0, 0, W, H], fill=(255, 255, 255, k))

        fr.save(f"{workdir}/f{i:04d}.png")

    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
        "-i", f"{workdir}/f%04d.png", "-i", wav,
        "-filter_complex", f"[1:a]apad=whole_dur={dur}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "24000", "-ac", "1",
        "-t", str(dur), out_path], check=True)
    for f in os.listdir(workdir):
        if f.startswith("f") and f.endswith(".png"):
            os.remove(os.path.join(workdir, f))
    return dur
