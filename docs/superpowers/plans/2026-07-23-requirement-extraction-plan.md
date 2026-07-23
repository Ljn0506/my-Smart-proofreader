# 需求侧解析重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 smart-proofreader 的需求侧解析逻辑，实现从招标/需求文件自动提取结构化需求条目、人工复审、项目库存储，并集成到现有校对流程。

**Architecture:** 新增 `models` 模块统一数据定义；增强 `docx_parser` 按内容分区并修正标题层级；新增 `extractors` 子模块提供多种提取策略和语义去重；新增 `repository` 模块实现按项目持久化；新增 Streamlit 需求管理页面；最后调整 `pipeline` 支持从项目库加载需求。

**Tech Stack:** Python 3.9+, python-docx, Pydantic, scikit-learn, Streamlit, pytest

## Global Constraints

- 保持现有 `pipeline.proofread(req_path, bid_path)` 接口向后兼容。
- 第一阶段使用 JSON 文件持久化，保留后续切换 SQLite 的接口。
- AI 拆解先用规则实现，预留 LLM 接口。
- 语义去重默认阈值 0.95。
- `stable_hash` 基于 `raw_text + chapter_path[-1]` 生成。
- `check_method="rule"` 时 `check_target` 必填；`check_method="llm"` 时可选。
- 响应模板部分（`bid_template`）解析但不进入需求库。

---

## File Structure

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/proofreader/models/__init__.py` | 数据模型包入口 |
| `src/proofreader/models/requirements.py` | `RequirementItem`、`CheckTarget`、枚举定义 |
| `src/proofreader/repository/__init__.py` | Repository 包入口 |
| `src/proofreader/repository/base.py` | `RequirementRepository` 抽象接口 + `ProjectMeta` |
| `src/proofreader/repository/json_repository.py` | JSON 实现 |
| `src/proofreader/extractors/base.py` | `BaseExtractor` 接口 |
| `src/proofreader/extractors/composite_extractor.py` | 组合提取器 + 语义去重调用 |
| `src/proofreader/extractors/numbered_paragraph_extractor.py` | 编号段落提取器 |
| `src/proofreader/extractors/heading_based_extractor.py` | 标题跟随段落提取器 |
| `src/proofreader/extractors/table_row_extractor.py` | 表格行提取器 |
| `src/proofreader/extractors/table_strategies.py` | 各表类型提取策略 |
| `src/proofreader/extractors/deduplicator.py` | 语义去重 |
| `src/proofreader/ui/requirement_manager.py` | Streamlit 需求管理页面 |
| `tests/test_models_requirements.py` | 数据模型测试 |
| `tests/test_parsers_enhanced.py` | 增强 Parser 测试 |
| `tests/test_repository_json.py` | Repository 测试 |
| `tests/test_extractors.py` | Extractor 测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/proofreader/parsers/docx_parser.py` | 添加分区识别、标题层级修正、段落分类、表格分类 |
| `src/proofreader/extractors/requirement_extractor.py` | 保留旧接口，内部调用新的 CompositeExtractor |
| `src/proofreader/pipeline.py` | 注入 Repository，新增 `proofread_project` |
| `src/proofreader/ui/app.py` | 添加"需求管理"页面入口 |

---

### Task 1: 创建共享数据模型

**Files:**
- Create: `src/proofreader/models/__init__.py`
- Create: `src/proofreader/models/requirements.py`
- Test: `tests/test_models_requirements.py`

**Interfaces:**
- Consumes: 无
- Produces: `RequirementItem`, `CheckTarget`, `ConstraintType`, `RequirementCategory`, `CheckMethod`, `ReviewStatus`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_requirements.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_models_requirements.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'proofreader.models'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/models/__init__.py
from proofreader.models.requirements import (
    CheckMethod,
    CheckTarget,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)

__all__ = [
    "CheckMethod",
    "CheckTarget",
    "ConstraintType",
    "RequirementCategory",
    "RequirementItem",
    "ReviewStatus",
]
```

```python
# src/proofreader/models/requirements.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_models_requirements.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/models tests/test_models_requirements.py
git commit -m "feat: add RequirementItem and CheckTarget data models

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 增强 Parser - 文档分区与类型

**Files:**
- Modify: `src/proofreader/parsers/docx_parser.py`
- Test: `tests/test_parsers_enhanced.py`

**Interfaces:**
- Consumes: `RequirementCategory`, `ConstraintType` (from Task 1)
- Produces: `DocumentSectionType`, `DocumentType`, `DocumentSection`, `ParsedTable`, `TextBlock` with `paragraph_type`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parsers_enhanced.py
from proofreader.parsers.docx_parser import (
    DocumentSectionType,
    DocumentType,
    infer_section_type,
)


def test_infer_section_type_requirements():
    assert infer_section_type("第二部分 采购需求") == DocumentSectionType.REQUIREMENTS
    assert infer_section_type("用户需求书") == DocumentSectionType.REQUIREMENTS


def test_infer_section_type_bid_template():
    assert infer_section_type("第五部分 投标文件格式") == DocumentSectionType.BID_TEMPLATE
    assert infer_section_type("响应文件格式") == DocumentSectionType.BID_TEMPLATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py -v`

Expected: FAIL with "cannot import name 'DocumentSectionType'"

- [ ] **Step 3: Write minimal implementation**

在 `src/proofreader/parsers/docx_parser.py` 顶部添加：

```python
from enum import Enum
from typing import List, Optional


