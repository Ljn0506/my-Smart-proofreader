import pytest

from proofreader.parsers.document_type_classifier import classify_document
from proofreader.parsers.docx_parser import ParsedDocument


def _make_doc(title: str, headings: list[str], intro: str) -> ParsedDocument:
    from proofreader.parsers.docx_parser import TextBlock
    doc = ParsedDocument(path="test.docx")
    doc.title = title
    doc.headings = [TextBlock(text=h, block_type="heading", level=1) for h in headings]
    doc.blocks = []
    return doc


def test_classify_bixuan_tender():
    doc = _make_doc("广州市荔湾区中医医院数据安全及个人信息保护服务项目比选文件", ["第一部分 邀请函", "第二部分 响应供应商须知"], "")
    result = classify_document(doc)
    assert result.document_type == "tender"
    assert result.procurement_method == "bixuan"
    assert result.confidence >= 0.85


def test_classify_bid_response():
    doc = _make_doc("响应文件", ["一、资格性文件", "二、商务部分", "三、技术部分", "四、价格部分"], "")
    result = classify_document(doc)
    assert result.document_type == "bid_response"
    assert result.confidence >= 0.85


def test_classify_registration():
    doc = _make_doc("报名文件", ["一、营业执照", "二、承诺函"], "")
    result = classify_document(doc)
    assert result.document_type == "bid_registration"


def test_classify_low_confidence():
    doc = _make_doc("采购文件", [], "")
    result = classify_document(doc)
    assert result.confidence < 0.85
