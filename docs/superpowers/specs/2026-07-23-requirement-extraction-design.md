# 需求侧解析重构设计文档

## 1. 背景与目标

### 1.1 当前痛点

现有 `requirement_extractor.py` 存在以下问题：

1. **提取不准确、漏提**：仅基于简单规则提取编号段落，忽略表格、标题跟随段落、项目符号列表等需求来源。
2. **条目结构太简单**：缺少 `category`（分类）、`constraint_type`（约束类型）、`check_method`（校对方式）、`check_target`（检查目标）等关键字段。
3. **无法人工复审补充**：提取结果直接进入 pipeline，没有持久化和人工修正环节。

### 1.2 目标流程

```
招标需求书 ──→ AI自动拆解 ──→ 需求条目化 ──→ 人工复审补充 ──→ 结构化需求库
```

第一阶段先搭框架，AI 拆解暂用规则实现；后续平滑接入 LLM（云端 + 本地）。

### 1.3 设计原则

- **按内容解析**：Parser 根据文档内容识别分区，不依赖不可靠的 Heading 样式。
- **章节 + 招标分类双视角**：每个需求条目同时保留 `chapter_path`（文档章节层级）和 `category`（商务/技术/资质/评分等）。
- **人工闭环**：Streamlit 提供需求管理页面，支持上传 → 自动提取 → 编辑 → 保存项目库。
- **可扩展**：Extractor、Repository、CheckTarget 均设计为接口，便于后续接 AI、换存储、加模板继承。

---

## 2. 数据模型

### 2.1 枚举定义

```python
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
    MERGED = "merged"         # 归并入核心需求
    DEPRECATED = "deprecated" # 版本更新后失效
```

### 2.2 检查目标

```python
class CheckTarget(BaseModel):
    type: str  # numeric_compare / existence / certificate_compare / text_contains / ...
    field: str | None = None      # 要检查的字段/段落
    operator: str | None = None   # >= / <= / == / contains / in 等
    value: Any | None = None      # 目标值
    unit: str | None = None       # 单位（如 %、天、人）
    description: str | None = None  # LLM 引导性描述
```

- `check_method="rule"` 时，`check_target` 必填。
- `check_method="llm"` 时，`check_target` 可选填引导性描述。

### 2.3 需求条目

```python
class RequirementItem(BaseModel):
    # === 标识 ===
    id: str                              # 可读 ID，如 "BID001-3.2-005"
    stable_hash: str | None = None       # 内容哈希，跨版本追踪用

    # === 来源定位 ===
    source_doc: str                      # 来源文件名
    chapter_path: list[str]              # ["3 技术要求", "3.2 性能指标"]
    title: str | None = None             # 小节标题

    # === 需求内容 ===
    raw_text: str                        # 原始文本
    normalized_text: str                 # 清洗后用于匹配/比对

    # === 分类 ===
    category: RequirementCategory
    constraint_type: ConstraintType

    # === 校对执行信息 ===
    check_method: CheckMethod            # 用什么方式校对
    check_target: CheckTarget | None = None
    match_keywords: list[str] = []       # 定位投标文件段落的锚点

    # === 溯源与状态 ===
    extracted_by: str                    # "rule" / "llm" / "manual"
    review_status: ReviewStatus = ReviewStatus.DRAFT
    manual_note: str | None = None

    # === 模板继承预留 ===
    template_ref: str | None = None      # 引用公共模板条目 ID
    project_specific: bool = False       # 是否为该项目特有

    # === 元数据 ===
    created_at: datetime | None = None
    modified_at: datetime | None = None
    version: int = 1
```

`stable_hash` 基于 `raw_text + chapter_path[-1]` 生成。

---

## 3. Parser 层设计

### 3.1 输出结构

