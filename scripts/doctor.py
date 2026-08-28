# -*- coding: utf-8 -*-
"""doctor.py —— 环境自检；--check-template 校验模板占位符。退出码 0=全部可用。"""
import re
import shutil
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
KNOWN_KEYS = {"TITLE", "KICKER", "DATE", "DURATION", "SPEAKERS_LINE", "SOURCE_URL",
              "MINDMAP_B64", "BODY", "CHAPTER_TITLE", "CHAPTER_TIME",
              "SPEAKER", "COLOR", "AVATAR", "TS", "PARAS_HTML", "IDX"}  # 占位符契约：须与 scripts/render.py 的 ctx 键集合保持同步


def check_env() -> int:
    bad = 0

    def item(name: str, ok: bool, hint: str = ""):
        nonlocal bad
        print(("  ✅ " if ok else "  ❌ ") + name + (f"   {hint}" if not ok and hint else ""))
        if not ok:
            bad += 1

    print("🔍 interview-report-kit 环境自检")
    item("ffmpeg", shutil.which("ffmpeg") is not None, "安装：winget install Gyan.FFmpeg 或 brew install ffmpeg")
    item("node", shutil.which("node") is not None, "安装：https://nodejs.org")
    item("mmdc(mermaid-cli)", shutil.which("mmdc") is not None, "安装：npm i -g @mermaid-js/mermaid-cli")
    for mod, hint in (("playwright", "pip install playwright && playwright install chromium"),
                      ("faster_whisper", "pip install faster-whisper")):
        try:
            __import__(mod)
            item(f"python:{mod}", True)
        except ImportError:
            item(f"python:{mod}", False, hint)
    return 1 if bad else 0


def check_template(path: Path) -> int:
    txt = path.read_text(encoding="utf-8")
    problems = []
    for m in re.finditer(r"\{\{(\w+)\}\}", txt):
        if m.group(1) not in KNOWN_KEYS:
            problems.append(f"未知占位符 {{{{{m.group(1)}}}}}")
    for kind in ("IF:MINDMAP", "#CHAPTER", "#ENTRY"):
        if f"<!--{kind}-->" in txt and f"<!--/{kind.lstrip('#')}-->" not in txt:
            problems.append(f"块 <!--{kind}--> 未闭合")
    if "<!--#ENTRY-->" in txt and "<!--#CHAPTER-->" not in txt:
        problems.append("#ENTRY 块必须嵌套在 #CHAPTER 块内")
    if path.stem == "minutes" and "<!--#CHAPTER-->" not in txt:  # 与 render.py 按 stem 分发的约定一致
        problems.append("minutes 模板必须包含 <!--#CHAPTER-->…<!--/CHAPTER--> 可重复块")
    if path.stem == "minutes" and "<!--#ENTRY-->" not in txt:
        problems.append("minutes 模板必须包含 #ENTRY 块")
    for p in problems:
        print("  ❌ " + p)
    if not problems:
        print(f"  ✅ 模板合法：{path.name}")
    return 1 if problems else 0


# 同步块：doctor.py / build_transcript.py / asr.py / fetch_minutes.py / apply_corrections.py / render.py 六个脚本的 GBK 容错保持一致
if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        if _s and hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(errors="replace")
            except Exception:
                pass


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--check-template":
        sys.exit(check_template(Path(args[1])))
    sys.exit(check_env())
