# -*- coding: utf-8 -*-
"""build_transcript.py —— minutes_raw.json → 会议实录.md（逐段：**发言人** 时间戳 + 段落）。
用法：python scripts/build_transcript.py minutes_raw.json [--out 会议实录.md] [--url 来源链接]
     [--rename "spk:0=张三,spk:1=主持人"]
json 结构：{"source_label":来源名?,"total_expected":N?,"url":来源链接?,"meeting_time":会议时间?,
"paras":[{"s":发言人,"t":毫秒?,"x":文本},...]}（fetch_feishu / fetch_tencent / agent 结构化 /
asr_diarize 产出）。t 缺省输出无时间戳行；--rename 按映射改写发言人，未映射的 spk: 标签保留并提示。
"""
import argparse
import json
import sys
from pathlib import Path

from speaker_check import warn_if_no_speakers


def hmss(ms: int) -> str:
    s = ms // 1000
    return f"{s//3600:02d}:{s//60%60:02d}:{s%60:02d}"


def parse_rename(spec: str) -> dict:
    """'spk:0=张三,spk:1=主持人' → {'spk:0': '张三', ...}；格式错即退出。"""
    out = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            sys.exit(f"--rename 格式错误（应为 旧名=新名，逗号分隔）：{part}")
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    if not out:
        sys.exit("--rename 为空")
    return out


def build(md_path: Path, json_path: Path, url_override: str = None, rename: dict = None) -> None:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"json 损坏或非 UTF-8：{json_path}（{type(e).__name__}: {e}）")
    paras = raw.get("paras")
    if not paras:
        sys.exit("json 缺少 paras 数组（疑似爬取写入了错误响应体）")
    if rename:
        for p in paras:
            if p.get("s") in rename:
                p["s"] = rename[p["s"]]
        unmapped = sorted({p.get("s") for p in paras
                           if str(p.get("s") or "").startswith("spk:") and p.get("s") not in rename})
        if unmapped:
            print(f"⚠️ 未映射的说话人标签保留原名：{'、'.join(unmapped)}")
    warn_if_no_speakers(paras)
    if raw.get("total_expected") not in (None, len(paras)):
        print(f"⚠️ 警告：段数 {len(paras)} 与 total_expected {raw['total_expected']} 不符，爬取可能截断")
    speakers = list(dict.fromkeys(p.get("s") for p in paras if p.get("s")))
    url = url_override or raw.get("url")
    label = raw.get("source_label") or "飞书妙记"
    meeting_time = raw.get("meeting_time")
    lines = [
        "# 访谈会议实录",
        "",
        f"> 来源：{label} {url}" if url else f"> 记录来源：{label}",
    ]
    if meeting_time:
        lines.append(f"> 会议时间：{meeting_time}")
    last_t = paras[-1].get("t") if paras else None
    lines += [
        f"> 发言人 {len(speakers)} 人：{'、'.join(speakers)}",
        f"> 发言 {len(paras)} 段 · 末段 {hmss(int(last_t)) if last_t is not None else '-'}",
        "> 说明：本文件为原始实录，未经校对。",
        "",
        "---",
        "",
    ]
    for p in paras:
        text = " ".join(str(p.get("x", "")).split())
        if not text:
            continue
        head = f"**{p.get('s') or '—'}**"
        if p.get("t") is not None:
            head += f" {hmss(int(p['t']))}"
        lines += [head, "", text, ""]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {md_path}（{len(paras)} 段 / {len(speakers)} 人）")


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
    ap.add_argument("json_path", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录.md"))
    ap.add_argument("--url", default=None, help="覆盖 json 内 url")
    ap.add_argument("--rename", default=None,
                    help='发言人改名映射，如 "spk:0=张三,spk:1=主持人"（逗号分隔，新名不可含逗号；'
                         "对话式标记后落名）")
    a = ap.parse_args()
    if not a.json_path.exists():
        sys.exit(f"文件不存在：{a.json_path}")
    build(a.out, a.json_path, a.url, parse_rename(a.rename) if a.rename else None)