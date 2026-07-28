# 需求提取重构 — 框架与接口对齐文档

> 日期：2026-07-28  
> 分支：`fix/task4-docx-section-table`  
> 范围：Tasks 1-11 已实现，Task 12/13 尚未开始  

## 1. 目标

把本次需求提取重构成一个**端到端可运行的框架**：

- 输入：招标/需求 Word 文档
- 处理：解析 → 分区 → 多策略提取 → 语义去重 → 持久化 → 校对
- 输出：带偏离检测的校对结果 + 可人工确认的需求条目

本文档先梳理已搭建的各层组件、接口契约，再列出当前未对齐的地方，作为继续实施 Task 12/13 的前置依据。

---

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ UI (Streamlit)                                                      │
│  ├─ app.py                 批量文档校对页（已有）                   │
│  └─ requirement_manager.py 需求管理页（Task 13 计划）               │
├─────────────────────────────────────────────────────────────────────┤
│ Pipeline                                                            │
│  └─ Proofreader                                                       │
│       ├─ proofread(req_path, bid_path)        单文件校对（已有）    │
│       ├─ proofread_batch(req_paths, bid_paths) 批量校对（已有）     │
│       └─ proofread_project(project_id, bid_path) 基于仓库校对（Task 12）
├─────────────────────────────────────────────────────────────────────┤
│ Repository                                                          │
│  └─ JsonRequirementRepository                                         │
│       ├─ create_project / list_projects                               │
│       ├─ save_requirements / load_requirements                        │
│       └─ save_parsed / load_parsed (Phase 1 stub)                     │
├─────────────────────────────────────────────────────────────────────┤
│ Extractors                                                          │
│  └─ CompositeExtractor                                                │
│       ├─ HeadingBasedExtractor                                        │
│       ├─ NumberedParagraphExtractor                                   │
│       ├─ TableRowExtractor → table_strategies (Technical/Service/...) │
│       └─ SemanticDeduplicator                                         │
├─────────────────────────────────────────────────────────────────────┤
│ Parser                                                              │
│  └─ parse_docx_with_sections(docx_path) → ParsedDocument              │
│       ├─ DocumentSection (headings, paragraphs, tables)               │
│       ├─ ParsedTable (table_type, header, rows)                       │
│       └─ TextBlock (text, block_type, paragraph_type, index)          │
├─────────────────────────────────────────────────────────────────────┤
│ Model                                                               │
│  └─ RequirementItem (Pydantic BaseModel)                              │
│       ├─ 必填：id, source_doc, chapter_path, raw_text, normalized_text│
│       ├─ 分类：category, constraint_type, check_method, review_status  │
│       └─ 扩展：check_target, match_keywords, stable_hash, title 等    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 各层接口契约

### 3.1 数据模型：`RequirementItem`

位置：`src/proofreader/models/requirements.py`

| 字段 | 类型 | 说明 | 旧名（待迁移） |
|---|---|---|---|
| `id` | `str` | 条目唯一 ID | `item_id` |
| `stable_hash` | `Optional[str]` | 内容确定性哈希，用于去重 | - |
| `source_doc` | `str` | 来源文档路径 | - |
| `chapter_path` | `List[str]` | 章节路径（如 `["一、项目概况", "1.1 技术指标"]`） | - |
| `title` | `Optional[str]` | 所属章节/产品标题 | `section_title` |
| `raw_text` | `str` | 原始文本 | `text` |
| `normalized_text` | `str` | 归一化文本（去空格、符号等） | - |
| `category` | `RequirementCategory` | 条目分类 | - |
| `constraint_type` | `ConstraintType` | 约束强度 | - |
| `check_method` | `CheckMethod` | 检查方式 | - |
| `check_target` | `Optional[CheckTarget]` | 结构化检查目标 | - |
| `match_keywords` | `List[str]` | 匹配关键词 | - |
| `constraint_keywords` | `List[str]` | 旧约束词列表（新字段，默认空） | - |
| `extracted_by` | `str` | 提取器标识 | - |
| `review_status` | `ReviewStatus` | `draft` / `confirmed` / ... | - |
| `project_specific` | `bool` | 是否项目特有 | - |

**当前状态**：已加入临时兼容层
- 构造时支持旧关键字：`item_id` → `id`、`text` → `raw_text`、`section_title` → `title`。
- 只传旧字段时，自动补齐 `category=OTHER`、`constraint_type=REFERENCE`、`check_method=RULE`、`extracted_by="legacy"` 等默认值。
- 仍保留 `item_id`、`text`、`section_title` 三个只读属性供旧代码读取。

