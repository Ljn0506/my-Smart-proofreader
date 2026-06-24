"""把投标文件按商务、技术、价格三部分拆分。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from proofreader.parsers.docx_parser import ParsedDocument, TextBlock


class BidSectionType(str, Enum):
    BUSINESS = "business"      # 商务部分
    TECHNICAL = "technical"    # 技术部分
    PRICE = "price"            # 价格部分
    OTHER = "other"            # 其他/未识别


SECTION_KEYWORDS = {
    BidSectionType.BUSINESS: [
        "商务", "资格", "资质", "证明", "营业执照", "授权", "报价", "合同",
        "付款", "履约", "保证金", "法人代表", "业绩", "审计",
    ],
    BidSectionType.TECHNICAL: [
        "技术", "方案", "实施", "服务", "架构", "功能", "性能", "设计",
        "开发", "部署", "运维", "售后", "培训", "验收", "交付", "质保",
    ],
    BidSectionType.PRICE: [
        "价格", "报价", "分项", "总价", "金额", "币种", "税率", "发票",
        "费用", "预算", "投标报价",
    ],
}


@dataclass
class BidSection:
    section_type: BidSectionType
    title: str
    blocks: List[TextBlock] = field(default_factory=list)
    start_index: int = 0
    end_index: int = 0


def _score_section(text: str) -> dict[BidSectionType, int]:
    """根据关键词给段落打分，判断属于哪个部分。"""
    scores = {stype: 0 for stype in BidSectionType}
    text_lower = text.lower()
    for stype, keywords in SECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[stype] += 1
    return scores


def split_bid_sections(doc: ParsedDocument) -> List[BidSection]:
    """按标题关键词把投标文件拆分为商务、技术、价格三部分。"""
    sections: List[BidSection] = []
    current_section: BidSection | None = None

    for block in doc.blocks:
        if block.block_type == "heading":
            # 标题决定新章节
            scores = _score_section(block.text)
            # 找最高分且大于 0 的部分
            best_type = BidSectionType.OTHER
            best_score = 0
            for stype, score in scores.items():
                if score > best_score:
                    best_score = score
                    best_type = stype

            if current_section is not None:
                current_section.end_index = block.index
                sections.append(current_section)

            current_section = BidSection(
                section_type=best_type,
                title=block.text,
                blocks=[block],
                start_index=block.index,
            )
        else:
            if current_section is None:
                current_section = BidSection(
                    section_type=BidSectionType.OTHER,
                    title="开头",
                    blocks=[block],
                    start_index=block.index,
                )
            else:
                current_section.blocks.append(block)

    if current_section is not None:
        current_section.end_index = len(doc.blocks)
        sections.append(current_section)

    return sections


def get_blocks_by_section(sections: List[BidSection], section_type: BidSectionType) -> List[TextBlock]:
    """获取指定类型的所有文本块。"""
    blocks = []
    for sec in sections:
        if sec.section_type == section_type:
            blocks.extend(sec.blocks)
    return blocks
