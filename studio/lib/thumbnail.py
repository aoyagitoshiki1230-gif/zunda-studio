#!/usr/bin/env python3
"""サムネイル生成(1280x720)

参考にした定石:
  メイン文字 80〜120px / 袋文字は文字サイズの5〜10% / 文字は6〜15字
  顔は画面の1/3以上 / 白・黒・黄が万能色 / 教育系は青、注意喚起は赤
  最小表示 168x94px でも読めること
"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "assets", "frames")
W, H = 1280, 720
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
f = lambda p, s: ImageFont.truetype(p, s)


def _char(img, expr, height, xy, keep=0.56):
    """立ち絵を顔が大きく見えるバストアップに切って合成する"""
    ch = Image.open(os.path.join(FRAMES, f"{expr}_a.png")).convert("RGBA")
    bbox = ch.split()[3].getbbox()
    ch = ch.crop((bbox[0], bbox[1], bbox[2], bbox[1] + int((bbox[3]-bbox[1]) * keep)))
    w = int(ch.width * height / ch.height)
    ch = ch.resize((w, height), Image.LANCZOS)
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", ch.size, (20, 30, 16, 255)),
             (xy[0] + 8, xy[1] + 10), ch.split()[3].point(lambda v: int(v * 0.42)))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(ch, xy)


def _from_video(path, tint, strength=0.55):
    """出来上がった動画のフレームを背景に使う。
       立ち絵のいない左側だけを切り出してぼかすので、二重像にならない。"""
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 90, int(im.width * 0.62), im.height - 210))
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(26))
    lay = Image.new("RGB", (W, H), tint)
    return Image.blend(im, lay, strength).convert("RGBA")


def _grad(c1, c2):
    y = np.linspace(0, 1, H)[:, None]; x = np.linspace(0, 1, W)[None, :]
    t = y * 0.6 + x * 0.4
    a, b = np.array(c1, float), np.array(c2, float)
    return Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8)).convert("RGBA")


def _burst(img, cx, cy, color, n=34, op=40):
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for i in range(n):
        a0 = i * 2 * math.pi / n; a1 = a0 + math.pi / n * 0.82; R = 1900
        d.polygon([(cx, cy), (cx + R*math.cos(a0), cy + R*math.sin(a0)),
                   (cx + R*math.cos(a1), cy + R*math.sin(a1))], fill=color + (op,))
    return Image.alpha_composite(img, lay)


def _badge(d, xy, text, font, bg, fg=(255, 255, 255), pad=(18, 12)):
    w = int(d.textlength(text, font=font))
    box = [xy[0], xy[1], xy[0] + w + pad[0]*2, xy[1] + font.size + pad[1]*2]
    d.rounded_rectangle(box, radius=10, fill=bg)
    d.text((xy[0] + pad[0], xy[1] + pad[1]), text, font=font, fill=fg)


def _big(d, xy, text, size, fill, stroke):
    fo = f(FB, size)
    d.text(xy, text, font=fo, fill=fill, stroke_width=max(6, round(size * 0.09)),
           stroke_fill=stroke)
    return size


def _rule(d, y, x0, x1, color):
    d.rectangle([x0, y, x1, y + 9], fill=color)


# ---------- 3つの型 ----------
def alert(t, base=None):
    """注意喚起型(赤・集中線)。動画の山場を前面に出す"""
    img = _from_video(base, (128, 26, 20), 0.62) if base else _grad((150, 32, 24), (86, 14, 12))
    img = _burst(img, 470, 380, (255, 214, 120))
    _char(img, t.get("expr", "surprise"), 690, (760, 40))
    d = ImageDraw.Draw(img)
    ink, edge, hi = (255, 255, 255), (46, 10, 8), (255, 216, 64)
    _badge(d, (58, 58), t["eyebrow"], f(FM, 32), (250, 214, 70), (60, 20, 12))
    _big(d, (58, 140), t["l1"],   96,  ink, edge)
    _big(d, (58, 262), t["hero"], 168, hi,  edge)
    _big(d, (58, 452), t["l3"],   92,  ink, edge)
    _rule(d, 596, 58, 470, (250, 214, 70))
    d.text((58, 622), t["sub"], font=f(FM, 38), fill=(255, 236, 214))
    return img


def guide(t, base=None):
    """解説型(青)。落ち着いた入門ガイドとして見せる"""
    img = _from_video(base, (22, 58, 106), 0.60) if base else _grad((26, 68, 122), (12, 32, 66))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); dd = ImageDraw.Draw(lay)
    for i in range(-6, 26):
        dd.line([(i*70, 0), (i*70+220, H)], fill=(255, 255, 255, 16), width=26)
    img = Image.alpha_composite(img, lay)
    _char(img, t.get("expr", "normal"), 700, (770, 30))
    d = ImageDraw.Draw(img)
    ink, edge, hi, acc = (255, 255, 255), (8, 22, 44), (255, 216, 64), (108, 208, 122)
    _badge(d, (58, 56), t["badge"], f(FM, 34), acc, (10, 34, 18))
    _big(d, (58, 142), t["l1"],   132, ink, edge)
    _big(d, (58, 296), t["hero"], 132, hi,  edge)
    _big(d, (58, 452), t["l3"],   104, ink, edge)
    _rule(d, 600, 58, 430, acc)
    d.text((58, 626), t["sub"], font=f(FM, 36), fill=(196, 218, 244))
    return img


def number(t, base=None):
    """数字型(明るい緑)。件数を主役にする"""
    img = _from_video(base, (232, 244, 224), 0.62) if base else _grad((236, 246, 226), (188, 218, 176))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); dd = ImageDraw.Draw(lay)
    dd.ellipse([-160, 120, 620, 900], fill=(255, 255, 255, 130))
    img = Image.alpha_composite(img, lay.filter(ImageFilter.GaussianBlur(80)))
    _char(img, t.get("expr", "think"), 700, (768, 30))
    d = ImageDraw.Draw(img)
    ink, edge, acc, num = (32, 54, 26), (255, 255, 255), (58, 122, 48), (226, 122, 32)
    _badge(d, (58, 54), t["eyebrow"], f(FM, 32), acc)
    _big(d, (56, 148), t["l1"],  84,  ink, edge)
    _big(d, (48, 254), t["num"], 250, num, edge)
    nw = int(d.textlength(t["num"], font=f(FB, 250)))
    _big(d, (56 + nw + 34, 330), t["l2"], 96,  ink, edge)
    _big(d, (56 + nw + 34, 440), t["l3"], 112, ink, edge)
    _rule(d, 604, 56, 470, acc)
    d.text((56, 630), t["sub"], font=f(FM, 36), fill=(64, 92, 56))
    return img


STYLES = {"alert": alert, "guide": guide, "number": number}


def grab_frame(video_path, at_sec, out_path):
    """出来上がった動画から1コマ取り出す"""
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at_sec),
                    "-i", video_path, "-frames:v", "1", out_path], check=True)
    return out_path


def build(spec, outdir, base=None):
    """台本JSONの thumbnail ブロックから3案を書き出す。
       base に動画のフレームを渡すと、それを背景に使って動画と見た目を揃える。"""
    os.makedirs(outdir, exist_ok=True)
    made = []
    for key, fn in STYLES.items():
        if key not in spec:
            continue
        t = dict(spec[key]); t.setdefault("eyebrow", spec.get("eyebrow", ""))
        p = os.path.join(outdir, f"thumbnail_{key}.jpg")
        fn(t, base).convert("RGB").save(p, quality=92)
        made.append(p)
    # 最小表示での確認用
    if made:
        s = Image.new("RGB", (len(made)*183 + 15, 120), (24, 24, 24))
        for i, p in enumerate(made):
            s.paste(Image.open(p).resize((168, 94)), (15 + i*183, 13))
        s.save(os.path.join(outdir, "thumbnail_smallcheck.png"))
    return made
