import tempfile
from pathlib import Path

import pytest

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


def test_repo_rejects_path_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonRequirementRepository(base_dir=Path(tmp))
        with pytest.raises(ValueError):
            repo.create_project("../evil", "x")
        repo.create_project("legal", "x")
        with pytest.raises(ValueError):
            repo.save_requirements("../evil", [])
        assert not (Path(tmp).parent / "evil").exists()


def test_repo_load_missing_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonRequirementRepository(base_dir=Path(tmp))
        repo.create_project("p", "n")
        assert repo.load_requirements("p") == []


def test_repo_load_bad_schema_raises():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonRequirementRepository(base_dir=Path(tmp))
        repo.create_project("p", "n")
        path = Path(tmp) / "p" / "requirements.json"
        path.write_text('{"schema_version": "2.0", "items": []}', encoding="utf-8")
        with pytest.raises(ValueError):
            repo.load_requirements("p")
