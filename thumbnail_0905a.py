#!/usr/bin/env python3
"""サムネイル生成(1280x720)

守っている定石:
  スマホの一覧では 168x94px まで縮む。そこで読めない文字は無いのと同じ
  主役の文字は2〜6字。行数は3行まで。袋文字は文字サイズの9〜11%
  顔は大きく。立ち絵は白フチで背景から浮かせる
  文字の下には必ず暗い(または明るい)帯を敷いて、背景と勝負させない
"""
__VERSION__ = "2026-09-05a"
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "assets", "frames")
W, H   = 1280, 720
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
FM = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
f = lambda p, s: ImageFont.truetype(p, max(12, int(s)))

TEXT_X   = 52
TEXT_W   = 690          # 文字を置いてよい横幅(立ち絵にかからない範囲)


# ---------- 部品 ----------
def _fit(text, maxw, hi, lo, font=FB):
    """maxw に収まる、いちばん大きい文字サイズを返す"""
    text = str(text or "")
    if not text:
        return f(font, lo)
    s = hi
    while s > lo and f(font, s).getlength(text) > maxw:
        s -= 2
    if f(font, s).getlength(text) > maxw:
        # 下限まで縮めても収まらない。画面外にはみ出すより小さくするほうを選ぶ
        while s > 28 and f(font, s).getlength(text) > maxw:
            s -= 2
        print(f"  サムネの文字が長すぎるので{s}pxまで縮めました: {text[:18]}")
    return f(font, s)


def _outlined(ch, px=12, color=(255, 255, 255, 255)):
    """立ち絵のまわりに白フチを付けて、背景から浮かせる"""
    a = ch.split()[3]
    grown = a.filter(ImageFilter.MaxFilter(9))
    for _ in range(max(0, px // 4)):
        grown = grown.filter(ImageFilter.MaxFilter(9))
    edge = Image.new("RGBA", ch.size, color)
    edge.putalpha(grown)
    out = Image.new("RGBA", ch.size, (0, 0, 0, 0))
    out.alpha_composite(edge)
    out.alpha_composite(ch)
    return out


def _char(img, expr, height, anchor=(1000, -20), keep=0.44, who="zunda",
          outline=12, halfw=0.36):
    """立ち絵を顔まわりで切り、頭の中心が anchor に来るように置く。
    anchor=(頭の中心の横位置, 上端)"""
    d = FRAMES if who == "zunda" else os.path.join(ROOT, "assets", f"frames_{who}")
    path = os.path.join(d, f"{expr}_a.png")
    if not os.path.exists(path):
        path = os.path.join(d, "normal_a.png")
    if not os.path.exists(path):
        path = os.path.join(FRAMES, f"{expr}_a.png")
    ch = Image.open(path).convert("RGBA")
    bb = ch.split()[3].getbbox()
    ch = ch.crop((bb[0], bb[1], bb[2], bb[1] + int((bb[3] - bb[1]) * keep)))

    # 頭の左右の中心を、上のほう(髪と顔)の重心から求める
    a = np.asarray(ch.split()[3], float)
    top = a[: max(1, int(a.shape[0] * 0.55))]
    colw = top.sum(axis=0)
    cx = int((colw * np.arange(len(colw))).sum() / max(1.0, colw.sum()))
    hw = int(ch.width * halfw)
    ch = ch.crop((max(0, cx - hw), 0, min(ch.width, cx + hw), ch.height))

    w = int(ch.width * height / ch.height)
    ch = ch.resize((w, height), Image.LANCZOS)
    if outline:
        ch = _outlined(ch, outline)
    x = int(anchor[0] - ch.width / 2)
    x = min(x, W - ch.width + 30)      # 右端で切れすぎないように寄せる
    x = max(x, 620)                    # 文字の側に入り込みすぎない
    y = anchor[1]
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", ch.size, (14, 22, 12, 255)),
             (x + 10, y + 14), ch.split()[3].point(lambda v: int(v * 0.5)))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    img.alpha_composite(ch, (x, y))
    return ch.width


def _bg_photo(tint, strength):
    """用意された背景画像を使う。無ければ None"""
    try:
        import video as V
        imgs = V.bg_images()
    except Exception:
        imgs = []
    if not imgs:
        return None
    im = Image.open(imgs[0]).convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    ox, oy = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((ox, oy, ox + W, oy + H)).filter(ImageFilter.GaussianBlur(16))
    return Image.blend(im, Image.new("RGB", (W, H), tint), strength).convert("RGBA")


def _from_video(path, tint, strength=0.55):
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 90, int(im.width * 0.62), im.height - 210))
    im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(26))
    return Image.blend(im, Image.new("RGB", (W, H), tint), strength).convert("RGBA")


