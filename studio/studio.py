#!/usr/bin/env python3
"""ずんだもん解説動画スタジオ

台本JSONを1つ渡すと、動画・サムネイル3案・タイトル候補・概要欄を
まとめて書き出す。VOICEVOX の取得と起動も自動で行う。

    python3 studio.py 台本.json [出力先]

出力:
    out/video.mp4
    out/thumbnail_alert.jpg / _guide.jpg / _number.jpg
    out/thumbnail_smallcheck.png   … スマホ最小表示での確認用
    out/description.txt            … 概要欄(貼り付け用)
    out/title_description.md       … タイトル候補+概要欄+確認事項
"""
import json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "lib"))


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    script_path = os.path.abspath(sys.argv[1])
    outdir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(ROOT, "out")
    os.makedirs(outdir, exist_ok=True)
    script = json.load(open(script_path, encoding="utf-8"))
    t0 = time.time()

    print("=" * 56)
    print(f" {script.get('chapter','(無題)')}  /  {len(script['scenes'])}シーン")
    print("=" * 56)

    # 1. 環境の準備(VOICEVOX の取得・起動)
    import setup as S
    S.prepare()

    # 2. 動画
    print("\n[動画] 生成開始")
    import video as V
    info = V.main(script_path, os.path.join(outdir, "video.mp4"))

    # 3. サムネイル
    print("\n[サムネ] 生成開始")
    import thumbnail as T
    # 出来上がった動画からフレームを1枚取り、サムネの背景に使う
    spec = script.get("thumbnail", {})
    at = spec.get("from_scene")
    chs = info["chapters"]
    idx = (at - 1) if isinstance(at, int) and 1 <= at <= len(chs) else 0
    sec = chs[idx][1] + chs[idx][2] * 0.5
    base = T.grab_frame(os.path.join(outdir, "video.mp4"), sec,
                        os.path.join(outdir, ".base.png"))
    print(f"  背景に使うコマ: {int(sec)//60}:{int(sec)%60:02d} ({chs[idx][0]})")
    thumbs = T.build(spec, outdir, base=base)
    for p in thumbs:
        print("  " + os.path.basename(p))

    # 4. タイトルと概要欄(タイムスタンプは動画の実測値)
    print("\n[メタ] 生成開始")
    import metadata as M
    checked, warn = M.build(script.get("meta", {}), info["chapters"], outdir)
    for t, n, note in checked:
        print(f"  [{n:2d}字/{note}] {t}")
    for w in warn:
        print(f"  ⚠ {w}")

    d = info["duration"]
    print("\n" + "=" * 56)
    print(f" 完了  {int(d)//60}分{int(d)%60}秒 / テロップ{info['telops']}枚 / 所要{time.time()-t0:.0f}秒")
    print(f" 出力先: {outdir}")
    print("=" * 56)
    print("\n※ YouTube への投稿はこの環境から通信できないため手動です。")
    print("   out/ の動画とサムネ、description.txt をそのまま使えます。")


if __name__ == "__main__":
    main()
