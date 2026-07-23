from __future__ import annotations

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.models.requirements import ConstraintType, RequirementCategory, RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParagraphType, ParsedDocument, TextBlock


class DummyExtractor(BaseExtractor):
    def extract_from_section(self, section, doc):
        if section.section_type == DocumentSectionType.REQUIREMENTS:
            return [RequirementItem(id="DUMMY-1", source_doc="test", chapter_path=["1"], raw_text="dummy", normalized_text="dummy", category=RequirementCategory.TECHNICAL, constraint_type=ConstraintType.MANDATORY, check_method="rule", extracted_by="dummy")]
        return []


def test_composite_extractor_skips_bid_template():
    doc = ParsedDocument(path="test.docx", doc_type="tender_document", title=None, sections=[], blocks=[], headings=[], raw_tables=[])
    doc.sections = [
        DocumentSection(DocumentSectionType.REQUIREMENTS, "需求", 1, 0, 10, ["需求"], [], []),
        DocumentSection(DocumentSectionType.BID_TEMPLATE, "响应模板", 1, 10, 20, ["响应模板"], [], []),
    ]
    extractor = CompositeExtractor(extractors=[DummyExtractor()])
    items = extractor.extract(doc)
    assert len(items) == 1
    assert items[0].id == "DUMMY-1"


def test_composite_extractor_deduplicates_by_id():
    class DuplicateExtractor(BaseExtractor):
        def extract_from_section(self, section, doc):
            return [
                RequirementItem(id="DUP-1", source_doc="test", chapter_path=["1"], raw_text="a", normalized_text="a", category=RequirementCategory.TECHNICAL, constraint_type=ConstraintType.MANDATORY, check_method="rule", extracted_by="dup"),
                RequirementItem(id="DUP-1", source_doc="test", chapter_path=["1"], raw_text="a", normalized_text="a", category=RequirementCategory.TECHNICAL, constraint_type=ConstraintType.MANDATORY, check_method="rule", extracted_by="dup"),
                RequirementItem(id="DUP-2", source_doc="test", chapter_path=["2"], raw_text="b", normalized_text="b", category=RequirementCategory.COMMERCIAL, constraint_type=ConstraintType.RECOMMENDED, check_method="rule", extracted_by="dup"),
            ]

    doc = ParsedDocument(path="test.docx", doc_type="tender_document", title=None, sections=[], blocks=[], headings=[], raw_tables=[])
    doc.sections = [DocumentSection(DocumentSectionType.REQUIREMENTS, "需求", 1, 0, 10, ["需求"], [], [])]
    extractor = CompositeExtractor(extractors=[DuplicateExtractor()])
    items = extractor.extract(doc)
    assert len(items) == 2
    assert {item.id for item in items} == {"DUP-1", "DUP-2"}


def test_numbered_paragraph_extractor():
    section = DocumentSection(
        DocumentSectionType.REQUIREMENTS,
        "需求",
        1,
        0,
        10,
        ["需求"],
        paragraphs=[
            TextBlock("1. 服务期限：合同签订起12个月。", "paragraph", paragraph_type=ParagraphType.NUMBERED_REQUIREMENT, index=0),
            TextBlock("详见招标文件", "paragraph", paragraph_type=ParagraphType.PLAIN_TEXT, index=1),
        ],
        tables=[],
    )
    extractor = NumberedParagraphExtractor()
    items = extractor.extract_from_section(section, None)
    assert len(items) == 1
    assert "12个月" in items[0].raw_text
    assert items[0].category == RequirementCategory.DELIVERY
    assert items[0].constraint_type == ConstraintType.MANDATORY


def test_heading_based_extractor():
    section = DocumentSection(
        DocumentSectionType.REQUIREMENTS,
        "2.1 桌面运维服务",
        2,
        0,
        10,
        ["二、运维服务需求", "2.1 桌面运维服务"],
        paragraphs=[
            TextBlock("现需配备3名驻场人员。", "paragraph", paragraph_type=ParagraphType.PLAIN_TEXT, index=0),
        ],
        tables=[],
    )
    extractor = HeadingBasedExtractor()
    items = extractor.extract_from_section(section, None)
    assert len(items) >= 1
    assert any("驻场人员" in item.raw_text for item in items)
