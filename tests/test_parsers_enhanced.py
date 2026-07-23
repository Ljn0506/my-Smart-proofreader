from pathlib import Path

import pytest

from proofreader.parsers.docx_parser import (
    DocumentSectionType,
    DocumentType,
    ParagraphType,
    TableType,
    classify_paragraph,
    classify_table,
    infer_heading_level,
    infer_section_type,
    parse_docx_with_sections,
)


def test_infer_heading_level_chinese():
    assert infer_heading_level("一、项目概述") == 1
    assert infer_heading_level("1.1 基础运维服务") == 2
    assert infer_heading_level("1.1.1 桌面运维") == 3
    assert infer_heading_level("(1) 工作内容") == 3


def test_classify_paragraph():
    assert classify_paragraph("1. 服务期限：12个月") == ParagraphType.NUMBERED_REQUIREMENT
    assert classify_paragraph("详见招标文件") == ParagraphType.PLAIN_TEXT


def test_infer_section_type_requirements():
    assert infer_section_type("第二部分 采购需求") == DocumentSectionType.REQUIREMENTS
    assert infer_section_type("用户需求书") == DocumentSectionType.REQUIREMENTS


def test_infer_section_type_bid_template():
    assert infer_section_type("第五部分 投标文件格式") == DocumentSectionType.BID_TEMPLATE
    assert infer_section_type("响应文件格式") == DocumentSectionType.BID_TEMPLATE


def test_classify_table_technical_spec():
    assert classify_table(["指标项", "技术要求"]) == TableType.TECHNICAL_SPEC


def test_classify_table_service_list():
    assert classify_table(["序号", "服务项", "服务频率", "服务要求"]) == TableType.SERVICE_LIST


def test_classify_table_evaluation():
    assert classify_table(["评审因素", "评分标准"]) == TableType.EVALUATION


def test_classify_table_unknown():
    assert classify_table(["foo", "bar"]) == TableType.UNKNOWN


@pytest.fixture
def sample_docx():
    return Path(__file__).resolve().parents[1] / "data" / "sample-docs" / "requirements.docx"


def test_parse_docx_with_sections_returns_document(sample_docx):
    result = parse_docx_with_sections(sample_docx)
    assert result.path == sample_docx
    assert result.doc_type == DocumentType.TENDER
    assert result.sections
    assert result.blocks
    assert all(block.paragraph_type is not None for block in result.blocks)


def test_parse_docx_with_sections_last_section_appended(sample_docx):
    result = parse_docx_with_sections(sample_docx)
    assert result.sections[-1].end_index > 0 or len(result.sections) == 1