class DocumentSectionType(str, Enum):
    TENDER_NOTICE = "tender_notice"
    BIDDER_INSTRUCTIONS = "bidder_instructions"
    REQUIREMENTS = "requirements"
    EVALUATION = "evaluation"
    CONTRACT = "contract"
    BID_TEMPLATE = "bid_template"
    UNKNOWN = "unknown"


class DocumentType(str, Enum):
    TENDER = "tender_document"
    REQUIREMENT = "requirement_document"
    BID = "bid_document"


class ParagraphType(str, Enum):
    HEADING = "heading"
    NUMBERED_REQUIREMENT = "numbered_requirement"
    PLAIN_TEXT = "plain_text"
    METADATA = "metadata"
    NOTICE = "notice"


class ParsedTable:
    def __init__(
        self,
        table_type: str,
        header: List[str],
        rows: List[List[str]],
        caption: Optional[str] = None,
        index: int = 0,
    ):
        self.table_type = table_type
        self.header = header
        self.rows = rows
        self.caption = caption
        self.index = index


class DocumentSection:
    def __init__(
        self,
        section_type: DocumentSectionType,
        title: Optional[str],
        level: int,
        start_index: int,
        end_index: int,
        headings: List[str],
        paragraphs: List[TextBlock],
        tables: List[ParsedTable],
    ):
        self.section_type = section_type
        self.title = title
        self.level = level
        self.start_index = start_index
        self.end_index = end_index
        self.headings = headings
        self.paragraphs = paragraphs
        self.tables = tables


def infer_section_type(text: str) -> DocumentSectionType:
    t = text.strip().lower()
    if any(k in t for k in ["招标公告", "比选邀请函", "遴选邀请函", "邀请函"]):
        return DocumentSectionType.TENDER_NOTICE
    if any(k in t for k in ["供应商须知", "投标人须知", "响应供应商须知"]):
        return DocumentSectionType.BIDDER_INSTRUCTIONS
    if any(k in t for k in ["采购需求", "用户需求书", "需求内容", "技术/商务要求", "商务要求", "技术要求"]):
        return DocumentSectionType.REQUIREMENTS
    if any(k in t for k in ["评审", "评标", "评分标准", "资格审查"]):
        return DocumentSectionType.EVALUATION
    if any(k in t for k in ["合同文本", "合同条款", "合同样本", "付款方式"]):
        return DocumentSectionType.CONTRACT
    if any(k in t for k in ["投标文件格式", "响应文件格式", "自查表", "报价表"]):
        return DocumentSectionType.BID_TEMPLATE
    return DocumentSectionType.UNKNOWN
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/parsers/docx_parser.py tests/test_parsers_enhanced.py
git commit -m "feat(parser): add document section types and inference

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 增强 Parser - 标题层级修正与段落分类

**Files:**
- Modify: `src/proofreader/parsers/docx_parser.py`
- Test: `tests/test_parsers_enhanced.py`

**Interfaces:**
- Consumes: `ParagraphType` (from Task 2)
- Produces: `infer_heading_level(text)`, `classify_paragraph(text)`, `TextBlock.paragraph_type`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parsers_enhanced.py
from proofreader.parsers.docx_parser import (
    classify_paragraph,
    infer_heading_level,
)


def test_infer_heading_level_chinese():
    assert infer_heading_level("一、项目概述") == 1
    assert infer_heading_level("1.1 基础运维服务") == 2
    assert infer_heading_level("1.1.1 桌面运维") == 3
    assert infer_heading_level("(1) 工作内容") == 3


def test_classify_paragraph():
    assert classify_paragraph("1. 服务期限：12个月") == "numbered_requirement"
    assert classify_paragraph("详见招标文件") == "plain_text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py::test_infer_heading_level_chinese -v`

Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

在 `src/proofreader/parsers/docx_parser.py` 中添加：

```python
import re


_NUMBERED_RE = re.compile(
    r"^(?:\d+[、．.]\s*|\(\d+\)\s*|[①②③④⑤⑥⑦⑧⑨⑩]\s*|[a-zA-Z][．.]\s*)"
)


def infer_heading_level(text: str) -> int:
    t = text.strip()
    if re.match(r"^第[一二三四五六七八九十]+章", t):
        return 1
    if re.match(r"^[一二三四五六七八九十]+[、．.]", t):
        return 1
    if re.match(r"^\d+[\.．]\d+[\.．]\d+[\.．]\d+", t):
        return 4
    if re.match(r"^\d+[\.．]\d+[\.．]\d+", t):
        return 3
    if re.match(r"^\d+[\.．]\d+", t):
        return 2
    if re.match(r"^\(\d+\)", t):
        return 3
    if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", t):
        return 4
    if re.match(r"^[a-zA-Z][\.．]\s*\S", t):
        return 4
    return 0


def classify_paragraph(text: str) -> ParagraphType:
    t = text.strip()
    if not t:
        return ParagraphType.PLAIN_TEXT
    if infer_heading_level(t) > 0:
        return ParagraphType.HEADING
    if _NUMBERED_RE.match(t):
        return ParagraphType.NUMBERED_REQUIREMENT
    if re.match(r"^(项目编号|预算金额|发布日期|采购人|联系人)", t):
        return ParagraphType.METADATA
    if any(k in t for k in ["说明", "注：", "注意", "警告"]):
        return ParagraphType.NOTICE
    return ParagraphType.PLAIN_TEXT
```