**问题**：兼容层是临时补丁，应在迁移完成后移除，避免模型长期背负历史字段。

### 3.2 文档解析层

位置：`src/proofreader/parsers/docx_parser.py`

| 类型 | 关键字段/方法 | 说明 |
|---|---|---|
| `ParsedDocument` | `path`, `doc_type`, `title`, `sections`, `blocks`, `headings`, `raw_tables` | 整份文档 |
| `DocumentSection` | `section_type`, `title`, `level`, `start`, `end`, `headings`, `paragraphs`, `tables` | 一个章节 |
| `ParsedTable` | `table_type`, `header`, `rows`, `index` | 解析后的表格 |
| `TextBlock` | `text`, `block_type`, `paragraph_type`, `index` | 文本块 |
| `ParagraphType` | `NORMAL`, `HEADING`, `NUMBERED_REQUIREMENT`, `NOTICE`, ... | 段落类型枚举 |
| `DocumentSectionType` | `REQUIREMENTS`, `BID_TEMPLATE`, ... | 章节类型枚举 |

入口函数：

```python
parse_docx(path: Path | str) -> ParsedDocument
parse_docx_with_sections(path: Path | str) -> ParsedDocument
```

`parse_docx_with_sections` 会填充 `sections` 和 `section_type`，是需求提取推荐入口。

### 3.3 提取器层

位置：`src/proofreader/extractors/`

| 组件 | 职责 | 关键方法 |
|---|---|---|
| `base.BaseExtractor` | 抽象接口 | `extract_from_section(section, doc) -> List[RequirementItem]` |
| `heading_prefix()` | 共享 ID 前缀生成 | - |
| `HeadingBasedExtractor` | 基于标题提取 | `extract_from_section` |
| `NumberedParagraphExtractor` | 基于编号段落提取 | `extract_from_section` |
| `TableRowExtractor` | 表格行分发 | `extract_from_section` |
| `table_strategies` | 按 `table_type` 选择策略 | `get_strategy(table_type) -> TableStrategy` |
| `CompositeExtractor` | 组合提取 + 去重 | `extract(doc) -> List[RequirementItem]` |
| `deduplicator.SemanticDeduplicator` | 两阶段去重 | `deduplicate(items) -> List[RequirementItem]` |
| `requirement_extractor` | 旧接口兼容入口 | `extract_requirements(doc) -> List[RequirementItem]` |

提取顺序：

1. `CompositeExtractor` 遍历 `doc.sections`，跳过 `BID_TEMPLATE`。
2. 对每个 section 依次调用 `HeadingBasedExtractor`、`NumberedParagraphExtractor`、`TableRowExtractor`。
3. 合并结果后交给 `SemanticDeduplicator`：先按 `stable_hash` 去重，再按 TF-IDF 余弦相似度 ≥ 0.95 去重。

### 3.4 仓库层

位置：`src/proofreader/repository/`

```python
class RequirementRepository(ABC):
    def create_project(self, project_id: str, name: str) -> ProjectMeta: ...
    def list_projects(self) -> List[ProjectMeta]: ...
    def save_requirements(self, project_id: str, items: List[RequirementItem]) -> None: ...
    def load_requirements(self, project_id: str) -> List[RequirementItem]: ...
    def save_parsed(self, project_id: str, docs: List[ParsedDocument]) -> None: ...
    def load_parsed(self, project_id: str) -> List[ParsedDocument]: ...
```

当前实现：`JsonRequirementRepository`，项目目录结构：

```
projects/
└── {project_id}/
    ├── meta.json
    ├── requirements.json
    ├── sources/
    └── parsed/
        └── parsed_documents.json
```

注意：`load_parsed` 目前是 Phase 1 stub，直接抛 `NotImplementedError`。Task 12 的 `proofread_project` 需要处理这一情况（文档里已提示“若无解析文档则传空列表”）。

### 3.5 Pipeline 层

位置：`src/proofreader/pipeline.py`

当前对外接口：

```python
class Proofreader:
    def __init__(self, ocr_use_gpu: bool = False, ocr_enabled: bool = True): ...

    def proofread(
        self,
        requirement_path: Path | str,
        bid_path: Path | str,
        cache_dir: Path | str | None = None,
    ) -> ProofreadResult: ...

    def proofread_batch(
        self,
        requirement_paths: List[Path | str],
        bid_paths: List[Path | str],
        cache_dir: Path | str | None = None,
        progress_callback: Callable[[int, int, Path], None] | None = None,
    ) -> ProofreadBatchResult: ...
```