```python
class DocumentSectionType(str, Enum):
    TENDER_NOTICE = "tender_notice"           # 招标公告/邀请函
    BIDDER_INSTRUCTIONS = "bidder_instructions" # 供应商/投标人须知
    REQUIREMENTS = "requirements"             # 采购需求/用户需求书
    EVALUATION = "evaluation"                 # 评审/评分
    CONTRACT = "contract"                     # 合同文本/条款
    BID_TEMPLATE = "bid_template"             # 投标文件格式（不跳过）
    UNKNOWN = "unknown"

class DocumentType(str, Enum):
    TENDER = "tender_document"      # 招标文件（含公告、须知、需求、评审、合同、模板）
    REQUIREMENT = "requirement_document"  # 纯需求文件
    BID = "bid_document"            # 投标文件/响应文件

class DocumentSection(BaseModel):
    section_type: DocumentSectionType
    title: str | None
    level: int
    start_index: int
    end_index: int
    headings: list[str]
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]

class ParsedDocument(BaseModel):
    path: Path
    doc_type: DocumentType
    title: str | None
    sections: list[DocumentSection]
    # 兼容旧接口
    blocks: list[ParsedParagraph]
    headings: list[ParsedHeading]
    raw_tables: list[ParsedTable]
```

### 3.2 分区识别规则（第一阶段）

基于标题关键词 + 内容模式：

| 分区类型 | 识别依据 |
|---------|---------|
| `tender_notice` | 标题含"招标公告"、"比选邀请函"、"遴选邀请函" |
| `bidder_instructions` | 标题含"供应商须知"、"投标人须知"、"响应供应商须知" |
| `requirements` | 标题含"采购需求"、"用户需求书"、"需求内容"、"技术/商务要求" |
| `evaluation` | 标题含"评审"、"评标"、"评分标准"、"资格审查" |
| `contract` | 标题含"合同文本"、"合同条款"、"合同样本" |
| `bid_template` | 标题含"投标文件格式"、"响应文件格式"、"自查表"、"报价表" |

### 3.3 标题层级修正

Heading 样式不可靠，需要结合编号模式重新推断层级：

- `第[一二三四五六七八九十]+章` → level 1
- `[一二三四五六七八九十]+[、．.]` → level 1
- `\d+[\.．]\s*\D` → level 2
- `(\d+)` → level 3
- `\d+[\.．]\d+` → level 3
- 英文项目符号 a/b/c → level 4+

同时处理 `★` / `▲` 标记：这些标记不影响层级，但会影响 `constraint_type`。

### 3.4 段落分类

```python
class ParagraphType(str, Enum):
    HEADING = "heading"
    NUMBERED_REQUIREMENT = "numbered_requirement"
    PLAIN_TEXT = "plain_text"
    METADATA = "metadata"
    NOTICE = "notice"
```

### 3.5 表格分类

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
```

基于表头关键词识别，第一阶段保存所有类型，后续根据真实数据扩展。

---

## 4. Extractor 层设计

### 4.1 接口

```python
class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, doc: ParsedDocument) -> list[RequirementItem]: ...
```

### 4.2 子提取器

```python
class HeadingBasedExtractor(BaseExtractor):
    """从章节标题和跟随的正文提取需求框架。"""

class NumberedParagraphExtractor(BaseExtractor):
    """从编号段落（1. / (1) / ①）提取需求条目。"""

class TableRowExtractor(BaseExtractor):
    """从表格行提取需求条目，按表类型分发策略。"""
```

### 4.3 表格行提取策略

```python
class TableRowExtractor(BaseExtractor):
    def extract_from_table(self, table: ParsedTable, context: SectionContext) -> list[RequirementItem]:
        strategy = self._choose_strategy(table.table_type)
        return strategy.extract(table, context)
```

| 表类型 | 策略 | 输出 |
|--------|------|------|
| `TECHNICAL_SPEC` | 每行一个需求 | `category=TECHNICAL` |
| `SERVICE_LIST` | 每行一个需求 | `category=TECHNICAL/DELIVERY` |
| `EVALUATION` | 提取评分项 | `category=SCORING, constraint_type=SCORING` |
| `CHECKLIST` | 每个检查项 | `category=QUALIFICATION/COMMERCIAL` |
| `QUALIFICATION` | 每个资质项 | `category=QUALIFICATION` |
| `PERFORMANCE` | 业绩要求 | `category=QUALIFICATION` |
| `PERSONNEL` | 人员要求 | `category=PERSONNEL` |
| `QUOTATION` | 通常不生成需求 | 保留表格，不生成条目 |

### 4.4 组合提取器

```python
class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors: list[BaseExtractor] | None = None):
        self.extractors = extractors or [
            HeadingBasedExtractor(),
            NumberedParagraphExtractor(),
            TableRowExtractor(),
        ]

    def extract(self, doc: ParsedDocument) -> list[RequirementItem]:
        items: list[RequirementItem] = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue  # 不进入需求库，但分区信息保留
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
        return self._deduplicate(items)
