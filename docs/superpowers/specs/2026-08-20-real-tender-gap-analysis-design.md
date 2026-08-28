# 真实招标文件/投标文件回归分析 —— 设计缺口补充文档

> 角色：产品/设计视角  
> 日期：2026-08-20  
> 版本：v1.0  
> 关联文档：[[2026-07-28-product-vision-and-design.md]]、[[2026-07-28-requirement-extraction-framework.md]]、[[2026-07-23-requirement-extraction-design.md]]

---

## 1. 文档目的

本文档以真实招投标文件为样本，对当前「智能投标文件校对系统」的设计进行回归分析，找出产品愿景文档与真实材料之间的差距，并给出设计补充方案。目的是让系统能覆盖医院信息化/网络安全/数据安全类采购中常见的文档形态与校验规则，而不是只停留在样例文档的假设结构上。

---

## 2. 样本与方法

### 2.1 样本清单

本次分析共使用 6 份真实文档，覆盖 3 种采购组织形式、2 种主要投标文件形态：

| 序号 | 文档 | 类型 | 关键特征 |
|---|---|---|---|
| 1 | 广州市荔湾区中医医院数据安全及个人信息保护服务项目（比选文件） | 招标文件 | 含邀请函、响应供应商须知、用户需求书、评分表、响应文件格式模板；使用 `★`/`▲` 标记 |
| 2 | 颐点报名文件-广州市荔湾区中医医院数据安全及个人信息保护服务项目 | 报名文件 | 纯资格报名材料：营业执照、法人证明/授权、承诺函、平台截图、信用查询截图 |
| 3 | 广东医科大学附属第二医院数据安全风险评估服务项目竞争性磋商文件 | 招标文件 | 竞争性磋商文件；含磋商邀请、采购需求、评审、响应文件格式与要求 |
| 4 | 广州医科大学附属第四医院2026年信息安全服务项目响应文件 | 投标文件 | 完整响应文件：资格性文件、商务部分、技术部分、价格部分 |
| 5 | 广州市胸科医院2026年网络安全等级保护测评服务项目报名文件 | 报名文件 | 综合性报名文件：含报价单、技术方案、资质证明、合同业绩 |
| 6 | 广东医科大学附属第二医院产品介绍报名表 | 产品报名表 | 产品准入会报名：产品资料、代理证书、参会代表身份证 |

### 2.2 分析方法

1. 将 `.doc` 转换为 `.docx`，再用 `pandoc` 提取结构化文本。
2. 逐份梳理：采购方式、章节结构、硬性要求、评分指标、证明材料类型、应答载体。
3. 与现有设计文档（产品愿景、需求提取框架、需求提取设计）逐项比对，识别缺失或未细化的能力。
4. 按「文档类型 → 解析 → 匹配 → 校验 → 导出」五层归类缺口。

---

## 3. 文档类型分类法（当前设计缺口）

### 3.1 当前设计假设

产品愿景文档默认流程是：

```
上传招标文件 → 提取需求条目 → 上传投标文件 → 语义匹配 → 输出问题
```

文档被简化为「招标需求 Word」和「投标响应 Word」两类，未区分采购组织形式和投标文件成熟度。

### 3.2 真实文档类型谱系

```
采购方文件（Tender）
├── 比选文件（综合评分法，含评分表）
├── 竞争性磋商文件（含磋商/二次报价规则）
├── 公开招标/遴选文件
├── 询价/单一来源文件
└── 产品准入报名表（产品会议，非招投标）

投标方文件（Bid）
├── 报名文件
│   ├── 纯资格报名：仅营业执照+资质+承诺+截图
│   └── 综合报名：含报价+技术方案+资质+业绩
├── 响应文件/投标文件
│   ├── 资格性文件
│   ├── 商务部分
│   ├── 技术部分
│   └── 价格部分
└── 产品解决方案（配合产品报名表）
```

### 3.3 设计缺口

| 缺口 | 说明 | 真实样本佐证 |
|---|---|---|
| 无文档类型自动检测 | 系统把 Tender 和 Bid 都当作统一 Word 处理 | 样本 1 是「比选文件」，样本 3 是「竞争性磋商文件」，样本 6 是「产品介绍报名表」 |
| 未按采购方式加载规则集 | 比选、磋商、招标的评分规则、报价轮次、资格要求不同 | 样本 1 用「综合评分法」，样本 3 有「磋商」流程，样本 6 仅需产品资料 |
| 未识别报名文件 vs 响应文件 | 报名文件可能只有资格材料，也可能含技术/报价 | 样本 2 是纯资格报名，样本 5 是含报价+技术的综合报名 |
| 未识别响应文件四段式结构 | 完整响应文件通常按「资格/商务/技术/价格」分块 | 样本 4 的目录明确分为四部分 |

### 3.4 设计补充

在 `ParsedDocument` 中新增 `document_type` 与 `procurement_method` 字段：

```python
class DocumentType(str, Enum):
    TENDER = "tender"              # 招标文件/比选文件/磋商文件
    BID_REGISTRATION = "bid_registration"   # 报名文件
    BID_RESPONSE = "bid_response"           # 完整响应/投标文件
    PRODUCT_SOLUTION = "product_solution"   # 产品解决方案
    OTHER = "other"

class ProcurementMethod(str, Enum):
    BIXUAN = "bixuan"              # 比选
    CUOSHANG = "competitive_negotiation"  # 竞争性磋商
    ZHAOBIAO = "tender"            # 公开招标
    XUANBA = "selection"           # 遴选
    PRODUCT_DEMO = "product_demo"  # 产品演示/准入
    OTHER = "other"
```

