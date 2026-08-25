from __future__ import annotations

from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.deduplicator import SemanticDeduplicator
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.extractors.scoring_extractor import ScoringExtractor
from proofreader.models.requirements import EvaluationRule, RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors=None):
        self.extractors = extractors or [NumberedParagraphExtractor()]
        self.deduplicator = SemanticDeduplicator(threshold=0.95)
        self.scoring_extractor = ScoringExtractor()

    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        # CompositeExtractor orchestrates over the whole document; per-section
        # extraction is delegated to its child extractors.
        return []

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        return self.extract_with_rules(doc).items

    def extract_with_rules(
        self, doc: ParsedDocument
    ) -> "ExtractionResult":
        items: List[RequirementItem] = []
        scoring_rules: List[EvaluationRule] = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
            scoring_rules.extend(self.scoring_extractor.extract_from_section(section, doc))

        items = self.deduplicator.deduplicate(items)
        scoring_rules = self.scoring_extractor.link_rules_to_items(scoring_rules, items)
        return ExtractionResult(items=items, evaluation_rules=scoring_rules)


class ExtractionResult:
    def __init__(
        self,
        items: List[RequirementItem],
        evaluation_rules: List[EvaluationRule],
    ):
        self.items = items
        self.evaluation_rules = evaluation_rules
