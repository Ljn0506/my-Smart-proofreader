"""内容一致性检查：参数、时间、缺失响应等。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import MatchResult, _extract_numbers
from proofreader.parsers.docx_parser import TextBlock


class IssueLevel(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueType(str, Enum):
    MISSING_RESPONSE = "missing_response"
    PARAMETER_MISMATCH = "parameter_mismatch"
    TIME_MISMATCH = "time_mismatch"
    KEYWORD_MISSING = "keyword_missing"
    SEMANTIC_LOW = "semantic_low"


@dataclass
class ConsistencyIssue:
    issue_id: str
    issue_type: IssueType
    level: IssueLevel
    requirement_id: str
    requirement_text: str
    bid_text: str
    message: str
    suggestion: str
    bid_blocks: List[TextBlock] = field(default_factory=list)
    candidate_bid_texts: List[Tuple[str, float]] = field(default_factory=list)
    # 需要在投标段落中精确标红的文字片段（如 "2年"、"8核"）
    highlight_spans: List[str] = field(default_factory=list)


TIME_UNITS = {"年": 365, "个月": 30, "月": 30, "天": 1, "日": 1, "小时": 1 / 24, "h": 1 / 24}

THRESHOLD_KEYWORDS = {
    "≥": ("ge", True),
    ">=": ("ge", True),
    ">": ("gt", True),
    "≤": ("le", False),
    "<=": ("le", False),
    "<": ("lt", False),
    "不少于": ("ge", True),
    "至少": ("ge", True),
    "最低": ("ge", True),
    "不超过": ("le", False),
    "不得超过": ("le", False),
    "不多于": ("le", False),
    "最多": ("le", False),
    "最高": ("le", False),
    "不大于": ("le", False),
    "不小于": ("ge", True),
    "以内": ("le", False),
    "达到": ("ge", True),
    "需达到": ("ge", True),
    "应为": ("ge", True),
}

# 当需求文本没有明确阈值方向词时，这些单位默认按"不少于"处理
# （技术参数通常表示最低要求，如并发用户、可用性、内存等）
DEFAULT_GE_UNITS = {"%", "人", "用户", "次", "个", "核", "gb", "g", "mb", "m", "tb", "t", "qps", "tps"}


def _has_7x24(text: str) -> bool:
    """检查文本是否包含 7×24 小时服务表述。"""
    return bool(re.search(r"\d+\s*[×xX]\s*24\s*小时", text))


def _detect_time_direction(req_text: str, match_start: int) -> str:
    """根据时间值前的约束关键词，判断该时间值的比较方向。"""
    prefix = req_text[:match_start]
    best_pos = -1
    best_dir = "ge"  # 默认按不少于处理
    for kw, (op, _) in THRESHOLD_KEYWORDS.items():
        pos = prefix.rfind(kw)
        if pos > best_pos:
            best_pos = pos
            best_dir = op
    return best_dir


def _extract_time_values(text: str) -> List[Tuple[float, str, str, int]]:
    """
    提取文本中所有时间值。
    返回 [(数值, 单位, 方向, 起始位置), ...]。
    """
    pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(年|个月|月|天|日|小时|h)")
    results = []
    for match in pattern.finditer(text):
        val = float(match.group(1))
        unit = match.group(2)
        direction = _detect_time_direction(text, match.start())
        results.append((val, unit, direction, match.start()))
    return results


def _strip_7x24(text: str) -> str:
    """移除 7×24 小时相关文本，避免普通时间提取重复处理。"""
    return re.sub(r"\d+\s*[×xX]\s*24\s*小时", "", text)


def _compare_time(req_text: str, bid_text: str) -> Tuple[List[str], List[str]]:
    """比较需求与投标中的时间值，返回不一致消息列表和投标中需标红的片段列表。"""
    messages: List[str] = []
    spans: List[str] = []

    # 特殊：7×24 小时服务
    if _has_7x24(req_text) and not (
        _has_7x24(bid_text) or "全天候" in bid_text or "全天" in bid_text
    ):
        messages.append("要求提供 7×24 小时技术支持服务，投标未明确承诺全天候服务")

    req_times = _extract_time_values(_strip_7x24(req_text))
    if not req_times:
        return messages, spans

    bid_times = _extract_time_values(_strip_7x24(bid_text))
    if not bid_times:
        messages.append("投标未明确响应时间要求")
        return messages, spans

    def _record_mismatch(req_val: float, req_unit: str, req_days: float, bid_val: float, bid_unit: str, bid_days: float, direction: str) -> None:
        if direction in ("ge", "gt") and bid_days < req_days:
            messages.append(f"要求不少于 {req_val}{req_unit}，投标仅 {bid_val}{bid_unit}")
        elif direction in ("le", "lt") and bid_days > req_days:
            messages.append(f"要求不超过 {req_val}{req_unit}，投标为 {bid_val}{bid_unit}")
        else:
            return
        spans.append(f"{bid_val:g}{bid_unit}")

    # 为每个需求时间值找同单位的投标时间值
    used_bid: set[int] = set()
    for req_val, req_unit, direction, _ in req_times:
        req_days = req_val * TIME_UNITS.get(req_unit, 1)
        matches = [
            (j, bv, bu, bd)
            for j, (bv, bu, bd, _) in enumerate(bid_times)
            if bu == req_unit and j not in used_bid
        ]
        if matches:
            j, bid_val, bid_unit, _ = matches[0]
            used_bid.add(j)
            bid_days = bid_val * TIME_UNITS.get(bid_unit, 1)
            _record_mismatch(req_val, req_unit, req_days, bid_val, bid_unit, bid_days, direction)
        else:
            # 尝试用未使用的第一个投标时间值兜底比较
            available = [j for j in range(len(bid_times)) if j not in used_bid]
            if available:
                j = available[0]
                bid_val, bid_unit, _, _ = bid_times[j]
                used_bid.add(j)
                bid_days = bid_val * TIME_UNITS.get(bid_unit, 1)
                _record_mismatch(req_val, req_unit, req_days, bid_val, bid_unit, bid_days, direction)

    return messages, spans


def _extract_simple_numbers(text: str) -> List[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


def _detect_number_direction(req_text: str, match_start: int, req_unit: str) -> str | None:
    """根据数值前的约束关键词判断比较方向；无明确方向时按单位类型给出默认方向。"""
    prefix = req_text[:match_start]
    best_pos = -1
    best_dir = None
    for kw, (op, _) in THRESHOLD_KEYWORDS.items():
        pos = prefix.rfind(kw)
        if pos > best_pos:
            best_pos = pos
            best_dir = op
    if best_dir is not None:
        return best_dir
    if req_unit.lower() in DEFAULT_GE_UNITS:
        return "ge"
    return None


def _record_number_mismatch(
    req_num: float,
    req_unit: str,
    bid_num: float,
    bid_unit: str | None,
    direction: str,
    messages: List[str],
    spans: List[str],
) -> None:
    unit_text = req_unit if bid_unit is not None else ""
    if direction in ("ge", "gt") and bid_num < req_num:
        messages.append(f"要求 ≥ {req_num}{unit_text}，投标为 {bid_num}{unit_text}")
    elif direction in ("le", "lt") and bid_num > req_num:
        messages.append(f"要求 ≤ {req_num}{unit_text}，投标为 {bid_num}{unit_text}")
    else:
        return
    spans.append(f"{bid_num:g}{unit_text}")


def _compare_numbers(req_text: str, bid_text: str) -> Tuple[Optional[str], List[str]]:
    # 提取带位置信息的数字+单位，用于逐个数判断方向
    req_pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|个|%|百分之|万元|元|次|QPS|TPS|套)"
    )
    bid_pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|个|%|百分之|万元|元|次|QPS|TPS|套)"
    )

    req_matches = list(req_pattern.finditer(req_text))
    bid_matches = list(bid_pattern.finditer(bid_text))

    # 为兼容语义匹配层，仍复用 _extract_numbers 返回的 (num, unit) 列表
    req_pairs = _extract_numbers(req_text)
    bid_pairs = _extract_numbers(bid_text)

    spans: List[str] = []
    if not req_pairs:
        return None, spans
    if not bid_pairs:
        return "投标未明确响应数值要求", spans

    messages: List[str] = []
    used_bid: set[int] = set()

    for req_idx, (req_num, req_unit) in enumerate(req_pairs):
        req_match = req_matches[req_idx] if req_idx < len(req_matches) else None
        match_start = req_match.start() if req_match else 0
        direction = _detect_number_direction(req_text, match_start, req_unit)
        if direction is None:
            continue

        # 优先找同单位的投标数值
        matches = [
            (j, bn, bu)
            for j, (bn, bu) in enumerate(bid_pairs)
            if bu.lower() == req_unit.lower() and j not in used_bid
        ]
        if matches:
            j, bid_num, _ = matches[0]
            used_bid.add(j)
            _record_number_mismatch(req_num, req_unit, bid_num, req_unit, direction, messages, spans)
        else:
            # 无同单位，按顺序使用未使用的投标数字兜底比较
            available = [j for j in range(len(bid_pairs)) if j not in used_bid]
            if available:
                j = available[0]
                bid_num, _ = bid_pairs[j]
                used_bid.add(j)
                _record_number_mismatch(req_num, req_unit, bid_num, None, direction, messages, spans)

    if messages:
        return "；".join(messages), spans
    return None, spans


def _make_issue(
    idx: int,
    suffix: str,
    issue_type: IssueType,
    level: IssueLevel,
    req: RequirementItem,
    bid_text: str,
    message: str,
    suggestion: str,
    bid_blocks: List[TextBlock],
    candidate_bid_texts: List[Tuple[str, float]] | None = None,
    highlight_spans: List[str] | None = None,
) -> ConsistencyIssue:
    return ConsistencyIssue(
        issue_id=f"ISS-{idx+1}-{suffix}",
        issue_type=issue_type,
        level=level,
        requirement_id=req.item_id,
        requirement_text=req.text,
        bid_text=bid_text,
        message=message,
        suggestion=suggestion,
        bid_blocks=bid_blocks,
        candidate_bid_texts=candidate_bid_texts or [],
        highlight_spans=highlight_spans or [],
    )


def _strip_numbering(text: str) -> str:
    """去除需求条目前的编号，避免把编号当作数值。"""
    patterns = [
        r"^\d+[\.、)）]\s*",
        r"^[（(]\d+[)）]\s*",
        r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*",
        r"^[一二三四五六七八九十]+[\.、)）]\s*",
        r"^[（(][一二三四五六七八九十]+[)）]\s*",
    ]
    for p in patterns:
        text = re.sub(p, "", text)
    return text


def check_consistency(
    match_results: List[MatchResult],
    semantic_threshold: float = 0.25,
) -> List[ConsistencyIssue]:
    issues: List[ConsistencyIssue] = []

    for idx, result in enumerate(match_results):
        req = result.requirement
        req_body = _strip_numbering(req.text)

        if not result.matched_blocks:
            # 提取需求中的关键约束词/数值作为标红提示
            miss_spans = [kw for kw in THRESHOLD_KEYWORDS if kw in req_body]
            miss_spans.extend(f"{num:g}{unit}" for num, unit in _extract_numbers(req_body))
            if not miss_spans:
                miss_spans = [req_body[:50]]
            issues.append(_make_issue(
                idx, "MISS", IssueType.MISSING_RESPONSE, IssueLevel.ERROR,
                req, "", "未找到投标文件中对应此需求的响应内容",
                "在投标文件中补充针对该需求的具体响应。", [], [], highlight_spans=miss_spans
            ))
            continue

        candidate_bid_texts = [(block.text, float(score)) for block, score in result.matched_blocks]
        best_block, best_score = result.matched_blocks[0]
        bid_text = best_block.text

        if result.match_type in ("exact", "keyword"):
            time_messages, time_spans = _compare_time(req_body, bid_text)
            for msg_idx, time_msg in enumerate(time_messages):
                issues.append(_make_issue(
                    idx, f"TIME-{msg_idx}", IssueType.TIME_MISMATCH, IssueLevel.WARNING,
                    req, bid_text, time_msg,
                    "核对并调整投标中的时间/期限表述，确保满足需求要求。",
                    [best_block], candidate_bid_texts, highlight_spans=[time_spans[msg_idx]] if msg_idx < len(time_spans) else [],
                ))

            # 若已报时间不一致，跳过数值型参数检查，避免重复
            if not time_messages:
                num_msg, num_spans = _compare_numbers(req_body, bid_text)
                if num_msg:
                    issues.append(_make_issue(
                        idx, "NUM", IssueType.PARAMETER_MISMATCH, IssueLevel.WARNING,
                        req, bid_text, num_msg,
                        "核对投标中的技术参数，确保与需求一致。",
                        [best_block], candidate_bid_texts, highlight_spans=num_spans,
                    ))
        else:
            if best_score < semantic_threshold:
                issues.append(_make_issue(
                    idx, "SEM", IssueType.SEMANTIC_LOW, IssueLevel.WARNING,
                    req, bid_text, f"投标中疑似未充分响应该需求（匹配度 {best_score:.2f}）",
                    "检查投标文件中是否有明确回应，必要时补充内容。",
                    [best_block], candidate_bid_texts, highlight_spans=[bid_text],
                ))

    return issues
