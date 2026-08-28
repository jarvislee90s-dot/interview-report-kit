# -*- coding: utf-8 -*-
"""speaker_check.py —— paras 发言人统计与全员无发言人告警（fetch_feishu / fetch_tencent /
build_transcript 复用）。场景 5：无发言人来源自动降级快速总结线。"""


def speaker_stats(paras) -> tuple:
    """返回 (总段数, 有名段数)。"""
    total = len(paras)
    named = sum(1 for p in paras if str(p.get("s") or "").strip())
    return total, named


def warn_if_no_speakers(paras) -> bool:
    """全员无发言人时打印告警并返回 True（降级快速总结线的判定依据）。"""
    total, named = speaker_stats(paras)
    if total and named == 0:
        print("⚠️ 该来源无发言人信息：无法生成按发言人组织的纪要，将走快速总结线"
              "（完成后提醒用户：补发言人信息才能出访谈纪要.html）——见 SKILL.md 第 0 环节场景 5。")
        return True
    return False