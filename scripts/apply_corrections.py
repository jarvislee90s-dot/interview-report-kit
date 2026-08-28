# -*- coding: utf-8 -*-
"""apply_corrections.py —— 读 corrections.json（agent 生成的校正规则）应用到 会议实录.md。
用法：python scripts/apply_corrections.py <会议实录.md> <corrections.json> [--out 会议实录（修正）.md]
规则格式：[{"old":"原文","new":"修正","expect":1,"basis":"依据"},...]
硬校验：每条规则命中数必须等于 expect；输出段落数必须与输入一致；违规即失败并报告。
契约：规则按序应用——第 i 条在 前 i-1 条应用后的文本 上计数与替换；expect 缺省为 1。
"""
import argparse
import json
import re
import sys
from pathlib import Path

PAT = re.compile(r"^\*\*(.+?)\*\* (\d{2}:\d{2}:\d{2})", re.M)
NOTE_OLD = "> 说明：本文件为原始实录，未经校对。"
NOTE_NEW = "> 说明：本文件已对照本地音频转录逐段交叉校对（依据见 corrections.json）。"


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_minutes.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        if _s and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except Exception:
                pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("md", type=Path)
    ap.add_argument("rules", type=Path)
    ap.add_argument("--out", type=Path, default=Path("会议实录（修正）.md"))
    a = ap.parse_args()
    for f in (a.md, a.rules):
        if not f.exists():
            sys.exit(f"文件不存在：{f}")
    text = a.md.read_text(encoding="utf-8")
    try:
        rules = json.loads(a.rules.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        sys.exit(f"corrections.json 损坏或非 UTF-8：{a.rules}（{type(e).__name__}: {e}）")
    if not isinstance(rules, list):
        sys.exit("corrections.json 顶层必须是规则数组")

    n_paras = len(PAT.findall(text))
    misses = []
    for i, r in enumerate(rules, 1):
        expect = r.get("expect", 1) if isinstance(r, dict) else None
        if (not isinstance(r, dict) or not isinstance(r.get("old"), str)
                or not isinstance(r.get("new"), str)
                or not isinstance(expect, int) or isinstance(expect, bool)):
            misses.append(f"  #{i} 规则非法（需为含字符串 old/new、整数 expect 的对象）")
            continue
        old, new = r["old"], r["new"]
        if not old:
            misses.append(f"  #{i} old 为空字符串")
            continue
        cnt = text.count(old)
        if cnt != expect:
            misses.append(f"  #{i} 命中 {cnt} 次 ≠ expect {expect}：{old}")
            continue
        text = text.replace(old, new)
    if misses:
        print("❌ 以下规则未通过硬校验，未写入任何文件：")
        print("\n".join(misses))
        sys.exit(1)

    if NOTE_OLD in text:
        text = text.replace(NOTE_OLD, NOTE_NEW, 1)
    else:  # 兼容历史头部措辞（如 fixtures 的“自动化爬取的原始实录”）
        text = re.sub(r"^> 说明：.*未经校对。*$", NOTE_NEW, text, count=1, flags=re.M)

    if len(PAT.findall(text)) != n_paras:
        sys.exit(f"❌ 段落数变化：{n_paras} → {len(PAT.findall(text))}（规则疑似破坏 **发言人** 时间戳行）")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print(f"✅ applied {len(rules)} 条 → {a.out}（段落数 {n_paras} 不变）")


if __name__ == "__main__":
    main()
