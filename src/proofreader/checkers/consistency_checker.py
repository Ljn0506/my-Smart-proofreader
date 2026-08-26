"""内容一致性检查：参数、时间、缺失响应等。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from proofreader.extractors.requirement_extractor import NUMBERING_PATTERNS, RequirementItem
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
    "规则": UnitMeta("metric", default_direction="ge"),
    "字段": UnitMeta("metric", default_direction="ge"),
    "条目": UnitMeta("metric", default_direction="ge"),
    "项": UnitMeta("metric", default_direction="ge"),
    "指标": UnitMeta("metric", default_direction="ge"),
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


_TIME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\+?\s*(年|个月|月|天|日|小时|h)")

_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z])(\d+(?:\.\d+)?)\+?\s*(?:并发|在线|同时|核心|可用性|成功率|内存|存储|容量|带宽|延迟|响应|吞吐|支持|达到|约为|大约|约|大概|解析|字段)?\s*"
    r"(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|用户|个|%|百分之|万元|元|次|QPS|TPS|套|规则|字段|条目|项|指标)",
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


_MULTIPLY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?(?:\s*[\*×x]\s*\d+(?:\.\d+)?)+)\s*(TB|T|GB|G|MB|M|核|个|次|套|%)",
    re.IGNORECASE,
)


def _expand_multiplication(text: str) -> str:
    """把 8*8TB 这种乘法表达式展开为 64TB，便于正则提取。"""
    def repl(m: re.Match) -> str:
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", m.group(0))]
        if len(nums) < 2:
            return m.group(0)
        unit = m.group(2)
        product = 1
        for n in nums:
            product *= n
        return f"{product:g}{unit}"

    return _MULTIPLY_PATTERN.sub(repl, text)


def _extract_quantities(
    text: str,
    pattern: re.Pattern,
    category: str | None = None,
) -> List[Quantity]:
    """按正则提取 Quantity 列表；category 用于过滤单位类别。"""
    text = _expand_multiplication(text)
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
            # 同单位候选中，选择数值上最满足方向要求的值：
            # ge/gt 选满足要求的最小值；le/lt 选满足要求的最大值；无满足则取极值
            candidates = [bq for _, bq in matches]
            if req_qty.direction in ("ge", "gt"):
                satisfying = [bq for bq in candidates if bq.normalized_value >= req_qty.normalized_value]
                if satisfying:
                    bid_qty = min(satisfying, key=lambda bq: bq.normalized_value)
                else:
                    bid_qty = max(candidates, key=lambda bq: bq.normalized_value)
            elif req_qty.direction in ("le", "lt"):
                satisfying = [bq for bq in candidates if bq.normalized_value <= req_qty.normalized_value]
                if satisfying:
                    bid_qty = max(satisfying, key=lambda bq: bq.normalized_value)
                else:
                    bid_qty = min(candidates, key=lambda bq: bq.normalized_value)
            else:
                bid_qty = candidates[0]
            used_bid.add(matches[candidates.index(bid_qty)][0])
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


# 证明材料/证书类要求的关键模式
_PROOF_CLAUSE_PATTERN = re.compile(
    r"[（(]\s*提供\s*[^）)]*?(?:证明|证书|材料|截图|报告|附件|扫描件|复印件)[^）)]*[)）]",
    re.IGNORECASE,
)
_PROOF_KEYWORDS = ["须提供", "需提供", "提供相关证明", "提供证明材料", "提供证书"]
_EVIDENCE_WORDS = ["已提供", "见附件", "附后", "详见", "证书编号", "编号", "扫描件", "复印件", "加盖公章", "盖章"]
# 投标方明确承诺满足/符合的表述，视为已响应证明材料类要求，避免把「了解并满足+需求原文」误判为 echo
_AFFIRMATIVE_RESPONSE_WORDS = ["满足", "符合", "了解并满足", "完全满足", "完全响应", "承诺满足", "承诺符合"]
# 以肯定性动词开头的响应，视为已作出实质性回应（而非仅复制需求原文）
_AFFIRMATIVE_PREFIXES = ["支持", "可满足", "可支持", "完全支持", "已支持", "具备"]


def _has_affirmative_response(req_text: str, bid_text: str) -> bool:
    """
    判断投标文本是否明确承诺满足/符合要求（而非仅重复需求原文）。

    关键：肯定性表述必须是投标**新增**的，而不是从需求原文中复制过来的。
    例如需求本身以"支持"开头，投标原文照抄"支持..."，不算实质性响应；
    而投标写"了解并满足硬件规格..."，其中"了解并满足"是新增表述，才算响应。
    """
    stripped = bid_text.strip().lstrip("▲★")
    for prefix in _AFFIRMATIVE_PREFIXES:
        if stripped.startswith(prefix) and prefix not in req_text:
            return True
    for word in _AFFIRMATIVE_RESPONSE_WORDS:
        if word in bid_text and word not in req_text:
            return True
    return False


def _extract_proof_clause(text: str) -> str | None:
    """提取文本中的证明材料/证书要求子句。"""
    match = _PROOF_CLAUSE_PATTERN.search(text)
    if match:
        return match.group(0)
    return None


def _has_proof_requirement(text: str) -> bool:
    """判断文本是否要求提供证明材料/证书。"""
    if _PROOF_CLAUSE_PATTERN.search(text):
        return True
    return any(kw in text for kw in _PROOF_KEYWORDS)


def _has_evidence_claim(text: str) -> bool:
    """判断投标文本是否声称已提供证明材料。"""
    return any(w in text for w in _EVIDENCE_WORDS)


def _strip_numbering(text: str) -> str:
    """去除需求条目前的编号，避免把编号当作数值。"""
    for pattern in NUMBERING_PATTERNS:
        text = re.sub(pattern + r"\s*", "", text)
    return text


# 硬件/接口/配置类需求中常见的「数 + 量词 + 实体」模式
_ENTITY_MEASURE_WORDS = r"(?:个|路|台|套|条|口|张|份|项|种|位|核|端口|接口|槽位)"
_NUMBERED_ENTITY_PATTERN = re.compile(
    rf"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*{_ENTITY_MEASURE_WORDS}\s*([^，。；、\s][^，。；、]*)",
    re.IGNORECASE,
)
# 实体中至少应包含一个技术关键词，才视为需要逐条响应的硬件/配置项
_ENTITY_TECH_KEYWORDS = [
    "口", "端口", "接口", "槽位", "cpu", "核", "内存", "硬盘", "存储", "光口", "电口",
    "串口", "网口", "管理口", "扫描口", "rj", "ge", "usb", "授权", "模块", "节点", "服务器",
    "设备", "磁盘", "raid", "ssd", "hdd", "tps", "qps", "ip", "mac",
]


def _extract_numbered_entities(text: str) -> List[Tuple[float, str]]:
    """
    提取「数字 + 量词 + 实体」列表，如：
    "1个GE管理口，4个千兆光口" → [(1, "GE管理口"), (4, "千兆光口")]

    过滤掉时间/进度类短语（如"2个月内"），只保留硬件/接口/配置类实体。
    """
    results = []
    for match in _NUMBERED_ENTITY_PATTERN.finditer(text):
        try:
            num = float(match.group(1))
        except ValueError:
            continue
        entity = match.group(2).strip()
        # 过滤过短或明显是时间/进度的实体
        if len(entity) < 2:
            continue
        norm = entity.lower()
        if any(norm.startswith(t) for t in ("月", "年", "天", "日", "小时", "分钟", "秒", "周")):
            continue
        if not any(kw in norm for kw in _ENTITY_TECH_KEYWORDS):
            continue
        results.append((num, entity))
    return results


def _normalize_entity(entity: str) -> str:
    """归一化实体名称，用于宽松匹配。"""
    entity = entity.lower()
    entity = re.sub(r"\s+", "", entity)
    # 统一常见变体
    entity = entity.replace("管理接口", "管理口")
    entity = entity.replace("接口", "口")
    # GE = Gigabit Ethernet，千兆管理口与 GE管理口 同义
    entity = entity.replace("ge管理口", "千兆管理口")
    return entity


def _find_missing_entities(req_text: str, bid_text: str) -> List[str]:
    """
    找出需求中列出但投标响应中未提及的实体。

    如果投标文本是表格行（含 " | "），尝试定位实际响应列（通常不是最末的"符合/是/否"列），
    避免需求原文被复制到投标表格前几列时造成「已响应」的假象。
    匹配规则：投标文本中完整包含实体，或包含实体去掉"接口"/"口"后的核心词。
    """
    req_entities = _extract_numbered_entities(req_text)
    if len(req_entities) < 2:
        # 只有单个实体时不做此项检查，避免过度敏感
        return []

    # 表格行取响应列：若最末列是短合规标识，则取倒数第二列；否则取最末列
    response_text = bid_text
    if " | " in bid_text:
        parts = [p.strip() for p in bid_text.split(" | ")]
        if len(parts) >= 2 and len(parts[-1]) <= 4 and parts[-1] in ("符合", "是", "否", "满足", "不满足"):
            response_text = parts[-2]
        else:
            response_text = parts[-1]

    bid_norm = _normalize_for_overlap(response_text)
    missing = []
    for _num, entity in req_entities:
        norm_entity = _normalize_entity(entity)
        # 完整匹配
        if norm_entity in bid_norm:
            continue
        # 核心词匹配：去掉末尾"口"/"端口"等通称后再试
        core = norm_entity
        for suffix in ("端口", "口", "槽位"):
            if core.endswith(suffix):
                core = core[: -len(suffix)]
                break
        if len(core) >= 2 and core in bid_norm:
            continue
        missing.append(entity)
    return missing


def _normalize_for_overlap(text: str) -> str:
    """归一化文本用于计算重叠率：去编号、去空格、统一大小写。"""
    text = _strip_numbering(text)
    text = re.sub(r"\s+", "", text)
    text = text.lower()
    # 同义词统一，避免投标写"千兆管理口"而需求写"GE管理口"时报缺失
    text = text.replace("ge管理口", "千兆管理口")
    return text


def _is_echo_response(req_text: str, bid_text: str) -> bool:
    """
    判断投标响应是否只是在重复需求原文（echo）。

    使用归一化后的字符集合重叠率和包含关系综合判断。
    若投标文本已明确承诺满足/符合，则不视为 echo。
    """
    if _has_affirmative_response(req_text, bid_text):
        return False

    req_norm = _normalize_for_overlap(req_text)
    bid_norm = _normalize_for_overlap(bid_text)
    if not req_norm or not bid_norm:
        return False

    # 投标与需求字符集合高重叠（>0.92）且未声明已提供证据，视为 echo。
    # 不再单独依据「包含证明子句」判定，避免把包含证明要求但已作实质性应答的段落误判为 echo。
    req_chars = set(req_norm)
    bid_chars = set(bid_norm)
    if not req_chars:
        return False
    overlap = len(req_chars & bid_chars) / len(req_chars)
    return overlap > 0.92


def _check_missing_proof(
    idx: int,
    req: RequirementItem,
    bid_text: str,
    bid_block: TextBlock,
    candidate_bid_texts: List[Tuple[str, float]],
) -> ConsistencyIssue | None:
    """
    检查「要求提供证明材料/证书，但投标仅重复需求原文未实际提供」的情况。
    """
    req_text = req.text
    if not _has_proof_requirement(req_text):
        return None
    if _has_evidence_claim(bid_text):
        return None
    if not _is_echo_response(req_text, bid_text):
        return None

    proof_clause = _extract_proof_clause(req_text) or "相关证明材料"
    return _make_issue(
        idx, "PROOF", IssueType.KEYWORD_MISSING, IssueLevel.WARNING,
        req, bid_text,
        f"需求要求{proof_clause}，投标未实际提供，仅重复需求描述",
        "在投标中补充对应的证明材料、证书或截图，并明确说明已提供。",
        [bid_block], candidate_bid_texts, highlight_spans=[proof_clause],
    )


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

        # 新增：检测要求提供证明/证书但投标仅 echo 需求原文的情况
        proof_issue = _check_missing_proof(idx, req, bid_text, best_block, candidate_bid_texts)
        if proof_issue is not None:
            issues.append(proof_issue)

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

        # 新增：检测投标是否遗漏需求中列出的具体技术实体（如 GE管理口）
        missing_entities = _find_missing_entities(req.text, bid_text)
        if missing_entities:
            issues.append(_make_issue(
                idx, "ENTITY", IssueType.KEYWORD_MISSING, IssueLevel.WARNING,
                req, bid_text,
                f"投标未明确响应以下技术项：{', '.join(missing_entities)}",
                "核对投标中的技术参数/配置项，确保需求列出的每项都有对应响应。",
                [best_block], candidate_bid_texts, highlight_spans=missing_entities,
            ))

    return issues