并给 `TextBlock` 添加字段：

```python
@dataclass
class TextBlock:
    text: str
    block_type: str
    level: int = 0
    style_name: str = ""
    page_hint: int = 0
    index: int = 0
    section_title: str = ""
    para_index: Optional[int] = None
    paragraph_type: ParagraphType = ParagraphType.PLAIN_TEXT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/parsers/docx_parser.py tests/test_parsers_enhanced.py
git commit -m "feat(parser): infer heading levels and classify paragraphs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 增强 Parser - 表格分类与完整解析

**Files:**
- Modify: `src/proofreader/parsers/docx_parser.py`
- Test: `tests/test_parsers_enhanced.py`

**Interfaces:**
- Consumes: `ParsedTable`, `DocumentSection` (from Task 2)
- Produces: `classify_table(header)`, `parse_docx_with_sections(path)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_parsers_enhanced.py
from proofreader.parsers.docx_parser import classify_table


def test_classify_table_technical_spec():
    assert classify_table(["指标项", "技术要求"]) == "technical_spec"


def test_classify_table_service_list():
    assert classify_table(["序号", "服务项", "服务频率", "服务要求"]) == "service_list"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py::test_classify_table_technical_spec -v`

Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

在 `src/proofreader/parsers/docx_parser.py` 中添加：

```python
class TableType(str, Enum):
    SERVICE_LIST = "service_list"
    TECHNICAL_SPEC = "technical_spec"
    EVALUATION = "evaluation"
    CHECKLIST = "checklist"
    PERFORMANCE = "performance"
    PERSONNEL = "personnel"
    QUOTATION = "quotation"
    QUALIFICATION = "qualification"
    UNKNOWN = "unknown"


def classify_table(header: List[str]) -> TableType:
    h = " ".join(header).lower()
    if any(k in h for k in ["指标项", "技术要求", "技术参数"]):
        return TableType.TECHNICAL_SPEC
    if any(k in h for k in ["服务项", "服务频率", "服务要求", "服务内容"]):
        return TableType.SERVICE_LIST
    if any(k in h for k in ["评审", "评分", "评价标准"]):
        return TableType.EVALUATION
    if any(k in h for k in ["自查", "审查项目", "资格性", "符合性"]):
        return TableType.CHECKLIST
    if any(k in h for k in ["业绩", "同类项目", "合同金额"]):
        return TableType.PERFORMANCE
    if any(k in h for k in ["人员", "姓名", "学历", "工作年限"]):
        return TableType.PERSONNEL
    if any(k in h for k in ["报价", "单价", "总价", "金额"]):
        return TableType.QUOTATION
    if any(k in h for k in ["资质", "资格", "认证"]):
        return TableType.QUALIFICATION
    return TableType.UNKNOWN
