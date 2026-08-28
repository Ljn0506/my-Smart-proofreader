from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument


def heading_prefix(section: DocumentSection) -> str:
    """Build a short ID prefix from the first two section headings."""
    prefix = "-".join(h.replace(" ", "")[:8] for h in section.headings[:2]) or "REQ"
    return prefix


class BaseExtractor(ABC):
    @abstractmethod
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]: ...
