"""pytest 风格的表格比对测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.checkers.table_checker import TableIssue, check_tables
from proofreader.parsers.docx_parser import ParsedDocument


@pytest.fixture
def req_doc_with_table() -> ParsedDocument:
    doc = ParsedDocument(path=Path("req.docx"))
    doc.raw_tables = [
        [
            ["参数项", "需求值"],
            ["并发用户", "≥1000"],
            ["响应时间", "≤2秒"],
        ]
    ]
    return doc


@pytest.fixture
def bid_doc_with_table() -> ParsedDocument:
    doc = ParsedDocument(path=Path("bid.docx"))
    doc.raw_tables = [
        [
            ["参数项", "投标值"],
            ["并发用户", "800"],
            ["响应时间", "1.5秒"],
        ]
    ]
    return doc


@pytest.fixture
def bid_doc_missing_table() -> ParsedDocument:
    doc = ParsedDocument(path=Path("bid.docx"))
    doc.raw_tables = [
        [
            ["报价项", "金额"],
            ["总价", "580万元"],
        ]
    ]
    return doc


def test_table_cell_mismatch(req_doc_with_table: ParsedDocument, bid_doc_with_table: ParsedDocument) -> None:
    """应检出表格单元格差异。"""
    issues = check_tables(req_doc_with_table, bid_doc_with_table)
    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, TableIssue)
    assert issue.requirement_table_index == 0
    assert issue.bid_table_index == 0
    assert any("1000" in d and "800" in d for d in issue.details)


def test_table_missing_in_bid(req_doc_with_table: ParsedDocument, bid_doc_missing_table: ParsedDocument) -> None:
    """应检出需求表格在投标中缺失。"""
    issues = check_tables(req_doc_with_table, bid_doc_missing_table)
    assert any(issue.requirement_table_index == 0 and issue.bid_table_index == -1 for issue in issues)


def test_no_tables() -> None:
    """双方均无表格时不应报错。"""
    req_doc = ParsedDocument(path=Path("req.docx"))
    bid_doc = ParsedDocument(path=Path("bid.docx"))
    assert check_tables(req_doc, bid_doc) == []
