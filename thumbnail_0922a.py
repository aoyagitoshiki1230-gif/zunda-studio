#!/usr/bin/env python3
"""サムネイル生成(1280x720)

守っている定石:
  スマホの一覧では 168x94px まで縮む。そこで読めない文字は無いのと同じ
  主役の文字は2〜6字。行数は3行まで。袋文字は文字サイズの9〜11%
  顔は大きく。立ち絵は白フチで背景から浮かせる
  文字の下には必ず暗い(または明るい)帯を敷いて、背景と勝負させない
"""
__VERSION__ = "2026-09-22a"
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


def _frames_dir(who):
    """その人の立ち絵フォルダ。相棒役(めたん)は1枚のシート画像しかリポジトリに
    置いていないので、切り出しがまだなら video 側の切り出しをここで呼ぶ。
    **これが無いと、動画を作る前にサムネだけ作ったときに黙ってずんだもんで代用され、
    「2人型」がずんだもん2人になる**(2026-09-19に clone 直後で踏んだ)"""
    if who == "zunda":
        return FRAMES
    d = os.path.join(ROOT, "assets", f"frames_{who}")
    import glob as _g
    if not _g.glob(os.path.join(d, "*_*.png")):
        try:
            import video as V
            V._sheet_frames(who)
        except Exception as e:
            print(f"  ⚠ {who} の立ち絵を用意できませんでした: {type(e).__name__}: {e}")
    return d


def _char(img, expr, height, anchor=(1000, -20), keep=0.44, who="zunda",
          outline=12, halfw=0.36, xmin=620, xmax=None):
    """立ち絵を顔まわりで切り、頭の中心が anchor に来るように置く。
    anchor=(頭の中心の横位置, 上端)"""
    d = _frames_dir(who)
    path = os.path.join(d, f"{expr}_a.png")
    if not os.path.exists(path):
        path = os.path.join(d, "normal_a.png")
    if not os.path.exists(path):
        path = os.path.join(FRAMES, f"{expr}_a.png")
        if who != "zunda":
            print(f"  ⚠ {who} の立ち絵が無いので、ずんだもんの絵で代用しました。"
                  f"2人型のサムネがずんだもん2人になっています")
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
        # 白フチは絵の外側に広がる。余白を足さずに付けると、フチが画像の端で
        # 切れて「白い四角」に見える(2026-09-19に2人型で踏んだ)
        pad = outline + 8
        room = Image.new("RGBA", (ch.width + pad*2, ch.height + pad*2), (0, 0, 0, 0))
        room.alpha_composite(ch, (pad, pad))
        ch = _outlined(room, outline)
    x = int(anchor[0] - ch.width / 2)
    # 右端で切れすぎないように寄せる(2人型では xmax でさらに内側に止める)
    x = min(x, img.width - ch.width + 30 if xmax is None else xmax)
    x = max(x, xmin)                   # 文字の側に入り込みすぎない
    y = anchor[1]
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", ch.size, (14, 22, 12, 255)),
             (x + 10, y + 14), ch.split()[3].point(lambda v: int(v * 0.5)))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    img.alpha_composite(ch, (x, y))
    return ch.width


def _bg_photo(tint, strength, size=None):
    """用意された背景画像を使う。無ければ None"""
    CW, CH = size or (W, H)
    try:
        import video as V
        imgs = V.bg_images()
    except Exception:
        imgs = []
    if not imgs:
        return None
    im = Image.open(imgs[0]).convert("RGB")
    k = max(CW / im.width, CH / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    ox, oy = (im.width - CW) // 2, (im.height - CH) // 2
    im = im.crop((ox, oy, ox + CW, oy + CH)).filter(ImageFilter.GaussianBlur(16))
    return Image.blend(im, Image.new("RGB", (CW, CH), tint), strength).convert("RGBA")


def _from_video(path, tint, strength=0.55, size=None):
    CW, CH = size or (W, H)
    im = Image.open(path).convert("RGB")
    im = im.crop((0, 90, int(im.width * 0.62), im.height - 210))
    k = max(CW / im.width, CH / im.height)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    ox, oy = (im.width - CW) // 2, (im.height - CH) // 2
    im = im.crop((ox, oy, ox + CW, oy + CH)).filter(ImageFilter.GaussianBlur(26))
    return Image.blend(im, Image.new("RGB", (CW, CH), tint), strength).convert("RGBA")


def _grad(c1, c2, size=None):
    CW, CH = size or (W, H)
    y = np.linspace(0, 1, CH)[:, None]; x = np.linspace(0, 1, CW)[None, :]
    t = y * 0.6 + x * 0.4
    a, b = np.array(c1, float), np.array(c2, float)
    return Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8)).convert("RGBA")


def _base(base, tint, strength, size=None):
    """背景の優先順位: 背景画像 > 動画のコマ > グラデーション"""
    return (_bg_photo(tint, strength, size) or
            (_from_video(base, tint, strength, size) if base else None) or
            _grad(tint, tuple(int(c * 0.55) for c in tint), size))