```

### 4.5 语义去重

```python
class SemanticDeduplicator:
    def __init__(self, similarity_threshold: float = 0.95):
        self.threshold = similarity_threshold

    def deduplicate(self, items: list[RequirementItem]) -> list[RequirementItem]:
        # 1. 按 stable_hash 粗去重
        # 2. 用 TF-IDF + 余弦相似度精去重
        # 3. 保留 chapter_path 更完整、表格来源优先的版本
```

### 4.6 AI Extractor 预留

```python
class LLMExtractor(BaseExtractor):
    def __init__(self, backend: str = "openai", model: str | None = None): ...
```

第一阶段用 `RuleBasedExtractor`（即 `CompositeExtractor`），后续通过配置切换。

---

## 5. Repository 层设计

### 5.1 项目目录结构

```
projects/
├── <project_id>/
│   ├── meta.json                 # 项目元数据
│   ├── requirements.json         # 结构化需求库
│   ├── sources/                  # 原始招标/需求文件
│   └── parsed/                   # Parser 输出缓存
│       └── parsed_documents.json
```

### 5.2 接口

```python
class RequirementRepository(ABC):
    @abstractmethod
    def create_project(self, project_id: str, name: str) -> ProjectMeta: ...

    @abstractmethod
    def save_parsed(self, project_id: str, docs: list[ParsedDocument]) -> None: ...

    @abstractmethod
    def load_parsed(self, project_id: str) -> list[ParsedDocument]: ...

    @abstractmethod
    def save_requirements(self, project_id: str, items: list[RequirementItem]) -> None: ...

    @abstractmethod
    def load_requirements(self, project_id: str) -> list[RequirementItem]: ...

    @abstractmethod
    def list_projects(self) -> list[ProjectMeta]: ...
```

### 5.3 第一阶段实现：`JsonRequirementRepository`

- 所有数据存 JSON。
- `requirements.json` 含 `schema_version` 字段，当前为 `"1.0"`。
- 加载时检查 schema 版本，不兼容时抛错并提示迁移。

### 5.4 第二阶段预留

- `SQLiteRequirementRepository`：后续实现。
- 公共需求模板：积累 3-5 个项目数据后，从需求库中提炼模板，引入 `template_ref` 和 `project_specific`。

---

## 6. 与现有 Pipeline 集成

### 6.1 Proofreader 调整

```python
class Proofreader:
    def __init__(
        self,
        repository: RequirementRepository | None = None,
        ocr_use_gpu: bool = False,
        ocr_enabled: bool = True,
    ):
        self.repo = repository or JsonRequirementRepository()
        ...

    def proofread_project(self, project_id: str, bid_path: Path) -> ProofreadResult:
        items = self.repo.load_requirements(project_id)
        requirements = [
            item for item in items
            if item.review_status == ReviewStatus.CONFIRMED
        ]
        # 后续流程保持不变
```

### 6.2 向后兼容

- `proofread(requirement_path, bid_path)` 仍可用，自动创建临时项目。
- 新增 `proofread_project(project_id, bid_path)` 从项目库加载。

---

## 7. Streamlit 需求管理页面

### 7.1 页面入口

```
sidebar
├── 需求管理
│   ├── 选择/创建项目
│   ├── 上传招标/需求文件
│   ├── 自动提取
│   ├── 人工复审
│   └── 保存需求库
└── 文档校对
    ├── 选择项目
    ├── 上传投标文件
    └── 开始校对