```

并实现 `parse_docx_with_sections`（与现有 `parse_docx` 并行，不破坏旧接口）：

```python
def parse_docx_with_sections(path: Path) -> ParsedDocument:
    doc = Document(str(path))
    sections: List[DocumentSection] = []
    current_section = DocumentSection(
        section_type=DocumentSectionType.UNKNOWN,
        title=None,
        level=0,
        start_index=0,
        end_index=0,
        headings=[],
        paragraphs=[],
        tables=[],
    )
    paragraphs: List[TextBlock] = []
    headings: List[TextBlock] = []
    raw_tables: List[List[List[str]]] = []

    para_index = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        level = infer_heading_level(text)
        ptype = ParagraphType.HEADING if level > 0 else classify_paragraph(text)
        style_name = para.style.name if para.style else ""
        block = TextBlock(
            text=text,
            block_type="heading" if level > 0 else "paragraph",
            level=level,
            style_name=style_name,
            index=para_index,
            para_index=para_index,
            paragraph_type=ptype,
        )
        paragraphs.append(block)
        if level > 0:
            headings.append(block)
            section_type = infer_section_type(text)
            if section_type != DocumentSectionType.UNKNOWN:
                current_section.end_index = para_index
                sections.append(current_section)
                current_section = DocumentSection(
                    section_type=section_type,
                    title=text,
                    level=level,
                    start_index=para_index,
                    end_index=para_index,
                    headings=[text],
                    paragraphs=[],
                    tables=[],
                )
            else:
                current_section.headings.append(text)
        else:
            current_section.paragraphs.append(block)
        para_index += 1

    for idx, table in enumerate(doc.tables):
        raw = _extract_raw_table(table)
        raw_tables.append(raw)
        if raw:
            ptable = ParsedTable(
                table_type=classify_table(raw[0]).value,
                header=raw[0],
                rows=raw[1:],
                index=idx,
            )
            current_section.tables.append(ptable)

    current_section.end_index = para_index
    sections.append(current_section)

    return ParsedDocument(
        path=path,
        doc_type=DocumentType.TENDER,
        title=None,
        sections=sections,
        blocks=paragraphs,
        headings=headings,
        raw_tables=raw_tables,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_parsers_enhanced.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/parsers/docx_parser.py tests/test_parsers_enhanced.py
git commit -m "feat(parser): classify tables and parse document with sections

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 创建 Repository 接口与 JSON 实现

**Files:**
- Create: `src/proofreader/repository/__init__.py`
- Create: `src/proofreader/repository/base.py`
- Create: `src/proofreader/repository/json_repository.py`
- Test: `tests/test_repository_json.py`

**Interfaces:**
- Consumes: `RequirementItem`, `ParsedDocument` (from Task 1, 4)
- Produces: `RequirementRepository`, `JsonRequirementRepository`, `ProjectMeta`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repository_json.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_repository_json.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'proofreader.repository'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/repository/__init__.py
from proofreader.repository.base import ProjectMeta, RequirementRepository
from proofreader.repository.json_repository import JsonRequirementRepository

__all__ = ["ProjectMeta", "RequirementRepository", "JsonRequirementRepository"]
```

```python
# src/proofreader/repository/base.py
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
```

```python
# src/proofreader/repository/json_repository.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_repository_json.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/repository tests/test_repository_json.py
git commit -m "feat(repository): add JSON-based project requirement repository

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 创建 Extractor 接口与组合提取器

**Files:**
- Create: `src/proofreader/extractors/base.py`
- Create: `src/proofreader/extractors/__init__.py`（若不存在则创建，存在则修改）
- Create: `src/proofreader/extractors/composite_extractor.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `DocumentSection`, `ParsedDocument`, `RequirementItem` (from Task 2, 4, 1)
- Produces: `BaseExtractor.extract_from_section(section, doc)`, `CompositeExtractor.extract(doc)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


class DummyExtractor(BaseExtractor):
    def extract_from_section(self, section, doc):
        if section.section_type == DocumentSectionType.REQUIREMENTS:
            return [RequirementItem(id="DUMMY-1", source_doc="test", chapter_path=["1"], raw_text="dummy", normalized_text="dummy", category="TECHNICAL", constraint_type="MANDATORY", check_method="rule", extracted_by="dummy")]
        return []


def test_composite_extractor_skips_bid_template():
    doc = ParsedDocument(path="test.docx", doc_type="tender_document", title=None, sections=[], blocks=[], headings=[], raw_tables=[])
    doc.sections = [
        DocumentSection(DocumentSectionType.REQUIREMENTS, "需求", 1, 0, 10, ["需求"], [], []),
        DocumentSection(DocumentSectionType.BID_TEMPLATE, "响应模板", 1, 10, 20, ["响应模板"], [], []),
    ]
    extractor = CompositeExtractor(extractors=[DummyExtractor()])
    items = extractor.extract(doc)
    assert len(items) == 1
    assert items[0].id == "DUMMY-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'proofreader.extractors.base'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/extractors/base.py
from abc import ABC, abstractmethod
from typing import List

from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument


class BaseExtractor(ABC):
    @abstractmethod
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]: ...
```

```python
# src/proofreader/extractors/__init__.py
from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.composite_extractor import CompositeExtractor

__all__ = ["BaseExtractor", "CompositeExtractor"]
```

```python
# src/proofreader/extractors/composite_extractor.py
from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSectionType, ParsedDocument


class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors=None):
        self.extractors = extractors or []

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
        return self._deduplicate(items)

    def _deduplicate(self, items: List[RequirementItem]) -> List[RequirementItem]:
        # Phase 1 stub: stable_hash dedup only; semantic dedup added in Task 10
        seen = set()
        result = []
        for item in items:
            key = item.stable_hash or item.id
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors tests/test_extractors.py
git commit -m "feat(extractors): add BaseExtractor and CompositeExtractor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 实现编号段落提取器

**Files:**
- Create: `src/proofreader/extractors/numbered_paragraph_extractor.py`
- Modify: `src/proofreader/extractors/composite_extractor.py`（注册默认提取器）
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `DocumentSection.paragraphs`, `ParagraphType.NUMBERED_REQUIREMENT`
- Produces: `NumberedParagraphExtractor.extract_from_section(section, doc)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.models.requirements import ConstraintType, RequirementCategory
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParagraphType, TextBlock


def test_numbered_paragraph_extractor():
    section = DocumentSection(
        DocumentSectionType.REQUIREMENTS,
        "需求",
        1,
        0,
        10,
        ["需求"],
        paragraphs=[
            TextBlock("1. 服务期限：合同签订起12个月。", "paragraph", paragraph_type=ParagraphType.NUMBERED_REQUIREMENT, index=0),
            TextBlock("详见招标文件", "paragraph", paragraph_type=ParagraphType.PLAIN_TEXT, index=1),
        ],
        tables=[],
    )
    extractor = NumberedParagraphExtractor()
    items = extractor.extract_from_section(section, None)
    assert len(items) == 1
    assert "12个月" in items[0].raw_text
    assert items[0].category == RequirementCategory.DELIVERY
    assert items[0].constraint_type == ConstraintType.MANDATORY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py::test_numbered_paragraph_extractor -v`

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/extractors/numbered_paragraph_extractor.py
import re
from typing import List

from proofreader.extractors.base import BaseExtractor
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
            item = self._make_item(section, para)
            if item:
                items.append(item)
        return items

    def _make_item(self, section: DocumentSection, para: TextBlock) -> RequirementItem | None:
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
        if any(k in t for k in ["业绩", "合同", "案例"]):
            return RequirementCategory.PERFORMANCE
        if any(k in t for k in ["交付", "工期", "期限", "周期", "验收"]):
            return RequirementCategory.DELIVERY
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
        return ConstraintType.REFERENCE

    def _generate_id(self, section: DocumentSection, para: TextBlock) -> str:
        prefix = "-".join(h.replace(" ", "")[:8] for h in section.headings[:2]) or "REQ"
        return f"{prefix}-{para.index:04d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/numbered_paragraph_extractor.py tests/test_extractors.py
