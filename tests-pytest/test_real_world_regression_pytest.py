"""真实场景回归测试。

这些测试记录了当前系统在真实投标文档中容易出现的漏检/误报问题。
当前标记为 xfail，修复对应模块后应移除 xfail 标记。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from proofreader.checkers.consistency_checker import check_consistency
from proofreader.checkers.table_checker import check_tables
from proofreader.checkers.typo_checker import check_typos
from proofreader.extractors.bid_splitter import BidSection, BidSectionType
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import match_requirements_to_bid
from proofreader.parsers.docx_parser import ParsedDocument, TextBlock


# ---------------------------------------------------------------------------
# 一致性检查真实场景
# ---------------------------------------------------------------------------

def _check_single_requirement(req_text: str, bid_text: str) -> list:
    """对单条需求和单条投标段落跑完整匹配+一致性检查，返回 issue 列表。"""
    req = RequirementItem(item_id="R1", text=req_text)
    bid_block = TextBlock(text=bid_text, block_type="paragraph", index=0)
    section = BidSection(
        section_type=BidSectionType.TECHNICAL, title="技术部分", blocks=[bid_block]
    )
    match_results = match_requirements_to_bid([req], [section])
    return check_consistency(match_results)


def test_bare_number_mismatch_should_be_detected() -> None:
    """并发用户数等裸数值偏离应被检出。"""
    issues = _check_single_requirement(
        "系统必须支持 1000 并发用户同时在线访问。",
        "经测试，系统可支持 800 用户同时在线。",
    )
    assert len(issues) > 0, "应检出发并发用户数不足"


def test_percentage_mismatch_should_be_detected() -> None:
    """系统可用性等百分比偏离应被检出。"""
    issues = _check_single_requirement(
        "系统可用性需达到 99.9%。",
        "系统可用性为 99.5%。",
    )
    assert len(issues) > 0, "应检出可用性百分比不足"


def test_threshold_keyword_dadao_should_be_detected() -> None:
    """'需达到'等阈值方向词应触发比较。"""
    issues = _check_single_requirement(
        "核心接口成功率需达到 99%。",
        "核心接口成功率为 95%。",
    )
    assert len(issues) > 0, "应检出入口成功率不足"


# ---------------------------------------------------------------------------
# 错别字检查真实场景
# ---------------------------------------------------------------------------

def _typo_issues_for(text: str) -> list:
    block = TextBlock(text=text, block_type="paragraph", index=0)
    return check_typos([block])


def test_typo_yingxiang_should_be_yingxiang() -> None:
    """'反映迅速'应为'响应迅速'。"""
    issues = _typo_issues_for("系统反映迅速，用户体验良好。")
    assert any("反映" in issue.word for issue in issues), "应检出'反映'错别字"


def test_typo_zizhi_should_be_zizhi() -> None:
    """'资职丰富'应为'资质丰富'。"""
    issues = _typo_issues_for("项目团队资职丰富。")
    assert any("资职" in issue.word for issue in issues), "应检出'资职'错别字"


# ---------------------------------------------------------------------------
# 表格比对真实场景
# ---------------------------------------------------------------------------

def _make_doc(raw_tables: list) -> ParsedDocument:
    doc = ParsedDocument(path=Path("dummy.docx"))
    doc.raw_tables = raw_tables
    return doc


def test_table_header_wording_variation_should_not_false_positive() -> None:
    """表头措辞不同但含义相同（需求值 vs 投标响应）不应误报未匹配。"""
    req_doc = _make_doc([
        [["参数项", "需求值"], ["并发用户", "≥1000"], ["响应时间", "≤2秒"]]
    ])
    bid_doc = _make_doc([
        [["技术指标", "投标响应"], ["并发用户", "800"], ["响应时间", "1.5秒"]]
    ])
    issues = check_tables(req_doc, bid_doc)
    # 期望：能正确匹配到表格并检出内容差异，而不是互相报“未找到对应表格”
    miss_issues = [i for i in issues if "未找到对应表格" in i.message]
    assert len(miss_issues) == 0, f"不应出现未匹配误报，实际问题：{issues}"


def test_table_row_order_invariant_should_not_false_positive() -> None:
    """表格行顺序不同但内容一致时不应误报。"""
    req_doc = _make_doc([
        [["参数项", "需求值"], ["并发用户", "≥1000"], ["响应时间", "≤2秒"]]
    ])
    bid_doc = _make_doc([
        [["参数项", "投标值"], ["响应时间", "≤2秒"], ["并发用户", "≥1000"]]
    ])
    issues = check_tables(req_doc, bid_doc)
    assert len(issues) == 0, f"内容一致仅顺序不同时不应报错，实际：{issues}"


def test_table_unit_gb_vs_g_should_not_false_positive() -> None:
    """GB 与 G 应视为等价单位，不应报不一致。"""
    req_doc = _make_doc([[["参数项", "需求值"], ["内存", "16GB"]]])
    bid_doc = _make_doc([[["参数项", "投标值"], ["内存", "16G"]]])
    issues = check_tables(req_doc, bid_doc)
    content_diffs = [i for i in issues if "内容不一致" in i.message]
    assert len(content_diffs) == 0, f"GB 与 G 不应报内容差异，实际：{content_diffs}"
