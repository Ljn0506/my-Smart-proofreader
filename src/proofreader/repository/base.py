from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List

from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument


@dataclass
class ProjectMeta:
    project_id: str
    project_name: str
    created_at: datetime
    modified_at: datetime
    version: int
    source_files: List[str] = field(default_factory=list)
    schema_version: str = "1.0"


class RequirementRepository(ABC):
    @abstractmethod
    def create_project(self, project_id: str, name: str) -> ProjectMeta: ...

    @abstractmethod
    def save_parsed(self, project_id: str, docs: List[ParsedDocument]) -> None: ...

    @abstractmethod
    def load_parsed(self, project_id: str) -> List[ParsedDocument]: ...

    @abstractmethod
    def save_requirements(self, project_id: str, items: List[RequirementItem]) -> None: ...

    @abstractmethod
    def load_requirements(self, project_id: str) -> List[RequirementItem]: ...

    @abstractmethod
    def list_projects(self) -> List[ProjectMeta]: ...