def _grad(c1, c2):
    y = np.linspace(0, 1, H)[:, None]; x = np.linspace(0, 1, W)[None, :]
    t = y * 0.6 + x * 0.4
    a, b = np.array(c1, float), np.array(c2, float)
    return Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8)).convert("RGBA")


def _base(base, tint, strength):
    """背景の優先順位: 背景画像 > 動画のコマ > グラデーション"""
    return (_bg_photo(tint, strength) or
            (_from_video(base, tint, strength) if base else None) or
            _grad(tint, tuple(int(c * 0.55) for c in tint)))


def _scrim(img, x0, x1, dark=True, power=1.0):
    """文字を置く側に帯を敷いて、背景と勝負させない"""
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    a = np.zeros((H, W), np.uint8)
    xs = np.linspace(0, 1, x1 - x0)
    col = (int(196 * power) * (1 - xs ** 2.2)).astype(np.uint8)
    a[:, x0:x1] = col[None, :]
    a[:, :x0] = int(196 * power)
    lay.putalpha(Image.fromarray(a))
    lay = Image.composite(Image.new("RGBA", (W, H),
                                    (8, 16, 8, 255) if dark else (255, 255, 255, 255)),
                          Image.new("RGBA", (W, H), (0, 0, 0, 0)), lay.split()[3])
    lay.putalpha(Image.fromarray(a))
    return Image.alpha_composite(img, lay)


def _burst(img, cx, cy, color, n=34, op=44):
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    for i in range(n):
        a0 = i * 2 * math.pi / n; a1 = a0 + math.pi / n * 0.82; R = 1900
        d.polygon([(cx, cy), (cx + R*math.cos(a0), cy + R*math.sin(a0)),
                   (cx + R*math.cos(a1), cy + R*math.sin(a1))], fill=color + (op,))
    return Image.alpha_composite(img, lay)


def _badge(d, xy, text, font, bg, fg=(255, 255, 255), pad=(20, 12), maxw=None):
    if not text:
        return 0
    if maxw:                       # 帯からはみ出さないところまで縮める
        font = _fit(text, maxw - pad[0] * 2, font.size, 20, FM)
    w = int(d.textlength(text, font=font))
    d.rounded_rectangle([xy[0], xy[1], xy[0] + w + pad[0]*2, xy[1] + font.size + pad[1]*2],
                        radius=11, fill=bg)
    d.text((xy[0] + pad[0], xy[1] + pad[1]), text, font=font, fill=fg)
    return font.size + pad[1]*2


def _line(d, xy, text, font, fill, stroke):
    if not text:
        return 0
    d.text(xy, str(text), font=font, fill=fill,
           stroke_width=max(7, round(font.size * 0.10)), stroke_fill=stroke)
    return int(font.size * 1.18)


# ---------- 3つの型 ----------
def alert(t, base=None):
    """注意喚起型。損する話・落とし穴に使う"""
    img = _base(base, (132, 28, 22), 0.66)
    img = _burst(img, 430, 360, (255, 214, 120))
    img = _scrim(img, 620, 1060, dark=True, power=1.0)
    _char(img, t.get("expr", "surprise"), 700, (1004, 16), keep=0.46,
          who=t.get("who", "zunda"))
    d = ImageDraw.Draw(img)
    ink, edge, hi = (255, 255, 255), (46, 10, 8), (255, 216, 64)
    y = 44
    y += _badge(d, (TEXT_X, y), t.get("eyebrow", ""), f(FM, 34), (250, 214, 70), (60, 20, 12),
                  maxw=TEXT_W) + 20
    y += _line(d, (TEXT_X, y), t.get("l1", ""),   _fit(t.get("l1"),   TEXT_W, 104, 62), ink, edge)
    y += _line(d, (TEXT_X, y), t.get("hero", ""), _fit(t.get("hero"), TEXT_W, 210, 108), hi, edge) + 6
    y += _line(d, (TEXT_X, y), t.get("l3", ""),   _fit(t.get("l3"),   TEXT_W, 104, 62), ink, edge)
    if t.get("sub"):
        d.rectangle([TEXT_X, 640, TEXT_X + 300, 649], fill=(250, 214, 70))
        d.text((TEXT_X, 662), t["sub"], font=_fit(t["sub"], 830, 36, 24, FM),
               fill=(255, 236, 214))
    return img