检测逻辑（三层兜底）：

1. **规则层**（第一层，默认执行）：
   - 读取标题/页眉/第一段关键词（如「比选文件」「竞争性磋商文件」「报名文件」「响应文件」「产品介绍报名表」）。
   - 读取目录结构（存在「资格性文件」「商务部分」「技术部分」「价格部分」→ `BID_RESPONSE`）。
   - 读取文件正文高频词（如「磋商」「报价」「技术方案」「报名表」）。

2. **Embedding 相似度层**（第二层，当规则层置信度不足时）：
   - 将文档标题、前 N 段文本、目录标题拼接为查询文本。
   - 与预置的各类型模板（比选文件、磋商文件、报名文件、响应文件、产品报名表）做 embedding 余弦相似度比对。
   - 取 Top-1 相似类型作为候选。

3. **LLM 层**（第三层，仅当 embedding 仍不足且用户启用本地 LLM 时）：
   - 将文档前 1000 字、标题、目录传入本地 LLM，要求输出 `document_type` 与 `procurement_method`。
   - LLM 结果带有「模型判断」标签，置信度由 LLM 输出概率或规则校验后得出。

**置信度与 UI 策略**：

```python
class DocumentClassificationResult(BaseModel):
    document_type: DocumentType
    procurement_method: ProcurementMethod
    confidence: float           # 0.0 - 1.0
    method: str                 # rule / embedding / llm
```

- `confidence ≥ 0.85`：直接采用，进入下一步。
- `0.70 ≤ confidence < 0.85`：UI 预填推荐类型，用户可一键确认或修改。
- `confidence < 0.70`：UI 强制要求用户选择文档类型；未选择前不进入解析流程。

**示例**：一份标题为「采购文件」、无目录、正文含「磋商邀请」「响应文件格式」的文档：
- 规则层可能只识别为 `TENDER / OTHER`，confidence 0.60。
- Embedding 层与「竞争性磋商文件」模板相似度高，提升到 `TENDER / COMPETITIVE_NEGOTIATION`，confidence 0.82。
- UI 提示用户确认，用户可改为「公开招标」或保持推荐。

---

## 4. 招标文件解析缺口

### 4.1 评分表与用户需求书分离

**真实样本**：样本 1 的评分表位于「第二部分 响应供应商须知」末尾，独立于「第三部分 用户需求书」。评分表中包含大量评分细则，例如：

> 对采购需求 1.1.5 服务工具要求中标注"▲"的重要技术参数的响应情况进行评审：全部参数响应为"正偏离"或"符合"的得 24 分，每出现一项响应为"负偏离"或不响应的，扣 3 分。

**缺口**：当前 `TableRowExtractor` 按表格类型提取，但并未把「评分表」单独识别为需求来源，也未把评分项作为 `RequirementItem` 的 `constraint_type=SCORING`。

**设计补充**：
- 在 `DocumentSectionType` 中新增 `SCORING_TABLE`。
- 在表格分类策略中识别评分表（关键词：评分表、评分标准、评审项目、分值、最高分值）。
- 提取评分表每一行为 `RequirementItem`：
  - `category = RequirementCategory.SCORING`
  - `constraint_type = ConstraintType.SCORING`
  - `max_score` 字段记录最高分值（新增字段）。
  - `evaluation_criteria` 字段记录评分细则（新增字段）。
- 对无法拆分为单条的聚合评分规则（如「全部响应得 24 分，每负偏离一项扣 3 分」），新增 `EvaluationRule` 模型：
  ```python
  class EvaluationRule(BaseModel):
      rule_text: str                     # 原始评分规则文本
      base_score: Optional[float]        # 满分
      deduction_per_item: Optional[float]
      applies_to_requirement_ids: List[str]  # 关联的需求条目 ID
      confidence: float                  # 规则解析置信度
  ```
- Phase 1/2 目标：识别评分表区域、提取原子评分项、保留聚合规则文本。
- Phase 3：用 LLM 或更复杂的规则解析聚合规则，关联到具体需求条目，并计算潜在失分。

**示例**：
- 原子评分项：「项目经理具备 PMP 证书，得 6 分」→ 提取为 `RequirementItem`，`max_score=6`。
- 聚合规则：「对 1.1.5 服务工具要求中标注『▲』的参数，全部响应得 24 分，每负偏离一项扣 3 分」→ 提取为 `EvaluationRule`，`base_score=24`，`deduction_per_item=3`，关联到 1.1.5 中所有带 `▲` 的条目。

### 4.2 响应文件格式模板应作为格式/结构规则

**真实样本**：样本 1 的第四部分是「响应文件格式」，包含响应函、授权书、资格声明、中小企业声明函等模板。样本 3 第六章是「响应文件格式与要求」。

**缺口**：当前 extractor 把响应文件格式模板当作普通段落提取，可能产生噪声条目，也未把它们识别为「投标文件中应出现的章节」。

