# -*- coding: utf-8 -*-
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_tencent as T  # noqa: E402


def _page(more, paragraphs):
    return {"code": 0, "more": more, "minutes": {"paragraphs": paragraphs}}


def test_paras_from_pages_maps_filters_sorts():
    p1 = _page(True, [
        {"pid": "28", "start_time": 1335349, "speaker": {"user_name": "YY评级"},
         "sentences": [{"words": [{"text": "时间差不多了"}, {"text": "，大家下午好。"}]}]},
        {"pid": "13", "start_time": 437348, "speaker": {"user_name": "YY评级"},
         "sentences": [{"words": [{"text": "好。"}]}]},
        {"pid": "14", "start_time": 500000, "speaker": {"user_name": "甲"},
         "sentences": [{"words": []}]},  # 空文本段应被过滤
    ])
    p2 = _page(False, [
        {"pid": "30", "start_time": 437000, "speaker": {"user_name": "陈老师"},
         "sentences": [{"words": [{"text": "各位领导下午好！"}]}]},
    ])
    paras = T.paras_from_pages([p1, p2])
    assert paras == [
        {"s": "陈老师", "t": 437000, "x": "各位领导下午好！"},
        {"s": "YY评级", "t": 437348, "x": "好。"},
        {"s": "YY评级", "t": 1335349, "x": "时间差不多了，大家下午好。"},
    ]


def test_paras_from_pages_missing_speaker():
    pg = _page(False, [{"pid": "1", "start_time": 10, "speaker": None,
                        "sentences": [{"words": [{"text": "x"}]}]}])
    assert T.paras_from_pages([pg]) == [{"s": "", "t": 10, "x": "x"}]