def _scrim(img, x0, x1, dark=True, power=1.0):
    """文字を置く側に帯を敷いて、背景と勝負させない"""
    CW, CH = img.size
    lay = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    a = np.zeros((CH, CW), np.uint8)
    xs = np.linspace(0, 1, x1 - x0)
    col = (int(196 * power) * (1 - xs ** 2.2)).astype(np.uint8)
    a[:, x0:x1] = col[None, :]
    a[:, :x0] = int(196 * power)
    lay.putalpha(Image.fromarray(a))
    lay = Image.composite(Image.new("RGBA", (CW, CH),
                                    (8, 16, 8, 255) if dark else (255, 255, 255, 255)),
                          Image.new("RGBA", (CW, CH), (0, 0, 0, 0)), lay.split()[3])
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


# ---------- 横サムネ4つの型(長編用) ----------
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
    # 桁が多いと立ち絵の顔まではみ出していた(1234567で実測)。
    # l2/l3 を置く余白を残したまま収まる大きさまで落とす
    need = 200 if (t.get("l2") or t.get("l3")) else 40
    fn, nw = f(FB, 268), 0
    if n:
        for size in range(268, 89, -12):
            fn = f(FB, size)
            nw = int(d.textlength(n, font=fn))
            if nw <= TEXT_W - need:
                break
        else:
            print(f"  サムネの数字が大きすぎるので90pxまで縮めました: {n}")
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


def duo(t, base=None):
    """2人型。ずんだもんと四国めたんを並べて「話している感」を出す。
    文字は左 620px に収める(めたんの立ち絵が読みやすさの計測範囲に入らない幅)"""
    tw  = 580
    img = _base(base, (18, 74, 58), 0.66)
    img = _burst(img, 380, 330, (255, 228, 152), n=40, op=30)
    img = _scrim(img, 560, 1010, dark=True, power=1.0)
    # 内側(奥)に小さいほう、外側(手前)に大きいほう。後に置いたほうが手前になる。
    # どちらの型でも happy は使わないこと(両手を上げる絵で横に広がり、奥の顔を隠す)。
    # front="guest" にすると、めたんが手前・大きめの並びに入れ替わる
    back, front = (t.get("who2", "guest"), t.get("who", "zunda"))
    be,   fe    = (t.get("expr2", "normal"), t.get("expr", "surprise"))
    if t.get("front", "zunda") != "zunda":
        back, front, be, fe = front, back, fe, be
    # めたんは頭の占める割合が小さいので、同じ高さだとずんだもんより顔が大きくなり、
    # 手前に置くと頭が画面の上で切れる。キャラごとに高さと上端を変える(2026-09-19bで実測)
    bh, by = (470, 250) if back  == "guest" else (436, 268)
    fh, fy = (690,  22) if front == "zunda" else (612,  44)
    _char(img, be, bh, (826, by), keep=0.46,
          who=back, outline=10, xmin=648, xmax=900)
    _char(img, fe, fh, (1046, fy), keep=0.46,
          who=front, xmin=900)
    d = ImageDraw.Draw(img)
    ink, edge, hi, acc = (255, 255, 255), (6, 30, 22), (255, 216, 64), (108, 208, 122)
    y = 44
    y += _badge(d, (TEXT_X, y), t.get("eyebrow", ""), f(FM, 34), acc, (8, 34, 20),
                maxw=tw) + 18
    y += _line(d, (TEXT_X, y), t.get("l1", ""),   _fit(t.get("l1"),   tw, 112, 62), ink, edge)
    y += _line(d, (TEXT_X, y), t.get("hero", ""), _fit(t.get("hero"), tw, 186, 96), hi, edge) + 6
    y += _line(d, (TEXT_X, y), t.get("l3", ""),   _fit(t.get("l3"),   tw, 112, 62), ink, edge)
    if t.get("sub"):
        d.rectangle([TEXT_X, 640, TEXT_X + 300, 649], fill=acc)
        d.text((TEXT_X, 662), t["sub"], font=_fit(t["sub"], 660, 36, 24, FM),
               fill=(214, 240, 226))
    return img


# ---------- ショート用の縦サムネ(1080x1920) ----------
SW, SH = 1080, 1920

def _scrim_v(img, y0, y1, dark=True, power=1.0):
    """上から下へ薄くなる帯。縦サムネで文字の下に敷く"""
    CW, CH = img.size
    a = np.zeros((CH, CW), np.uint8)
    ys = np.linspace(0, 1, max(1, y1 - y0))
    a[y0:y1, :] = (int(200 * power) * (1 - ys ** 2.0)).astype(np.uint8)[:, None]
    a[:y0, :] = int(200 * power)
    al = Image.fromarray(a)
    lay = Image.new("RGBA", (CW, CH), (8, 16, 8, 255) if dark else (255, 255, 255, 255))
    lay.putalpha(al)
    return Image.alpha_composite(img, lay)