**设计补充**：
- 在 `DocumentSectionType` 中新增 `RESPONSE_TEMPLATE`。
- 提取模板中的「章节标题」和「必填标记」，生成 `FormatRequirement`（新增模型）：
  - 期望章节标题
  - 是否必须
  - 引用来源（哪条资格要求）
- 该模型暂时不用于格式合规检查（本次范围外），但用于生成「证明材料索引表」和「偏离表」中的「需提供的证明材料」推断。

### 4.3 `★`/`▲` 标记未提升为约束类型

**真实样本**：样本 1 用户需求书明确说明：

> 标注"★"条款的，投标人必须作出响应，如作负偏离响应或不作响应的，视为无效投标处理；凡加"▲"的地方均被视为重要的技术指标要求或性能要求。

**缺口**：当前 `ConstraintType` 有 `MANDATORY`、`SCORING`、`RECOMMENDED`、`INFO`，但没有对应 `★`/`▲` 的语义。

**设计补充**：
- 保留现有枚举，但在解析阶段把 `★` 映射为 `MANDATORY`，把 `▲` 映射为 `SCORING`。
- 在 `RequirementItem` 中保留原始标记 `raw_marker: Optional[str]`（新增字段），便于导出时显示「★ 强制项」「▲ 评分项」。

### 4.4 需求分散在多个章节

**真实样本**：
- 样本 1：需求在「第二部分 响应供应商须知」的评分表和「第三部分 用户需求书」。
- 样本 3：需求在「第二章 采购需求」和「第四章 评审」。

**缺口**：当前 `CompositeExtractor` 主要基于标题和表格提取，对「章节边界」的利用不足，可能漏掉评分表中的评分项。

**设计补充**：
- 在 `DocumentSection` 中明确 `section_type`（INVITATION / INSTRUCTION / REQUIREMENT / SCORING / TEMPLATE / CONTRACT）。
- `CompositeExtractor` 按 `section_type` 选择提取策略：
  - `REQUIREMENT`：使用 Heading + Numbered + Table 提取。
  - `SCORING`：使用评分表策略提取。
  - `TEMPLATE`：提取格式模板标题，不生成需求条目。

---

## 5. 投标文件解析缺口

### 5.1 文档类型与期望结构检测

**真实样本**：
- 样本 2：报名文件，目录只有营业执照、法人证明、承诺函、截图。
- 样本 5：报名文件，目录却包含报价单、技术方案、资质证明、合同业绩。
- 样本 4：响应文件，目录明确分资格性文件、商务部分、技术部分、价格部分。

**缺口**：`bid_splitter` 当前按「商务/技术/价格/其他」分区，但未识别文档是报名文件还是响应文件，也未根据类型校验期望结构。

**设计补充**：
- `bid_splitter` 输出增加 `bid_document_type`。
- 根据 `bid_document_type` 生成期望章节列表：
  - `BID_REGISTRATION`：至少含营业执照、法人证明/授权、资格承诺、平台/信用截图。
  - `BID_RESPONSE`：应含资格性文件、商务部分、技术部分、价格部分。
- 缺失期望章节时生成「结构缺失」类 Issue（不阻断，作为风险提示）。

### 5.2 响应表/偏离表作为应答载体

**真实样本**：
- 样本 1 提供「项目服务工具技术响应偏离表」模板。
- 样本 4 包含「商务条款响应表」。
- 样本 5 的报价单即是一个价格响应表。

**缺口**：`semantic_matcher` 以段落为匹配单元，对表格化应答利用不足。当投标方把应答填入「偏离情况」「响应内容」列时，系统可能匹配不到。

**设计补充**：
- 在 `bid_splitter` 中识别响应表/偏离表（关键词：响应表、偏离表、应答表、技术响应、商务响应、报价表）。
- 对表格进行结构化解析：
  - 表头识别：序号、指标项、技术要求、响应内容、偏离情况、证明材料。
  - 把「响应内容/偏离情况」列作为该需求的首选匹配文本。
- 在 `semantic_matcher` 中，对表格化应答段落提高匹配权重。

---

## 6. 内容专项校验缺口

### 6.1 资格截图类型识别（OCR 校验）

**真实样本**：样本 2 包含多张截图：
- 信用中国：失信被执行人、重大税收违法失信主体、政府采购严重违法失信行为记录名单、严重失信主体名单查询。
- 中国政府采购网：政府采购严重违法失信行为信息记录。
- 广东省政府采购智慧云平台电子卖场入驻截图。

样本 5  additionally 要求：广东省政府采购网智慧云平台电子卖场定点集市信息技术服务供应商资质。

样本 4 additionally 包含：全国认证认可信息公共服务平台查询截图。

**缺口**：`ocr_checker` 目前做通用关键词覆盖，但无法识别「这是哪一类截图」「是否缺少某类截图」。

**设计补充**：
- 新增 `screenshot_type` 分类模型：
  - `CREDIT_CHINA_OVERDUE_EXECUTOR`
  - `CREDIT_CHINA_TAX_VIOLATION`
  - `CREDIT_CHINA_GOV_PROCUREMENT_VIOLATION`
  - `CREDIT_CHINA_SERIOUS_DISHONEST`
  - `GOV_PROCUREMENT_NETWORK`
  - `GUANGDONG_ELECTRONIC_MARKET`
  - `CERTIFICATION_RECOGNITION_PLATFORM`
  - `OTHER`
