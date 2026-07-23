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
from proofreader.parsers.docx_parser import DocumentSection, ParagraphType, ParsedDocument, TextBlock


class NumberedParagraphExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for para in section.paragraphs:
            if para.paragraph_type != ParagraphType.NUMBERED_REQUIREMENT:
                continue
            item = self._make_item(section, para, doc)
            if item:
                items.append(item)
        return items

    def _make_item(
        self, section: DocumentSection, para: TextBlock, doc: ParsedDocument
    ) -> RequirementItem | None:
        text = para.text.strip()
        if len(text) < 5:
            return None
        category = self._infer_category(text)
        constraint = self._infer_constraint(text)
        return RequirementItem(
            id=self._generate_id(section, para),
            source_doc=str(doc.path) if doc else "",
            chapter_path=section.headings[:],
            title=section.title,
            raw_text=text,
            normalized_text=text,
            category=category,
            constraint_type=constraint,
            check_method=CheckMethod.RULE,
            extracted_by="rule",
            review_status=ReviewStatus.DRAFT,
        )

    def _infer_category(self, text: str) -> RequirementCategory:
        t = text.lower()
        if any(k in t for k in ["资质", "营业执照", "信用", "认证", "联合体"]):
            return RequirementCategory.QUALIFICATION
        if any(k in t for k in ["人员", "工程师", "项目经理", "团队"]):
            return RequirementCategory.PERSONNEL
        if any(k in t for k in ["交付", "工期", "期限", "周期", "验收"]):
            return RequirementCategory.DELIVERY
        if any(k in t for k in ["业绩", "合同", "案例"]):
            return RequirementCategory.PERFORMANCE
        if any(k in t for k in ["付款", "报价", "金额", "价格"]):
            return RequirementCategory.COMMERCIAL
        return RequirementCategory.TECHNICAL

    def _infer_constraint(self, text: str) -> ConstraintType:
        if "★" in text:
            return ConstraintType.MANDATORY
        if "▲" in text:
            return ConstraintType.SCORING
        if any(k in text for k in ["必须", "须", "应", "不得", "不低于", "不少于", "不超过"]):
            return ConstraintType.MANDATORY
        if any(k in text for k in ["建议", "可", "宜"]):
            return ConstraintType.RECOMMENDED
        return ConstraintType.MANDATORY

    def _generate_id(self, section: DocumentSection, para: TextBlock) -> str:
        prefix = heading_prefix(section)
        return f"{prefix}-{para.index:04d}"
