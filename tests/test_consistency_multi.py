"""测试多时间值与多参数的一致性检查。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from proofreader.checkers.consistency_checker import (
    IssueLevel,
    IssueType,
    _compare_numbers,
    _compare_time,
    check_consistency,
)
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import MatchResult
from proofreader.parsers.docx_parser import TextBlock


def test_compare_time_multiple_values():
    req = "质保期不少于 3 年，交付期不超过 6 个月"
    bid = "质保期为 2 年，项目交付周期为 8 个月"
    msgs, spans = _compare_time(req, bid)
    assert len(msgs) == 2, f"应检出 2 处时间差异，实际 {len(msgs)}"
    assert any("3.0年" in m and "2.0年" in m for m in msgs)
    assert any("6.0个月" in m and "8.0个月" in m for m in msgs)
    print("✅ 多时间值比较通过")


def test_compare_time_single_value_unchanged():
    req = "质保期不少于 3 年"
    bid = "质保期为 2 年"
    msgs, spans = _compare_time(req, bid)
    assert len(msgs) == 1
    assert "3.0年" in msgs[0] and "2.0年" in msgs[0]
    print("✅ 单时间值比较通过")


def test_compare_time_7x24_only():
    req = "必须提供 7×24 小时技术支持服务"
    bid = "技术支持服务时间为工作日 9:00-18:00"
    msgs, spans = _compare_time(req, bid)
    assert len(msgs) == 1
    assert "7×24" in msgs[0]
    print("✅ 7×24 时间检查通过")


def test_compare_numbers_multiple_units():
    req = "培训次数不少于 3 次，每次不少于 20 人"
    bid = "提供 2 次集中培训，每次覆盖 15 人"
    msg, spans = _compare_numbers(req, bid)
    assert msg is not None
    assert "3.0次" in msg and "2.0次" in msg
    assert "20.0人" in msg and "15.0人" in msg
    print("✅ 多参数比较通过")


def test_check_consistency_multiple_time_issues():
    req = RequirementItem(
        item_id="R1",
        text="质保期不少于 3 年，交付期不超过 6 个月",
    )
    bid_block = TextBlock(
        text="质保期为 2 年，项目交付周期为 8 个月",
        block_type="paragraph",
        index=0,
    )
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.9)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    time_issues = [i for i in issues if i.issue_type == IssueType.TIME_MISMATCH]
    assert len(time_issues) == 2, f"应生成 2 个时间 issue，实际 {len(time_issues)}"
    assert all(i.level == IssueLevel.WARNING for i in time_issues)
    print("✅ check_consistency 多时间 issue 生成通过")


if __name__ == "__main__":
    test_compare_time_single_value_unchanged()
    test_compare_time_multiple_values()
    test_compare_time_7x24_only()
    test_compare_numbers_multiple_units()
    test_check_consistency_multiple_time_issues()
    print("\n多时间/多参数测试全部通过")
