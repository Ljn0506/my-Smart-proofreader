"""测试表格内容比对。"""
from pathlib import Path

from proofreader.checkers.table_checker import check_tables
from proofreader.parsers.docx_parser import ParsedDocument


def test_table_mismatch():
    req_doc = ParsedDocument(path=Path("req.docx"))
    req_doc.raw_tables = [
        [
            ["参数项", "需求值"],
            ["并发用户", "≥1000"],
            ["响应时间", "≤2秒"],
        ]
    ]

    bid_doc = ParsedDocument(path=Path("bid.docx"))
    bid_doc.raw_tables = [
        [
            ["参数项", "投标值"],
            ["并发用户", "800"],
            ["响应时间", "1.5秒"],
        ]
    ]

    issues = check_tables(req_doc, bid_doc)
    assert len(issues) == 1, f"应检出 1 处表格差异，实际 {len(issues)}"
    issue = issues[0]
    assert issue.requirement_table_index == 0
    assert issue.bid_table_index == 0
    assert any("1000" in d and "800" in d for d in issue.details), "应检出并发用户数值差异"
    print("✅ 表格差异检出通过")


def test_missing_table():
    req_doc = ParsedDocument(path=Path("req.docx"))
    req_doc.raw_tables = [
        [
            ["参数项", "需求值"],
            ["质保期", "3年"],
        ]
    ]

    bid_doc = ParsedDocument(path=Path("bid.docx"))
    bid_doc.raw_tables = [
        [
            ["报价项", "金额"],
            ["总价", "580万元"],
        ]
    ]

    issues = check_tables(req_doc, bid_doc)
    assert any(issue.requirement_table_index == 0 and issue.bid_table_index == -1 for issue in issues), \
        "应检出需求表格未匹配"
    print("✅ 缺失表格检出通过")


def test_no_tables():
    req_doc = ParsedDocument(path=Path("req.docx"))
    bid_doc = ParsedDocument(path=Path("bid.docx"))
    issues = check_tables(req_doc, bid_doc)
    assert issues == []
    print("✅ 无表格时通过")


if __name__ == "__main__":
    test_table_mismatch()
    test_missing_table()
    test_no_tables()
    print("\n表格比对测试全部通过")
