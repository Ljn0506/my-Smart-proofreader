#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

# 自动检测是否需要 arm64 架构前缀：
# 当前虚拟环境中的 sklearn 等包为 arm64 构建时，在 x86_64 shell 中直接运行会报架构不匹配。
# 先尝试直接导入 sklearn，失败则使用 /usr/bin/arch -arm64 作为前缀。
if python -c "import sklearn" >/dev/null 2>&1; then
    PYTHONPATH=src streamlit run src/proofreader/ui/app.py
else
    PYTHONPATH=src /usr/bin/arch -arm64 streamlit run src/proofreader/ui/app.py
fi
