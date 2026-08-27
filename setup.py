#!/usr/bin/env python3
"""実行環境の準備。
   この作業環境はセッションごとに作り直されるため、
   VOICEVOX の取得・展開・起動を毎回自動で行う。"""
import os, subprocess, sys, time, urllib.request

ENGINE_URL = ("https://github.com/VOICEVOX/voicevox_engine/releases/download/"
              "0.22.0/voicevox_engine-linux-cpu-0.22.0.7z.001")
ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VVDIR  = os.path.join(ROOT, ".voicevox")
PORT   = 50021
BASE   = f"http://127.0.0.1:{PORT}"

PKGS = ["numpy", "pillow", "scipy", "py7zr", "pyopenjtalk"]


def log(m): print(f"[準備] {m}", flush=True)


def alive(timeout=3):
    try:
        urllib.request.urlopen(BASE + "/version", timeout=timeout).read()
        return True
    except Exception:
        return False


def ensure_packages():
    missing = []
    for p in PKGS:
        mod = {"pillow": "PIL"}.get(p, p)
        try:
            __import__(mod)
        except ImportError:
            missing.append(p)
    if missing:
        log(f"不足パッケージを導入: {', '.join(missing)}")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                        "--break-system-packages", *missing], check=True)


def ensure_ffmpeg():
    if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
        raise SystemExit("ffmpeg が見つかりません。この環境では動画を書き出せません。")


def ensure_engine():
    if alive():
        log("VOICEVOX は起動済み")
        return
    run = os.path.join(VVDIR, "linux-cpu", "run")
    if not os.path.exists(run):
        os.makedirs(VVDIR, exist_ok=True)
        arc = os.path.join(VVDIR, "engine.7z")
        if not os.path.exists(arc):
            log("VOICEVOX を取得中 (約1.3GB)")
            t = time.time()
            urllib.request.urlretrieve(ENGINE_URL, arc)
            log(f"取得完了 {time.time()-t:.0f}秒")
        log("展開中")
        import py7zr
        t = time.time()
        with py7zr.SevenZipFile(arc, "r") as z:
            z.extractall(VVDIR)
        log(f"展開完了 {time.time()-t:.0f}秒")
        os.remove(arc)
    os.chmod(run, 0o755)
    log("エンジンを起動中")
    subprocess.Popen([run, "--host", "127.0.0.1", "--port", str(PORT)],
                     cwd=os.path.dirname(run),
                     stdout=open(os.path.join(VVDIR, "engine.log"), "w"),
                     stderr=subprocess.STDOUT)
    for _ in range(60):
        time.sleep(2)
        if alive():
            log("起動完了")
            return
    raise SystemExit("VOICEVOX が起動しませんでした。.voicevox/engine.log を確認してください。")


def prepare():
    ensure_packages()
    ensure_ffmpeg()
    ensure_engine()
