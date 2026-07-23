from datetime import datetime
from proofreader.models.requirements import (
    CheckTarget,
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)


def test_requirement_item_defaults():
    item = RequirementItem(
        id="REQ-1.1-001",
        source_doc="test.docx",
        chapter_path=["1 需求", "1.1 技术要求"],
        raw_text="系统可用性不低于 99.9%",
        normalized_text="系统可用性 >= 99.9%",
        category=RequirementCategory.TECHNICAL,
        constraint_type=ConstraintType.MANDATORY,
        check_method=CheckMethod.RULE,
        extracted_by="rule",
    )
    assert item.review_status == ReviewStatus.DRAFT
    assert item.version == 1
    assert item.match_keywords == []


def test_check_target_serialization():
    target = CheckTarget(
        type="numeric_compare",
        field="系统可用性",
        operator=">=",
        value=99.9,
        unit="%",
    )
    data = target.model_dump()
    assert data["type"] == "numeric_compare"
    assert data["value"] == 99.9