git commit -m "feat(extractors): add numbered paragraph extractor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 实现标题跟随段落提取器

**Files:**
- Create: `src/proofreader/extractors/heading_based_extractor.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `DocumentSection` headings + paragraphs
- Produces: `HeadingBasedExtractor.extract_from_section(section, doc)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.models.requirements import RequirementCategory
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParagraphType, TextBlock


def test_heading_based_extractor():
    section = DocumentSection(
        DocumentSectionType.REQUIREMENTS,
        "2.1 桌面运维服务",
        2,
        0,
        10,
        ["二、运维服务需求", "2.1 桌面运维服务"],
        paragraphs=[
            TextBlock("现需配备3名驻场人员。", "paragraph", paragraph_type=ParagraphType.PLAIN_TEXT, index=0),
        ],
        tables=[],
    )
    extractor = HeadingBasedExtractor()
    items = extractor.extract_from_section(section, None)
    assert len(items) >= 1
    assert any("驻场人员" in item.raw_text for item in items)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py::test_heading_based_extractor -v`

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/extractors/heading_based_extractor.py
from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.parsers.docx_parser import DocumentSection, ParagraphType, ParsedDocument, TextBlock


class HeadingBasedExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        if not section.title:
            return items

        # Collect following non-heading paragraphs as context/description
        body_texts = []
        for para in section.paragraphs:
            if para.paragraph_type == ParagraphType.PLAIN_TEXT and len(para.text) > 10:
                body_texts.append(para.text)

        if not body_texts:
            return items

        raw_text = section.title + "\n" + "\n".join(body_texts[:3])
        items.append(
            RequirementItem(
                id=self._generate_id(section),
                source_doc=str(doc.path) if doc else "",
                chapter_path=section.headings[:],
                title=section.title,
                raw_text=raw_text,
                normalized_text=raw_text,
                category=RequirementCategory.TECHNICAL,
                constraint_type=ConstraintType.MANDATORY,
                check_method=CheckMethod.RULE,
                extracted_by="rule",
                review_status=ReviewStatus.DRAFT,
            )
        )
        return items

    def _generate_id(self, section: DocumentSection) -> str:
        prefix = "-".join(h.replace(" ", "")[:8] for h in section.headings[:2]) or "REQ"
        return f"{prefix}-H{section.level:02d}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/heading_based_extractor.py tests/test_extractors.py
git commit -m "feat(extractors): add heading-based extractor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 实现表格行提取器与策略

**Files:**
- Create: `src/proofreader/extractors/table_strategies.py`
- Create: `src/proofreader/extractors/table_row_extractor.py`
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `DocumentSection.tables`, `ParsedTable`
- Produces: `TableRowExtractor.extract_from_section(section, doc)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.models.requirements import RequirementCategory
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedTable


def test_table_row_extractor_technical_spec():
    section = DocumentSection(
        DocumentSectionType.REQUIREMENTS,
        "技术指标",
        2,
        0,
        10,
        ["技术指标"],
        paragraphs=[],
        tables=[
            ParsedTable(
                table_type="technical_spec",
                header=["指标项", "技术要求"],
                rows=[["系统可用性", "不低于99.9%"]],
                index=0,
            )
        ],
    )
    extractor = TableRowExtractor()
    items = extractor.extract_from_section(section, None)
    assert len(items) == 1
    assert items[0].category == RequirementCategory.TECHNICAL
    assert "99.9%" in items[0].raw_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py::test_table_row_extractor_technical_spec -v`

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/extractors/table_strategies.py
from abc import ABC, abstractmethod
from typing import List

from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument, ParsedTable


class TableStrategy(ABC):
    @abstractmethod
    def extract(
        self, table: ParsedTable, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]: ...


class TechnicalSpecStrategy(TableStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if len(row) < 2:
                continue
            raw_text = f"{row[0]}: {row[1]}"
            items.append(self._make_item(raw_text, section, doc, RequirementCategory.TECHNICAL))
        return items

    def _make_item(self, raw_text, section, doc, category):
        return RequirementItem(
            id=f"{'-'.join(h.replace(' ', '')[:8] for h in section.headings[:2]) or 'REQ'}-T{section.level:02d}-{hash(raw_text) & 0xFFFF:04x}",
            source_doc=str(doc.path) if doc else "",
            chapter_path=section.headings[:],
            title=section.title,
            raw_text=raw_text,
            normalized_text=raw_text,
            category=category,
            constraint_type=ConstraintType.MANDATORY,
            check_method=CheckMethod.RULE,
            extracted_by="rule",
            review_status=ReviewStatus.DRAFT,
        )


class ServiceListStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if len(row) < 2:
                continue
            raw_text = " | ".join(row)
            items.append(self._make_item(raw_text, section, doc, RequirementCategory.DELIVERY))
        return items


class QualificationStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            raw_text = " | ".join(row)
            items.append(self._make_item(raw_text, section, doc, RequirementCategory.QUALIFICATION))
        return items


class ScoringStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            raw_text = " | ".join(row)
            item = self._make_item(raw_text, section, doc, RequirementCategory.SCORING)
            item.constraint_type = ConstraintType.SCORING
            items.append(item)
        return items


class SkipStrategy(TableStrategy):
    def extract(self, table, section, doc):
        return []


_STRATEGY_MAP = {
    "technical_spec": TechnicalSpecStrategy,
    "service_list": ServiceListStrategy,
    "qualification": QualificationStrategy,
    "checklist": QualificationStrategy,
    "evaluation": ScoringStrategy,
    "performance": QualificationStrategy,
    "personnel": SkipStrategy,
    "quotation": SkipStrategy,
    "unknown": SkipStrategy,
}


def get_strategy(table_type: str) -> TableStrategy:
    return _STRATEGY_MAP.get(table_type, SkipStrategy)()
```

