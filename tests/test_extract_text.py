# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import extract_text as X  # noqa: E402


def test_decode_utf8_and_gbk():
    assert X.decode_bytes("你好".encode("utf-8")) == "你好"
    assert X.decode_bytes("你好".encode("gb18030")) == "你好"


def test_decode_garbage_exits():
    with pytest.raises(SystemExit):
        X.decode_bytes(b"\xff\xfe\xff\xfe")


def test_extract_md_and_txt(tmp_path):
    f = tmp_path / "note.md"
    f.write_bytes("张三 00:01:23\n大家好".encode("utf-8"))  # write_bytes 避免 Windows \n→\r\n 翻译
    assert X.extract_any(f) == "张三 00:01:23\n大家好"


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("张三 00:01:23")
    d.add_paragraph("大家好")
    f = tmp_path / "a.docx"
    d.save(str(f))
    assert X.extract_any(f) == "张三 00:01:23\n大家好"


def test_extract_pdf_blank(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    f = tmp_path / "a.pdf"
    with open(f, "wb") as fh:
        w.write(fh)
    assert isinstance(X.extract_any(f), str)


def test_unsupported_ext_exits(tmp_path):
    f = tmp_path / "a.xls"
    f.write_bytes(b"x")
    with pytest.raises(SystemExit):
        X.extract_any(f)