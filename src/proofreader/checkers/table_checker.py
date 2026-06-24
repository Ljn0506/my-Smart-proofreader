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
    threshold: float = 0.5,
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
    """比对两个已匹配表格的内容差异。"""
    details: List[str] = []

    req_rows = len(req_table)
    bid_rows = len(bid_table)
    if req_rows != bid_rows:
        details.append(f"行数不一致：需求 {req_rows} 行，投标 {bid_rows} 行")

    req_cols = max(len(row) for row in req_table) if req_table else 0
    bid_cols = max(len(row) for row in bid_table) if bid_table else 0
    if req_cols != bid_cols:
        details.append(f"列数不一致：需求 {req_cols} 列，投标 {bid_cols} 列")

    # 按单元格逐格比较
    for r_idx, (req_row, bid_row) in enumerate(zip(req_table, bid_table)):
        row_key = _normalize(req_row[0]) if req_row else ""
        for c_idx, (req_cell, bid_cell) in enumerate(zip(req_row, bid_row)):
            if c_idx == 0 and row_key:
                # 第一列视为行键，通常应一致；若不一致单独提示
                req_norm = _normalize(req_cell)
                bid_norm = _normalize(bid_cell)
                if req_norm and bid_norm and req_norm != bid_norm:
                    details.append(
                        f"第 {r_idx + 1} 行行键不一致：需求「{req_cell.strip()[:40]}」"
                        f" vs 投标「{bid_cell.strip()[:40]}」"
                    )
                continue
            req_norm = _normalize(req_cell)
            bid_norm = _normalize(bid_cell)
            if req_norm and bid_norm and req_norm != bid_norm:
                key_hint = f"（行：{row_key}）" if row_key else ""
                details.append(
                    f"第 {r_idx + 1} 行第 {c_idx + 1} 列不一致{key_hint}："
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
