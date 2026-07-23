import tempfile
from pathlib import Path

from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.repository.json_repository import JsonRequirementRepository


def test_save_and_load_requirements():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonRequirementRepository(base_dir=Path(tmp))
        repo.create_project("proj-001", "测试项目")
        item = RequirementItem(
            id="REQ-1-001",
            source_doc="req.docx",
            chapter_path=["1 需求"],
            raw_text="测试需求",
            normalized_text="测试需求",
            category=RequirementCategory.TECHNICAL,
            constraint_type=ConstraintType.MANDATORY,
            check_method=CheckMethod.RULE,
            extracted_by="rule",
            review_status=ReviewStatus.CONFIRMED,
        )
        repo.save_requirements("proj-001", [item])
        loaded = repo.load_requirements("proj-001")
        assert len(loaded) == 1
        assert loaded[0].id == "REQ-1-001"
        assert loaded[0].review_status == ReviewStatus.CONFIRMED
