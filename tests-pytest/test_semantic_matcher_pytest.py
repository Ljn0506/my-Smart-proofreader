"""pytest 风格的语义匹配器单元测试。"""
from __future__ import annotations

from proofreader.extractors.bid_splitter import BidSection, BidSectionType
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.matchers.semantic_matcher import (
    MatchResult,
    _business_compatible,
    _extract_numbers,
    _extract_thresholds,
    _keyword_overlap,
    _numeric_compatible,
    _section_compatible,
    _strict_match,
    _time_compatible,
    match_requirements_to_bid,
)
from proofreader.parsers.docx_parser import TextBlock


def _make_req(text: str, section_title: str = "") -> RequirementItem:
    return RequirementItem(
        item_id="R1",
        source_doc="req.docx",
        chapter_path=["需求"],
        raw_text=text,
        normalized_text=text,
        category="技术参数",
        constraint_type="必须",
        check_method="rule",
        extracted_by="rule",
        section_title=section_title,
    )


def _make_block(text: str, section_title: str = "", block_type: str = "paragraph") -> TextBlock:
    return TextBlock(
        text=text,
        block_type=block_type,
        index=0,
        section_title=section_title,
    )


def test_extract_numbers_finds_quantity_with_unit() -> None:
    nums = _extract_numbers("系统必须支持 1000 并发用户同时在线访问。")
    assert any(n == 1000.0 and u == "用户" for n, u in nums)


def test_extract_thresholds_finds_thresholds() -> None:
    thresholds = _extract_thresholds("响应时间不超过 2 秒，可用性 ≥99.9%")
    values = {v for _, v in thresholds}
    assert 2.0 in values
    assert 99.9 in values


def test_keyword_overlap_same_text() -> None:
    text = "项目经理必须具备 PMP 证书"
    assert _keyword_overlap(text, text) == 1.0


def test_keyword_overlap_no_common_words() -> None:
    req = "系统必须支持 1000 并发用户"
    bid = "这是一段完全无关的投标说明文字"
    assert _keyword_overlap(req, bid) == 0.0


def test_time_compatible_with_time_units() -> None:
    assert _time_compatible("质保期不少于 3 年", "质保期为 2 年") is True


def test_time_compatible_missing_time_units() -> None:
    assert _time_compatible("质保期不少于 3 年", "系统支持高并发") is False


def test_time_compatible_7x24() -> None:
    assert _time_compatible("必须提供 7×24 小时技术支持服务", "提供全天候技术支持") is True


def test_numeric_compatible_with_matching_unit() -> None:
    assert _numeric_compatible("支持 1000 并发用户", "经测试支持 1000 用户") is True


def test_numeric_compatible_no_bid_numbers() -> None:
    assert _numeric_compatible("支持 1000 并发用户", "系统架构先进") is False


def test_business_compatible_requires_keyword() -> None:
    assert _business_compatible("项目经理具备 PMP 证书", "项目经理张三具备 PMP 证书") is True
    assert _business_compatible("项目经理具备 PMP 证书", "系统支持高并发") is False


def test_section_compatible_matches_substring() -> None:
    req = _make_req("需求", section_title="漏洞扫描系统")
    block = _make_block("响应", section_title="漏洞扫描系统")
    assert _section_compatible(req, block) is True


def test_section_compatible_mismatch() -> None:
    req = _make_req("需求", section_title="漏洞扫描系统")
    block = _make_block("响应", section_title="入侵检测系统")
    assert _section_compatible(req, block) is False


def test_strict_match_numeric_exact() -> None:
    req = _make_req("系统必须支持 1000 并发用户同时在线访问。")
    assert _strict_match(req, "经测试，系统可支持 1000 并发用户同时在线访问。") is True


def test_strict_match_rejects_numeric_mismatch() -> None:
    req = _make_req("系统必须支持 1000 并发用户同时在线访问。")
    assert _strict_match(req, "本系统采用微服务架构，支持高并发访问。") is False


def test_match_requirements_to_bid_returns_match_results() -> None:
    req = _make_req("系统必须支持 1000 并发用户同时在线访问。")
    block = _make_block(
        "经测试，系统可支持 800 并发用户同时在线访问。",
        section_title="技术要求",
    )
    section = BidSection(
        section_type=BidSectionType.TECHNICAL,
        title="技术要求",
        blocks=[block],
    )
    results = match_requirements_to_bid([req], [section])
    assert len(results) == 1
    assert isinstance(results[0], MatchResult)
    assert results[0].requirement == req


def test_match_requirements_to_bid_filters_by_section_type() -> None:
    req = _make_req("系统必须支持 1000 并发用户。", section_title="技术要求")
    tech_block = _make_block("支持 800 用户", section_title="技术要求")
    business_block = _make_block("项目经理具备 PMP 证书", section_title="商务部分")
    sections = [
        BidSection(BidSectionType.TECHNICAL, "技术要求", [tech_block]),
        BidSection(BidSectionType.BUSINESS, "商务部分", [business_block]),
    ]
    results = match_requirements_to_bid([req], sections, section_type=BidSectionType.TECHNICAL)
    assert len(results[0].matched_blocks) == 1
    assert results[0].matched_blocks[0][0].text == tech_block.text


def test_match_requirements_to_bid_empty_bid() -> None:
    req = _make_req("系统必须支持 1000 并发用户。")
    section = BidSection(BidSectionType.TECHNICAL, "技术要求", [])
    results = match_requirements_to_bid([req], [section])
    assert results[0].matched_blocks == []
    assert results[0].match_type == "none"