- 识别逻辑：结合 OCR 文本、网页标题栏、URL 栏、页面特征文字。
- 校验规则：
  - 根据招标文件要求，检查是否所有要求的截图类型都已提供。
  - 检查截图中的查询主体是否与被授权人/投标人名称一致。

> 实现难度：中。依赖网页标题栏、URL 栏、页面特征文字做规则识别；新平台截图模板可能未覆盖，需预留扩展入口。

### 6.2 证书有效期与范围校验

**真实样本**：
- 样本 4 列出 ISO9001、ISO20000、ISO27001、GB/T27922 售后服务认证等证书。
- 样本 5 列出 CCRC 安全集成/安全运维/风险评估/应急处理、ISO 系列证书。
- 样本 6 要求营业执照必须有年审、产品代理证书必须提供。

**缺口**：当前 OCR 只能识别证书名称，无法识别证书有效期、认证范围、证书编号。

**设计补充**：
- 新增 `certificate_checker`：
  - 识别证书类型（ISO/CCRC/CISP/等保/软著/专利等）。
  - 识别证书有效期（起止日期），检查是否覆盖投标有效期。
  - 识别认证范围，检查是否覆盖项目所需范围（如 GB/T27922 范围须包括「网络信息安全集成」）。
  - 识别证书主体，检查是否与投标人名称一致。
- 对「全国认证认可信息公共服务平台查询截图」做 OCR，提取证书状态（有效/注销/撤销）。

> 实现难度：中高。证书版式差异大，有效期与认证范围字段位置不固定；建议先覆盖常见 ISO/CCRC/CISP 模板，低置信度时标记复核。

### 6.3 人员-证书-社保证明三元组校验

**真实样本**：样本 1 评分表要求：

> 需提供证书或证明材料扫描件及项目经理近 6 个月内任意月份与之匹配的社保证明。

样本 4 的「拟投入本项目的人员资质」列出项目经理、项目团队，并附社会保险参保人员证明。

**缺口**：当前设计把「人员」「证书」「社保」作为独立关键词检查，未建立三者关联。

**设计补充**：
- 新增 `personnel_checker`：
  - 从投标文件中提取人员名单（项目经理、技术负责人、技术人员）。
  - 对每个人员，识别其持有的证书（CISP、PMP、CCRC-DSO 等）。
  - 检查是否提供该人员的社保证明（近 6 个月任意月份）。
  - 对招标文件中明确要求的人员+证书组合，生成「缺失人员」「缺失证书」「缺失社保证明」三类 Issue。

> 实现难度：中高。人员-证书-社保三元组关联依赖 OCR 质量；建议先做「人员清单存在性」和「证书存在性」校验，关联校验作为增强。

### 6.4 近三年同类业绩合同校验

**真实样本**：样本 1 评分表要求：

> 根据投标人提供自 2023 年 1 月 1 日至今已完成的同类业绩（包括数据安全分类分级服务、数据安全风险评估服务、个人信息安全影响评估服务）合同复印件，每提供一份 2 分，最高 10 分。须提供合同关键页，关键页包括采购内容、签订日期、双方盖章等。

样本 5 提供了一份「近三年同类项目的采购合同」汇总表，并附合同图片。

**缺口**：当前设计未校验业绩合同的时间范围、金额、采购内容、签章。

**设计补充**：
- 新增 `performance_checker`：
  - 从投标文件中提取「同类业绩表」或「合同汇总表」。
  - 对每份合同图片 OCR，提取：
    - 签订日期，检查是否在招标文件要求的近三年范围内。
    - 合同金额，检查是否与业绩表一致。
    - 采购内容/项目名称，检查是否属于「同类业绩」。
    - 双方盖章页，检查是否存在盖章（通过 OCR 检测「公章」「合同专用章」等字样或圆形印鉴轮廓）。
  - 生成 Issue：合同时间不符、金额不符、内容不匹配、缺少签章页。

> 实现难度：中高。合同图片 OCR 质量不稳定，签章检测困难；建议先从业绩汇总表读取金额/日期，合同图片仅做交叉验证；签章检测降级为「是否含盖章页」弱检测。

### 6.5 承诺函识别与响应校验

**真实样本**：
- 样本 2：政府采购法 22 条承诺、无失信记录承诺、无关联关系/不转包分包承诺。
- 样本 5：不外包第三方服务公司承诺、保密承诺、服务团队承诺、实施要求承诺、售后承诺。

**缺口**：当前把承诺函当作普通段落处理，无法识别「承诺了哪类要求」。

**设计补充**：
- 新增 `commitment_checker`：
  - 识别承诺函标题/致函对象，分类为：
    - `GOVERNMENT_PROCUREMENT_LAW_22`
    - `NO_SUBCONTRACT`
    - `NO_ASSOCIATION`
    - `NO_OUTSOURCE`
    - `CONFIDENTIALITY`
    - `SERVICE_TERM`
    - `DATA_SECURITY`
    - `OTHER`
  - 把招标文件中「要求提供承诺函」的条款与投标文件中识别到的承诺函类型匹配。
  - 检查承诺函是否盖章、日期是否在有效期内。

> 实现难度：低-中。承诺函标题/致函对象表述多样，但可通过关键词规则覆盖主要类型；盖章检测依赖 OCR 识别印章或「盖章」字样。