```

### 7.2 页面流程

1. **选择/创建项目**
   - 下拉选择已有项目，或输入新项目 ID 创建。
   - 显示项目元数据。

2. **上传招标/需求文件**
   - 支持上传一个或多个 `.docx` / `.doc`。
   - `.doc` 自动通过 LibreOffice 转 `.docx`。
   - 原始文件保存到 `projects/<project_id>/sources/`。

3. **自动提取**
   - 调用 `RuleBasedExtractor.extract(docs)` 生成候选条目。
   - 所有新条目 `review_status = DRAFT`。

4. **人工复审表格**
   - 用 `st.data_editor` 展示条目列表。
   - 可编辑字段：`category`、`constraint_type`、`check_method`、`check_target`、`match_keywords`、`raw_text`、`review_status`、`manual_note`。
   - 支持增删行、批量确认（DRAFT → CONFIRMED）。
   - 只读字段：`id`、`stable_hash`、`created_at`、`modified_at`、`version`。

5. **保存需求库**
   - 点击"保存"后调用 `JsonRepository.save_requirements(project_id, items)`。
   - 更新 `meta.json` 和 `modified_at`。

6. **导入/导出**
   - 导出当前项目需求库为 JSON/Excel。
   - 导入已编辑的 JSON/Excel 回填。

---

## 8. 测试策略

| 测试层级 | 内容 |
|---------|------|
| Parser 测试 | 验证分区识别、标题层级修正、表格分类 |
| Extractor 测试 | 对真实文件样本，验证提取出的 `RequirementItem` 字段 |
| Repository 测试 | 验证 save/load、版本兼容 |
| UI 测试 | Streamlit `AppTest` 或手工验证 |
| 集成测试 | 端到端：上传需求书 → 提取 → 保存 → 校对投标文件 |

---

## 9. 实施顺序建议

1. **Phase 1：Parser 增强**
   - 实现文档分区、标题层级修正、表格分类。
   - 对真实文件输出结构进行验证。

2. **Phase 2：数据模型 + Repository**
   - 定义 `RequirementItem`、`CheckTarget`、枚举。
   - 实现 `JsonRequirementRepository`。

3. **Phase 3：Extractor 重构**
   - 实现 `CompositeExtractor` + 三种子提取器。
   - 实现语义去重。

4. **Phase 4：Streamlit 需求管理页面**
   - 新增需求管理页面。
   - 集成 Parser + Extractor + Repository。

5. **Phase 5：Pipeline 集成**
   - 修改 `Proofreader` 支持从项目库加载。
   - 保持旧接口兼容。

6. **Phase 6：AI Extractor（后续）**
   - 实现 `LLMExtractor`，支持云端/本地模型。

7. **Phase 7：模板继承 + SQLite（后续）**
   - 积累数据后提炼公共需求模板。
   - 按需切换到 SQLite。

---

## 10. 风险与待定项

| 风险 | 应对 |
|------|------|
| 真实文件样式不统一，Parser 规则覆盖不全 | 先用规则覆盖多数情况，后续引入 LLM 兜底 |
| 表格内容复杂，自动分类可能出错 | 第一阶段保存所有表格类型，人工复审时修正 |
| 语义去重阈值需要调优 | 默认 0.95，根据实际效果调整 |
| 项目库 JSON 文件变大后性能下降 | 第二阶段切 SQLite |

---

## 附录：真实文件分析摘要

基于 `/Users/ljn/smart-proofreader/原始招标文件/` 中的 8 个文件分析：

- **文档类型混杂**：完整招标文件、纯需求文件、需求+响应模板、比选文件、报名表、Excel 清单。
- **标题层级不统一**：样式名不可靠，必须结合文本编号模式推断。
- **需求来源多样**：编号段落、标题跟随段落、表格行、项目符号列表。
- **约束标记明确**：`★`=必须满足，`▲`=重要评分。
- **表格类型可识别**：技术指标、服务清单、评审、自查、业绩、人员、报价。
- **响应模板部分**：包含响应表、自查表、资格证明、报价表等，需解析但默认不进入需求库。
