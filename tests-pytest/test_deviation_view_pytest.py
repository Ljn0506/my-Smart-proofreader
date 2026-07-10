"""偏离分析界面与高亮函数测试。"""
from __future__ import annotations

from proofreader.checkers.consistency_checker import (
    IssueLevel,
    IssueType,
    check_consistency,
)
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import MatchResult, match_requirements_to_bid
from proofreader.parsers.docx_parser import TextBlock
from proofreader.ui.highlighting import add_highlights, highlight_differences, html_escape


def test_html_escape() -> None:
    """HTML 特殊字符应被正确转义。"""
    assert html_escape("<script>") == "&lt;script&gt;"
    assert html_escape("a & b") == "a &amp; b"


def test_add_highlights_basic() -> None:
    """基本高亮应生成带 span 的 HTML。"""
    text = "质保期不少于3年"
    html = add_highlights(text, [(3, 6, "#ffcc80")])
    assert '<span style="background-color: #ffcc80;' in html
    assert "不少于" in html


def test_highlight_differences_same_number() -> None:
    """数字一致时投标侧应为绿色高亮。"""
    req = "质保期不少于3年"
    bid = "提供3年质保服务"
    req_html, bid_html = highlight_differences(req, bid)
    assert "#e3f2fd" in req_html  # 需求数字浅蓝
    assert "#c8e6c9" in bid_html  # 投标数字绿色


def test_highlight_differences_different_number() -> None:
    """数字不一致时投标侧应为黄色高亮。"""
    req = "质保期不少于3年"
    bid = "提供2年质保服务"
    req_html, bid_html = highlight_differences(req, bid)
    assert "#fff176" in bid_html  # 投标数字黄色


def test_highlight_differences_missing_number() -> None:
    """投标中缺失需求数字时应提示。"""
    req = "质保期不少于3年"
    bid = "提供质保服务"
    req_html, bid_html = highlight_differences(req, bid)
    assert "未找到对应项" in bid_html


def test_check_consistency_includes_candidates() -> None:
    """ConsistencyIssue 应携带候选投标段落。"""
    req = RequirementItem(item_id="R1", text="质保期不少于3年")
    bid_block_1 = TextBlock(text="提供2年质保", block_type="paragraph", index=0)
    bid_block_2 = TextBlock(text="提供5年售后服务", block_type="paragraph", index=1)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block_1, 0.9), (bid_block_2, 0.5)],
        best_score=0.9,
        match_type="exact",
    )
    issues = check_consistency([match])
    assert len(issues) == 1
    issue = issues[0]
    assert len(issue.candidate_bid_texts) == 2
    assert issue.candidate_bid_texts[0][0] == "提供2年质保"
    assert issue.candidate_bid_texts[1][0] == "提供5年售后服务"


def test_check_consistency_candidate_order() -> None:
    """候选段落应按匹配分数降序排列。"""
    req = RequirementItem(item_id="R1", text="质保期不超过2年")
    bid_block_1 = TextBlock(text="质保期为3年", block_type="paragraph", index=0)
    bid_block_2 = TextBlock(text="质保期为1年", block_type="paragraph", index=1)
    match = MatchResult(
        requirement=req,
        matched_blocks=[(bid_block_1, 0.95), (bid_block_2, 0.8)],
        best_score=0.95,
        match_type="exact",
    )
    issues = check_consistency([match])
    assert len(issues) > 0
    assert issues[0].candidate_bid_texts[0][1] == 0.95
    assert issues[0].candidate_bid_texts[1][1] == 0.8
