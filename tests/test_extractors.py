from __future__ import annotations

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.models.requirements import ConstraintType, RequirementCategory, RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


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