### 6.6 商务条款响应校验

**真实样本**：样本 3 第二章「主要商务要求」包含：
- 标的提供时间：自合同签订之日起 2 个月内完成项目并发起验收程序。
- 付款方式：验收通过次日起 30 日内一次性支付 100%。
- 标的提供地点：广东医科大学附属第二医院。
- 验收要求：4 条细则。

样本 4 包含「商务条款响应表」。

**缺口**：当前 `consistency_checker` 主要处理技术参数和时间，对付款方式、交付地点、验收要求等商务条款缺少专项识别。

**设计补充**：
- 在 `consistency_checker` 中新增商务条款规则：
  - 识别「付款方式」「验收要求」「交付地点」「服务期限」「质保期」等关键词。
  - 检查投标文件是否在商务条款响应表或正文中明确响应。
  - 对时间类商务条款（如 2 个月、30 日）做数值校验。

---

## 7. 跨文档一致性缺口

### 7.1 当前已实现

产品愿景文档中列出 Must Have：
- 项目名称/编号一致性校验
- 投标人名称一致性校验

### 7.2 需要扩展的跨文档一致性

| 检查项 | 说明 | 真实样本佐证 |
|---|---|---|
| 投标有效期 | 招标文件要求 90 天；响应函中应声明 90 天 | 样本 1、样本 4 |
| 合同履行期限/服务期限 | 招标文件要求 2 个月或指定日期前完成；投标应响应 | 样本 3、样本 5 |
| 付款方式 | 招标文件要求验收后 30 日付 100%；投标应无异议或明确响应 | 样本 3 |
| 交付地点 | 招标文件指定医院名称；投标应一致 | 样本 3 |
| 报价有效期 | 与投标有效期通常一致，但需单独校验 | 样本 4 |
| 授权有效期 | 法定代表人授权书有效期应覆盖投标有效期 | 样本 2 授权书有效期 2026-07-15 至 2027-04-21 |
| 授权代表一致性 | 授权委托书中的被授权人、响应函签名代表、项目联系人应一致 | 样本 2 被授权人钟嘉丽，项目联系人也应为钟嘉丽 |

### 7.3 设计补充

扩展 `business_info_checker` 为 `cross_document_checker`：

```python
class CrossDocumentCheck(str, Enum):
    PROJECT_NAME = "project_name"
    PROJECT_NUMBER = "project_number"
    BIDDER_NAME = "bidder_name"
    BID_VALIDITY = "bid_validity"
    CONTRACT_PERFORMANCE_TERM = "contract_performance_term"
    PAYMENT_METHOD = "payment_method"
    DELIVERY_LOCATION = "delivery_location"
    AUTHORIZATION_VALIDITY = "authorization_validity"
    AUTHORIZED_REPRESENTATIVE = "authorized_representative"
```

- 从招标文件提取：项目信息、有效期、付款/交付/验收要求。
- 从投标文件提取：响应函、授权书、报价函、商务条款响应表中的对应信息。
- 生成「跨文档不一致」Issue，定位到两份文档的具体段落。

> 实现难度：中。难点在于从两类文档中稳定提取关键信息；建议与 `document_type_classifier` 配合，先识别文档类型再选择提取规则。

---

## 8. 设计补充方案总览

### 8.1 新增模块

| 模块 | 职责 | 位置 |
|---|---|---|
| `document_type_classifier` | 识别招标/投标/报名/产品解决方案文档类型及采购方式 | `src/proofreader/parsers/document_type_classifier.py` |
| `date_normalizer` | 统一解析日期、期间、相对时间表达 | `src/proofreader/utils/date_normalizer.py` |
| `screenshot_checker` | 识别截图类型、校验截图主体与完整性 | `src/proofreader/checkers/screenshot_checker.py` |
| `certificate_checker` | 识别证书类型、有效期、范围、主体 | `src/proofreader/checkers/certificate_checker.py` |
| `personnel_checker` | 人员-证书-社保证明三元组校验 | `src/proofreader/checkers/personnel_checker.py` |
| `performance_checker` | 近三年同类业绩合同校验 | `src/proofreader/checkers/performance_checker.py` |
| `commitment_checker` | 承诺函类型识别与响应校验 | `src/proofreader/checkers/commitment_checker.py` |
| `cross_document_checker` | 招标与投标文件关键信息一致性 | `src/proofreader/checkers/cross_document_checker.py` |

**date_normalizer 说明**：
- 负责统一解析所有时间表达，供 `certificate_checker`、`performance_checker`、`personnel_checker`、`cross_document_checker`、`consistency_checker` 调用。
- 支持格式：
  - 绝对日期：2026年7月15日、2026.07.15、2026/07/15、二〇二六年七月十五日
  - 日期范围：2026-07-15 至 2027-04-21
  - 相对期间：近三年、近6个月、90天内、自合同签订之日起2个月
- 输出：
  - `NormalizedDate(date, precision, is_relative)`
  - `NormalizedPeriod(start, end, description)`
- 无法解析时返回 `None` 并附带原始文本，触发「无法识别即提示复核」原则。

### 8.2 扩展模块

