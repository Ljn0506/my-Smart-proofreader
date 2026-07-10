"""pytest 风格的完整流程测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.pipeline import Proofreader, ProofreadResult


@pytest.fixture(scope="module")
def result(sample_result: ProofreadResult) -> ProofreadResult:
    return sample_result


def test_requirements_extracted(result: ProofreadResult) -> None:
    """应提取到 9 条需求。"""
    assert len(result.requirements) == 9


def test_bid_sections_split(result: ProofreadResult) -> None:
    """投标文件应被拆分为若干部分。"""
    assert len(result.bid_sections) >= 3


def test_consistency_issues_found(result: ProofreadResult) -> None:
    """应检出 7 处一致性/偏离问题（含修复后的并发用户数不一致）。"""
    assert len(result.consistency_issues) == 7
    assert any("1000" in issue.message and "800" in issue.message for issue in result.consistency_issues)


def test_typo_issues_found(result: ProofreadResult) -> None:
    """应检出至少 1 处错别字。"""
    assert len(result.typo_issues) >= 1
    assert any(typo.word == "架购" for typo in result.typo_issues)


def test_ocr_issues_found(result: ProofreadResult) -> None:
    """应检出至少 1 处截图 OCR 问题。"""
    assert len(result.ocr_issues) >= 1


def test_table_issues_count(result: ProofreadResult) -> None:
    """样例文档不含表格，表格问题应为 0。"""
    assert len(result.table_issues) == 0


def test_proofreader_runs_on_real_files(sample_docs_dir: Path, proofreader: Proofreader) -> None:
    """确保能直接对真实 docx 文件执行校对。"""
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    assert isinstance(result, ProofreadResult)
    assert result.requirement_doc.path.exists()
    assert result.bid_doc.path.exists()


def test_proofreader_runs_on_doc_files(sample_docs_dir: Path, proofreader: Proofreader) -> None:
    """确保能直接对真实 .doc 文件执行校对。"""
    req_doc_path = sample_docs_dir / "requirements.doc"
    if not req_doc_path.exists():
        pytest.skip("未找到 .doc 样例文件，跳过本测试")

    result = proofreader.proofread(
        req_doc_path,
        sample_docs_dir / "bid.docx",
    )
    assert isinstance(result, ProofreadResult)
    assert result.requirement_doc.path.suffix.lower() == ".doc"
    assert len(result.requirements) == 9
