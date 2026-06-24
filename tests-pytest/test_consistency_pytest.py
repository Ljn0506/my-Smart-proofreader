"""pytest 风格的一致性检查测试。"""
from __future__ import annotations

from proofreader.checkers.consistency_checker import (
    IssueType,
    _compare_numbers,
    _compare_time,
    check_consistency,
)
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import MatchResult
from proofreader.parsers.docx_parser import TextBlock


def test_compare_single_time_mismatch() -> None:
    """单时间值不一致应返回一条消息。"""
    msgs = _compare_time("质保期不少于 3 年", "质保期为 2 年")
    assert len(msgs) == 1
    assert "3.0年" in msgs[0] and "2.0年" in msgs[0]


def test_compare_multiple_time_mismatches() -> None:
    """同一条需求含多个时间值时，应分别检出。"""
    req = "质保期不少于 3 年，交付期不超过 6 个月"
    bid = "质保期为 2 年，项目交付周期为 8 个月"
    msgs = _compare_time(req, bid)
    assert len(msgs) == 2
    assert any("3.0年" in m and "2.0年" in m for m in msgs)
    assert any("6.0个月" in m and "8.0个月" in m for m in msgs)


def test_compare_7x24_service() -> None:
    """7×24 小时服务未响应时应检出。"""
    msgs = _compare_time("必须提供 7×24 小时技术支持服务", "技术支持服务时间为工作日 9:00-18:00")
    assert len(msgs) == 1
    assert "7×24" in msgs[0]


def test_compare_numbers_multiple_units() -> None:
    """多参数（不同单位）应同时比较。"""
    msg = _compare_numbers("培训次数不少于 3 次，每次不少于 20 人", "提供 2 次集中培训，每次覆盖 15 人")
    assert msg is not None
    assert "3.0次" in msg and "2.0次" in msg
    assert "20.0人" in msg and "15.0人" in msg


def test_check_consistency_generates_multiple_time_issues() -> None:
    """check_consistency 对多时间值需求应生成多个 issue。"""
    req = RequirementItem(item_id="R1", text="质保期不少于 3 年，交付期不超过 6 个月")
    bid_block = TextBlock(text="质保期为 2 年，项目交付周期为 8 个月", block_type="paragraph", index=0)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.9)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    time_issues = [i for i in issues if i.issue_type == IssueType.TIME_MISMATCH]
    assert len(time_issues) == 2
