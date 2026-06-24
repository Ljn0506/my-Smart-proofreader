"""校对流程编排。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from proofreader.checkers.consistency_checker import ConsistencyIssue, check_consistency
from proofreader.checkers.ocr_checker import OcrEngine, OcrIssue, check_images
from proofreader.checkers.table_checker import TableIssue, check_tables
from proofreader.checkers.typo_checker import TypoIssue, check_typos
from proofreader.extractors.bid_splitter import BidSection, split_bid_sections
from proofreader.extractors.requirement_extractor import RequirementItem, extract_requirements
from proofreader.matchers.semantic_matcher import MatchResult, match_requirements_to_bid
from proofreader.parsers.docx_parser import ParsedDocument, parse_docx


@dataclass
class ProofreadResult:
    requirement_doc: ParsedDocument
    bid_doc: ParsedDocument
    requirements: List[RequirementItem]
    bid_sections: List[BidSection]
    matches: List[MatchResult]
    consistency_issues: List[ConsistencyIssue]
    typo_issues: List[TypoIssue]
    ocr_issues: List[OcrIssue]
    table_issues: List[TableIssue]


class Proofreader:
    def __init__(self, ocr_use_gpu: bool = False):
        self.ocr_engine = OcrEngine(use_gpu=ocr_use_gpu)

    def proofread(
        self,
        requirement_path: Path | str,
        bid_path: Path | str,
        cache_dir: Path | str | None = None,
    ) -> ProofreadResult:
        """执行完整校对流程。"""
        requirement_path = Path(requirement_path)
        bid_path = Path(bid_path)
        cache_dir = Path(cache_dir) if cache_dir else Path(".cache")

        # 1. 解析文档
        req_doc = parse_docx(requirement_path)
        bid_doc = parse_docx(bid_path)

        # 2. 提取需求条目
        requirements = extract_requirements(req_doc)

        # 3. 拆分投标文件
        bid_sections = split_bid_sections(bid_doc)

        # 4. 段落匹配（全部投标内容）
        matches = match_requirements_to_bid(requirements, bid_sections)

        # 5. 一致性检查
        consistency_issues = check_consistency(matches)

        # 6. 错别字检查
        typo_issues = check_typos(bid_doc.blocks)

        # 7. 截图 OCR 检查
        ocr_issues = check_images(bid_doc, requirements, self.ocr_engine, cache_dir / "images")

        # 8. 表格内容比对
        table_issues = check_tables(req_doc, bid_doc)

        return ProofreadResult(
            requirement_doc=req_doc,
            bid_doc=bid_doc,
            requirements=requirements,
            bid_sections=bid_sections,
            matches=matches,
            consistency_issues=consistency_issues,
            typo_issues=typo_issues,
            ocr_issues=ocr_issues,
            table_issues=table_issues,
        )
