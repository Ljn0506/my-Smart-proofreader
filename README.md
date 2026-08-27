# 智能文档校对器

针对 Word 投标文件与需求文件进行自动校对，发现内容不一致、偏离、缺失、错别字等问题，并以三栏对照方式展示结果。

查看最新变更记录请见 [`CHANGELOG.md`](CHANGELOG.md)。

## 功能特性

- **Word 解析**：支持 `.docx` / `.doc` 段落、标题、表格提取（.doc 依赖 LibreOffice 转换），采用单次遍历解析并自动生成段落类型、标题层级与章节结构
- **文档类型识别**：自动区分采购需求文件、投标文件等招标文档类型，并给出规则化置信度
- **多文件批量校对**：需求文件与投标文件均支持多选上传；系统先梳理合并全部需求文件，再基于全部需求逐项校对每个投标文件
- **需求条目提取**：自动识别编号项、标题项、表格行；支持组合提取器与语义去重
- **评分项提取**：从表格中抽取原子评分项与聚合评分规则（`EvaluationRule`），供后续评分分析使用（尚未接入校对流水线）
- **日期规范化**：将中文绝对日期、相对周期与日期范围统一归一化（已提供工具函数，流水线集成待完成）
- **投标文件分段**：自动识别商务、技术、价格三部分
- **内容一致性检查**：技术参数、服务期限、交付时间等偏离检测
- **错别字检查**：基于常见错词表和单位规则
- **截图 OCR 检查**：提取图片文字并与需求关键词匹配
- **项目级需求库**：基于 JSON 的 `RequirementRepository`（pipeline 集成与 UI 入口参见 `TODOS.md`）
- **三栏可视化**：需求文件、投标文件、问题列表对照展示

## 快速开始

```bash
# 1. 进入项目目录
cd /Users/ljn/smart-proofreader

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 启动桌面应用
./run.sh
```

启动后，在浏览器中打开 http://localhost:8501 使用。

## 运行测试

```bash
# 1. 进入项目目录并激活虚拟环境
cd /Users/ljn/smart-proofreader
source .venv/bin/activate

# 2. 运行全部测试（pytest + 旧版集成测试）
./run_tests.sh
```

如需生成模拟测试文档：

```bash
PYTHONPATH=src python tests/generate_sample_docs.py
```

## 项目结构

```
smart-proofreader/
├── src/proofreader/
│   ├── parsers/          # docx 解析与文档类型识别
│   ├── extractors/       # 需求提取、投标分段、评分项提取
│   ├── matchers/         # 语义匹配
│   ├── checkers/         # 一致性/错别字/OCR 检查
│   ├── models/           # 数据模型与枚举
│   ├── repository/       # 项目级需求库（JSON 持久化）
│   ├── utils/            # 日期规范化等工具
│   ├── ui/               # Streamlit 界面
│   └── pipeline.py       # 流程编排
├── tests/                # 测试脚本与样例文档
├── tests-pytest/         # pytest 测试套件
├── data/sample-docs/     # 模拟测试文档
├── requirements.txt
├── run.sh
├── run_tests.sh
└── README.md
```

## 技术栈

- Python 3.9+
- Streamlit（桌面 UI）
- python-docx（Word 解析）
- scikit-learn（TF-IDF 语义匹配）
- easyocr（截图 OCR）
- pydantic（数据模型校验）
- openpyxl（Excel 报告导出）

## 相关文档

- 产品构思、框架设计与接口对齐文档见 [`docs/superpowers/specs/`](docs/superpowers/specs/)。
- 实施计划与后续路线图见 [`docs/superpowers/plans/`](docs/superpowers/plans/)。

## 注意事项

- OCR 首次运行会自动下载 easyocr 模型，需要联网。
- `.doc` 文件需要通过 LibreOffice（`soffice` / `libreoffice`）转换为 `.docx` 后解析，请确保系统已安装 LibreOffice。
- 所有文本校对逻辑在本地执行，不上传云端。
- 为防止畸形或超大文档导致内存耗尽，解析器和 OCR 对文档大小、图片尺寸与像素数做了上限保护。
