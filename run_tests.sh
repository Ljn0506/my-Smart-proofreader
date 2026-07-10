#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

# 自动检测是否需要 arm64 架构前缀：
# 当前虚拟环境中的 sklearn 等包为 arm64 构建时，在 x86_64 shell 中直接运行会报架构不匹配。
# 先尝试直接导入 sklearn，失败则使用 /usr/bin/arch -arm64 作为前缀。
if python -c "import sklearn" >/dev/null 2>&1; then
    PYTHON_PREFIX=()
else
    PYTHON_PREFIX=("/usr/bin/arch" "-arm64")
fi

run_legacy_test() {
    PYTHONPATH=src "${PYTHON_PREFIX[@]}" python "$@"
}

echo "Running pytest..."
"${PYTHON_PREFIX[@]}" pytest

echo ""
echo "Running legacy tests..."
run_legacy_test tests/test_pipeline.py
run_legacy_test tests/test_consistency_multi.py
run_legacy_test tests/test_table_checker.py
run_legacy_test tests/test_verify_expected.py

echo ""
echo "All tests passed."
