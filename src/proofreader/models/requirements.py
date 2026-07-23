from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


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
    id: str
    stable_hash: Optional[str] = None
    source_doc: str
    chapter_path: List[str]
    title: Optional[str] = None
    raw_text: str
    normalized_text: str
    category: RequirementCategory
    constraint_type: ConstraintType
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
