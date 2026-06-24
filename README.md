# 智能文档校对器

针对 Word 投标文件与需求文件进行自动校对，发现内容不一致、偏离、缺失、错别字等问题，并以三栏对照方式展示结果。

## 功能特性

- **Word 解析**：支持 `.docx` 段落、标题、表格提取
- **需求条目提取**：自动识别编号项、约束关键词、表格行
- **投标文件分段**：自动识别商务、技术、价格三部分
- **内容一致性检查**：技术参数、服务期限、交付时间等偏离检测
- **错别字检查**：基于常见错词表和单位规则
- **截图 OCR 检查**：提取图片文字并与需求关键词匹配
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

## 生成测试文档

```bash
source .venv/bin/activate
PYTHONPATH=src python tests/generate_sample_docs.py
PYTHONPATH=src python tests/test_pipeline.py
```

## 项目结构

```
smart-proofreader/
├── src/proofreader/
│   ├── parsers/          # docx 解析
│   ├── extractors/       # 需求提取、投标分段
│   ├── matchers/         # 语义匹配
│   ├── checkers/         # 一致性/错别字/OCR 检查
│   ├── ui/               # Streamlit 界面
│   └── pipeline.py       # 流程编排
├── tests/                # 测试脚本与样例文档
├── data/sample-docs/     # 模拟测试文档
├── requirements.txt
├── run.sh
└── README.md
```

## 技术栈

- Python 3.9+
- Streamlit（桌面 UI）
- python-docx（Word 解析）
- scikit-learn（TF-IDF 语义匹配）
- easyocr（截图 OCR）
- pycorrector（错别字检查）

## 注意事项

- OCR 首次运行会自动下载 easyocr 模型，需要联网。
- 所有文本校对逻辑在本地执行，不上传云端。
