# -*- coding: utf-8 -*-
"""extract_text.py —— 本地纪要文档（md/txt/docx/pdf）→ 纯文本 .extracted.txt（UTF-8）。
只做解码与格式提取，不做发言人/时间戳结构识别（结构化由 agent 环节完成，见 SKILL.md A2 通道）。
用法：python scripts/extract_text.py <文件> [--out <名>.extracted.txt]
"""
import argparse
import sys
from pathlib import Path

DOC_EXTS = {".md", ".txt", ".docx", ".pdf"}


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    sys.exit("❌ 文本解码失败（utf-8 / gb18030 均失败）：请用 UTF-8 或 GBK 重存文件")


def extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        sys.exit("未安装 python-docx：pip install python-docx")
    try:
        paras = [p.text for p in docx.Document(str(path)).paragraphs]
    except Exception as e:
        sys.exit(f"❌ docx 解析失败（{type(e).__name__}: {e}）：请在 Word 中重存或另存为 txt")
    return "\n".join(paras)


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("未安装 pypdf：pip install pypdf")
    try:
        pages = [pg.extract_text() or "" for pg in PdfReader(str(path)).pages]
    except Exception as e:
        sys.exit(f"❌ pdf 解析失败（{type(e).__name__}: {e}）：请重存或转存为 txt/docx")
    return "\n".join(pages)


def extract_any(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return decode_bytes(path.read_bytes())
    if ext == ".docx":
        return extract_docx(path)
    if ext == ".pdf":
        return extract_pdf(path)
    sys.exit(f"不支持的格式 {ext}（支持 {' '.join(sorted(DOC_EXTS))}）")


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
    ap.add_argument("file", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="默认 <名>.extracted.txt")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"文件不存在：{a.file}")
    text = extract_any(a.file)
    out = a.out or a.file.with_name(a.file.stem + ".extracted.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    n_lines = len([l for l in text.splitlines() if l.strip()])
    print(f"✅ 提取完成：{n_lines} 行 / {len(text)} 字 → {out}")
    print("下一步：agent 按 SKILL.md A2 通道读取该文件，忠实结构化为 minutes_raw.json，再跑 build_transcript。")