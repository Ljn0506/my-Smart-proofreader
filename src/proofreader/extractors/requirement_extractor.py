"""从需求文件中提取「需求条目」。"""
from __future__ import annotations

from typing import List

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument


def extract_requirements(doc: ParsedDocument) -> List[RequirementItem]:
    """兼容旧接口：从 ParsedDocument 提取需求条目。"""
    extractor = CompositeExtractor(
        extractors=[
            HeadingBasedExtractor(),
            NumberedParagraphExtractor(),
            TableRowExtractor(),
        ]
    )
    return extractor.extract(doc)
