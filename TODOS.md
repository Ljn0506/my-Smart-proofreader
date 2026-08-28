# TODOS

## Pipeline / Repository

### 集成 Repository 到 pipeline 并新增 `proofread_project`

**What:** 修改 `src/proofreader/pipeline.py`，注入 `RequirementRepository` 抽象接口，并增加 `proofread_project(project_id, ...)` 入口，用于按项目持久化需求与校对结果。

**Why:** 当前 `pipeline.py` 仅支持单次 `proofread(req_path, bid_path)` 调用；项目级复用需求库、跨文件累积状态需要 repository 集成。

**Context:** `RequirementRepository` 与 `JsonRequirementRepository` 已在 `src/proofreader/repository/` 实现；`pipeline.py` 中 `_parse_requirements` 已做批量去重，但未与 repository 的 save/load 打通。 deferred from docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md.

**Effort:** M
**Priority:** P1
**Depends on:** None

### 为 `proofread_project` 添加测试

**What:** 创建 `tests/test_pipeline_project.py` 或等价测试，覆盖项目级需求持久化、复用、去重及跨投标文件校对流程。

**Why:** 没有测试的 repository 集成容易在项目 ID、路径解析、缓存失效等边界上回退。

**Context:** 现有 `tests/test_pipeline.py` 已覆盖单次校对流程，可作为项目级测试的模板。 deferred from docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md.

**Effort:** S
**Priority:** P1
**Depends on:** 集成 Repository 到 pipeline 并新增 `proofread_project`

## UI

### 创建 Streamlit 需求管理页面

**What:** 新增 `src/proofreader/ui/requirement_manager.py`，提供项目需求查看、编辑、导入/导出功能。

**Why:** 项目级需求库需要 UI 入口让用户管理需求，而不是仅通过代码或 JSON 文件操作。

**Context:** `src/proofreader/ui/app.py` 已存在 Streamlit 主入口；新页面应复用 `RequirementRepository` 与 `RequirementItem` 模型。 deferred from docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md.

**Effort:** M
**Priority:** P1
**Depends on:** 集成 Repository 到 pipeline 并新增 `proofread_project`

### 在 Streamlit 主导航增加「需求管理」入口

**What:** 修改 `src/proofreader/ui/app.py`，在导航菜单中增加「需求管理」选项并路由到新的 requirement_manager 页面。

**Why:** 新页面必须能从主应用访问，否则用户无法使用。

**Context:** Streamlit 通常使用 `st.sidebar.radio` 或 `st.navigation` 进行页面路由。 deferred from docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md.

**Effort:** XS
**Priority:** P1
**Depends on:** 创建 Streamlit 需求管理页面

## Models

### 当 `check_method="rule"` 时强制要求 `check_target`

**What:** 在 `RequirementItem` 的校验器或提取逻辑中，当 `check_method` 为 `rule` 时要求 `check_target` 非空；若为空则抛出 ValidationError 或记录警告。

**Why:** `check_target` 定义规则检查的对象（文本、表格、截图等），缺失会导致下游检查器不知道该对什么内容执行规则。

**Context:** `RequirementItem.check_target` 当前为 `Optional[CheckTarget]`；需要评估是否所有 rule 类型需求都必须有 target，还是先给默认值再逐步收紧。 deferred from docs/superpowers/plans/2026-07-23-requirement-extraction-plan.md.

**Effort:** S
**Priority:** P1
**Depends on:** None
