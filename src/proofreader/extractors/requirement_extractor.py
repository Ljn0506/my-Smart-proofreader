"""从需求文件中提取「需求条目」。"""
from __future__ import annotations

from typing import List

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument


CONSTRAINT_KEYWORDS = [
    "必须", "应", "须", "不得", "禁止", "应当", "需要", "要求",
    "不少于", "不超过", "不大于", "不小于", "至少", "最多", "最低", "最高",
    "≥", "≤", ">", "<", "等于", "为", "质保期", "保修期", "交付期", "工期", "周期", "响应时间", "到货时间",
]

STRONG_CONSTRAINTS = set([
    "必须", "须", "应", "应当", "不得", "禁止", "需要", "要求",
    "不少于", "不超过", "不大于", "不小于", "至少", "最多", "最低", "最高",
    "≥", "≤", ">", "<",
])

NUMBERING_PATTERNS = [
    r"^\d+[\.、)）]",
    r"^[（(]\d+[)）]",
    r"^[①②③④⑤⑥⑦⑧⑨⑩]",
    r"^[一二三四五六七八九十]+[\.、)）]",
    r"^[（(][一二三四五六七八九十]+[)）]",
]

__all__ = ["RequirementItem", "CONSTRAINT_KEYWORDS", "STRONG_CONSTRAINTS", "NUMBERING_PATTERNS", "extract_requirements"]


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