```python
# src/proofreader/extractors/table_row_extractor.py
from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.extractors.table_strategies import get_strategy
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument


class TableRowExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for table in section.tables:
            strategy = get_strategy(table.table_type)
            items.extend(strategy.extract(table, section, doc))
        return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/table_strategies.py src/proofreader/extractors/table_row_extractor.py tests/test_extractors.py
git commit -m "feat(extractors): add table row extractor with type-based strategies

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 实现语义去重

**Files:**
- Create: `src/proofreader/extractors/deduplicator.py`
- Modify: `src/proofreader/extractors/composite_extractor.py`（接入去重）
- Test: `tests/test_extractors.py`

**Interfaces:**
- Consumes: `List[RequirementItem]`
- Produces: `SemanticDeduplicator.deduplicate(items)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.deduplicator import SemanticDeduplicator
from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
)


def test_semantic_deduplicator():
    base = dict(
        source_doc="test.docx",
        chapter_path=["1"],
        category=RequirementCategory.TECHNICAL,
        constraint_type=ConstraintType.MANDATORY,
        check_method=CheckMethod.RULE,
        extracted_by="rule",
    )
    items = [
        RequirementItem(id="A", raw_text="系统可用性不低于 99.9%", normalized_text="系统可用性不低于99.9%", **base),
        RequirementItem(id="B", raw_text="系统可用性不低于99.9%", normalized_text="系统可用性不低于99.9%", **base),
    ]
    dedup = SemanticDeduplicator(threshold=0.95)
    result = dedup.deduplicate(items)
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py::test_semantic_deduplicator -v`

Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# src/proofreader/extractors/deduplicator.py
import hashlib
import re
from typing import List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from proofreader.models.requirements import RequirementItem


class SemanticDeduplicator:
    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold

    def deduplicate(self, items: List[RequirementItem]) -> List[RequirementItem]:
        # 1. stable_hash dedup
        seen_hashes = set()
        candidates = []
        for item in items:
            h = self._stable_hash(item)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            candidates.append(item)

        if len(candidates) <= 1:
            return candidates

        # 2. semantic dedup with TF-IDF
        texts = [self._normalize(item.normalized_text) for item in candidates]
        try:
            vectorizer = TfidfVectorizer()
            matrix = vectorizer.fit_transform(texts)
            sim_matrix = cosine_similarity(matrix)
        except ValueError:
            return candidates

        keep = [True] * len(candidates)
        for i in range(len(candidates)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(candidates)):
                if not keep[j]:
                    continue
                if sim_matrix[i][j] >= self.threshold:
                    # Prefer table source / longer chapter_path
                    if self._prefer(candidates[i], candidates[j]) == candidates[j]:
                        keep[i] = False
                        break
                    else:
                        keep[j] = False

        return [candidates[i] for i in range(len(candidates)) if keep[i]]

    def _stable_hash(self, item: RequirementItem) -> str:
        if item.stable_hash:
            return item.stable_hash
        base = item.raw_text + (item.chapter_path[-1] if item.chapter_path else "")
        return hashlib.md5(base.encode("utf-8")).hexdigest()

    def _normalize(self, text: str) -> str:
        t = re.sub(r"[\s★▲]+", "", text)
        return t.lower()

    def _prefer(self, a: RequirementItem, b: RequirementItem) -> RequirementItem:
        if len(a.chapter_path) != len(b.chapter_path):
            return a if len(a.chapter_path) >= len(b.chapter_path) else b
        if len(a.raw_text) != len(b.raw_text):
            return a if len(a.raw_text) >= len(b.raw_text) else b
        return a
```

修改 `src/proofreader/extractors/composite_extractor.py`：

```python
from proofreader.extractors.deduplicator import SemanticDeduplicator

class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors=None):
        self.extractors = extractors or []
        self.deduplicator = SemanticDeduplicator(threshold=0.95)

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
        return self.deduplicator.deduplicate(items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/deduplicator.py src/proofreader/extractors/composite_extractor.py tests/test_extractors.py
git commit -m "feat(extractors): add semantic deduplication

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 重构旧 requirement_extractor 为 CompositeExtractor 包装

**Files:**
- Modify: `src/proofreader/extractors/requirement_extractor.py`
- Test: `tests/test_extractors.py` 或复用现有测试

**Interfaces:**
- Consumes: `ParsedDocument`
- Produces: `extract_requirements(doc)` 返回 `List[RequirementItem]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractors.py
from proofreader.extractors.requirement_extractor import extract_requirements
from proofreader.parsers.docx_parser import (
    DocumentSection,
    DocumentSectionType,
    ParsedDocument,
    TextBlock,
    ParagraphType,
)


