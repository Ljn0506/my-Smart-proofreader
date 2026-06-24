"""pytest 风格的报告导出测试。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from proofreader.exporters import export_to_excel, export_to_word
from proofreader.pipeline import ProofreadResult


def test_export_to_word_creates_file(sample_result: ProofreadResult) -> None:
    """Word 导出应生成可读取的 docx 文件。"""
    output = Path("/tmp/test_report.docx")
    export_to_word(sample_result, output)

    assert output.exists()
    doc = Document(output)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "智能文档校对报告" in text
    assert "校对摘要" in text

    output.unlink(missing_ok=True)


def test_export_to_excel_creates_file(sample_result: ProofreadResult) -> None:
    """Excel 导出应生成可读取的 xlsx 文件。"""
    output = Path("/tmp/test_report.xlsx")
    export_to_excel(sample_result, output)

    assert output.exists()
    wb = load_workbook(output)
    sheet_names = wb.sheetnames
    assert "一致性偏离" in sheet_names
    assert "表格问题" in sheet_names
    assert "错别字" in sheet_names
    assert "截图OCR" in sheet_names

    # 检查一致性偏离 sheet 有数据
    ws = wb["一致性偏离"]
    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) >= 2  # 表头 + 至少一行数据

    output.unlink(missing_ok=True)


def test_export_to_word_empty_issues(tmp_path: Path) -> None:
    """空问题列表时 Word 导出不应报错。"""
    from proofreader.parsers.docx_parser import ParsedDocument

    empty_result = ProofreadResult(
        requirement_doc=ParsedDocument(path=tmp_path / "req.docx"),
        bid_doc=ParsedDocument(path=tmp_path / "bid.docx"),
        requirements=[],
        bid_sections=[],
        matches=[],
        consistency_issues=[],
        typo_issues=[],
        ocr_issues=[],
        table_issues=[],
    )
    output = tmp_path / "empty_report.docx"
    export_to_word(empty_result, output)
    assert output.exists()
