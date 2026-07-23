from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import List

from proofreader.extractors.base import heading_prefix
from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument, ParsedTable


class TableStrategy(ABC):
    @abstractmethod
    def extract(
        self, table: ParsedTable, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]: ...


class TechnicalSpecStrategy(TableStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if len(row) < 2:
                continue
            raw_text = f"{row[0]}: {row[1]}"
            items.append(
                self._make_item(raw_text, section, doc, RequirementCategory.TECHNICAL)
            )
        return items

    def _make_item(
        self,
        raw_text: str,
        section: DocumentSection,
        doc: ParsedDocument,
        category: RequirementCategory,
        constraint_type: ConstraintType = ConstraintType.MANDATORY,
    ) -> RequirementItem:
        prefix = heading_prefix(section)
        stable_hash = hashlib.sha256(
            (raw_text + (section.headings[-1] if section.headings else "")).encode()
        ).hexdigest()[:16]
        return RequirementItem(
            id=f"{prefix}-T{section.level:02d}-{hash(raw_text) & 0xFFFF:04x}",
            stable_hash=stable_hash,
            source_doc=str(doc.path) if doc else "",
            chapter_path=section.headings[:],
            title=section.title,
            raw_text=raw_text,
            normalized_text=raw_text,
            category=category,
            constraint_type=constraint_type,
            check_method=CheckMethod.RULE,
            extracted_by="rule",
            review_status=ReviewStatus.DRAFT,
        )


class ServiceListStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if len(row) < 2:
                continue
            raw_text = " | ".join(row)
            items.append(
                self._make_item(raw_text, section, doc, RequirementCategory.DELIVERY)
            )
        return items


class QualificationStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if not row:
                continue
            raw_text = " | ".join(row)
            items.append(
                self._make_item(
                    raw_text, section, doc, RequirementCategory.QUALIFICATION
                )
            )
        return items


class ScoringStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if not row:
                continue
            raw_text = " | ".join(row)
            items.append(
                self._make_item(
                    raw_text,
                    section,
                    doc,
                    RequirementCategory.SCORING,
                    constraint_type=ConstraintType.SCORING,
                )
            )
        return items


class SkipStrategy(TableStrategy):
    def extract(self, table, section, doc):
        return []


_STRATEGY_MAP = {
    "technical_spec": TechnicalSpecStrategy,
    "service_list": ServiceListStrategy,
    "qualification": QualificationStrategy,
    "checklist": QualificationStrategy,
    "evaluation": ScoringStrategy,
    "performance": QualificationStrategy,
    "personnel": SkipStrategy,
    "quotation": SkipStrategy,
    "unknown": SkipStrategy,
}


def get_strategy(table_type: str) -> TableStrategy:
    return _STRATEGY_MAP.get(table_type, SkipStrategy)()
