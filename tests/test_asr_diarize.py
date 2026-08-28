# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from asr_diarize import merge_sentences, spk_samples  # noqa: E402


def test_merge_same_spk_and_interleave():
    sents = [{"text": "大家好，", "start": 1000, "end": 2000, "spk": 0},
             {"text": "今天讲三件事。", "start": 2100, "end": 4000, "spk": 0},
             {"text": "谢谢。", "start": 4100, "end": 4500, "spk": 1},
             {"text": "不客气。", "start": 4600, "end": 5000, "spk": 1},
             {"text": "那继续。", "start": 5100, "end": 5500, "spk": 0}]
    paras = merge_sentences(sents, max_chars=200)
    assert paras == [
        {"s": "spk:0", "t": 1000, "x": "大家好，今天讲三件事。"},
        {"s": "spk:1", "t": 4100, "x": "谢谢。不客气。"},
        {"s": "spk:0", "t": 5100, "x": "那继续。"},
    ]


def test_merge_splits_long():
    sents = [{"text": "长" * 30, "start": i * 1000, "end": i * 1000 + 500, "spk": 2}
             for i in range(3)]
    paras = merge_sentences(sents, max_chars=70)
    assert len(paras) == 2 and len(paras[0]["x"]) == 60 and len(paras[1]["x"]) == 30


def test_merge_skips_empty_text():
    assert merge_sentences([{"text": "  ", "start": 0, "end": 1, "spk": 0}]) == []


def test_spk_samples_first_mid_last():
    paras = [{"s": "spk:0", "t": 0, "x": f"句{i}"} for i in range(5)]
    assert spk_samples(paras) == {"spk:0": ["句0", "句2", "句4"]}