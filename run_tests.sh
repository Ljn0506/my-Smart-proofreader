#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate

# 自动检测虚拟环境二进制架构：先尝试原生导入 sklearn，失败则依次尝试 x86_64 / arm64。
if python -c "import sklearn" >/dev/null 2>&1; then
    PYTHON_PREFIX=()
elif /usr/bin/arch -x86_64 python -c "import sklearn" >/dev/null 2>&1; then
    PYTHON_PREFIX=("/usr/bin/arch" "-x86_64")
elif /usr/bin/arch -arm64 python -c "import sklearn" >/dev/null 2>&1; then
    PYTHON_PREFIX=("/usr/bin/arch" "-arm64")
else
    echo "无法以任何架构导入 sklearn，请检查虚拟环境。" >&2
    exit 1
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
