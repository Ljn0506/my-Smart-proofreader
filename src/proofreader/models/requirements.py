from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ConstraintType(str, Enum):
    MANDATORY = "必须"
    SCORING = "评分项"
    RECOMMENDED = "建议"
    REFERENCE = "仅供参考"


class RequirementCategory(str, Enum):
    QUALIFICATION = "资质条件"
    PERSONNEL = "人员要求"
    PERFORMANCE = "业绩要求"
    TECHNICAL = "技术参数"
    COMMERCIAL = "商务条款"
    FORMAT = "封装格式"
    DELIVERY = "交付要求"
    SCORING = "评分标准"
    OTHER = "其他"


class CheckMethod(str, Enum):
    RULE = "rule"
    LLM = "llm"
    RULE_LLM = "rule+llm"
    MANUAL = "manual"


class ReviewStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    MODIFIED = "modified"
    REJECTED = "rejected"
    MERGED = "merged"
    DEPRECATED = "deprecated"


class CheckTarget(BaseModel):
    type: str
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Any = None
    unit: Optional[str] = None
    description: Optional[str] = None


class RequirementItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., validation_alias=AliasChoices("item_id", "id"))
    stable_hash: Optional[str] = None
    source_doc: str
    chapter_path: List[str]
    title: Optional[str] = Field(default=None, validation_alias=AliasChoices("section_title", "title"))
    raw_text: str = Field(..., validation_alias=AliasChoices("text", "raw_text"))
    normalized_text: str
    category: RequirementCategory
    constraint_type: ConstraintType
    constraint_keywords: List[str] = Field(default_factory=list)
    check_method: CheckMethod
    check_target: Optional[CheckTarget] = None
    match_keywords: List[str] = Field(default_factory=list)
    extracted_by: str
    review_status: ReviewStatus = ReviewStatus.DRAFT
    manual_note: Optional[str] = None
    template_ref: Optional[str] = None
    project_specific: bool = False
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    version: int = 1

    @model_validator(mode="before")
    @classmethod
    def _fill_legacy_defaults(cls, data: Any) -> Any:
        """让旧代码只传 item_id/text/section_title 时也能构造新模型。"""
        if isinstance(data, dict):
            if "normalized_text" not in data and "text" in data:
                data["normalized_text"] = data["text"]
            if "source_doc" not in data:
                data["source_doc"] = ""
            if "chapter_path" not in data:
                data["chapter_path"] = []
            if "category" not in data:
                data["category"] = RequirementCategory.OTHER
            if "constraint_type" not in data:
                data["constraint_type"] = ConstraintType.REFERENCE
            if "check_method" not in data:
                data["check_method"] = CheckMethod.RULE
            if "extracted_by" not in data:
                data["extracted_by"] = "legacy"
        return data

    @property
    def item_id(self) -> str:
        return self.id

    @property
    def text(self) -> str:
        return self.raw_text

    @property
    def section_title(self) -> str:
        return self.title or (self.chapter_path[-1] if self.chapter_path else "")
