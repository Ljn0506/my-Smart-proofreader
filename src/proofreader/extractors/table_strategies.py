from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import List, Optional

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
            id=f"{prefix}-T{section.level:02d}-{stable_hash[:4]}",
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
            max_score = self._extract_max_score(row)
            marker = self._extract_marker(raw_text)
            item = self._make_item(
                raw_text=raw_text,
                section=section,
                doc=doc,
                category=RequirementCategory.SCORING,
                constraint_type=ConstraintType.SCORING,
            )
            item.max_score = max_score
            item.raw_marker = marker
            item.evaluation_criteria = raw_text
            items.append(item)
        return items

    def _extract_max_score(self, row: List[str]) -> Optional[float]:
        for cell in reversed(row):
            m = re.search(r"(\d+(?:\.\d+)?)", cell)
            if m and ("分" in cell or "%" not in cell):
                return float(m.group(1))
        return None

    def _extract_marker(self, text: str) -> Optional[str]:
        if "★" in text:
            return "★"
        if "▲" in text:
            return "▲"
        return None


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