| 模块 | 扩展内容 |
|---|---|
| `docx_parser.py` | 输出 `document_type` 与 `procurement_method`；识别评分表、响应文件格式模板章节 |
| `composite_extractor.py` | 按章节类型选择提取策略；新增评分表提取路径 |
| `table_strategies.py` | 新增 `ScoringTableStrategy`、`ResponseTableStrategy`、`PerformanceTableStrategy` |
| `bid_splitter.py` | 识别报名文件/响应文件；识别响应表/偏离表；按期望结构校验 |
| `semantic_matcher.py` | 对表格化应答段落提高权重；支持偏离表「响应内容」列作为匹配源 |
| `consistency_checker.py` | 增加商务条款（付款、交付、验收、服务期限）校验 |
| `exporters/excel_exporter.py` | 新增 Issue 类型：结构缺失、截图缺失、证书过期、人员缺失、业绩不符、承诺缺失 |
| `exporters/bid_annotator.py` | 支持上述新 Issue 类型的高亮与批注 |

### 8.3 数据模型扩展

```python
class RequirementItem(BaseModel):
    # 已有字段 ...
    raw_marker: Optional[str] = None          # "★" / "▲"
    max_score: Optional[float] = None         # 评分项最高分值
    evaluation_criteria: Optional[str] = None # 评分细则

class EvaluationRule(BaseModel):
    rule_text: str                            # 原始评分规则文本
    base_score: Optional[float] = None        # 满分
    deduction_per_item: Optional[float] = None
    applies_to_requirement_ids: List[str] = []  # 关联的需求条目 ID
    confidence: float = 1.0                   # 规则解析置信度

class FormatRequirement(BaseModel):
    title: str
    required: bool
    source_requirement_id: Optional[str]

class EvidenceLocation(BaseModel):
    evidence_type: str                        # screenshot/certificate/contract/commitment
    page: Optional[int]
    section_title: Optional[str]
    confidence: float

class DocumentClassificationResult(BaseModel):
    document_type: DocumentType
    procurement_method: ProcurementMethod
    confidence: float
    method: str                               # rule / embedding / llm

class NormalizedDate(BaseModel):
    date: date
    precision: str                            # DAY / MONTH / YEAR
    is_relative: bool = False
    raw_text: str

class NormalizedPeriod(BaseModel):
    start: Optional[date]
    end: Optional[date]
    description: str
    raw_text: str
```

### 8.4 与 7-28 框架的接口衔接

为避免新增能力与既有 pipeline 脱节，每个新模块需遵循以下接口契约：

| 模块 | 调用方 | 输入 | 输出 | 触发时机 |
|---|---|---|---|---|
| `document_type_classifier` | `docx_parser` | `Document` 对象（标题、目录、前 N 段文本） | `DocumentClassificationResult` | 解析阶段 |
| `screenshot_checker` | `Proofreader.pipeline` | `RequirementItem` + `List[EmbeddedImage]`（已 OCR） | `List[Issue]` | OCR 检查阶段 |
| `certificate_checker` | `Proofreader.pipeline` | `RequirementItem` + `List[EmbeddedImage]`（已 OCR） | `List[Issue]` | OCR 检查阶段 |
| `personnel_checker` | `Proofreader.pipeline` | 招标人员要求 `RequirementItem` + 投标文本块 + 图片 OCR 结果 | `List[Issue]` | 一致性检查阶段 |
| `performance_checker` | `Proofreader.pipeline` | 招标业绩要求 `RequirementItem` + 投标表格 + 合同图片 OCR | `List[Issue]` | 一致性检查阶段 |
| `commitment_checker` | `Proofreader.pipeline` | 招标承诺要求 `RequirementItem` + 投标文本块 | `List[Issue]` | 一致性检查阶段 |
| `cross_document_checker` | `Proofreader.pipeline` | 招标文件关键信息字典 + 投标文件关键信息字典 | `List[Issue]` | 商务信息检查阶段 |

**Issue 类型映射**：

```python
class IssueType(str, Enum):
    # 已有 ...
    MISSING_SCREENSHOT = "missing_screenshot"
    SCREENSHOT_MISMATCH = "screenshot_mismatch"
    CERTIFICATE_EXPIRED = "certificate_expired"
    CERTIFICATE_SCOPE_MISMATCH = "certificate_scope_mismatch"
    CERTIFICATE_SUBJECT_MISMATCH = "certificate_subject_mismatch"
    MISSING_PERSONNEL = "missing_personnel"
    MISSING_CERTIFICATE_FOR_PERSON = "missing_certificate_for_person"
    MISSING_SOCIAL_PROOF = "missing_social_proof"
    PERFORMANCE_TIME_MISMATCH = "performance_time_mismatch"
    PERFORMANCE_AMOUNT_MISMATCH = "performance_amount_mismatch"
    PERFORMANCE_CONTENT_MISMATCH = "performance_content_mismatch"
    PERFORMANCE_MISSING_SEAL = "performance_missing_seal"
    MISSING_COMMITMENT = "missing_commitment"
    COMMITMENT_NOT_STAMPED = "commitment_not_stamped"
    CROSS_DOCUMENT_INCONSISTENT = "cross_document_inconsistent"
```

**数据流**：

