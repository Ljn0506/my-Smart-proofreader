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


TIME_UNITS = {"年": 365, "个月": 30, "月": 30, "天": 1, "日": 1, "小时": 1, "h": 1}

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
}


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


def _compare_time(req_text: str, bid_text: str) -> List[str]:
    """比较需求与投标中的时间值，返回所有不一致消息。"""
    messages: List[str] = []

    # 特殊：7×24 小时服务
    if _has_7x24(req_text) and not (
        _has_7x24(bid_text) or "全天候" in bid_text or "全天" in bid_text
    ):
        messages.append("要求提供 7×24 小时技术支持服务，投标未明确承诺全天候服务")

    req_times = _extract_time_values(_strip_7x24(req_text))
    if not req_times:
        return messages

    bid_times = _extract_time_values(_strip_7x24(bid_text))
    if not bid_times:
        messages.append("投标未明确响应时间要求")
        return messages

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
            if direction in ("ge", "gt") and bid_days < req_days:
                messages.append(f"要求不少于 {req_val}{req_unit}，投标仅 {bid_val}{bid_unit}")
            elif direction in ("le", "lt") and bid_days > req_days:
                messages.append(f"要求不超过 {req_val}{req_unit}，投标为 {bid_val}{bid_unit}")
        else:
            # 尝试用未使用的第一个投标时间值兜底比较
            available = [j for j in range(len(bid_times)) if j not in used_bid]
            if available:
                j = available[0]
                bid_val, bid_unit, _, _ = bid_times[j]
                used_bid.add(j)
                bid_days = bid_val * TIME_UNITS.get(bid_unit, 1)
                if direction in ("ge", "gt") and bid_days < req_days:
                    messages.append(f"要求不少于 {req_val}{req_unit}，投标仅 {bid_val}{bid_unit}")
                elif direction in ("le", "lt") and bid_days > req_days:
                    messages.append(f"要求不超过 {req_val}{req_unit}，投标为 {bid_val}{bid_unit}")

    return messages


def _extract_simple_numbers(text: str) -> List[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]


def _compare_numbers(req_text: str, bid_text: str) -> Optional[str]:
    # 优先按单位配对比较
    req_pairs = _extract_numbers(req_text)
    bid_pairs = _extract_numbers(bid_text)
    if not req_pairs:
        return None
    if not bid_pairs:
        return "投标未明确响应数值要求"

    direction = None
    for kw, (op, _) in THRESHOLD_KEYWORDS.items():
        if kw in req_text:
            direction = op
            break

    messages = []
    used_bid = set()
    for req_num, req_unit in req_pairs:
        # 找同单位的投标数值
        matches = [(j, bn, bu) for j, (bn, bu) in enumerate(bid_pairs) if bu.lower() == req_unit.lower()]
        if matches:
            j, bid_num, _ = matches[0]
            used_bid.add(j)
            if direction in ("ge", "gt") and bid_num < req_num:
                messages.append(f"要求 ≥ {req_num}{req_unit}，投标为 {bid_num}{req_unit}")
            elif direction in ("le", "lt") and bid_num > req_num:
                messages.append(f"要求 ≤ {req_num}{req_unit}，投标为 {bid_num}{req_unit}")
        else:
            # 无同单位，尝试用裸数字比较
            if bid_pairs and len(bid_pairs) > len(used_bid):
                j = min(set(range(len(bid_pairs))) - used_bid)
                bid_num, _ = bid_pairs[j]
                used_bid.add(j)
                if direction in ("ge", "gt") and bid_num < req_num:
                    messages.append(f"要求 ≥ {req_num}，投标为 {bid_num}")
                elif direction in ("le", "lt") and bid_num > req_num:
                    messages.append(f"要求 ≤ {req_num}，投标为 {bid_num}")

    if messages:
        return "；".join(messages)
    return None


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
            issues.append(_make_issue(
                idx, "MISS", IssueType.MISSING_RESPONSE, IssueLevel.ERROR,
                req, "", "未找到投标文件中对应此需求的响应内容",
                "在投标文件中补充针对该需求的具体响应。", []
            ))
            continue

        best_block, best_score = result.matched_blocks[0]
        bid_text = best_block.text

        if result.match_type in ("exact", "keyword"):
            time_messages = _compare_time(req_body, bid_text)
            for msg_idx, time_msg in enumerate(time_messages):
                issues.append(_make_issue(
                    idx, f"TIME-{msg_idx}", IssueType.TIME_MISMATCH, IssueLevel.WARNING,
                    req, bid_text, time_msg,
                    "核对并调整投标中的时间/期限表述，确保满足需求要求。", [best_block]
                ))

            # 若已报时间不一致，跳过数值型参数检查，避免重复
            if not time_messages:
                num_msg = _compare_numbers(req_body, bid_text)
                if num_msg:
                    issues.append(_make_issue(
                        idx, "NUM", IssueType.PARAMETER_MISMATCH, IssueLevel.WARNING,
                        req, bid_text, num_msg,
                        "核对投标中的技术参数，确保与需求一致。", [best_block]
                    ))
        else:
            if best_score < semantic_threshold:
                issues.append(_make_issue(
                    idx, "SEM", IssueType.SEMANTIC_LOW, IssueLevel.WARNING,
                    req, bid_text, f"投标中疑似未充分响应该需求（匹配度 {best_score:.2f}）",
                    "检查投标文件中是否有明确回应，必要时补充内容。", [best_block]
                ))

    return issues
