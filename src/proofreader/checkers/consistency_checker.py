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


@dataclass
class UnitMeta:
    """单位元数据：换算系数（time 类单位）与默认比较方向。"""

    category: str  # "time" 或 "metric"
    conversion: float | None = None  # 换算到基准单位（如天），非 time 单位为 None
    default_direction: str | None = None  # 无量词方向时的默认方向


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

# 统一单位元数据表：合并原 TIME_UNITS 与原 DEFAULT_GE_UNITS，避免规则分散
UNIT_METAS: dict[str, UnitMeta] = {
    # 时间单位：带换算系数，默认方向 ≥
    "年": UnitMeta("time", conversion=365, default_direction="ge"),
    "个月": UnitMeta("time", conversion=30, default_direction="ge"),
    "月": UnitMeta("time", conversion=30, default_direction="ge"),
    "天": UnitMeta("time", conversion=1, default_direction="ge"),
    "日": UnitMeta("time", conversion=1, default_direction="ge"),
    "小时": UnitMeta("time", conversion=1 / 24, default_direction="ge"),
    "h": UnitMeta("time", conversion=1 / 24, default_direction="ge"),
    # 常用技术参数单位：默认方向 ≥
    "%": UnitMeta("metric", default_direction="ge"),
    "人": UnitMeta("metric", default_direction="ge"),
    "用户": UnitMeta("metric", default_direction="ge"),
    "次": UnitMeta("metric", default_direction="ge"),
    "个": UnitMeta("metric", default_direction="ge"),
    "核": UnitMeta("metric", default_direction="ge"),
    "gb": UnitMeta("metric", default_direction="ge"),
    "g": UnitMeta("metric", default_direction="ge"),
    "mb": UnitMeta("metric", default_direction="ge"),
    "m": UnitMeta("metric", default_direction="ge"),
    "tb": UnitMeta("metric", default_direction="ge"),
    "t": UnitMeta("metric", default_direction="ge"),
    "qps": UnitMeta("metric", default_direction="ge"),
    "tps": UnitMeta("metric", default_direction="ge"),
}


@dataclass
class Quantity:
    """从文本中提取的数值+单位+比较方向。"""

    value: float
    unit: str
    direction: str
    position: int
    meta: UnitMeta | None = None

    @property
    def normalized_value(self) -> float:
        """换算到基准单位后的值；无换算系数时返回原值。"""
        if self.meta is not None and self.meta.conversion is not None:
            return self.value * self.meta.conversion
        return self.value

    @property
    def is_time(self) -> bool:
        """是否为时间类量值。"""
        return self.meta is not None and self.meta.category == "time"


_TIME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(年|个月|月|天|日|小时|h)")

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(?:并发|在线|同时|核心|可用性|成功率|内存|存储|容量|带宽|延迟|响应|吞吐|支持|达到|约为|大约|约|大概)?\s*"
    r"(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|用户|个|%|百分之|万元|元|次|QPS|TPS|套)",
    re.IGNORECASE,
)


def _has_7x24(text: str) -> bool:
    """检查文本是否包含 7×24 小时服务表述。"""
    return bool(re.search(r"\d+\s*[×xX]\s*24\s*小时", text))


def _strip_7x24(text: str) -> str:
    """移除 7×24 小时相关文本，避免普通时间提取重复处理。"""
    return re.sub(r"\d+\s*[×xX]\s*24\s*小时", "", text)


def _detect_direction(req_text: str, match_start: int, unit: str | None = None) -> str | None:
    """根据阈值方向词判断比较方向；无明确方向时按单位元数据返回默认方向。"""
    prefix = req_text[:match_start]
    best_pos = -1
    best_dir: str | None = None
    for kw, (op, _) in THRESHOLD_KEYWORDS.items():
        pos = prefix.rfind(kw)
        if pos > best_pos:
            best_pos = pos
            best_dir = op
    if best_dir is not None:
        return best_dir
    if unit:
        meta = UNIT_METAS.get(unit.lower())
        if meta is not None:
            return meta.default_direction
    return None


def _extract_quantities(
    text: str,
    pattern: re.Pattern,
    category: str | None = None,
) -> List[Quantity]:
    """按正则提取 Quantity 列表；category 用于过滤单位类别。"""
    results: List[Quantity] = []
    for match in pattern.finditer(text):
        val = float(match.group(1))
        unit = match.group(2)
        unit_lower = unit.lower()
        meta = UNIT_METAS.get(unit_lower)
        if category is not None and (meta is None or meta.category != category):
            continue
        direction = _detect_direction(text, match.start(), unit_lower)
        if direction is None:
            continue
        results.append(Quantity(val, unit, direction, match.start(), meta))
    return results


def _extract_time_quantities(text: str) -> List[Quantity]:
    """提取文本中所有时间量值。"""
    return _extract_quantities(text, _TIME_PATTERN, category="time")


def _extract_number_quantities(text: str) -> List[Quantity]:
    """提取文本中所有非时间类数值量值。"""
    return _extract_quantities(text, _NUMBER_PATTERN, category="metric")


