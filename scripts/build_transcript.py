# -*- coding: utf-8 -*-
"""build_transcript.py —— minutes_raw.json → 会议实录.md（逐段：**发言人** 时间戳 + 段落）。
用法：python scripts/build_transcript.py minutes_raw.json [--out 会议实录.md] [--url 来源链接]
json 结构：{"total_expected":N,"url":妙记链接?,"meeting_time":会议时间?,
"paras":[{"s":发言人,"t":毫秒,"x":文本},...]}（fetch_minutes.py 产出；url/meeting_time 可选，
--url 覆盖 json 内 url；total_expected 与段数不符时打印截断警告）
"""
import argparse
import json
import sys
from pathlib import Path


def hmss(ms: int) -> str:
    s = ms // 1000
    return f"{s//3600:02d}:{s//60%60:02d}:{s%60:02d}"


def build(md_path: Path, json_path: Path, url_override: str = None) -> None:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"json 损坏或非 UTF-8：{json_path}（{type(e).__name__}: {e}）")
    paras = raw.get("paras")
    if not paras:
        sys.exit("json 缺少 paras 数组（疑似爬取写入了错误响应体）")
    if raw.get("total_expected") not in (None, len(paras)):
        print(f"⚠️ 警告：段数 {len(paras)} 与 total_expected {raw['total_expected']} 不符，爬取可能截断")
    speakers = list(dict.fromkeys(p.get("s") for p in paras if p.get("s")))
    url = url_override or raw.get("url")
    meeting_time = raw.get("meeting_time")
    lines = [
        "# 访谈会议实录",
        "",
        f"> 来源：飞书妙记 {url}" if url else "> 记录来源：飞书妙记（自动化爬取）",
    ]
    if meeting_time:
        lines.append(f"> 会议时间：{meeting_time}")
    lines += [
        f"> 发言人 {len(speakers)} 人：{'、'.join(speakers)}",
        f"> 发言 {len(paras)} 段 · 末段 {hmss(paras[-1].get('t', 0)) if paras else '-'}",
        "> 说明：本文件为原始实录，未经校对。",
        "",
        "---",
        "",
    ]
    for p in paras:
        text = " ".join(str(p.get("x", "")).split())
        if not text:
            continue
        lines += [f"**{p.get('s') or '—'}** {hmss(int(p.get('t', 0)))}", "", text, ""]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {md_path}（{len(paras)} 段 / {len(speakers)} 人）")


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
    ap.add_argument("json_path", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录.md"))
    ap.add_argument("--url", default=None, help="覆盖 json 内 url")
    a = ap.parse_args()
    if not a.json_path.exists():
        sys.exit(f"文件不存在：{a.json_path}")
    build(a.out, a.json_path, a.url)
