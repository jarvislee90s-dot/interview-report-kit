# tests/test_apply_corrections.py
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import apply_corrections as AC  # noqa: E402

MD_NO_TS = """# 访谈会议实录

> 记录来源：本地文档：x.txt
> 说明：本文件为原始实录，未经校对。

---

**甲**

大家好。

**乙** 00:00:05

谢谢。
"""


def _run(tmp_path, md_text, rules, monkeypatch):
    md = tmp_path / "会议实录.md"
    md.write_text(md_text, encoding="utf-8")
    rj = tmp_path / "corrections.json"
    rj.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "会议实录（修正）.md"
    monkeypatch.setattr(sys, "argv",
                        ["apply_corrections.py", str(md), str(rj), "--out", str(out)])
    AC.main()
    return out.read_text(encoding="utf-8")


def test_apply_on_no_ts_transcript(tmp_path, monkeypatch):
    txt = _run(tmp_path, MD_NO_TS,
               [{"old": "大家好", "new": "大家好。各位", "expect": 1, "basis": "t"}], monkeypatch)
    assert "大家好。各位" in txt
    assert "已对照本地音频转录逐段交叉校对" in txt


def test_guard_breaking_speaker_line_on_no_ts(tmp_path, monkeypatch):
    # 无时间戳实录：规则吃掉 **发言人** 行必须被段落数守卫拦下（时间戳可选后的回归锁）
    with pytest.raises(SystemExit) as ei:
        _run(tmp_path, MD_NO_TS,
             [{"old": "**甲**", "new": "甲", "expect": 1, "basis": "t"}], monkeypatch)
    assert "段落数变化" in str(ei.value)
