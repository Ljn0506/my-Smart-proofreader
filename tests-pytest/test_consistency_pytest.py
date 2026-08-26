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
    msgs, spans = _compare_time("质保期不少于 3 年", "质保期为 2 年")
    assert len(msgs) == 1
    assert "3.0年" in msgs[0] and "2.0年" in msgs[0]
    assert spans == ["2年"]


def test_compare_multiple_time_mismatches() -> None:
    """同一条需求含多个时间值时，应分别检出。"""
    req = "质保期不少于 3 年，交付期不超过 6 个月"
    bid = "质保期为 2 年，项目交付周期为 8 个月"
    msgs, spans = _compare_time(req, bid)
    assert len(msgs) == 2
    assert any("3.0年" in m and "2.0年" in m for m in msgs)
    assert any("6.0个月" in m and "8.0个月" in m for m in msgs)
    assert "2年" in spans
    assert "8个月" in spans


def test_compare_7x24_service() -> None:
    """7×24 小时服务未响应时应检出。"""
    msgs, spans = _compare_time("必须提供 7×24 小时技术支持服务", "技术支持服务时间为工作日 9:00-18:00")
    assert len(msgs) == 1
    assert "7×24" in msgs[0]


def test_compare_numbers_multiple_units() -> None:
    """多参数（不同单位）应同时比较。"""
    msg, spans = _compare_numbers("培训次数不少于 3 次，每次不少于 20 人", "提供 2 次集中培训，每次覆盖 15 人")
    assert msg is not None
    assert "3.0次" in msg and "2.0次" in msg
    assert "20.0人" in msg and "15.0人" in msg
    assert "2次" in spans
    assert "15人" in spans


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


def test_check_consistency_detects_missing_proof() -> None:
    """投标仅重复要求提供证书的需求原文时，应检出缺失证明。"""
    req_text = "支持检测的漏洞数大于250000条，兼容CVE等主流标准，（提供CVE Compatible证书）。"
    bid_text = "支持检测的漏洞数大于250000条，兼容CVE等主流标准，（提供CVE Compatible证书）。"
    req = RequirementItem(item_id="R1", text=req_text)
    bid_block = TextBlock(text=bid_text, block_type="heading", index=0)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.95)],
        best_score=0.95,
        match_type="exact",
    )
    issues = check_consistency([match])
    proof_issues = [i for i in issues if i.issue_type == IssueType.KEYWORD_MISSING and "PROOF" in i.issue_id]
    assert len(proof_issues) == 1
    assert "CVE Compatible" in proof_issues[0].message
    assert "未实际提供" in proof_issues[0].message


def test_check_consistency_skips_proof_when_bid_asserts_compliance() -> None:
    """投标方明确承诺满足/符合（如'了解并满足'）时，不应误判为缺失证明。"""
    req_text = "不低于1个GE管理口，不低于4个千兆光口，（提供截图证明并加盖厂商公章）。"
    bid_text = "了解并满足硬件规格及性能要求：1个RJ45串口，4个千兆光口，1个接口扩展槽位。"
    req = RequirementItem(item_id="R1", text=req_text)
    bid_block = TextBlock(text=bid_text, block_type="paragraph", index=0)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.9)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    proof_issues = [i for i in issues if i.issue_type == IssueType.KEYWORD_MISSING and "PROOF" in i.issue_id]
    assert len(proof_issues) == 0, f"不应把明确承诺满足的响应误判为缺失证明，实际生成：{proof_issues}"


def test_check_consistency_detects_missing_entity() -> None:
    """投标遗漏需求列出的某个硬件实体时，应检出。"""
    req_text = "不低于1个RJ45串口，不低于1个GE管理口，不低于4个千兆光口，不低于1个接口扩展槽位。"
    # 表格行格式：需求 | 响应 | 符合；响应中遗漏 GE管理口
    bid_text = "1 | 不低于1个RJ45串口... | 1个RJ45串口，4个千兆光口，1个接口扩展槽位 | 符合"
    req = RequirementItem(item_id="R1", text=req_text)
    bid_block = TextBlock(text=bid_text, block_type="table_row", index=0)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.9)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    entity_issues = [i for i in issues if i.issue_type == IssueType.KEYWORD_MISSING and "ENTITY" in i.issue_id]
    assert len(entity_issues) == 1
    assert "GE管理口" in entity_issues[0].message
    assert "RJ45串口" not in entity_issues[0].message  # 已响应的不应被报缺失


def test_check_consistency_skips_entity_when_all_present() -> None:
    """投标完整响应所有实体时，不应误报。"""
    req_text = "不低于1个RJ45串口，不低于1个GE管理口，不低于4个千兆光口。"
    bid_text = "1 | ... | 1个RJ45串口，1个GE管理口，4个千兆光口 | 符合"
    req = RequirementItem(item_id="R1", text=req_text)
    bid_block = TextBlock(text=bid_text, block_type="table_row", index=0)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block, 0.9)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    entity_issues = [i for i in issues if i.issue_type == IssueType.KEYWORD_MISSING and "ENTITY" in i.issue_id]
    assert len(entity_issues) == 0
