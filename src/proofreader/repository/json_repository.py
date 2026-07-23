from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List

from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument
from proofreader.repository.base import ProjectMeta, RequirementRepository


class JsonRequirementRepository(RequirementRepository):
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("projects")

    def _project_dir(self, project_id: str) -> Path:
        return self.base_dir / project_id

    def create_project(self, project_id: str, name: str) -> ProjectMeta:
        project_dir = self._project_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "sources").mkdir(exist_ok=True)
        (project_dir / "parsed").mkdir(exist_ok=True)
        now = datetime.now()
        meta = ProjectMeta(
            project_id=project_id,
            project_name=name,
            created_at=now,
            modified_at=now,
            version=1,
        )
        self._save_meta(project_id, meta)
        return meta

    def _save_meta(self, project_id: str, meta: ProjectMeta) -> None:
        path = self._project_dir(project_id) / "meta.json"
        path.write_text(
            json.dumps(meta.__dict__, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_meta(self, project_id: str) -> ProjectMeta:
        path = self._project_dir(project_id) / "meta.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["modified_at"] = datetime.fromisoformat(data["modified_at"])
        return ProjectMeta(**data)

    def save_parsed(self, project_id: str, docs: List[ParsedDocument]) -> None:
        # Phase 1: stub serialization to avoid complexity
        path = self._project_dir(project_id) / "parsed" / "parsed_documents.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{"path": str(d.path)} for d in docs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_parsed(self, project_id: str) -> List[ParsedDocument]:
        raise NotImplementedError("load_parsed is stubbed in Phase 1")

    def save_requirements(self, project_id: str, items: List[RequirementItem]) -> None:
        path = self._project_dir(project_id) / "requirements.json"
        data = {
            "schema_version": "1.0",
            "project_id": project_id,
            "generated_at": datetime.now().isoformat(),
            "items": [item.model_dump() for item in items],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = self._load_meta(project_id)
        meta.modified_at = datetime.now()
        self._save_meta(project_id, meta)

    def load_requirements(self, project_id: str) -> List[RequirementItem]:
        path = self._project_dir(project_id) / "requirements.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != "1.0":
            raise ValueError(f"Unsupported schema version: {data.get('schema_version')}")
        return [RequirementItem(**item) for item in data.get("items", [])]

    def list_projects(self) -> List[ProjectMeta]:
        projects: List[ProjectMeta] = []
        if not self.base_dir.exists():
            return projects
        for project_dir in self.base_dir.iterdir():
            if project_dir.is_dir() and (project_dir / "meta.json").exists():
                projects.append(self._load_meta(project_dir.name))
        return projects
