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
    out/short_meta.md              … ショート用タイトル/説明欄/固定コメント
"""
__VERSION__ = "2026-09-03b"
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

    # 2-b2. さらにその前に「結論を先に見せる」フックを置く
    hook_dur = 0.0
    hk = meta.get("hook_big") or []
    if script.get("hook", True) and meta.get("hook_say") and hk:
      try:
        print("\n[フック] 生成開始")
        import opening as OP
        hk_mp4 = os.path.join(outdir, ".hook.mp4")
        hook_dur = OP.build_hook(hk_mp4, meta["hook_say"], hk)
        main = os.path.join(outdir, "video.mp4")
        tmp  = os.path.join(outdir, ".main0.mp4")
        shutil.move(main, tmp)
        lst = os.path.join(outdir, ".concat0.txt")
        with open(lst, "w") as fp:
            fp.write(f"file '{hk_mp4}'\nfile '{tmp}'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", main], check=True)
        os.remove(tmp); os.remove(lst); os.remove(hk_mp4)
        info["chapters"] = ([("フック", 0.0, hook_dur)] +
                            [(t, st + hook_dur, d) for t, st, d in info["chapters"]])
        info["duration"] += hook_dur
        op_dur += hook_dur          # サムネ用のコマ取り位置もずらす
        print(f"  フック {hook_dur:.1f}秒 を先頭に結合")
      except Exception as e:
        hook_dur = 0.0
        print(f"  フックを作れなかったので続行: {type(e).__name__}: {e}")
    elif script.get("hook", True):
        print("\n[フック] meta.hook_say と meta.hook_big が無いので省略")

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
    chs = [c for c in info["chapters"] if c[0] not in ("オープニング", "フック", "エンディング")]
    idx = (at - 1) if isinstance(at, int) and 1 <= at <= len(chs) else 0
    sec = chs[idx][1] + chs[idx][2] * 0.5
    if op_dur and idx == 0: sec = op_dur + 2.0
    base = T.grab_frame(os.path.join(outdir, "video.mp4"), sec,
                        os.path.join(outdir, ".base.png"))
    print(f"  背景に使うコマ: {int(sec)//60}:{int(sec)%60:02d} ({chs[idx][0]})")
    thumbs = T.build(spec, outdir, base=base)
    for p in thumbs:
        print("  " + os.path.basename(p))

    # 3-b. ショート動画(縦)
    if script.get("short_video", True):
      try:
        print("\n[ショート] 生成開始")
        sd = V.build_short(script_path, os.path.join(outdir, "short.mp4"))
        print(f"  short.mp4 {sd:.0f}秒")
      except Exception as e:
        print(f"  ショートを作れなかったので続行: {type(e).__name__}: {e}")

    # 4. タイトルと概要欄(タイムスタンプは動画の実測値)
    print("\n[メタ] 生成開始")
    import metadata as M
    checked, warn = M.build(script.get("meta", {}), info["chapters"], outdir)
    for t, n, note in checked:
        print(f"  [{n:2d}字/{note}] {t}")
    for w in warn:
        print(f"  ⚠ {w}")

    # 4-b. ショート用のタイトル・説明欄と、固定コメント
    try:
        sp = V.short_spec(script)
        long_title = (script.get("meta", {}).get("titles") or
                      [script.get("chapter", "")])[0]
        st = M.build_short_meta(script.get("meta", {}),
                                script.get("short") or sp, long_title, outdir)
        if st:
            print("  ショート用タイトル: " + " / ".join(st))
        else:
            print("  ⚠ ショートのタイトルが長編と同じです。"
                  "台本の short.titles に別案を入れてください")
    except Exception as e:
        print(f"  ショート用メタを作れなかったので続行: {type(e).__name__}: {e}")

    d = info["duration"]
    print("\n" + "=" * 56)
    print(f" 完了  {int(d)//60}分{int(d)%60}秒 / テロップ{info['telops']}枚 / 所要{time.time()-t0:.0f}秒")
    print(f" 出力先: {outdir}")
    print("=" * 56)
    print("\n※ YouTube への投稿はこの環境から通信できないため手動です。")
    print("   out/ の動画とサムネ、description.txt をそのまま使えます。")


if __name__ == "__main__":
    main()
