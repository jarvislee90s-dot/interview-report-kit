# -*- coding: utf-8 -*-
"""asr_diarize.py —— 音频 → minutes_raw.json（FunASR 转写 + cam++ 说话人分离，s=spk:N）。
用法：python scripts/asr_diarize.py <音频/视频文件> [--outdir asr_runs/<名>] [--out minutes_raw.json]
依赖：pip install -r requirements-diarize.txt（模型自动从 ModelScope 下载，国内直连，无需 HF 授权）。
产物：asr_runs/<名>/diarize_raw.json（句级原始）+ minutes_raw.json（段级，s=spk:0/1/2…）。
结束后打印每号声音首/中/末样例句，供对话式标记（SKILL.md ③′）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from asr import extract_wav  # 复用 ffmpeg 提取（同目录模块）
from speaker_check import warn_if_no_speakers


def merge_sentences(sentences: list, max_chars: int = 500) -> list:
    """句级 [{text,start,end,spk}]（毫秒）→ 段级 [{s,t,x}]：同人相邻合并，超长切段。"""
    paras = []
    for s in sentences:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        spk = f"spk:{s.get('spk', '?')}"
        if paras and paras[-1]["s"] == spk and len(paras[-1]["x"]) + len(text) <= max_chars:
            paras[-1]["x"] += text
        else:
            paras.append({"s": spk, "t": int(s.get("start", 0)), "x": text})
    return paras


def spk_samples(paras: list) -> dict:
    """每号声音取首/中/末段文本（前 60 字），供对话式标记辨认。"""
    by = {}
    for p in paras:
        by.setdefault(p["s"], []).append(p["x"][:60])
    return {k: [texts[i] for i in sorted({0, len(texts) // 2, len(texts) - 1})]
            for k, texts in by.items()}


def load_model():
    try:
        from funasr import AutoModel
    except ImportError:
        sys.exit("未安装 funasr：pip install -r requirements-diarize.txt")
    return AutoModel(model="paraformer-zh", vad_model="fsmn-vad",
                     punc_model="ct-punc", spk_model="cam++", disable_update=True)


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_feishu.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
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
    ap.add_argument("--outdir", type=Path, default=None, help="默认 asr_runs/<文件名>")
    ap.add_argument("--out", type=Path, default=Path("minutes_raw.json"))
    a = ap.parse_args()
    if not a.media.exists():
        sys.exit(f"文件不存在：{a.media}")
    if shutil.which("ffmpeg") is None:
        sys.exit("未安装 ffmpeg：安装：winget install Gyan.FFmpeg 或 brew install ffmpeg")
    outdir = a.outdir or Path("asr_runs") / a.media.stem
    outdir.mkdir(parents=True, exist_ok=True)
    raw_p, json_p = outdir / "diarize_raw.json", outdir / "minutes_raw.json"

    if raw_p.exists() and json_p.exists():  # 断点续跑
        raw = json.loads(raw_p.read_text(encoding="utf-8"))
        print("  ✅ 分离转录已存在，跳过模型调用")
    else:
        extract_wav(a.media, outdir / "audio.wav")
        model = load_model()
        print("  👂 FunASR 转录 + 说话人分离（首次运行自动下载模型；CPU 耗时可观，建议后台）…")
        res = model.generate(input=str(outdir / "audio.wav"), batch_size_s=300)
        sentences = (res[0] or {}).get("sentence") or []
        raw = {"sentences": sentences}
        raw_p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        json_p.unlink(missing_ok=True)

    paras = merge_sentences(raw.get("sentences") or [])
    if not paras:
        sys.exit("  ❌ 分离转录结果为空")
    warn_if_no_speakers(paras)
    a.out.write_text(json.dumps({"source_label": "本地录音（FunASR 分离转录）", "paras": paras},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    json_p.write_text(a.out.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"  ✅ 分离转录完成：{len(paras)} 段 → {raw_p.name} / {a.out}")
    print("👂 说话人样例（供对话式标记，SKILL.md ③′）：")
    n_of = {}
    for p in paras:
        n_of[p["s"]] = n_of.get(p["s"], 0) + 1
    for spk, samples in spk_samples(paras).items():
        print(f"  {spk}（{n_of[spk]} 段）：" + " / ".join(f"「{t}」" for t in samples))
    print('下一步：问用户各号是谁，然后 build_transcript --rename "spk:0=名字,…" 落名。')