from __future__ import annotations

from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors=None):
        self.extractors = extractors or [NumberedParagraphExtractor()]

    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        # CompositeExtractor orchestrates over the whole document; per-section
        # extraction is delegated to its child extractors.
        return []

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
        return self._deduplicate(items)

    def _deduplicate(self, items: List[RequirementItem]) -> List[RequirementItem]:
        # Phase 1 stub: stable_hash dedup only; semantic dedup added in Task 10
        seen = set()
        result = []
        for item in items:
            key = item.stable_hash or item.id
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