```
招标 Word
  → docx_parser + document_type_classifier
  → CompositeExtractor（Heading / Numbered / Table / Scoring）
  → SemanticDeduplicator
  → RequirementRepository（已确认需求）

投标 Word
  → docx_parser + document_type_classifier
  → bid_splitter（按类型与章节拆分）
  → semantic_matcher（含响应表优先匹配）
  → consistency_checker / table_checker / typo_checker / ocr_checker
  → screenshot_checker / certificate_checker / personnel_checker
  → performance_checker / commitment_checker / cross_document_checker
  → exporters（Excel / 标注 Word / 偏离表 / 证明材料索引表）
```

### 8.5 OCR/LLM 技术边界与准确率评估

新增 checker 大量依赖 OCR，必须明确技术边界，防止低质量识别结果导致误报或用户不信任。

| 能力 | 依赖技术 | 预期准确率 | 置信度阈值 | Fallback | 默认开关 |
|---|---|---|---|---|---|
| 截图类型识别 | OCR + 规则 | 高（≥ 85%） | 0.80 | 低置信度标记「需人工复核」 | 开 |
| 证书有效期提取 | OCR + 日期解析 | 中（70-85%） | 0.75 | 低置信度不判过期，仅提示「未识别到有效期」 | 开 |
| 证书认证范围提取 | OCR + NER/模板 | 中（65-80%） | 0.70 | 低置信度不判范围不符 | 开 |
| 证书主体提取 | OCR + 名称匹配 | 高（≥ 85%） | 0.80 | 低置信度标记复核 | 开 |
| 合同签订日期提取 | OCR + 日期解析 | 中（70-85%） | 0.75 | 无法识别时提示「需人工确认」 | 开 |
| 合同金额提取 | OCR + 金额解析 | 中（70-85%） | 0.75 | 与业绩表不一致且低置信时标记复核 | 开 |
| 合同签章页检测 | OCR/图像 | 低（50-65%） | 0.60 | 仅检测「是否含盖章页」关键词，不做章印真实性验证 | 开 |
| 人员姓名-证书关联 | OCR + 规则 | 中（65-80%） | 0.70 | 低置信度标记复核 | 开 |
| 社保证明期间提取 | OCR + 日期范围解析 | 中（70-85%） | 0.75 | 无法识别时提示复核 | 开 |
| 承诺函类型识别 | 文本分类/规则 | 高（≥ 85%） | 0.80 | 低置信度归为 OTHER | 开 |
| 复杂语义判断（如方案是否完整） | LLM | 中（依模型而定） | — | 默认关闭；仅在本地/安全模型下可选开启 | 关 |

**LLM 使用边界**：
- 默认关闭，所有设计优先使用规则 + OCR。
- 如用户启用 LLM，仅用于：
  - 判断复杂技术方案段落是否实质回应了需求。
  - 辅助识别证书/截图类型（当规则无法覆盖新模板时）。
- LLM 输出必须有「模型判断」标签，明确告知用户非规则判定，需重点复核。
- 敏感内容（项目细节、价格、人员身份证）不上传外部 API；LLM 必须在本地或用户指定的安全环境运行。

**准确率评估方法**：
- 每类 OCR 能力上线前，在 20-50 份真实样本上统计：真阳性、假阳性、假阴性、未识别率。
- 准确率未达到表中预期时，该 checker 降级为「辅助提示」，不生成致命/高 Issue。
- 建立「误报反馈」机制：用户在 UI 上标记「此 Issue 是误报」，反馈数据用于优化阈值。

### 8.6 各 checker 实现难度与风险

| Checker | 难度 | 主要风险 | 建议阶段 |
|---|---|---|---|
| `document_type_classifier` | 低 | 标题关键词规则覆盖不全 | Phase 1 |
| 评分表提取 | 中 | 评分表格式多样，分值列位置不固定 | Phase 1 |
| `screenshot_checker` | 中 | 新平台截图模板未覆盖 | Phase 2 |
| `certificate_checker` | 中高 | 证书版式多，有效期/范围字段位置差异大 | Phase 2 |
| `personnel_checker` | 中高 | 人员-证书-社保三元组关联依赖 OCR 质量 | Phase 3 |
| `performance_checker` | 中高 | 合同图片 OCR 质量不稳定，签章检测困难 | Phase 3 |
| `commitment_checker` | 低-中 | 承诺函标题表述多样 | Phase 3 |
| `cross_document_checker` | 中 | 需要先从两类文档中稳定提取关键信息 | Phase 2 |

**特别说明**：
- **签章检测**：不做印章真伪鉴别，仅做「是否存在盖章页」的弱检测。强签章检测需要图像分割与印章识别，准确率难以保证，建议作为后续研究项。
- **认证范围匹配**：先覆盖 ISO9001/ISO20000/ISO27001/CCRC/CISP 等常见证书模板；范围匹配采用关键词覆盖（如「网络信息安全集成」），不做完整的语义推理。
- **合同金额/日期**：优先从业绩汇总表读取，合同图片 OCR 作为交叉验证；两者不一致时标记复核。

---

## 9. MoSCoW 与 Roadmap 更新

### 9.1 产品愿景文档 MoSCoW 调整建议

把以下条目从 **Should Have** 提升为 **Must Have**，因为真实文档已证明它们是高频废标风险点：

| 原位置 | 能力 | 调整 |
|---|---|---|
| Should Have | 营业执照/业绩/财务/纳税社保深度校验 | → Must Have（业绩合同、人员社保） |
| Should Have | 目录页码一致性校验 | 保持 Should Have（本次不实现） |
| Could Have | 自定义检查规则 | 保持 Could Have |

