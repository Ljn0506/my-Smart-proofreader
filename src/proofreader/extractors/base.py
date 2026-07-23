from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument


class BaseExtractor(ABC):
    @abstractmethod
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]: ...