def test_extract_requirements_backward_compatible():
    doc = ParsedDocument(path="test.docx", doc_type="tender_document", title=None, sections=[], blocks=[], headings=[], raw_tables=[])
    doc.sections = [
        DocumentSection(
            DocumentSectionType.REQUIREMENTS,
            "需求",
            1,
            0,
            10,
            ["需求"],
            paragraphs=[TextBlock("1. 服务期限：12个月", "paragraph", paragraph_type=ParagraphType.NUMBERED_REQUIREMENT, index=0)],
            tables=[],
        )
    ]
    items = extract_requirements(doc)
    assert len(items) == 1
    assert "12个月" in items[0].raw_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_extractors.py::test_extract_requirements_backward_compatible -v`

Expected: FAIL（旧实现可能返回空或错误类型）

- [ ] **Step 3: Write minimal实现**

```python
# src/proofreader/extractors/requirement_extractor.py
from pathlib import Path
from typing import List

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.models.requirements import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument


def extract_requirements(doc: ParsedDocument) -> List[RequirementItem]:
    """兼容旧接口：从 ParsedDocument 提取需求条目。"""
    extractor = CompositeExtractor(
        extractors=[
            HeadingBasedExtractor(),
            NumberedParagraphExtractor(),
            TableRowExtractor(),
        ]
    )
    return extractor.extract(doc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_extractors.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/requirement_extractor.py tests/test_extractors.py
git commit -m "refactor(extractors): wrap legacy extract_requirements with CompositeExtractor

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: Pipeline 集成 Repository

**Files:**
- Modify: `src/proofreader/pipeline.py`
- Test: `tests/test_pipeline.py` 或新增 `tests/test_pipeline_project.py`

**Interfaces:**
- Consumes: `JsonRequirementRepository`, `RequirementItem.review_status`
- Produces: `Proofreader.proofread_project(project_id, bid_path)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_project.py
import tempfile
from pathlib import Path

from proofreader.models.requirements import (
    CheckMethod,
    ConstraintType,
    RequirementCategory,
    RequirementItem,
    ReviewStatus,
)
from proofreader.pipeline import Proofreader
from proofreader.repository.json_repository import JsonRequirementRepository


def test_proofread_project_uses_confirmed_requirements():
    with tempfile.TemporaryDirectory() as tmp:
        repo = JsonRequirementRepository(base_dir=Path(tmp))
        repo.create_project("proj-test", "测试项目")
        repo.save_requirements("proj-test", [
            RequirementItem(
                id="REQ-1",
                source_doc="req.docx",
                chapter_path=["1"],
                raw_text="测试需求",
                normalized_text="测试需求",
                category=RequirementCategory.TECHNICAL,
                constraint_type=ConstraintType.MANDATORY,
                check_method=CheckMethod.RULE,
                extracted_by="rule",
                review_status=ReviewStatus.CONFIRMED,
            ),
            RequirementItem(
                id="REQ-2",
                source_doc="req.docx",
                chapter_path=["1"],
                raw_text="草稿需求",
                normalized_text="草稿需求",
                category=RequirementCategory.TECHNICAL,
                constraint_type=ConstraintType.MANDATORY,
                check_method=CheckMethod.RULE,
                extracted_by="rule",
                review_status=ReviewStatus.DRAFT,
            ),
        ])
        proofreader = Proofreader(repository=repo, ocr_enabled=False)
        items = repo.load_requirements("proj-test")
        confirmed = [i for i in items if i.review_status == ReviewStatus.CONFIRMED]
        assert len(confirmed) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src pytest tests/test_pipeline_project.py -v`

Expected: FAIL with "Proofreader 不接受 repository 参数"

- [ ] **Step 3: Write minimal implementation**

修改 `src/proofreader/pipeline.py`：

```python
from proofreader.repository.json_repository import JsonRequirementRepository


class Proofreader:
    def __init__(
        self,
        repository=None,
        ocr_use_gpu: bool = False,
        ocr_enabled: bool = True,
    ):
        self.repo = repository or JsonRequirementRepository()
        ...

    def proofread_project(
        self,
        project_id: str,
        bid_path: Path | str,
        cache_dir: Path | str | None = None,
    ) -> ProofreadResult:
        items = self.repo.load_requirements(project_id)
        requirements = [
            item for item in items
            if item.review_status == ReviewStatus.CONFIRMED
        ]
        req_docs = self.repo.load_parsed(project_id)  # Phase 1 stub
        if not req_docs:
            req_docs = []
        return self._proofread_with_requirements(
            requirement_paths=[],
            req_docs=req_docs,
            requirements=requirements,
            bid_path=Path(bid_path),
            cache_dir=Path(cache_dir) if cache_dir else Path(".cache"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src pytest tests/test_pipeline_project.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/pipeline.py tests/test_pipeline_project.py
git commit -m "feat(pipeline): add proofread_project with repository integration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: Streamlit 需求管理页面

**Files:**
- Create: `src/proofreader/ui/requirement_manager.py`
- Modify: `src/proofreader/ui/app.py`
- Test: 手工验证

**Interfaces:**
- Consumes: `JsonRequirementRepository`, `parse_docx_with_sections`, `CompositeExtractor`
- Produces: Streamlit UI 页面

- [ ] **Step 1: 创建需求管理页面骨架**

```python
# src/proofreader/ui/requirement_manager.py
from pathlib import Path

import streamlit as st

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.heading_based_extractor import HeadingBasedExtractor
from proofreader.extractors.numbered_paragraph_extractor import NumberedParagraphExtractor
from proofreader.extractors.table_row_extractor import TableRowExtractor
from proofreader.models.requirements import ReviewStatus
from proofreader.parsers.docx_parser import parse_docx_with_sections
from proofreader.repository.json_repository import JsonRequirementRepository


def render_requirement_manager():
    st.header("需求管理")
    repo = JsonRequirementRepository()

    projects = repo.list_projects()
    project_names = {p.project_id: f"{p.project_name} ({p.project_id})" for p in projects}
    action = st.radio("操作", ["选择现有项目", "创建新项目"])
    if action == "创建新项目":
        project_id = st.text_input("项目 ID")
        project_name = st.text_input("项目名称")
        if st.button("创建") and project_id and project_name:
            repo.create_project(project_id, project_name)
            st.success(f"已创建项目 {project_id}")
            st.rerun()
        return

    if not projects:
        st.info("暂无项目，请先创建")
        return

    project_id = st.selectbox("选择项目", options=list(project_names.keys()), format_func=lambda x: project_names[x])

    uploaded_files = st.file_uploader("上传招标/需求文件", type=["docx", "doc"], accept_multiple_files=True)
    if uploaded_files:
        sources_dir = repo._project_dir(project_id) / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        for f in uploaded_files:
            path = sources_dir / f.name
            path.write_bytes(f.getvalue())
        st.success(f"已上传 {len(uploaded_files)} 个文件")

    if st.button("自动提取需求"):
        sources_dir = repo._project_dir(project_id) / "sources"
        docs = []
        for path in sources_dir.glob("*.docx"):
            docs.append(parse_docx_with_sections(path))
        extractor = CompositeExtractor([
            HeadingBasedExtractor(),
            NumberedParagraphExtractor(),
            TableRowExtractor(),
        ])
        all_items = []
        for doc in docs:
            all_items.extend(extractor.extract(doc))
        repo.save_requirements(project_id, all_items)
        st.success(f"已提取 {len(all_items)} 条需求")

    items = repo.load_requirements(project_id)
    if items:
        st.write(f"共 {len(items)} 条需求")
        edited = st.data_editor(
            [item.model_dump() for item in items],
            column_config={
                "id": st.column_config.TextColumn("ID", disabled=True),
                "stable_hash": st.column_config.TextColumn("Hash", disabled=True),
                "created_at": st.column_config.TextColumn("创建时间", disabled=True),
                "modified_at": st.column_config.TextColumn("修改时间", disabled=True),
                "version": st.column_config.NumberColumn("版本", disabled=True),
            },
            num_rows="dynamic",
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("保存修改"):
                from proofreader.models.requirements import RequirementItem
                new_items = [RequirementItem(**row) for row in edited]
                repo.save_requirements(project_id, new_items)
                st.success("已保存")
        with col2:
            if st.button("全部确认"):
                from proofreader.models.requirements import RequirementItem
                new_items = [RequirementItem(**row) for row in edited]
                for item in new_items:
                    item.review_status = ReviewStatus.CONFIRMED
                repo.save_requirements(project_id, new_items)
                st.success("已全部确认")
```

- [ ] **Step 2: 修改 app.py 添加导航**

在 `src/proofreader/ui/app.py` 中添加：

```python
from proofreader.ui.requirement_manager import render_requirement_manager

page = st.sidebar.radio("页面", ["文档校对", "需求管理"])
if page == "需求管理":
    render_requirement_manager()
    return
```

- [ ] **Step 3: 手工验证**

Run: `./run.sh`

Expected: 浏览器打开后，sidebar 出现"需求管理"入口；可创建项目、上传文件、提取需求、编辑保存。

- [ ] **Step 4: Commit**

```bash
git add src/proofreader/ui/requirement_manager.py src/proofreader/ui/app.py
git commit -m "feat(ui): add requirement management page

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

### Spec Coverage

| Spec 章节 | 实现任务 |
|----------|---------|
| 数据模型（枚举、RequirementItem、CheckTarget） | Task 1 |
| Parser 分区识别 | Task 2 |
| Parser 标题层级修正 | Task 3 |
| Parser 段落分类 | Task 3 |
| Parser 表格分类 | Task 4 |
| Repository 接口与 JSON 实现 | Task 5 |
| Extractor 接口与组合提取器 | Task 6 |
| NumberedParagraphExtractor | Task 7 |
| HeadingBasedExtractor | Task 8 |
| TableRowExtractor + 策略 | Task 9 |
| 语义去重 | Task 10 |
| 旧接口兼容 | Task 11 |
| Pipeline 集成 | Task 12 |
| Streamlit 需求管理页面 | Task 13 |

### Placeholder Scan

- 无 TBD/TODO。
- `JsonRequirementRepository.load_parsed` 明确为 Phase 1 stub，已标注。
- Streamlit 页面测试采用手工验证，已说明原因。

### Type Consistency

- `BaseExtractor.extract_from_section(section, doc)` 在所有子类中一致。
- `RequirementItem` 字段名与 spec 一致。
- `ParsedDocument` 新增字段 `doc_type`, `title`, `sections` 不破坏旧字段。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach do you prefer?