新增 Must Have：

- [ ] 文档类型自动检测（招标/投标/报名/产品方案）。
- [ ] 采购方式识别（比选/磋商/招标/遴选/产品报名）。
- [ ] 评分表作为需求来源提取。
- [ ] `★`/`▲` 标记识别并映射为强制/评分约束。
- [ ] 资格截图类型识别（信用中国 4 类、政府采购网、云平台、认证认可平台）。
- [ ] 证书有效期与认证范围校验。
- [ ] 人员-证书-社保证明三元组校验。
- [ ] 近三年同类业绩合同时间/金额/内容/签章校验。
- [ ] 承诺函类型识别与匹配。
- [ ] 跨文档一致性扩展（有效期、服务期限、付款方式、交付地点、授权代表）。

新增 Should Have：

- [ ] 响应表/偏离表结构化解析与优先匹配。
- [ ] 响应文件格式模板提取（作为证明材料推断来源）。
- [ ] 产品报名表/产品解决方案专项处理。

### 9.2 实施顺序建议

**Phase 1：文档类型与招标解析增强**
1. 实现 `document_type_classifier`（规则 + embedding + LLM 兜底，输出 confidence）。
2. 实现 `date_normalizer`（统一日期/期间解析）。
3. 扩展 `docx_parser` 识别评分表、响应文件格式模板。
4. 在 `CompositeExtractor` 中接入评分表提取策略；保留聚合评分规则为 `EvaluationRule`。
5. 在 `RequirementItem` 中增加 `raw_marker`、`max_score`、`evaluation_criteria`。

**Phase 2：投标内容专项校验**
1. 扩展 `bid_splitter` 识别响应表/偏离表。
2. 实现 `screenshot_checker`。
3. 实现 `certificate_checker`。
4. 实现 `cross_document_checker`（扩展商务信息校验）。

**Phase 3：复杂关系校验与聚合规则解析**
1. 实现 `personnel_checker`。
2. 实现 `performance_checker`。
3. 实现 `commitment_checker`。
4. 用 LLM 或复杂规则解析 `EvaluationRule`，关联到具体需求条目并计算潜在失分。
5. 更新导出器支持新 Issue 类型。

---

## 10. 关键设计原则重申

1. **宁可误报，不可漏报**：强制项（`★`）和人员/证书/业绩类证明材料必须高召回。
2. **人机协同**：截图类型、证书有效期等 OCR 结果必须有置信度，低置信度时标记为「需人工复核」而不是直接判定失败。
3. **无法识别即提示复核，不静默跳过**：任何 checker 在无法识别证据时，必须生成 `UNRECOGNIZED_EVIDENCE` Issue 或等效提示，不允许直接 `return []` 静默跳过。严重级别按需求约束类型区分：强制项为高/致命，评分项为中，普通建议项为低。
4. **可解释性**：每个 Issue 必须定位到招标文件条款、投标文件位置、判断依据（如「合同签订日期 2022-05-10，不在 2023-01-01 至今范围内」）。
5. **渐进式落地**：Phase 1 先解决「不知道看什么文档」和「评分项漏提取」问题；Phase 2/3 再解决复杂的图文关系校验。

---

## 11. 附录：典型 Issue 示例（来自样本）

| Issue 类型 | 需求来源 | 投标位置 | 期望行为 |
|---|---|---|---|
| 缺少信用中国截图 | 样本 1 资格要求第 3 条 | 样本 2 截图区 | 检测到缺少「严重失信主体名单查询」截图 |
| 证书过期 | 样本 1 评分表项目经理 CISP 证书 | 样本 4 人员资质 | 检测到 CISP 证书有效期不覆盖投标日期 |
| 业绩时间不符 | 样本 1 评分表「2023-01-01 至今」 | 样本 5 合同表 | 某合同签订日期 2022-05-10，触发时间不符 |
| 授权代表不一致 | 样本 1 授权委托书要求 | 样本 2 授权书、响应函 | 授权书被授权人为钟嘉丽，响应函签名代表为空/不一致 |
| 缺少社保证明 | 样本 1 评分表项目经理要求 | 样本 4 项目经理资质 | 未找到冯志君近 6 个月社保证明 |
| 商务条款未响应 | 样本 3 付款方式 30 日内 100% | 样本 4 商务条款响应表 | 响应表未填写付款方式或填写不一致 |
| 技术响应表未填 | 样本 1 服务工具要求 15 项 | 样本 5 技术参数应答 | 检测到 15 项中某几项未在响应表/正文中应答 |
| 缺少平台资质 | 样本 5 服务商资格要求 | 样本 5 资质证明 | 未找到「广东省政府采购网智慧云平台电子卖场定点集市信息技术服务供应商资质」截图 |

---

## 12. 待后续补充（本次范围外）

- 格式合规检查：封面、连续页码、A4 规格、正副本份数、签字盖章、密封要求。这些规则在医院采购中非常具体，但依赖版式/版面分析，建议作为单独一期「版式合规 checker」实现。
- 招标文件澄清/修改版本管理。
- 多轮报价（磋商/谈判）的报价版本对比。
- SaaS 化与多人协作评审。