Task 12 计划新增：

```python
def proofread_project(
    self,
    project_id: str,
    bid_path: Path | str,
    cache_dir: Path | str | None = None,
) -> ProofreadResult:
    items = self.repo.load_requirements(project_id)
    requirements = [i for i in items if i.review_status == ReviewStatus.CONFIRMED]
    req_docs = self.repo.load_parsed(project_id) or []
    return self._proofread_with_requirements(
        requirement_paths=[],
        req_docs=req_docs,
        requirements=requirements,
        bid_path=Path(bid_path),
        cache_dir=Path(cache_dir) if cache_dir else Path(".cache"),
    )
```

内部主流程：

```
_parse_requirements(req_paths)
  → parse_docx → CompositeExtractor → List[RequirementItem]

_proofread_with_requirements(req_paths, req_docs, requirements, bid_path, cache_dir)
  1. parse_docx(bid_path) → bid_doc
  2. split_bid_sections(bid_doc, product_names) → bid_sections
  3. match_requirements_to_bid(requirements, bid_sections) → matches
  4. check_consistency(matches) → consistency_issues
  5. check_typos(bid_doc.blocks) → typo_issues
  6. check_images(bid_doc, requirements, ocr_engine) → ocr_issues
  7. check_tables(merged_req_doc, bid_doc) → table_issues
  8. 返回 ProofreadResult
```

### 3.6 检查器/匹配器层

| 模块 | 输入 | 当前读取的旧字段 | 需迁移到 |
|---|---|---|---|
| `matchers/semantic_matcher.py` | `List[RequirementItem]` + `List[BidSection]` | `req.text`, `req.section_title` | `req.raw_text`, `req.title` |
| `checkers/consistency_checker.py` | `List[MatchResult]` | `req.item_id`, `req.text`, `req.section_title` | `req.id`, `req.raw_text`, `req.title` |
| `checkers/ocr_checker.py` | `ParsedDocument` + `List[RequirementItem]` + `OcrEngine` | `req.text`, `req.section_title`, `req.constraint_keywords` | `req.raw_text`, `req.title`, `req.constraint_keywords` |
| `ui/app.py` | `ProofreadResult` | `req.item_id`, `req.text`, `req.constraint_keywords` | `req.id`, `req.raw_text`, `req.constraint_keywords` |

`checkers/table_checker.py`、`checkers/typo_checker.py` 不直接依赖 `RequirementItem`。

### 3.7 UI 层

位置：`src/proofreader/ui/`

| 页面 | 文件 | 状态 |
|---|---|---|
| 批量文档校对 | `app.py` | 已有，调用 `Proofreader.proofread_batch` |
| 需求管理 | `requirement_manager.py` | Task 13 计划创建：项目创建/选择、上传需求文件、自动提取、编辑确认需求 |
| 高亮辅助 | `highlighting.py` | 已有，依赖 `CONSTRAINT_KEYWORDS` 和 `THRESHOLD_KEYWORDS` |

---

## 4. 当前未对齐的问题

### 4.1 模型字段不一致（阻塞级）

新的 `RequirementItem` 与下游调用方字段名不一致。虽然加了临时兼容层，但 `pipeline.py` 内部仍通过 `RequirementItem` 的旧属性访问数据，依赖的是兼容属性。若移除兼容层会立刻崩溃。

**建议**：统一迁移到新的字段名，然后删除兼容层。

### 4.2 `load_parsed` 是 stub（已知限制）

`JsonRequirementRepository.load_parsed` 当前抛 `NotImplementedError`。

**影响**：
- Task 12 的 `proofread_project` 不能把解析后的需求文档传给表格检查器，表格检查会退化。
- Task 13 上传文件后只能重新 `parse_docx_with_sections` 提取需求，无法复用已保存的解析结果。

**建议**：Phase 1 先按 brief 标注为 stub，表格检查器用空 `ParsedDocument` 或从原始文件重新解析兜底；后续再实现完整序列化。

### 4.3 Pipeline 构造方式待扩展

当前 `Proofreader.__init__` 只有 `ocr_use_gpu` 和 `ocr_enabled`。

Task 12 需要支持传入 `repository`：

```python
def __init__(self, repository=None, ocr_use_gpu=False, ocr_enabled=True):
    self.repo = repository or JsonRequirementRepository()
```

### 4.4 需求管理页面与 Pipeline 的衔接

