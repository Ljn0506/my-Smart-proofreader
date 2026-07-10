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
