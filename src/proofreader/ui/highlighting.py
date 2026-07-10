"""偏离分析原文高亮辅助函数。"""
from __future__ import annotations

import re
from html import escape as html_escape
from typing import List, Tuple

from proofreader.checkers.consistency_checker import THRESHOLD_KEYWORDS
from proofreader.extractors.requirement_extractor import CONSTRAINT_KEYWORDS


_NUMBER_UNIT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(核|核数|CPU|GB|G|TB|T|MB|M|年|个月|月|天|日|小时|分钟|秒|ms|s|人|个|%|百分之|万元|元|次|QPS|TPS|套)",
    re.IGNORECASE,
)


def add_highlights(text: str, highlights: List[Tuple[int, int, str]]) -> str:
    """在文本指定区间添加背景色高亮。highlights: [(start, end, color), ...]。"""
    if not highlights:
        return html_escape(text)

    highlights = sorted(highlights, key=lambda x: x[0])
    merged: List[Tuple[int, int, str]] = []
    for start, end, color in highlights:
        if merged and start < merged[-1][1]:
            prev_start, prev_end, prev_color = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end), prev_color)
        else:
            merged.append((start, end, color))

    parts: List[str] = []
    last_end = 0
    for start, end, color in merged:
        parts.append(html_escape(text[last_end:start]))
        parts.append(
            '<span style="background-color: {color}; padding: 1px 3px; border-radius: 3px;">'.format(
                color=color
            )
        )
        parts.append(html_escape(text[start:end]))
        parts.append("</span>")
        last_end = end
    parts.append(html_escape(text[last_end:]))
    return "".join(parts)


def highlight_differences(req_text: str, bid_text: str) -> Tuple[str, str]:
    """
    对需求原文和投标原文进行高亮。

    需求中：数字+单位浅蓝，阈值/约束词橙色。
    投标中：与需求一致的数字绿色，不一致的黄色；缺失时在末尾提示。
    """
    req_highlights: List[Tuple[int, int, str]] = []
    bid_highlights: List[Tuple[int, int, str]] = []

    req_numbers = list(_NUMBER_UNIT_PATTERN.finditer(req_text))
    bid_numbers = list(_NUMBER_UNIT_PATTERN.finditer(bid_text))

    for m in req_numbers:
        req_highlights.append((m.start(), m.end(), "#e3f2fd"))  # 浅蓝

    missing_in_bid: List[str] = []
    for m in req_numbers:
        req_num = float(m.group(1))
        req_unit = m.group(2).lower()
        matched = False
        for bm in bid_numbers:
            bid_num = float(bm.group(1))
            bid_unit = bm.group(2).lower()
            if bid_unit == req_unit:
                matched = True
                if abs(bid_num - req_num) < 1e-6:
                    bid_highlights.append((bm.start(), bm.end(), "#c8e6c9"))  # 绿
                else:
                    bid_highlights.append((bm.start(), bm.end(), "#fff176"))  # 黄
                break
        if not matched:
            missing_in_bid.append(m.group(0))

    threshold_words = list(THRESHOLD_KEYWORDS.keys())
    for kw in threshold_words:
        for m in re.finditer(re.escape(kw), req_text):
            req_highlights.append((m.start(), m.end(), "#ffcc80"))  # 橙

    for kw in CONSTRAINT_KEYWORDS:
        for m in re.finditer(re.escape(kw), req_text):
            req_highlights.append((m.start(), m.end(), "#ffcc80"))

    req_html = add_highlights(req_text, req_highlights)
    bid_html = add_highlights(bid_text, bid_highlights)

    if missing_in_bid:
        bid_html += (
            f'<div style="margin-top:8px; color:#d32f2f; font-size:12px;">'
            f'⚠️ 投标中未找到对应项：{"、".join(missing_in_bid)}</div>'
        )

    return req_html, bid_html
