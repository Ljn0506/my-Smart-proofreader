from __future__ import annotations

from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.table_strategies import get_strategy
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument


class TableRowExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for table in section.tables:
            strategy = get_strategy(table.table_type)
            items.extend(strategy.extract(table, section, doc))
        return items
