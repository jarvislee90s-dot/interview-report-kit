# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_transcript as B  # noqa: E402


def _run(tmp_path, data, **kw):
    j = tmp_path / "minutes_raw.json"
    j.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "会议实录.md"
    B.build(out, j, **kw)
    return out.read_text(encoding="utf-8")


def test_source_label_and_url(tmp_path):
    txt = _run(tmp_path, {"source_label": "腾讯会议录制", "url": "https://meeting.tencent.com/cw/x",
                          "paras": [{"s": "甲", "t": 61000, "x": "你好"}]})
    assert "> 来源：腾讯会议录制 https://meeting.tencent.com/cw/x" in txt
    assert "**甲** 00:01:01" in txt


def test_default_label_feishu_when_missing(tmp_path):
    txt = _run(tmp_path, {"paras": [{"s": "甲", "t": 0, "x": "你好"}]})
    assert "> 记录来源：飞书妙记" in txt


def test_missing_t_renders_no_timestamp(tmp_path):
    txt = _run(tmp_path, {"paras": [{"s": "甲", "x": "没戳"}, {"s": "乙", "t": 5000, "x": "有戳"}]})
    assert "**甲**\n" in txt and "**乙** 00:00:05" in txt
    assert "末段 00:00:05" in txt


def test_rename_maps_and_keeps_unmapped(tmp_path, capsys):
    txt = _run(tmp_path, {"paras": [{"s": "spk:0", "t": 0, "x": "a"},
                                    {"s": "spk:1", "t": 1000, "x": "b"}]},
               rename={"spk:0": "张三"})
    assert "**张三**" in txt and "**spk:1**" in txt
    assert "spk:1" in capsys.readouterr().out


def test_no_speaker_warning(tmp_path, capsys):
    _run(tmp_path, {"paras": [{"s": "", "t": 0, "x": "a"}]})
    assert "无发言人" in capsys.readouterr().out