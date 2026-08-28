"""将需求条目与投标文件段落做匹配。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List, Tuple

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from proofreader.extractors.bid_splitter import BidSection, BidSectionType
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.parsers.docx_parser import TextBlock


# 数字+单位正则
# 允许数字与单位之间有少量修饰词（如"1000 并发用户"、"99.9%"）
# 加上 (?<![A-Za-z]) 避免把版本号（如 Oracle11g、Windows2003）当成技术参数
NUMBER_UNIT_PATTERN = re.compile(
    r"(?<![A-Za-z])(\d+(?:\.\d+)?)\+?\s*(?:并发|在线|同时|核心|可用性|成功率|内存|存储|容量|带宽|延迟|响应|吞吐|支持|达到|约为|大约|约|大概|解析|字段)?\s*"
    r"(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|用户|个|%|百分之|万元|元|次|QPS|TPS|套|规则|字段|条目|项|指标)",
    re.IGNORECASE,
)

# 阈值关键词
THRESHOLD_PATTERNS = [
    re.compile(r"[≥>=]\s*(\d+(?:\.\d+)?)"),
    re.compile(r"[≤<=]\s*(\d+(?:\.\d+)?)"),
    re.compile(r"不少于\s*(\d+(?:\.\d+)?)"),
    re.compile(r"不超过\s*(\d+(?:\.\d+)?)"),
    re.compile(r"至少\s*(\d+(?:\.\d+)?)"),
    re.compile(r"最多\s*(\d+(?:\.\d+)?)"),
]


@dataclass
class MatchResult:
    requirement: RequirementItem
    matched_blocks: List[Tuple[TextBlock, float]]  # block + score
    best_score: float
    match_type: str  # "exact", "keyword", "semantic", "none"


def _extract_numbers(text: str) -> List[Tuple[float, str]]:
    """提取文本中的数字和单位。"""
    results = []
    for match in NUMBER_UNIT_PATTERN.finditer(text):
        try:
            num = float(match.group(1))
            unit = match.group(2)
            results.append((num, unit))
        except ValueError:
            continue
    return results


def _extract_thresholds(text: str) -> List[Tuple[str, float]]:
    """提取阈值表达式，如 ≥8、不少于5年。"""
    results = []
    for pattern in THRESHOLD_PATTERNS:
        for match in pattern.finditer(text):
            try:
                results.append((match.group(0), float(match.group(1))))
            except (ValueError, IndexError):
                continue
    return results


STOPWORDS = set([
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也",
    "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "那",
    "必须", "应", "须", "需要", "要求", "提供", "具备", "支持", "实现", "包括", "用于", "以及",
])


@lru_cache(maxsize=1024)
def _segment(text: str) -> frozenset[str]:
    """用 jieba 分词，并过滤停用词和过短词。"""
    words = set()
    for w in jieba.lcut(text.lower()):
        w = w.strip()
        if len(w) >= 2 and w not in STOPWORDS:
            words.add(w)
        elif w.isdigit():
            words.add(w)
    return frozenset(words)


@lru_cache(maxsize=1024)
def _jieba_tokenize(text: str) -> tuple[str, ...]:
    """供 TfidfVectorizer 使用的中文分词器。"""
    tokens: List[str] = []
    for w in jieba.lcut(text.lower()):
        w = w.strip()
        if not w:
            continue
        if w.isdigit() or (len(w) >= 2 and w not in STOPWORDS):
            tokens.append(w)
    return tuple(tokens)


def _keyword_overlap(req_text: str, bid_text: str) -> float:
    """关键词重叠度，基于中文分词的 Jaccard。"""
    req_words = _segment(req_text)
    bid_words = _segment(bid_text)
    if not req_words:
        return 0.0
    intersection = req_words & bid_words
    return len(intersection) / len(req_words)


def _time_unit_bonus(req_text: str, bid_text: str) -> float:
    """如果时间单位一致，给予额外加分。"""
    req_numbers = _extract_numbers(req_text)
    bid_numbers = _extract_numbers(bid_text)
    if not req_numbers or not bid_numbers:
        return 0.0
    req_units = set(u.lower() for _, u in req_numbers)
    bid_units = set(u.lower() for _, u in bid_numbers)
    if req_units & bid_units:
        return 0.15
    return 0.0


_TIME_UNITS = {"年", "个月", "月", "天", "日", "小时", "h"}
_TIME_RELATED_WORDS = {"工作日", "小时", "分钟", "秒", "全天候", "全天", "7×24", "7x24", "7X24"}


def _has_7x24(text: str) -> bool:
    """检查文本是否包含 7×24 小时服务表述。"""
    return bool(re.search(r"\d+\s*[×xX]\s*24\s*小时", text))


def _time_compatible(req_text: str, bid_text: str) -> bool:
    """时间类需求要求投标文本中也出现时间单位或时间相关表述，否则视为不匹配。"""
    # 7×24 小时服务的特殊处理：投标可用「全天候/全天/7×24」响应
    if _has_7x24(req_text) and (_has_7x24(bid_text) or "全天候" in bid_text or "全天" in bid_text):
        return True
    req_numbers = _extract_numbers(req_text)
    if not req_numbers:
        return True
    req_time_units = {u.lower() for _, u in req_numbers if u.lower() in _TIME_UNITS}
    if not req_time_units:
        return True
    bid_numbers = _extract_numbers(bid_text)
    bid_time_units = {u.lower() for _, u in bid_numbers if u.lower() in _TIME_UNITS}
    if bid_time_units:
        return True
    # 投标中出现「工作日/小时/分钟/秒」等时间相关词，也视为时间兼容
    return any(w in bid_text for w in _TIME_RELATED_WORDS)


def _numeric_compatible(req_text: str, bid_text: str) -> bool:
    """有数值/单位的需求要求投标文本中也出现相关数值/单位，避免匹配到纯标题段落。"""
    req_numbers = _extract_numbers(req_text)
    if not req_numbers:
        return True
    # 7×24 小时服务：投标可用「全天候/全天/7×24/工作日/小时」等时间表述响应
    if _has_7x24(req_text) and any(w in bid_text for w in _TIME_RELATED_WORDS):
        return True
    bid_numbers = _extract_numbers(bid_text)
    if not bid_numbers:
        return False
    req_units = {u.lower() for _, u in req_numbers}
    bid_units = {u.lower() for _, u in bid_numbers}
    return bool(req_units & bid_units)


_BUSINESS_KEYWORDS = {"业绩", "合同", "项目经理", "资质", "实施进度", "实施方案", "验收", "试运行", "维保期"}


def _business_compatible(req_text: str, bid_text: str) -> bool:
    """商务/资质类关键词：需求中出现时，投标文本必须也包含对应关键词，避免被无关技术段落命中。"""
    req_business = {kw for kw in _BUSINESS_KEYWORDS if kw in req_text}
    if not req_business:
        return True
    return any(kw in bid_text for kw in req_business)


def _strict_match(req_item: RequirementItem, bid_text: str) -> bool:
    """严格匹配：核心数字和单位匹配，且内容关键词必须有实质重叠，避免纯数字巧合命中。"""
    req_numbers = _extract_numbers(req_item.text)
    bid_numbers = _extract_numbers(bid_text)

    keyword_overlap = _keyword_overlap(req_item.text, bid_text)

    # 数值/单位防误匹配：需求含数值/单位但投标无对应数值/单位时，直接排除
    if not _numeric_compatible(req_item.text, bid_text):
        return False

    # 时间类需求防误匹配：需求含时间单位但投标无时间单位时，直接排除
    if req_numbers:
        req_time_units = {u.lower() for _, u in req_numbers if u.lower() in _TIME_UNITS}
        if req_time_units and not any(u.lower() in _TIME_UNITS for _, u in bid_numbers):
            return False

    # 时间类单位匹配：需求与投标都出现相同时间单位（如 年/月/天），放宽关键词门槛
    if req_numbers and bid_numbers:
        req_time_units = {u.lower() for _, u in req_numbers if u.lower() in _TIME_UNITS}
        bid_time_units = {u.lower() for _, u in bid_numbers if u.lower() in _TIME_UNITS}
        if req_time_units & bid_time_units and keyword_overlap > 0.05:
            return True

    # 单位匹配：需求中的数字单位在投标中出现，但要求内容关键词有足够重叠
    if req_numbers and bid_numbers:
        req_units = set(u.lower() for _, u in req_numbers)
        bid_units = set(u.lower() for _, u in bid_numbers)
        if req_units & bid_units and keyword_overlap > 0.15:
            return True

    # 数值完全匹配
    if req_numbers and bid_numbers:
        req_set = set((round(n, 2), u.lower()) for n, u in req_numbers)
        bid_set = set((round(n, 2), u.lower()) for n, u in bid_numbers)
        if req_set & bid_set and keyword_overlap > 0.2:
            return True

    # 商务/资质类关键词：需求中出现时，投标文本必须也包含对应关键词，避免被无关技术段落命中
    if not _business_compatible(req_item.text, bid_text):
        return False

    # 没有数字的需求，要求较高的内容关键词重叠
    return keyword_overlap >= 0.3


def _section_compatible(req: RequirementItem, block: TextBlock) -> bool:
    """判断需求条目与投标 block 是否属于同一章节/产品。"""
    if not req.section_title or not block.section_title:
        return True
    r = req.section_title.lower()
    b = block.section_title.lower()
    return r in b or b in r


@lru_cache(maxsize=64)
def _get_bid_vectors(
    bid_texts: tuple[str, ...],
) -> tuple[TfidfVectorizer, Any]:
    """获取投标文本的 TF-IDF 向量；使用 LRU 缓存避免重复 fit_transform。"""
    vectorizer = TfidfVectorizer(tokenizer=_jieba_tokenize, token_pattern=None)
    try:
        bid_vectors = vectorizer.fit_transform(list(bid_texts))
    except ValueError:
        # 文本为空或无法向量化：返回空向量占位
        bid_vectors = vectorizer.fit_transform([])

    return vectorizer, bid_vectors


def _match_with_vectors(
    requirements: List[RequirementItem],
    bid_blocks: List[TextBlock],
    bid_texts: List[str],
    vectorizer: TfidfVectorizer,
    bid_vectors: Any,
) -> List[MatchResult]:
    """使用已预计算的投标向量完成需求-投标匹配。"""
    req_texts = [r.text for r in requirements]
    results: List[MatchResult] = []

    if not bid_blocks or not requirements:
        for req in requirements:
            results.append(MatchResult(req, [], 0.0, "none"))
        return results

    try:
        req_vectors = vectorizer.transform(req_texts)
        sim_matrix = cosine_similarity(req_vectors, bid_vectors)
    except ValueError:
        # 文本为空或无法向量化
        for req in requirements:
            results.append(MatchResult(req, [], 0.0, "none"))
        return results

    for i, req in enumerate(requirements):
        # 优先只和同一章节/产品的投标段落匹配
        compatible_indices = [
            j for j, block in enumerate(bid_blocks) if _section_compatible(req, block)
        ] or list(range(len(bid_blocks)))

        # 严格匹配
        block_scores = []
        for j in compatible_indices:
            block = bid_blocks[j]
            bid_text = block.text
            semantic_score = float(sim_matrix[i, j])
            keyword_score = _keyword_overlap(req.text, bid_text)
            strict = _strict_match(req, bid_text)
            # 综合得分：语义分 + 关键词分 + 时间单位加分
            combined_score = semantic_score + keyword_score * 0.5 + _time_unit_bonus(req.text, bid_text)
            block_scores.append((block, semantic_score, combined_score, keyword_score, strict))

        # 对每类命中分别收集，按综合分排序
        strict_hits: List[Tuple[TextBlock, float]] = []
        keyword_hits: List[Tuple[TextBlock, float]] = []
        semantic_hits: List[Tuple[TextBlock, float]] = []

        for block, semantic_score, combined_score, keyword_score, strict in block_scores:
            if strict:
                strict_hits.append((block, combined_score))
                continue
            time_ok = _time_compatible(req.text, block.text)
            numeric_ok = _numeric_compatible(req.text, block.text)
            business_ok = _business_compatible(req.text, block.text)
            if keyword_score >= 0.3 and time_ok and numeric_ok and business_ok:
                keyword_hits.append((block, combined_score))
            elif semantic_score >= 0.20 and time_ok and numeric_ok and business_ok:
                semantic_hits.append((block, semantic_score))

        strict_hits = sorted(strict_hits, key=lambda x: x[1], reverse=True)[:5]
        keyword_hits = sorted(keyword_hits, key=lambda x: x[1], reverse=True)[:5]
        semantic_hits = sorted(semantic_hits, key=lambda x: x[1], reverse=True)[:5]

        if strict_hits:
            match_type = "exact"
            all_hits = strict_hits
        elif keyword_hits:
            match_type = "keyword"
            all_hits = keyword_hits
        elif semantic_hits:
            match_type = "semantic"
            all_hits = semantic_hits
        else:
            match_type = "none"
            # 兜底：取语义分最高的块
            if block_scores:
                best = max(block_scores, key=lambda x: x[1])
                all_hits = [(best[0], best[1])]
            else:
                all_hits = []

        results.append(
            MatchResult(
                requirement=req,
                matched_blocks=all_hits[:5],
                best_score=all_hits[0][1] if all_hits else 0.0,
                match_type=match_type,
            )
        )

    return results


def match_requirements_to_bid(
    requirements: List[RequirementItem],
    bid_sections: List[BidSection],
    section_type: BidSectionType | None = None,
) -> List[MatchResult]:
    """
    将需求条目与投标文件段落匹配。
    如果指定 section_type，则只在该部分匹配；否则匹配全部。
    """
    # 收集待匹配的投标文本块（保留长标题，便于检测「把需求原文当响应」的 echo 情况）
    def _keep_block(b: TextBlock) -> bool:
        if b.block_type != "heading":
            return True
        # 短标题（如 "一、漏洞扫描系统"）排除；长标题可能是重复的需求原文，保留
        return len(b.text.strip()) >= 30

    if section_type:
        bid_blocks = []
        for sec in bid_sections:
            if sec.section_type == section_type:
                bid_blocks.extend([b for b in sec.blocks if _keep_block(b)])
    else:
        bid_blocks = [b for sec in bid_sections for b in sec.blocks if _keep_block(b)]

    bid_texts = [b.text for b in bid_blocks]
    if not bid_blocks:
        return [MatchResult(req, [], 0.0, "none") for req in requirements]

    vectorizer, bid_vectors = _get_bid_vectors(tuple(bid_texts))

    # 处理空投标向量（无法向量化时返回兜底结果）
    if bid_vectors.shape[0] == 0:
        return [MatchResult(req, [], 0.0, "none") for req in requirements]

    return _match_with_vectors(requirements, bid_blocks, bid_texts, vectorizer, bid_vectors)
