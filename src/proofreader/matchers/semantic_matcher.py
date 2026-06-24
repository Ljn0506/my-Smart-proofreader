"""将需求条目与投标文件段落做匹配。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from proofreader.extractors.bid_splitter import BidSection, BidSectionType
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.parsers.docx_parser import TextBlock


# 数字+单位正则
NUMBER_UNIT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|个|%|百分之|万元|元|次|QPS|TPS|套)",
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


def _segment(text: str) -> set[str]:
    """用 jieba 分词，并过滤停用词和过短词。"""
    words = set()
    for w in jieba.lcut(text.lower()):
        w = w.strip()
        if len(w) >= 2 and w not in STOPWORDS:
            words.add(w)
        elif w.isdigit():
            words.add(w)
    return words


def _jieba_tokenize(text: str) -> List[str]:
    """供 TfidfVectorizer 使用的中文分词器。"""
    tokens: List[str] = []
    for w in jieba.lcut(text.lower()):
        w = w.strip()
        if not w:
            continue
        if w.isdigit() or (len(w) >= 2 and w not in STOPWORDS):
            tokens.append(w)
    return tokens


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


def _strict_match(req_item: RequirementItem, bid_text: str) -> bool:
    """严格匹配：核心数字和单位匹配，或内容关键词高度重叠。"""
    req_numbers = _extract_numbers(req_item.text)
    bid_numbers = _extract_numbers(bid_text)

    # 单位匹配：需求中的数字单位在投标中出现（数字可不同，留给后续偏差检查）
    if req_numbers and bid_numbers:
        req_units = set(u.lower() for _, u in req_numbers)
        bid_units = set(u.lower() for _, u in bid_numbers)
        if req_units & bid_units and _keyword_overlap(req_item.text, bid_text) > 0.05:
            return True

    # 数值完全匹配
    if req_numbers and bid_numbers:
        req_set = set((round(n, 2), u.lower()) for n, u in req_numbers)
        bid_set = set((round(n, 2), u.lower()) for n, u in bid_numbers)
        if req_set & bid_set and _keyword_overlap(req_item.text, bid_text) > 0.1:
            return True

    # 没有数字的需求，要求较高的内容关键词重叠
    overlap = _keyword_overlap(req_item.text, bid_text)
    return overlap >= 0.3


def match_requirements_to_bid(
    requirements: List[RequirementItem],
    bid_sections: List[BidSection],
    section_type: BidSectionType | None = None,
) -> List[MatchResult]:
    """
    将需求条目与投标文件段落匹配。
    如果指定 section_type，则只在该部分匹配；否则匹配全部。
    """
    # 收集待匹配的投标文本块（排除标题）
    if section_type:
        bid_blocks = []
        for sec in bid_sections:
            if sec.section_type == section_type:
                bid_blocks.extend([b for b in sec.blocks if b.block_type != "heading"])
    else:
        bid_blocks = [b for sec in bid_sections for b in sec.blocks if b.block_type != "heading"]

    bid_texts = [b.text for b in bid_blocks]
    req_texts = [r.text for r in requirements]

    results: List[MatchResult] = []

    if not bid_blocks or not requirements:
        for req in requirements:
            results.append(MatchResult(req, [], 0.0, "none"))
        return results

    # TF-IDF 向量（使用 jieba 中文分词）
    vectorizer = TfidfVectorizer(tokenizer=_jieba_tokenize, token_pattern=None)
    try:
        all_texts = req_texts + bid_texts
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        req_vectors = tfidf_matrix[: len(req_texts)]
        bid_vectors = tfidf_matrix[len(req_texts):]
        sim_matrix = cosine_similarity(req_vectors, bid_vectors)
    except ValueError:
        # 文本为空或无法向量化
        for req in requirements:
            results.append(MatchResult(req, [], 0.0, "none"))
        return results

    for i, req in enumerate(requirements):
        # 严格匹配
        strict_hits: List[Tuple[TextBlock, float]] = []
        keyword_hits: List[Tuple[TextBlock, float]] = []
        semantic_hits: List[Tuple[TextBlock, float]] = []

        block_scores = []
        for j, block in enumerate(bid_blocks):
            bid_text = block.text
            semantic_score = float(sim_matrix[i, j])
            keyword_score = _keyword_overlap(req.text, bid_text)
            strict = _strict_match(req, bid_text)
            # 综合得分：语义分 + 关键词分 + 时间单位加分
            combined_score = semantic_score + keyword_score * 0.5 + _time_unit_bonus(req.text, bid_text)
            block_scores.append((block, semantic_score, combined_score, keyword_score, strict))

        # 对每类命中分别收集，按综合分排序
        strict_hits = [(b, c) for b, s, c, k, strict in block_scores if strict]
        keyword_hits = [(b, c) for b, s, c, k, strict in block_scores if not strict and k >= 0.3]
        semantic_hits = [(b, c) for b, s, c, k, strict in block_scores if not strict and k < 0.3 and s >= 0.15]

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
