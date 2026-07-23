from proofreader.parsers.docx_parser import (
    DocumentSectionType,
    DocumentType,
    ParagraphType,
    classify_paragraph,
    infer_heading_level,
    infer_section_type,
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
