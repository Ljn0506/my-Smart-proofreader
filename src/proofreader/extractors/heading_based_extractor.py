from __future__ import annotations

from typing import List

from proofreader.extractors.base import BaseExtractor, heading_prefix
from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.parsers.docx_parser import DocumentSection, ParagraphType, ParsedDocument


class HeadingBasedExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        if not section.title:
            return items

        # Collect following non-heading paragraphs as context/description
        body_texts = []
        for para in section.paragraphs:
            if para.paragraph_type == ParagraphType.PLAIN_TEXT and len(para.text) > 10:
                body_texts.append(para.text)

        if not body_texts:
            return items

        raw_text = section.title + "\n" + "\n".join(body_texts[:3])
        items.append(
            RequirementItem(
                id=self._generate_id(section),
                source_doc=str(doc.path) if doc else "",
                chapter_path=section.headings[:],
                title=section.title,
                raw_text=raw_text,
                normalized_text=raw_text,
                category=RequirementCategory.TECHNICAL,
                constraint_type=ConstraintType.MANDATORY,
                check_method=CheckMethod.RULE,
                extracted_by="rule",
                review_status=ReviewStatus.DRAFT,
            )
        )
        return items

    def _generate_id(self, section: DocumentSection) -> str:
        prefix = heading_prefix(section)
        return f"{prefix}-H{section.level:02d}"
