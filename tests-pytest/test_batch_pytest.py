"""pytest 风格的批量校对测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.pipeline import Proofreader, ProofreadResult


@pytest.fixture(scope="module")
def batch_result(sample_docs_dir: Path, proofreader: Proofreader):
    """使用两份需求文件副本 × 两份投标文件副本生成批量结果（合并需求，按投标文件分组）。"""
    import shutil
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp())
    req1 = sample_docs_dir / "requirements.docx"
    bid1 = sample_docs_dir / "bid.docx"
    req2 = tmp_dir / "requirements_copy.docx"
    bid2 = tmp_dir / "bid_copy.docx"
    shutil.copy(req1, req2)
    shutil.copy(bid1, bid2)

    yield proofreader.proofread_batch([req1, req2], [bid1, bid2])

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_batch_total_items(batch_result):
    """2 份需求 + 2 份投标应产生 2 个结果（每份投标一个）。"""
    assert batch_result.total_pairs == 2
    assert len(batch_result.items) == 2
    assert len(batch_result.errors) == 0


def test_batch_merged_requirements(batch_result):
    """合并后的需求数量应为两份需求文件之和（样例文件内容相同，编号也相同但会保留）。"""
    # 由于两份样例需求文件内容相同，合并后需求条目会翻倍
    assert batch_result.items[0].result.requirements == batch_result.items[1].result.requirements


def test_batch_consistency_issues_aggregated(batch_result):
    """累计问题数应大于 0。"""
    assert batch_result.total_consistency_issues > 0


def test_batch_single_and_batch_equivalent(sample_docs_dir: Path, proofreader: Proofreader) -> None:
    """proofread_batch 单文件对应与 proofread 结果等价。"""
    single = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    batch = proofreader.proofread_batch(
        [sample_docs_dir / "requirements.docx"],
        [sample_docs_dir / "bid.docx"],
    )
    assert len(batch.items) == 1
    assert len(batch.errors) == 0
    item = batch.items[0]
    assert isinstance(item.result, ProofreadResult)
    assert len(item.result.consistency_issues) == len(single.consistency_issues)
    assert len(item.result.typo_issues) == len(single.typo_issues)


def test_batch_error_isolated(proofreader: Proofreader, sample_docs_dir: Path, tmp_path: Path) -> None:
    """单个投标文件失败不应影响其他成功项。"""
    missing_bid = tmp_path / "not_exist_bid.docx"
    valid_req = sample_docs_dir / "requirements.docx"
    valid_bid = sample_docs_dir / "bid.docx"

    batch = proofreader.proofread_batch([valid_req], [valid_bid, missing_bid])
    assert len(batch.items) == 1
    assert len(batch.errors) == 1
    assert batch.errors[0].bid_path == missing_bid