def guide(t, base=None):
    """解説型。入門ガイドとして落ち着いて見せる"""
    img = _base(base, (24, 62, 112), 0.64)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0)); dd = ImageDraw.Draw(lay)
    for i in range(-6, 26):
        dd.line([(i*70, 0), (i*70+220, H)], fill=(255, 255, 255, 16), width=26)
    img = Image.alpha_composite(img, lay)
    img = _scrim(img, 620, 1060, dark=True, power=0.95)
    _char(img, t.get("expr", "normal"), 706, (1006, 10), keep=0.46,
          who=t.get("who", "zunda"))
    d = ImageDraw.Draw(img)
    ink, edge, hi, acc = (255, 255, 255), (8, 22, 44), (255, 216, 64), (108, 208, 122)
    y = 42
    y += _badge(d, (TEXT_X, y), t.get("badge") or t.get("eyebrow", ""),
                f(FM, 34), acc, (10, 34, 18)) + 18
    y += _line(d, (TEXT_X, y), t.get("l1", ""),   _fit(t.get("l1"),   TEXT_W, 140, 74), ink, edge)
    y += _line(d, (TEXT_X, y), t.get("hero", ""), _fit(t.get("hero"), TEXT_W, 150, 82), hi, edge)
    y += _line(d, (TEXT_X, y), t.get("l3", ""),   _fit(t.get("l3"),   TEXT_W, 122, 66), ink, edge)
    if t.get("sub"):
        d.rectangle([TEXT_X, 640, TEXT_X + 300, 649], fill=acc)
        d.text((TEXT_X, 662), t["sub"], font=_fit(t["sub"], 830, 36, 24, FM),
               fill=(206, 224, 246))
    return img


def number(t, base=None):
    """数字型。件数を主役にする"""
    img = _base(base, (240, 248, 232), 0.70)
    img = _scrim(img, 640, 1080, dark=False, power=1.0)
    _char(img, t.get("expr", "think"), 700, (1004, 18), keep=0.46,
          who=t.get("who", "zunda"))
    d = ImageDraw.Draw(img)
    ink, edge, acc, num = (30, 52, 24), (255, 255, 255), (58, 122, 48), (226, 122, 32)
    y = 42
    y += _badge(d, (TEXT_X, y), t.get("eyebrow", ""), f(FM, 34), acc, maxw=TEXT_W) + 16
    y += _line(d, (TEXT_X, y), t.get("l1", ""), _fit(t.get("l1"), TEXT_W, 96, 58), ink, edge)

    n  = str(t.get("num", ""))
    fn = f(FB, 268)
    nw = int(d.textlength(n, font=fn)) if n else 0
    if n:
        d.text((TEXT_X - 6, y - 24), n, font=fn, fill=num,
               stroke_width=24, stroke_fill=edge)
    rx = TEXT_X + nw + 30
    rw = max(180, TEXT_W - nw - 30)
    ry = y + 30
    ry += _line(d, (rx, ry), t.get("l2", ""), _fit(t.get("l2"), rw, 104, 54), ink, edge)
    _line(d, (rx, ry), t.get("l3", ""), _fit(t.get("l3"), rw, 118, 58), ink, edge)
    if t.get("sub"):
        d.rectangle([TEXT_X, 640, TEXT_X + 300, 649], fill=acc)
        d.text((TEXT_X, 662), t["sub"], font=_fit(t["sub"], 830, 36, 24, FM),
               fill=(64, 92, 56))
    return img


STYLES = {"alert": alert, "guide": guide, "number": number}


def grab_frame(video_path, at_sec, out_path):
    """出来上がった動画から1コマ取り出す"""
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at_sec),
                    "-i", video_path, "-frames:v", "1", out_path], check=True)
    return out_path


def legibility(path):
    """168x94 まで縮めても読めるかを、明暗の差で機械的に見る。
    左半分(文字がある側)の縮小画像で、隣り合う画素の差が大きいほど文字が立っている"""
    im = Image.open(path).convert("L").resize((168, 94), Image.LANCZOS)
    a = np.asarray(im, float)[:, :100]
    gx = np.abs(np.diff(a, axis=1)).mean()
    gy = np.abs(np.diff(a, axis=0)).mean()
    return round((gx + gy) / 2, 1)


def build(spec, outdir, base=None):
    """台本JSONの thumbnail ブロックから3案を書き出す"""
    os.makedirs(outdir, exist_ok=True)
    made, notes = [], []
    for key, fn in STYLES.items():
        if key not in spec:
            continue
        t = dict(spec[key])
        t.setdefault("eyebrow", spec.get("eyebrow", ""))
        t.setdefault("who", spec.get("who", "zunda"))
        p = os.path.join(outdir, f"thumbnail_{key}.jpg")
        fn(t, base).convert("RGB").save(p, quality=92)
        sc = legibility(p)
        notes.append((key, sc))
        made.append(p)
    if made:
        s = Image.new("RGB", (len(made)*183 + 15, 120), (24, 24, 24))
        for i, p in enumerate(made):
            s.paste(Image.open(p).resize((168, 94)), (15 + i*183, 13))
        s.save(os.path.join(outdir, "thumbnail_smallcheck.png"))
    for key, sc in notes:
        mark = "OK" if sc >= 9.0 else "文字が弱いかも"
        print(f"  {key}: 小さい表示での読みやすさ {sc} ({mark})")
    return made
