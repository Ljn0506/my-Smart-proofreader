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


def _is_uniform_section_row(text: str) -> bool:
    """判断表格行是否为章节标题行（各列内容相同，如 '二、网络回溯分析平台 | ...'）。"""
    cells = [c.strip() for c in text.split(" | ") if c.strip()]
    return len(cells) > 1 and all(c == cells[0] for c in cells)


# 需求行常见标志词，出现这些词说明该 "heading" 其实是需求条目，不应作为章节标题
_CONSTRAINT_MARKERS = ["必须", "应", "须", "不少于", "不超过", "不大于", "不小于", "提供", "截图证明", "加盖公章", "（提供"]


def _is_section_title_block(block: TextBlock) -> bool:
    """判断一个 block 是否是投标文件中的章节/产品标题。"""
    if block.block_type == "heading":
        # 真正的标题通常较短；过长的 "heading" 实际是表格里的需求行
        if len(block.text) > 80:
            return False
        # 包含需求标志词的需求行不应当作标题
        if any(marker in block.text for marker in _CONSTRAINT_MARKERS):
            return False
        return True
    if block.block_type == "table_row":
        return _is_uniform_section_row(block.text)
    return False


# 产品/系统常见词尾，用于在缺少需求标题列表时自动识别产品章节
_PRODUCT_MARKERS = ["系统", "平台", "评估", "工具", "设备"]


def _match_product_title(text: str, product_names: List[str] | None = None) -> str | None:
    """判断标题是否对应某个产品/系统章节，返回匹配到的产品名。"""
    title = text.strip(" ★▲")
    if len(title) > 80:
        return None

    if product_names:
        # 优先匹配最长的产品名，避免子串冲突
        for name in sorted(product_names, key=len, reverse=True):
            if name and name in title:
                return name
        return None

    # 启发式：包含产品标志词且不包含需求标志词
    if any(marker in title for marker in _CONSTRAINT_MARKERS):
        return None
    if any(marker in title for marker in _PRODUCT_MARKERS):
        return title
    return None


def split_bid_sections(
    doc: ParsedDocument,
    product_names: List[str] | None = None,
) -> List[BidSection]:
    """按标题/表格章节行把投标文件拆分，并为每个 block 标注所属章节标题。

    :param product_names: 需求文件中的产品/章节名称列表，用于把子标题下的 block 正确归到产品下。
    """
    sections: List[BidSection] = []
    current_section: BidSection | None = None
    current_product: str | None = None

    for block in doc.blocks:
        is_section_title = _is_section_title_block(block)

        if is_section_title:
            title_text = block.text.split(" | ", 1)[0].strip() if " | " in block.text else block.text.strip()
            scores = _score_section(title_text)
            best_type = BidSectionType.OTHER
            best_score = 0
            for stype, score in scores.items():
                if score > best_score:
                    best_score = score
                    best_type = stype

            matched_product = _match_product_title(title_text, product_names)
            if matched_product:
                current_product = matched_product
            # 非产品标题（如 ★硬件规格、授权委托书）不重置产品上下文，
            # 保证子标题和证明材料下的 block 仍能归到当前产品。"

            if current_section is not None:
                current_section.end_index = block.index
                sections.append(current_section)

            current_section = BidSection(
                section_type=best_type,
                title=title_text,
                blocks=[block],
                start_index=block.index,
            )
            # 产品章节下的 block 统一标注为产品名，便于后续按产品匹配
            block.section_title = current_product or title_text
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
            block.section_title = current_product or current_section.title

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
