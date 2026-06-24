"""从需求文件中提取「需求条目」。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from proofreader.parsers.docx_parser import ParsedDocument, TextBlock


# 约束关键词，用于识别需求语句
CONSTRAINT_KEYWORDS = [
    "必须", "应", "须", "不得", "禁止", "应当", "需要", "要求",
    "不少于", "不超过", "不大于", "不小于", "至少", "最多", "最低", "最高",
    "≥", "≤", ">", "<", "等于", "为", "质保期", "保修期", "交付期", "工期", "周期", "响应时间", "到货时间",
]

# 强约束词：出现即可视为需求
STRONG_CONSTRAINTS = set([
    "必须", "须", "应", "应当", "不得", "禁止", "需要", "要求",
    "不少于", "不超过", "不大于", "不小于", "至少", "最多", "最低", "最高",
    "≥", "≤", ">", "<",
])

# 自动编号模式
NUMBERING_PATTERNS = [
    r"^\d+[\.、)）]",            # 1.  1、  1)
    r"^[（(]\d+[)）]",           # (1) （1）
    r"^[①②③④⑤⑥⑦⑧⑨⑩]",        # 圈号
    r"^[一二三四五六七八九十]+[\.、)）]",  # 一、 二.
    r"^[（(][一二三四五六七八九十]+[)）]",  # （一）
]


@dataclass
class RequirementItem:
    """一条需求条目。"""
    item_id: str
    text: str
    source_blocks: List[TextBlock] = field(default_factory=list)
    is_numbered: bool = False
    constraint_keywords: List[str] = field(default_factory=list)
    level: int = 0


def _has_numbering(text: str) -> bool:
    """判断是否以编号开头。"""
    for pattern in NUMBERING_PATTERNS:
        if re.match(pattern, text.strip()):
            return True
    return False


def _extract_numbering_prefix(text: str) -> str:
    """提取编号前缀。"""
    for pattern in NUMBERING_PATTERNS:
        match = re.match(pattern, text.strip())
        if match:
            return match.group(0)
    return ""


def _detect_constraints(text: str) -> List[str]:
    """检测文本中包含的约束关键词。"""
    return [kw for kw in CONSTRAINT_KEYWORDS if kw in text]


def _is_likely_heading(block: TextBlock) -> bool:
    """判断是否可能是章节标题而非需求条目。"""
    if block.block_type == "heading":
        return True
    # 没有约束关键词且很短，可能是小标题
    if len(block.text) < 15 and not _detect_constraints(block.text):
        return True
    return False


def extract_requirements(doc: ParsedDocument) -> List[RequirementItem]:
    """从解析后的需求文档中提取需求条目。"""
    items: List[RequirementItem] = []
    current_item: RequirementItem | None = None

    for block in doc.blocks:
        text = block.text.strip()
        if not text:
            continue

        if _is_likely_heading(block):
            # 标题结束当前条目，先追加
            if current_item is not None:
                items.append(current_item)
                current_item = None
            continue

        is_numbered = _has_numbering(text)
        constraints = _detect_constraints(text)

        # 过滤：无编号时，必须有至少一个强约束词才算需求
        has_strong = any(c in STRONG_CONSTRAINTS for c in constraints)
        if not is_numbered and not has_strong:
            if current_item is not None:
                items.append(current_item)
                current_item = None
            continue

        # 如果是新编号开头，或者当前无条目但有约束词，则新建条目
        if is_numbered or (current_item is None and constraints):
            if current_item is not None:
                items.append(current_item)

            prefix = _extract_numbering_prefix(text)
            item_id = prefix or f"REQ-{len(items) + 1}"
            current_item = RequirementItem(
                item_id=item_id,
                text=text,
                source_blocks=[block],
                is_numbered=is_numbered,
                constraint_keywords=constraints,
                level=block.level,
            )
        else:
            # 合并到当前条目（无编号的续行）
            if current_item is None:
                continue
            current_item.text += "\n" + text
            current_item.source_blocks.append(block)
            current_item.constraint_keywords = _detect_constraints(current_item.text)

    if current_item is not None:
        items.append(current_item)

    return items
