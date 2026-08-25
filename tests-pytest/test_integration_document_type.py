from pathlib import Path

import pytest

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.parsers.docx_parser import parse_docx


@pytest.fixture(scope="module")
def tender_doc_path():
    return Path(
        "/Users/ljn/原始投标文件/原始招标文件/广州市荔湾区中医医院数据安全及个人信息保护服务项目/"
        "（比选文件）广州市荔湾区中医医院数据安全及个人信息保护服务项目.doc"
    )


def test_real_tender_classification_and_scoring(tender_doc_path, tmp_path):
    if not tender_doc_path.exists():
        pytest.skip("Real tender doc not found")
    parsed = parse_docx(tender_doc_path)
    assert parsed.doc_type == "tender"
    assert parsed.procurement_method == "bixuan"
    assert parsed.classification_confidence >= 0.85

    extractor = CompositeExtractor(extractors=[TableRowExtractor()])
    result = extractor.extract_with_rules(parsed)
    scoring_items = [it for it in result.items if it.category == "评分标准"]
    assert len(scoring_items) > 0
    assert any(it.max_score is not None for it in scoring_items)


def test_sample_doc_classification(sample_docs_dir):
    doc_path = sample_docs_dir / "requirements.docx"
    if not doc_path.exists():
        pytest.skip("sample requirements.docx not found")
    parsed = parse_docx(doc_path)
    assert parsed.doc_type is not None
    assert parsed.procurement_method is not None
    assert parsed.classification_confidence > 0


def test_sample_doc_scoring_extraction(sample_docs_dir):
    doc_path = sample_docs_dir / "requirements.docx"
    if not doc_path.exists():
        pytest.skip("sample requirements.docx not found")
    parsed = parse_docx(doc_path)
    extractor = CompositeExtractor(extractors=[TableRowExtractor()])
    result = extractor.extract_with_rules(parsed)
    # 样例文档中若无评分表，则评分项列表为空也是可接受的
    scoring_items = [it for it in result.items if it.category == "评分标准"]
    for item in scoring_items:
        assert item.max_score is not None or item.evaluation_criteria is not None
