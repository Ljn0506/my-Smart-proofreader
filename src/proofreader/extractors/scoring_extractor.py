"""从评分表周边文本中提取聚合评分规则（EvaluationRule）。"""
from __future__ import annotations

import re
from typing import List

from proofreader.models.requirements import EvaluationRule, RequirementCategory, RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


_AGGREGATE_PATTERNS = [
    re.compile(r"全部.*?得\s*(\d+(?:\.\d+)?)\s*分，每.*?扣\s*(\d+(?:\.\d+)?)\s*分"),
    re.compile(r"全部.*?得\s*(\d+(?:\.\d+)?)\s*分(?!，每)"),
]


class ScoringExtractor:
    """从 EVALUATION section 的段落文本中提取聚合评分规则。

    注意：本类不继承 BaseExtractor，因为其产出是 EvaluationRule 而非 RequirementItem。
    """

    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[EvaluationRule]:
        if section.section_type != DocumentSectionType.EVALUATION:
            return []

        rules = []
        paragraphs = section.paragraphs if hasattr(section, "paragraphs") else []
        text = "\n".join(p.text for p in paragraphs)
        for pattern in _AGGREGATE_PATTERNS:
            for m in pattern.finditer(text):
                base_score = float(m.group(1))
                deduction = float(m.group(2)) if m.lastindex >= 2 else None
                rules.append(
                    EvaluationRule(
                        rule_text=m.group(0),
                        base_score=base_score,
                        deduction_per_item=deduction,
                        confidence=0.8,
                    )
                )
        return rules

    def link_rules_to_items(
        self, rules: List[EvaluationRule], items: List[RequirementItem]
    ) -> List[EvaluationRule]:
        """将聚合规则与同一章节路径下的评分项关联。"""
        linked = []
        for rule in rules:
            linked.append(
                rule.model_copy(
                    update={
                        "applies_to_requirement_ids": [
                            it.id
                            for it in items
                            if it.category == RequirementCategory.SCORING
                        ]
                    }
                )
            )
        return linked
