"""校对流程编排。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

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


@dataclass
class BatchResultItem:
    """批量校对中的一个投标文件结果（对应合并后的全部需求）。"""

    bid_path: Path
    result: ProofreadResult
    requirement_paths: List[Path] = field(default_factory=list)


@dataclass
class BatchProofreadError:
    """批量校对中失败的投标文件。"""

    bid_path: Path
    error: str
    requirement_paths: List[Path] = field(default_factory=list)


@dataclass
class ProofreadBatchResult:
    """多文件批量校对结果。"""

    items: List[BatchResultItem]
    errors: List[BatchProofreadError]

    @property
    def total_pairs(self) -> int:
        return len(self.items) + len(self.errors)

    @property
    def total_consistency_issues(self) -> int:
        return sum(len(item.result.consistency_issues) for item in self.items)

    @property
    def total_table_issues(self) -> int:
        return sum(len(item.result.table_issues) for item in self.items)

    @property
    def total_typo_issues(self) -> int:
        return sum(len(item.result.typo_issues) for item in self.items)

    @property
    def total_ocr_issues(self) -> int:
        return sum(len(item.result.ocr_issues) for item in self.items)


class Proofreader:
    def __init__(self, ocr_use_gpu: bool = False, ocr_enabled: bool = True):
        self.ocr_enabled = ocr_enabled
        self.ocr_engine: OcrEngine | None = OcrEngine(use_gpu=ocr_use_gpu) if ocr_enabled else None

    def _proofread_with_requirements(
        self,
        requirement_paths: List[Path],
        req_docs: List[ParsedDocument],
        requirements: List[RequirementItem],
        bid_path: Path,
        cache_dir: Path,
    ) -> ProofreadResult:
        """使用已预解析的需求文档和条目对单个投标文件执行校对。"""
        # 1. 解析投标文件
        bid_doc = parse_docx(bid_path)

        # 2. 拆分投标文件
        product_names = sorted({r.section_title for r in requirements if r.section_title}, key=len, reverse=True)
        bid_sections = split_bid_sections(bid_doc, product_names=product_names)

        # 3. 段落匹配
        matches = match_requirements_to_bid(requirements, bid_sections)

        # 4. 一致性检查
        consistency_issues = check_consistency(matches)

        # 5. 错别字检查
        typo_issues = check_typos(bid_doc.blocks)

        # 6. 截图 OCR 检查（按投标文件隔离缓存，避免同名图片互相覆盖）
        ocr_issues: List[OcrIssue] = []
        if self.ocr_engine is not None:
            ocr_cache_dir = cache_dir / "images" / bid_path.stem
            ocr_issues = check_images(bid_doc, requirements, self.ocr_engine, ocr_cache_dir)

        # 7. 表格内容比对（使用合并后的需求文档）
        merged_req_doc = ParsedDocument(
            path=requirement_paths[0] if requirement_paths else Path("requirements.docx")
        )
        merged_req_doc.blocks = []
        merged_req_doc.headings = []
        merged_req_doc.raw_tables = []
        for doc in req_docs:
            merged_req_doc.blocks.extend(doc.blocks)
            merged_req_doc.headings.extend(doc.headings)
            merged_req_doc.raw_tables.extend(doc.raw_tables)
        table_issues = check_tables(merged_req_doc, bid_doc)

        return ProofreadResult(
            requirement_doc=merged_req_doc,
            bid_doc=bid_doc,
            requirements=requirements,
            bid_sections=bid_sections,
            matches=matches,
            consistency_issues=consistency_issues,
            typo_issues=typo_issues,
            ocr_issues=ocr_issues,
            table_issues=table_issues,
        )

    def _parse_requirements(
        self, requirement_paths: List[Path]
    ) -> tuple[List[ParsedDocument], List[RequirementItem]]:
        """预先解析所有需求文件并合并需求条目。"""
        req_docs = [parse_docx(p) for p in requirement_paths]
        requirements: List[RequirementItem] = []
        for doc in req_docs:
            requirements.extend(extract_requirements(doc))
        return req_docs, requirements

    def proofread(
        self,
        requirement_path: Path | str,
        bid_path: Path | str,
        cache_dir: Path | str | None = None,
    ) -> ProofreadResult:
        """执行完整校对流程（单需求文件 vs 单投标文件）。"""
        req_path = Path(requirement_path)
        req_docs, requirements = self._parse_requirements([req_path])
        return self._proofread_with_requirements(
            [req_path],
            req_docs,
            requirements,
            Path(bid_path),
            Path(cache_dir) if cache_dir else Path(".cache"),
        )

    def proofread_batch(
        self,
        requirement_paths: List[Path | str],
        bid_paths: List[Path | str],
        cache_dir: Path | str | None = None,
        progress_callback: Callable[[int, int, Path], None] | None = None,
    ) -> ProofreadBatchResult:
        """批量校对：合并所有需求文件的需求，对每个投标文件分别执行校对。"""
        items: List[BatchResultItem] = []
        errors: List[BatchProofreadError] = []
        cache_dir = Path(cache_dir) if cache_dir else Path(".cache")
        req_paths = [Path(p) for p in requirement_paths]
        total = len(bid_paths)

        # 批量场景：需求文件只解析一次，避免重复 I/O 与提取
        req_docs, requirements = self._parse_requirements(req_paths)

        for idx, bid_path in enumerate(bid_paths, start=1):
            bid_path = Path(bid_path)
            try:
                result = self._proofread_with_requirements(
                    req_paths, req_docs, requirements, bid_path, cache_dir
                )
                items.append(BatchResultItem(bid_path, result, req_paths))
            except Exception as exc:
                errors.append(
                    BatchProofreadError(
                        bid_path=bid_path,
                        error=f"{type(exc).__name__}: {exc}",
                        requirement_paths=req_paths,
                    )
                )
            if progress_callback is not None:
                progress_callback(idx, total, bid_path)

        return ProofreadBatchResult(items=items, errors=errors)
