# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import speaker_check as SC  # noqa: E402


def test_stats_counts_nonempty_speakers():
    assert SC.speaker_stats([{"s": "甲", "x": "1"}, {"s": "  ", "x": "2"}, {"x": "3"}]) == (3, 1)


def test_warn_fires_when_all_empty(capsys):
    assert SC.warn_if_no_speakers([{"s": "", "x": "a"}]) is True
    assert "无发言人" in capsys.readouterr().out


def test_warn_silent_when_named(capsys):
    assert SC.warn_if_no_speakers([{"s": "甲", "x": "a"}]) is False
    assert capsys.readouterr().out == ""