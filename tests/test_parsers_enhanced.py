from proofreader.parsers.docx_parser import (
    DocumentSectionType,
    DocumentType,
    infer_section_type,
)


def test_infer_section_type_requirements():
    assert infer_section_type("第二部分 采购需求") == DocumentSectionType.REQUIREMENTS
    assert infer_section_type("用户需求书") == DocumentSectionType.REQUIREMENTS


def test_infer_section_type_bid_template():
    assert infer_section_type("第五部分 投标文件格式") == DocumentSectionType.BID_TEMPLATE
    assert infer_section_type("响应文件格式") == DocumentSectionType.BID_TEMPLATE
