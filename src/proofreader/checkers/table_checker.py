"""需求文件与投标文件表格内容比对。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from proofreader.parsers.docx_parser import ParsedDocument


@dataclass
class TableIssue:
    """表格比对发现的问题。"""

    issue_id: str
    requirement_table_index: int
    bid_table_index: int
    message: str
    suggestion: str
    details: List[str] = field(default_factory=list)


def _normalize(text: str) -> str:
    """归一化单元格文本，用于比对。"""
    text = text.strip()
    # 全角转半角
    table = str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ％",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz%",
    )
    text = text.translate(table)
    # 合并连续空白
    text = re.sub(r"\s+", " ", text)
    return text.lower()


# 单位简写 -> 标准写法（小写）
_UNIT_ALIASES = {
    "g": "gb",
    "m": "mb",
    "t": "tb",
}


_UNIT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(gb|g|mb|m|tb|t)\b", re.IGNORECASE)


def _normalize_cell(text: str) -> str:
    """归一化单元格内容，包括统一 GB/G、MB/M、TB/T 等单位简写。"""
    text = _normalize(text)

    def _replace_unit(match: re.Match) -> str:
        num = match.group(1)
        unit = match.group(2).lower()
        unit = _UNIT_ALIASES.get(unit, unit)
        return f"{num}{unit}"

    return _UNIT_PATTERN.sub(_replace_unit, text)


def _table_signature(table: List[List[str]]) -> str:
    """用表头生成表格签名，用于匹配。"""
    if not table:
        return ""
    header = table[0]
    return " ".join(_normalize(cell) for cell in header if _normalize(cell))


def _tokenize(text: str) -> List[str]:
    """使用 jieba 分词，用于表格表头匹配。"""
    return [w for w in jieba.lcut(text.lower()) if len(w.strip()) >= 2 or w.strip().isdigit()]


def _row_keys(table: List[List[str]]) -> set[str]:
    """提取表格第一列行键（除表头外），用于辅助匹配。"""
    keys: set[str] = set()
    for row in table[1:]:
        if row:
            keys.add(_normalize(row[0]))
    return keys


def _match_tables(
    req_tables: List[List[List[str]]],
    bid_tables: List[List[List[str]]],
    threshold: float = 0.35,
) -> List[Tuple[int, int, float]]:
    """
    将需求表格与投标表格按表头语义 + 行键重叠度匹配。
    返回 [(req_index, bid_index, score), ...]。
    """
    if not req_tables or not bid_tables:
        return []

    req_signatures = [_table_signature(t) for t in req_tables]
    bid_signatures = [_table_signature(t) for t in bid_tables]

    vectorizer = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None)
    try:
        all_sigs = req_signatures + bid_signatures
        matrix = vectorizer.fit_transform(all_sigs)
        req_vectors = matrix[: len(req_tables)]
        bid_vectors = matrix[len(req_tables) :]
        sim_matrix = cosine_similarity(req_vectors, bid_vectors)
    except ValueError:
        return []

    matches: List[Tuple[int, int, float]] = []
    used_bid: set[int] = set()

    # 贪心匹配：每个需求表格匹配最相似的未使用投标表格
    for req_idx in range(len(req_tables)):
        best_bid = -1
        best_score = threshold
        req_keys = _row_keys(req_tables[req_idx])
        for bid_idx in range(len(bid_tables)):
            if bid_idx in used_bid:
                continue
            header_score = float(sim_matrix[req_idx, bid_idx])
            # 行键重叠度作为辅助
            bid_keys = _row_keys(bid_tables[bid_idx])
            if req_keys and bid_keys:
                overlap = len(req_keys & bid_keys) / max(len(req_keys), len(bid_keys))
            else:
                overlap = 0.0
            # 综合得分：表头占 60%，行键占 40%
            score = header_score * 0.6 + overlap * 0.4
            if score > best_score:
                best_score = score
                best_bid = bid_idx
        if best_bid >= 0:
            matches.append((req_idx, best_bid, best_score))
            used_bid.add(best_bid)

    return matches


def _compare_tables(
    req_table: List[List[str]],
    bid_table: List[List[str]],
) -> List[str]:
    """比对两个已匹配表格的内容差异（按第一列行键对齐）。"""
    details: List[str] = []

    if not req_table or not bid_table:
        return details

    req_header = req_table[0]
    bid_header = bid_table[0]
    req_rows = req_table[1:]
    bid_rows = bid_table[1:]

    if len(req_header) != len(bid_header):
        details.append(
            f"表头列数不一致：需求 {len(req_header)} 列，投标 {len(bid_header)} 列"
        )

    # 按行键建立投标行索引
    bid_row_map: Dict[str, List[str]] = {}
    duplicate_keys: set[str] = set()
    for row in bid_rows:
        if not row:
            continue
        key = _normalize(row[0])
        if not key:
            continue
        if key in bid_row_map:
            duplicate_keys.add(key)
        else:
            bid_row_map[key] = row

    # 逐行对比：以需求行的行键去投标表格中找对应行
    for req_row in req_rows:
        if not req_row:
            continue
        req_key = _normalize(req_row[0])
        if not req_key:
            continue
        if req_key not in bid_row_map:
            details.append(f"行键「{req_row[0].strip()[:40]}」在投标表格中未找到")
            continue

        bid_row = bid_row_map[req_key]
        if req_key in duplicate_keys:
            details.append(
                f"行键「{req_row[0].strip()[:40]}」在投标表格中重复出现，已取首次出现行进行比对"
            )

        max_cols = max(len(req_row), len(bid_row))
        for c_idx in range(1, max_cols):
            req_cell = req_row[c_idx] if c_idx < len(req_row) else ""
            bid_cell = bid_row[c_idx] if c_idx < len(bid_row) else ""
            req_norm = _normalize_cell(req_cell)
            bid_norm = _normalize_cell(bid_cell)
            if req_norm and bid_norm and req_norm != bid_norm:
                details.append(
                    f"行「{req_row[0].strip()[:40]}」第 {c_idx + 1} 列不一致："
                    f"需求「{req_cell.strip()[:40]}」 vs 投标「{bid_cell.strip()[:40]}」"
                )

    return details


def check_tables(req_doc: ParsedDocument, bid_doc: ParsedDocument) -> List[TableIssue]:
    """比对需求文件与投标文件中的表格，返回差异列表。"""
    issues: List[TableIssue] = []
    req_tables = req_doc.raw_tables
    bid_tables = bid_doc.raw_tables

    if not req_tables or not bid_tables:
        return issues

    matches = _match_tables(req_tables, bid_tables)
    matched_bid_indices = {bid_idx for _, bid_idx, _ in matches}

    # 未匹配到的需求表格
    for req_idx in range(len(req_tables)):
        if not any(req_idx == m[0] for m in matches):
            issues.append(
                TableIssue(
                    issue_id=f"TABLE-MISS-{req_idx + 1}",
                    requirement_table_index=req_idx,
                    bid_table_index=-1,
                    message=f"需求表格 #{req_idx + 1} 在投标文件中未找到对应表格",
                    suggestion="在投标文件中补充对应表格内容。",
                    details=["表头示例：" + _table_signature(req_tables[req_idx])[:80]],
                )
            )

    # 已匹配表格的单元格比对
    for pair_idx, (req_idx, bid_idx, score) in enumerate(matches):
        req_table = req_tables[req_idx]
        bid_table = bid_tables[bid_idx]
        details = _compare_tables(req_table, bid_table)
        if details:
            issues.append(
                TableIssue(
                    issue_id=f"TABLE-DIFF-{pair_idx + 1}",
                    requirement_table_index=req_idx,
                    bid_table_index=bid_idx,
                    message=f"需求表格 #{req_idx + 1} 与投标表格 #{bid_idx + 1} 内容不一致（表头匹配度 {score:.0%}）",
                    suggestion="核对并修正投标表格中的参数、数值或描述。",
                    details=details[:20],  # 限制详情数量，避免报告过长
                )
            )

    # 未匹配到的投标表格（可选提示）
    for bid_idx in range(len(bid_tables)):
        if bid_idx not in matched_bid_indices:
            issues.append(
                TableIssue(
                    issue_id=f"TABLE-EXTRA-{bid_idx + 1}",
                    requirement_table_index=-1,
                    bid_table_index=bid_idx,
                    message=f"投标表格 #{bid_idx + 1} 在需求文件中未找到对应表格",
                    suggestion="确认该表格是否为投标方自行补充内容。",
                    details=[],
                )
            )

    return issues