def compare_quantity(req_qty: Quantity, bid_qty: Quantity) -> Tuple[bool, str | None, str | None]:
    """
    比较需求 Quantity 与投标 Quantity 是否满足方向要求。
    返回 (是否通过, 不一致消息, 投标中需标红的片段)。
    """
    req_val = req_qty.normalized_value
    bid_val = bid_qty.normalized_value

    if req_qty.direction in ("ge", "gt"):
        passed = bid_val >= req_val if req_qty.direction == "ge" else bid_val > req_val
    elif req_qty.direction in ("le", "lt"):
        passed = bid_val <= req_val if req_qty.direction == "le" else bid_val < req_val
    else:
        return True, None, None

    if passed:
        return True, None, None

    # 时间类单位：沿用原有消息格式，始终显示单位
    if req_qty.is_time:
        if req_qty.direction in ("ge", "gt"):
            message = f"要求不少于 {req_qty.value}{req_qty.unit}，投标仅 {bid_qty.value}{bid_qty.unit}"
        else:
            message = f"要求不超过 {req_qty.value}{req_qty.unit}，投标为 {bid_qty.value}{bid_qty.unit}"
        span = f"{bid_qty.value:g}{bid_qty.unit}"
        return False, message, span

    # 非时间类单位：当投标单位与需求单位不一致（兜底匹配）时不显示单位，保持与原 _record_number_mismatch 一致
    show_unit = bid_qty.unit == req_qty.unit and bool(req_qty.unit)
    unit_text = req_qty.unit if show_unit else ""
    if req_qty.direction in ("ge", "gt"):
        message = f"要求 ≥ {req_qty.value}{unit_text}，投标为 {bid_qty.value}{unit_text}"
    else:
        message = f"要求 ≤ {req_qty.value}{unit_text}，投标为 {bid_qty.value}{unit_text}"
    span = f"{bid_qty.value:g}{unit_text}"
    return False, message, span


def _match_and_compare_quantities(
    req_quantities: List[Quantity],
    bid_quantities: List[Quantity],
) -> Tuple[List[str], List[str]]:
    """将需求量值与投标量值按单位优先匹配并比较，返回消息与标红片段列表。"""
    messages: List[str] = []
    spans: List[str] = []
    used_bid: set[int] = set()

    for req_qty in req_quantities:
        # 优先匹配同单位、未使用的投标量值
        matches = [
            (j, bq)
            for j, bq in enumerate(bid_quantities)
            if bq.unit == req_qty.unit and j not in used_bid
        ]
        bid_qty: Quantity | None = None
        if matches:
            j, bid_qty = matches[0]
            used_bid.add(j)
        else:
            available = [j for j in range(len(bid_quantities)) if j not in used_bid]
            if available:
                j = available[0]
                raw_bq = bid_quantities[j]
                used_bid.add(j)
                # 兜底匹配：将投标单位置空，触发 compare_quantity 不显示单位的逻辑
                bid_qty = Quantity(raw_bq.value, "", raw_bq.direction, raw_bq.position, raw_bq.meta)

        if bid_qty is None:
            continue

        passed, message, span = compare_quantity(req_qty, bid_qty)
        if not passed and message:
            messages.append(message)
            if span:
                spans.append(span)

    return messages, spans


def _compare_time(req_text: str, bid_text: str) -> Tuple[List[str], List[str]]:
    """比较需求与投标中的时间值，返回不一致消息列表和投标中需标红的片段列表。"""
    messages: List[str] = []
    spans: List[str] = []

    # 特殊：7×24 小时服务
    if _has_7x24(req_text) and not (
        _has_7x24(bid_text) or "全天候" in bid_text or "全天" in bid_text
    ):
        messages.append("要求提供 7×24 小时技术支持服务，投标未明确承诺全天候服务")

    req_times = _extract_time_quantities(_strip_7x24(req_text))
    if not req_times:
        return messages, spans

    bid_times = _extract_time_quantities(_strip_7x24(bid_text))
    if not bid_times:
        messages.append("投标未明确响应时间要求")
        return messages, spans

    msgs, spns = _match_and_compare_quantities(req_times, bid_times)
    messages.extend(msgs)
    spans.extend(spns)
    return messages, spans


def _compare_numbers(req_text: str, bid_text: str) -> Tuple[Optional[str], List[str]]:
    """比较需求与投标中的非时间数值，返回不一致消息与标红片段列表。"""
    req_nums = _extract_number_quantities(req_text)
    if not req_nums:
        return None, []

    bid_nums = _extract_number_quantities(bid_text)
    if not bid_nums:
        return "投标未明确响应数值要求", []

    messages, spans = _match_and_compare_quantities(req_nums, bid_nums)
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
                highlight_spans = [time_spans[msg_idx]] if msg_idx < len(time_spans) else []
                issues.append(_make_issue(
                    idx, f"TIME-{msg_idx}", IssueType.TIME_MISMATCH, IssueLevel.WARNING,
                    req, bid_text, time_msg,
                    "核对并调整投标中的时间/期限表述，确保满足需求要求。",
                    [best_block], candidate_bid_texts, highlight_spans=highlight_spans,
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
                    [best_block], candidate_bid_texts, highlight_spans=[],
                ))

    return issues