def vertical(t, base=None):
    """ショート用の縦サムネ。1080x1920(9:16)。

    ★ ショートフィード(スワイプ中)には出ません。出るのは
      ホームのShorts棚・チャンネルのShortsタブ・検索結果です。
    ★ 棚では下が切れることがあるので、文字は全部上半分に置いてあります。
    """
    tw = SW - 96                      # 左右48pxの余白
    img = _base(base, (18, 74, 58), 0.66, size=(SW, SH))
    img = _burst(img, SW // 2, 470, (255, 228, 152), n=44, op=30)
    img = _scrim_v(img, 0, 1120, dark=True, power=1.0)

    # 立ち絵は下半分。ここは切れてもよい場所
    back, front = (t.get("who2", "guest"), t.get("who", "zunda"))
    be,   fe    = (t.get("expr2", "normal"), t.get("expr", "surprise"))
    # 下端は画面の外に出す(棚で切れる場所なので、そこで切れているほうが自然に見える)
    if t.get("with_guest", True):
        _char(img, be, 700, (268, 1232), keep=0.46, who=back, outline=12,
              xmin=0, xmax=SW - 420)
    _char(img, fe, 900, (742, 1006), keep=0.46, who=front, xmin=SW // 2 - 160)

    d = ImageDraw.Draw(img)
    ink, edge, hi, acc = (255, 255, 255), (6, 30, 22), (255, 216, 64), (108, 208, 122)
    x, y = 48, 66
    y += _badge(d, (x, y), t.get("eyebrow", ""), f(FM, 52), acc, (8, 34, 20),
                pad=(26, 16), maxw=tw) + 30
    y += _line(d, (x, y), t.get("l1", ""),   _fit(t.get("l1"),   tw, 150, 84), ink, edge)
    y += _line(d, (x, y), t.get("hero", ""), _fit(t.get("hero"), tw, 250, 130), hi, edge) + 10
    y += _line(d, (x, y), t.get("l3", ""),   _fit(t.get("l3"),   tw, 150, 84), ink, edge)
    if t.get("sub"):
        d.rectangle([x, y + 26, x + 360, y + 38], fill=acc)
        d.text((x, y + 60), t["sub"], font=_fit(t["sub"], tw, 54, 34, FM),
               fill=(214, 240, 226))
    return img


STYLES = {"alert": alert, "guide": guide, "number": number, "duo": duo,
          "vertical": vertical}


def vertical_for_short(script, outdir, base=None):
    """ショートの台本1つから縦サムネを1枚だけ書き出す(モードB用)。
    文字は `thumbnail.vertical` があればそれを、無ければ `short` から組む。
    背景画像を使うので、動画のコマ(base)は無くてもよい"""
    spec = dict(script.get("thumbnail") or {})
    t = dict(spec.get("vertical") or {})
    sh = script.get("short") or {}
    if not (t.get("hero") or t.get("l1") or t.get("l3")):
        # 指定が無いときは見出しを主役にする。読点や「、」で2行に割ると収まりがよい
        title = str(sh.get("title") or script.get("chapter") or "")
        for sep in ("、", "。", "，", ","):
            if sep in title[1:-1]:
                a, b = title.split(sep, 1)
                t["l1"], t["hero"] = a + sep, b
                break
        else:
            t["hero"] = title
        bl = [x for x in (sh.get("bullets") or []) if x]
        if bl:
            t.setdefault("sub", str(bl[0]))
    t.setdefault("eyebrow", spec.get("eyebrow") or "毎日 お金の注意報")
    os.makedirs(outdir, exist_ok=True)
    pth = os.path.join(outdir, "thumbnail_vertical.jpg")
    vertical(t, base).convert("RGB").save(pth, quality=92)
    sc = legibility(pth)
    print(f"  縦サムネ: 小さい表示での読みやすさ {sc} "
          f"({'OK' if sc >= 9.0 else '文字が弱いかも'})")
    return pth


def grab_frame(video_path, at_sec, out_path):
    """出来上がった動画から1コマ取り出す"""
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at_sec),
                    "-i", video_path, "-frames:v", "1", out_path], check=True)
    return out_path


def legibility(path):
    """小さい表示でも読めるかを、明暗の差で機械的に見る。
    文字がある側の縮小画像で、隣り合う画素の差が大きいほど文字が立っている。
    横サムネは左半分、縦サムネ(ショート)は上半分を見る"""
    im = Image.open(path).convert("L")
    if im.height > im.width:                     # 縦サムネ。Shorts棚の大きさに縮める
        im = im.resize((108, 192), Image.LANCZOS)
        a = np.asarray(im, float)[:112, :]       # 文字を置いた上半分
    else:
        im = im.resize((168, 94), Image.LANCZOS)
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
        s = Image.new("RGB", (len(made)*183 + 15, 215), (24, 24, 24))
        for i, p in enumerate(made):
            im = Image.open(p)
            s.paste(im.resize((108, 192) if im.height > im.width else (168, 94)),
                    (15 + i*183, 13))
        s.save(os.path.join(outdir, "thumbnail_smallcheck.png"))
    for key, sc in notes:
        mark = "OK" if sc >= 9.0 else "文字が弱いかも"
        print(f"  {key}: 小さい表示での読みやすさ {sc} ({mark})")
    return made
