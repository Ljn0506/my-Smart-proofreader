"""pytest 风格的 .doc 文件解析测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.parsers.docx_parser import (
    convert_doc_to_docx,
    find_soffice,
    parse_docx,
)


@pytest.fixture(scope="module")
def requirements_doc_path(sample_docs_dir: Path) -> Path:
    """返回需求文件的 .doc 版本路径（如不存在则跳过）。"""
    path = sample_docs_dir / "requirements.doc"
    if not path.exists():
        pytest.skip("未找到 .doc 样例文件，跳过 .doc 相关测试")
    return path


def test_soffice_is_available() -> None:
    """当前环境应能找到 LibreOffice/soffice 命令；否则跳过 .doc 测试。"""
    if find_soffice() is None:
        pytest.skip("未找到 soffice/libreoffice，跳过 .doc 转换测试")


def test_convert_doc_to_docx(requirements_doc_path: Path, tmp_path: Path) -> None:
    """.doc 文件应能被转换为 .docx。"""
    converted = convert_doc_to_docx(requirements_doc_path, tmp_path)
    assert converted.exists()
    assert converted.suffix.lower() == ".docx"


def test_parse_doc_file(requirements_doc_path: Path) -> None:
    """parse_docx 应能直接解析 .doc 文件并提取内容。"""
    parsed = parse_docx(requirements_doc_path)
    assert parsed.path == requirements_doc_path
    assert len(parsed.blocks) > 0
    # 应能提取到标题
    assert len(parsed.headings) > 0
    # 应能提取到包含需求文本的段落
    assert any("并发用户" in block.text for block in parsed.blocks)


def test_parse_doc_file_keeps_original_path(requirements_doc_path: Path) -> None:
    """解析 .doc 后，ParsedDocument.path 应保留原始 .doc 路径。"""
    parsed = parse_docx(requirements_doc_path)
    assert parsed.path.suffix.lower() == ".doc"


def test_parse_docx_para_index_maps_body_paragraphs(tmp_path: Path) -> None:
    """paragraph/heading 块的 para_index 应与 Document.paragraphs 对齐，表格行为 None。"""
    from docx import Document

    doc_path = tmp_path / "para_index.docx"
    doc = Document()
    doc.add_paragraph("第一段")
    doc.add_paragraph("")  # 空段落
    doc.add_paragraph("第二段")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "表头"
    table.cell(0, 1).text = "值"
    table.cell(1, 0).text = "项"
    table.cell(1, 1).text = "数据"
    doc.add_paragraph("第三段")
    doc.save(doc_path)

    parsed = parse_docx(doc_path)

    # 段落块按 body paragraph 顺序出现，para_index 与 Document.paragraphs 一致
    paragraph_blocks = [b for b in parsed.blocks if b.block_type in ("paragraph", "heading")]
    assert len(paragraph_blocks) == 3
    assert paragraph_blocks[0].text == "第一段"
    assert paragraph_blocks[0].para_index == 0
    assert paragraph_blocks[1].text == "第二段"
    assert paragraph_blocks[1].para_index == 2  # 跳过了空段落 index 1
    assert paragraph_blocks[2].text == "第三段"
    assert paragraph_blocks[2].para_index == 3  # 表格不占 paragraph

    # 表格行无 para_index
    table_blocks = [b for b in parsed.blocks if b.block_type == "table_row"]
    assert len(table_blocks) == 2
    for block in table_blocks:
        assert block.para_index is None


def test_parsed_document_has_classification(sample_docs_dir: Path) -> None:
    """parse_docx 应附加文档类型与采购方式分类结果。"""
    doc_path = sample_docs_dir / "requirements.docx"
    if not doc_path.exists():
        pytest.skip("sample requirements.docx not found")
    parsed = parse_docx(doc_path)
    assert parsed.doc_type is not None
    assert parsed.procurement_method is not None
    assert parsed.classification_confidence > 0
