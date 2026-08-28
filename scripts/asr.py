# -*- coding: utf-8 -*-
"""asr.py —— 音频文件 → transcript.txt / transcript.json（ffmpeg 提取 + faster-whisper）。
用法：python scripts/asr.py <音频/视频文件> [--model large-v3-turbo] [--language zh] [--outdir .]
说明：CPU 转录约 1.2× 音频时长；产物已存在则跳过（断点续跑）。HF 下载失败时自动以
hf-mirror 重跑自身（_ASR_MIRROR 标记防循环回退；Windows 下 os.execve 段错误，故用子进程）。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def extract_wav(src: Path, wav: Path) -> None:
    if wav.exists():
        print(f"  ✅ 音频已存在：{wav}")
        return
    part = wav.with_name(wav.name + ".part")
    print("  🎵 ffmpeg 提取 16k 单声道 wav …")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "pcm_s16le",
                        "-ar", "16000", "-ac", "1", "-f", "wav", str(part)], check=True,
                       capture_output=True)
    except subprocess.CalledProcessError as e:
        for line in e.stderr.decode("utf-8", "replace").strip().splitlines()[-5:]:
            print("    " + line)
        sys.exit("  ❌ ffmpeg 提取失败（上方为 stderr 末 5 行）")
    os.replace(part, wav)


def load_model(model: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("未安装 faster-whisper：pip install faster-whisper")
    return WhisperModel(model, device="auto", compute_type="auto")


def transcribe(wav: Path, wm, language: str, outdir: Path) -> None:
    txt, js = outdir / "transcript.txt", outdir / "transcript.json"
    if txt.exists() and js.exists():
        print("  ✅ 转录已存在，跳过")
        return
    try:
        segments, info = wm.transcribe(str(wav), language=language, vad_filter=True)
        print(f"  ⏱ 时长 {info.duration/60:.0f} 分钟，CPU 预计 ~{info.duration*1.2/60:.0f} 分钟")
        rows, lines = [], []
        for seg in segments:
            rows.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
            lines.append(seg.text.strip())
            print(f"    [{seg.end/info.duration:5.1%}] [{seg.start:8.1f}] {seg.text.strip()[:40]}",
                  end="\r", flush=True)
        txt_text = "\n".join(lines)
        js_text = json.dumps({"language": info.language, "duration": info.duration,
                              "segments": rows}, ensure_ascii=False, indent=1)
    except Exception as e:
        sys.exit(f"  ❌ 转录失败（{type(e).__name__}: {e}）")
    print()
    txt.write_text(txt_text, encoding="utf-8")
    js.write_text(js_text, encoding="utf-8")
    print(f"  ✅ 转录完成：{len(rows)} 段 → {txt.name} / {js.name}")


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_minutes.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        if _s and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("media", type=Path)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--outdir", type=Path, default=Path("."))
    a = ap.parse_args()
    if not a.media.exists():
        sys.exit(f"文件不存在：{a.media}")
    if shutil.which("ffmpeg") is None:
        sys.exit("未安装 ffmpeg：安装：winget install Gyan.FFmpeg 或 brew install ffmpeg")
    a.outdir.mkdir(parents=True, exist_ok=True)
    wav = a.outdir / "audio.wav"
    extract_wav(a.media, wav)
    try:
        wm = load_model(a.model)
    except Exception as e:
        if os.environ.get("HF_ENDPOINT") or os.environ.get("_ASR_MIRROR"):
            sys.exit(f"  ❌ 模型装载失败（{type(e).__name__}: {e}）")
        print()
        print(f"  ⚠️ 默认源装载失败（{type(e).__name__}），切换 hf-mirror 重跑…")
        # 注：Windows 下 os.execve 实测段错误（Py3.14），改用子进程重跑自身，env 于 import 前生效
        r = subprocess.run([sys.executable, str(Path(__file__)), *sys.argv[1:]],
                           env={**os.environ, "HF_ENDPOINT": "https://hf-mirror.com",
                                "_ASR_MIRROR": "1"})
        sys.exit(r.returncode)
    transcribe(wav, wm, a.language, a.outdir)