Task 13 的 `requirement_manager.py` 将：
1. 创建/选择项目。
2. 上传需求文件到 `projects/{id}/sources/`。
3. 点击“自动提取需求”时调用 `CompositeExtractor.extract(doc)`，得到 `List[RequirementItem]`。
4. 保存到 `requirements.json`。
5. 用户在 `st.data_editor` 中编辑/确认，`review_status=CONFIRMED` 后保存。

Task 12 的 `proofread_project` 则读取这些 `CONFIRMED` 需求去校对投标文件。

**衔接点**：`RequirementItem.model_dump()` 在 Streamlit data_editor 中会变成 dict，编辑后重新 `RequirementItem(**row)` 构造。需要确保所有字段（尤其是枚举、datetime）能正常往返。

---

## 5. 接口契约汇总

| 调用方 | 被调用方 | 输入 | 输出 | 当前状态 |
|---|---|---|---|---|
| `app.py` | `Proofreader.proofread_batch` | 需求路径列表、投标路径列表 | `ProofreadBatchResult` | ✅ 可用 |
| `requirement_manager.py` (计划) | `JsonRequirementRepository` + `CompositeExtractor` | 上传的 docx | 持久化需求条目 | ⏳ Task 13 |
| `Proofreader.proofread_project` (计划) | `JsonRequirementRepository.load_requirements` | `project_id` | `List[RequirementItem]` (confirmed) | ⏳ Task 12 |
| `CompositeExtractor.extract` | 各 extractor + `SemanticDeduplicator` | `ParsedDocument` | `List[RequirementItem]` | ✅ 可用 |
| `_proofread_with_requirements` | `match_requirements_to_bid` | `List[RequirementItem]` + `List[BidSection]` | `List[MatchResult]` | ⚠️ 依赖旧字段 |
| `_proofread_with_requirements` | `check_consistency` | `List[MatchResult]` | `List[ConsistencyIssue]` | ⚠️ 依赖旧字段 |
| `_proofread_with_requirements` | `check_images` | `ParsedDocument` + `List[RequirementItem]` | `List[OcrIssue]` | ⚠️ 依赖旧字段 |

---

## 6. 推荐实施顺序

1. **迁移下游字段到新版模型**
   - `matchers/semantic_matcher.py`：`req.text` → `req.raw_text`，`req.section_title` → `req.title`
   - `checkers/consistency_checker.py`：`req.item_id` → `req.id`，`req.text` → `req.raw_text`
   - `checkers/ocr_checker.py`：`req.text` → `req.raw_text`，`req.section_title` → `req.title`
   - `ui/app.py`：`req.item_id` → `req.id`，`req.text` → `req.raw_text`
   - 测试文件同步更新。

2. **移除临时兼容层**
   - 从 `RequirementItem` 中移除旧字段别名、默认值补齐和 `item_id`/`text`/`section_title` 属性。
   - 保留 `constraint_keywords` 字段（OCR 检查器需要）。

3. **实施 Task 12：Pipeline 集成 Repository**
   - 修改 `Proofreader.__init__` 接受 `repository`。
   - 实现 `proofread_project`。
   - 新增 `tests/test_pipeline_project.py`。

4. **实施 Task 13：Streamlit 需求管理页面**
   - 创建 `src/proofreader/ui/requirement_manager.py`。
   - 在 `app.py` 添加侧边栏导航。
   - 手工验证。

5. **最终全分支评审**
   - 跑完整 `tests-pytest/` 和 `tests/`。
   - 检查是否还有旧字段残留。

---

## 7. 决策记录

- **2026-07-28**：因 Task 11 删除了旧 `RequirementItem` 导致下游 import 失败，临时在 `models/requirements.py` 中加入旧字段兼容层，以便框架其他部分能继续运行。该兼容层应在迁移完成后删除。
- **`load_parsed` stub**：按 brief 标记为 Phase 1 暂不实装，后续再实现 `ParsedDocument` 的完整序列化/反序列化。

---

## 8. 待确认事项

1. 是否同意按第 6 节的顺序实施：先迁移下游字段、移除兼容层，再做 Task 12/13？
2. `ui/app.py` 里展示需求时除了 `id`/`raw_text`/`constraint_keywords`，是否还需要展示 `category`、`constraint_type`、`review_status` 等字段？
3. `load_parsed` 的 Phase 1 stub 是否接受“表格检查器用空 `ParsedDocument` 兜底”，还是需要在 Task 12 里实现最小化解析文档重建？
