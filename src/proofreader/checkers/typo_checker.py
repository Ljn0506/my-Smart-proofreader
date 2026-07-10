"""投标文件错别字检查。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from proofreader.parsers.docx_parser import TextBlock


@dataclass
class TypoIssue:
    block: TextBlock
    word: str
    position: int
    suggestion: str
    message: str


# 常见错词表（可扩展）
COMMON_TYPO_DICT = {
    "质保其": "质保期",
    "响影": "影响",
    "维户": "维护",
    "部暑": "部署",
    "架购": "架构",
    "性有": "性能",
    "功有": "功能",
    "投述": "投诉",
    "受后": "售后",
    "培圳": "培训",
    "到贷": "到货",
    "合通": "合同",
    "资职": "资质",
    "负偏离": "负偏离",
}

# 上下文相关错词：某些词单独可能是正确的，但在特定上下文中应为另一个词
CONTEXT_TYPO_PATTERNS = [
    # "反映"在描述系统性能/速度时通常为"响应"之误
    (re.compile(r"反映\s*(迅速|速度|时间|快|慢|及时|灵敏|性能|能力)", re.IGNORECASE), "反映", "响应"),
]

# 单位错误模式
UNIT_ERRORS = [
    (re.compile(r"(\d+)\s*G(?!B)\b"), r"\1 GB"),
    (re.compile(r"(\d+)\s*T(?!B)\b"), r"\1 TB"),
    (re.compile(r"(\d+)\s*M(?!B|Hz)\b"), r"\1 MB"),
]


def _is_number_or_punctuation(text: str) -> bool:
    return bool(re.match(r"^[\d\s\.，,。、；：:\-]+$", text))


def check_typos(blocks: List[TextBlock]) -> List[TypoIssue]:
    """检查文本块中的错别字和单位错误。"""
    issues: List[TypoIssue] = []

    for block in blocks:
        text = block.text
        if not text or len(text) < 4:
            continue

        # 检查常见错词
        for wrong, correct in COMMON_TYPO_DICT.items():
            for match in re.finditer(re.escape(wrong), text):
                issues.append(
                    TypoIssue(
                        block=block,
                        word=wrong,
                        position=match.start(),
                        suggestion=correct,
                        message=f"疑似错别字：「{wrong}」建议改为「{correct}」",
                    )
                )

        # 检查上下文相关错词
        for pattern, wrong, correct in CONTEXT_TYPO_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    TypoIssue(
                        block=block,
                        word=wrong,
                        position=match.start(),
                        suggestion=correct,
                        message=f"疑似错别字：「{wrong}」建议改为「{correct}」",
                    )
                )

        # 检查单位简写错误
        for pattern, suggestion_template in UNIT_ERRORS:
            for match in pattern.finditer(text):
                original = match.group(0)
                suggestion = pattern.sub(suggestion_template, original)
                issues.append(
                    TypoIssue(
                        block=block,
                        word=original,
                        position=match.start(),
                        suggestion=suggestion,
                        message=f"单位表述不规范：「{original}」建议改为「{suggestion}」",
                    )
                )

    return issues
