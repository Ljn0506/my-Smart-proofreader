"""pytest 共享 fixture。"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.pipeline import Proofreader


@pytest.fixture(scope="session")
def sample_docs_dir() -> Path:
    """返回样例文档目录。"""
    return Path(__file__).parent.parent / "data" / "sample-docs"


@pytest.fixture(scope="session")
def proofreader() -> Proofreader:
    """返回共享的 Proofreader 实例（OCR Reader 会被缓存）。"""
    return Proofreader()


@pytest.fixture(scope="session")
def sample_result(proofreader: Proofreader, sample_docs_dir: Path):
    """返回样例文档校对结果。"""
    return proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
