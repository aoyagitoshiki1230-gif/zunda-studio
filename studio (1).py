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
import json, os, shutil, subprocess, sys, time

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

    # 2-b. オープニングを本編の前に付ける
    meta = script.get("meta", {})
    op_dur = 0.0
    if script.get("opening", True):
      try:
        print("\n[OP] 生成開始")
        import opening as OP
        op_mp4 = os.path.join(outdir, ".op.mp4")
        op_dur = OP.build(op_mp4,
                          meta.get("channel_name", "ずんだもん解説"),
                          meta.get("tagline", "気になるあれこれを10分で"),
                          meta.get("op_narration"))
        main = os.path.join(outdir, "video.mp4")
        tmp  = os.path.join(outdir, ".main.mp4")
        shutil.move(main, tmp)
        lst = os.path.join(outdir, ".concat.txt")
        with open(lst, "w") as fp:
            fp.write(f"file '{op_mp4}'\nfile '{tmp}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", main], check=True)
        os.remove(tmp); os.remove(lst); os.remove(op_mp4)
        # 目次はOPの分だけ後ろにずれる
        info["chapters"] = ([("オープニング", 0.0, op_dur)] +
                            [(t, st + op_dur, d) for t, st, d in info["chapters"]])
        info["duration"] += op_dur
        print(f"  OP {op_dur:.1f}秒 を先頭に結合")
      except Exception as e:
        op_dur = 0.0
        print(f"  OPを作れなかったので本編のみで続行: {type(e).__name__}: {e}")

    # 2-c. エンディングを末尾に付ける
    ed_dur = 0.0
    if script.get("ending", True):
      try:
        print("\n[ED] 生成開始")
        import opening as OP
        ed_mp4 = os.path.join(outdir, ".ed.mp4")
        ed_dur = OP.build_ending(ed_mp4,
                                 meta.get("channel_name", "ずんだもん生活の知恵"),
                                 meta.get("tagline", "気になるあれこれを10分で"),
                                 meta.get("ed_narration"))
        main = os.path.join(outdir, "video.mp4")
        tmp  = os.path.join(outdir, ".main2.mp4")
        shutil.move(main, tmp)
        lst = os.path.join(outdir, ".concat2.txt")
        with open(lst, "w") as fp:
            fp.write(f"file '{tmp}'\nfile '{ed_mp4}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", main], check=True)
        os.remove(tmp); os.remove(lst); os.remove(ed_mp4)
        info["chapters"] = info["chapters"] + [("エンディング", info["duration"], ed_dur)]
        info["duration"] += ed_dur
        print(f"  ED {ed_dur:.1f}秒 を末尾に結合")
      except Exception as e:
        ed_dur = 0.0
        print(f"  EDを作れなかったので本編のみで続行: {type(e).__name__}: {e}")

    # 3. サムネイル
    print("\n[サムネ] 生成開始")
    import thumbnail as T
    # 出来上がった動画からフレームを1枚取り、サムネの背景に使う
    spec = script.get("thumbnail", {})
    at = spec.get("from_scene")
    chs = [c for c in info["chapters"] if c[0] != "オープニング"]
    idx = (at - 1) if isinstance(at, int) and 1 <= at <= len(chs) else 0
    sec = chs[idx][1] + chs[idx][2] * 0.5
    if op_dur and idx == 0: sec = op_dur + 2.0
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
