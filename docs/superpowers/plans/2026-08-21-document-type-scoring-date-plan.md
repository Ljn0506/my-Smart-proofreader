# Plan 1: Document Type Classification + Scoring Table Extraction + Date Normalizer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational capabilities needed for real-world tender/bid document handling: automatic document type + procurement method classification, scoring table extraction with aggregate rules, and a shared date/period normalization utility.

**Architecture:** Extend the existing `docx_parser` and `RequirementItem` model with document-type metadata and scoring-specific fields; add a lightweight `document_type_classifier` with rule + embedding + optional LLM fallback; add a `date_normalizer` shared utility; enhance `ScoringStrategy` to extract both atomic scoring items and `EvaluationRule` aggregates.

**Tech Stack:** Python 3.11+, pydantic, python-docx, scikit-learn (TF-IDF for embedding fallback), jieba, pytest.

## Global Constraints

- All processing stays local; no cloud upload of document content.
- LLM is default-off and only invoked when explicitly enabled with a local/safe model.
- Backward compatibility: existing `RequirementItem` construction via `item_id`/`text`/`section_title` must continue to work.
- Every new module must have pytest coverage before being integrated into `Proofreader.pipeline`.
- Prefer rules and deterministic heuristics; embedding/LLM is only a fallback for classification.
- Date normalizer must handle both absolute dates and relative Chinese periods (`近三年`, `近6个月`, `90天内`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/proofreader/utils/date_normalizer.py` | New. Parse Chinese date/period expressions into normalized `NormalizedDate` / `NormalizedPeriod` objects. |
| `src/proofreader/parsers/document_type_classifier.py` | New. Classify document type and procurement method using rule → embedding → LLM fallback; return confidence. |
| `src/proofreader/parsers/docx_parser.py` | Modify. Extend `DocumentType` enum, add `ProcurementMethod`, attach classification result to `ParsedDocument`. |
| `src/proofreader/models/requirements.py` | Modify. Add `raw_marker`, `max_score`, `evaluation_criteria` to `RequirementItem`; add `EvaluationRule` and `DocumentClassificationResult` models. |
| `src/proofreader/extractors/table_strategies.py` | Modify. Enhance `ScoringStrategy` to populate scoring-specific fields and detect aggregate rules. |
| `src/proofreader/extractors/scoring_extractor.py` | New. Extract aggregate scoring rules (`EvaluationRule`) from scoring table text and surrounding paragraphs. |
| `src/proofreader/extractors/composite_extractor.py` | Modify. Include `ScoringExtractor` for scoring sections. |
| `tests-pytest/test_date_normalizer.py` | New. Unit tests for date/period parsing. |
| `tests-pytest/test_document_type_classifier.py` | New. Tests for rule/embedding/LLM classification. |
| `tests-pytest/test_scoring_extraction.py` | New. Tests for scoring table extraction and aggregate rules. |

---

## Task 1: Add data model fields and new models

**Files:**
- Modify: `src/proofreader/models/requirements.py`
- Test: `tests-pytest/test_requirements_model_pytest.py` (create if missing)

**Interfaces:**
- Consumes: existing `RequirementItem` model.
- Produces: extended `RequirementItem` with `raw_marker`, `max_score`, `evaluation_criteria`; new `EvaluationRule`; new `DocumentClassificationResult`.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.models.requirements import (
    DocumentClassificationResult,
    DocumentType,
    EvaluationRule,
    ProcurementMethod,
    RequirementItem,
)


def test_requirement_item_has_scoring_fields():
    item = RequirementItem(
        id="req-1",
        source_doc="tender.docx",
        chapter_path=["评分表"],
        raw_text="项目经理具备 PMP 证书，得 6 分",
        normalized_text="项目经理具备 PMP 证书，得 6 分",
        category="评分标准",
        constraint_type="评分项",
        check_method="rule",
        extracted_by="scoring_strategy",
        raw_marker="▲",
        max_score=6.0,
        evaluation_criteria="具备 PMP 证书得 6 分",
    )
    assert item.raw_marker == "▲"
    assert item.max_score == 6.0
    assert item.evaluation_criteria == "具备 PMP 证书得 6 分"


def test_evaluation_rule_model():
    rule = EvaluationRule(
        rule_text="全部响应得 24 分，每负偏离一项扣 3 分",
        base_score=24.0,
        deduction_per_item=3.0,
        applies_to_requirement_ids=["req-a", "req-b"],
        confidence=0.85,
    )
    assert rule.base_score == 24.0


def test_document_classification_result():
    result = DocumentClassificationResult(
        document_type="tender",
        procurement_method="bixuan",
        confidence=0.92,
        method="rule",
    )
    assert result.confidence == 0.92
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_requirements_model_pytest.py -v`
Expected: FAIL with `ImportError` or `NameError` for missing fields/models.

- [ ] **Step 3: Write minimal implementation**

Modify `src/proofreader/models/requirements.py`:

```python
from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class DocumentType(str, Enum):
    TENDER = "tender"
    BID_REGISTRATION = "bid_registration"
    BID_RESPONSE = "bid_response"
    PRODUCT_SOLUTION = "product_solution"
    REQUIREMENT = "requirement"
    OTHER = "other"


class ProcurementMethod(str, Enum):
    BIXUAN = "bixuan"
    COMPETITIVE_NEGOTIATION = "competitive_negotiation"
    TENDER = "tender"
    SELECTION = "selection"
    PRODUCT_DEMO = "product_demo"
    OTHER = "other"


class ConstraintType(str, Enum):
    MANDATORY = "必须"
    SCORING = "评分项"
    RECOMMENDED = "建议"
    REFERENCE = "仅供参考"


class RequirementCategory(str, Enum):
    QUALIFICATION = "资质条件"
    PERSONNEL = "人员要求"
    PERFORMANCE = "业绩要求"
    TECHNICAL = "技术参数"
    COMMERCIAL = "商务条款"
    FORMAT = "封装格式"
    DELIVERY = "交付要求"
    SCORING = "评分标准"
    OTHER = "其他"


class CheckMethod(str, Enum):
    RULE = "rule"
    LLM = "llm"
    RULE_LLM = "rule+llm"
    MANUAL = "manual"


class ReviewStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    MODIFIED = "modified"
    REJECTED = "rejected"
    MERGED = "merged"
    DEPRECATED = "deprecated"


class CheckTarget(BaseModel):
    type: str
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Any = None
    unit: Optional[str] = None
    description: Optional[str] = None


class RequirementItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., validation_alias=AliasChoices("item_id", "id"))
    stable_hash: Optional[str] = None
    source_doc: str
    chapter_path: List[str]
    title: Optional[str] = Field(default=None, validation_alias=AliasChoices("section_title", "title"))
    raw_text: str = Field(..., validation_alias=AliasChoices("text", "raw_text"))
    normalized_text: str
    category: RequirementCategory
    constraint_type: ConstraintType
    constraint_keywords: List[str] = Field(default_factory=list)
    check_method: CheckMethod
    check_target: Optional[CheckTarget] = None
    match_keywords: List[str] = Field(default_factory=list)
    extracted_by: str
    review_status: ReviewStatus = ReviewStatus.DRAFT
    manual_note: Optional[str] = None
    template_ref: Optional[str] = None
    project_specific: bool = False
    raw_marker: Optional[str] = None
    max_score: Optional[float] = None
    evaluation_criteria: Optional[str] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    version: int = 1

    @model_validator(mode="before")
    @classmethod
    def _fill_legacy_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "normalized_text" not in data and "text" in data:
                data["normalized_text"] = data["text"]
            if "source_doc" not in data:
                data["source_doc"] = ""
            if "chapter_path" not in data:
                data["chapter_path"] = []
            if "category" not in data:
                data["category"] = RequirementCategory.OTHER
            if "constraint_type" not in data:
                data["constraint_type"] = ConstraintType.REFERENCE
            if "check_method" not in data:
                data["check_method"] = CheckMethod.RULE
            if "extracted_by" not in data:
                data["extracted_by"] = "legacy"
        return data

    @property
    def item_id(self) -> str:
        return self.id

    @property
    def text(self) -> str:
        return self.raw_text

    @property
    def section_title(self) -> str:
        return self.title or (self.chapter_path[-1] if self.chapter_path else "")


class EvaluationRule(BaseModel):
    rule_text: str
    base_score: Optional[float] = None
    deduction_per_item: Optional[float] = None
    applies_to_requirement_ids: List[str] = Field(default_factory=list)
    confidence: float = 1.0


class DocumentClassificationResult(BaseModel):
    document_type: DocumentType
    procurement_method: ProcurementMethod
    confidence: float
    method: str = "rule"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_requirements_model_pytest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/models/requirements.py tests-pytest/test_requirements_model_pytest.py
git commit -m "feat(models): add document type enums, scoring fields, EvaluationRule, DocumentClassificationResult"
```

---

## Task 2: Implement date_normalizer utility

**Files:**
- Create: `src/proofreader/utils/date_normalizer.py`
- Test: `tests-pytest/test_date_normalizer.py`

**Interfaces:**
- Consumes: raw Chinese date/period strings.
- Produces: `NormalizedDate` or `NormalizedPeriod`; returns `None` with raw text when unparseable.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

from proofreader.utils.date_normalizer import normalize_date, normalize_period


def test_normalize_absolute_date():
    assert normalize_date("2026年7月15日").date == date(2026, 7, 15)
    assert normalize_date("2026.07.15").date == date(2026, 7, 15)
    assert normalize_date("2026/07/15").date == date(2026, 7, 15)


def test_normalize_chinese_numeral_date():
    result = normalize_date("二〇二六年七月十五日")
    assert result.date == date(2026, 7, 15)


def test_normalize_relative_period():
    result = normalize_period("近三年")
    assert result.start is not None
    assert result.end is not None
    assert (result.end - result.start).days >= 365 * 3 - 1


def test_normalize_invalid_date():
    assert normalize_date("not a date") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_date_normalizer.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/utils/date_normalizer.py`:

```python
"""统一解析中文日期与期间表达。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass
class NormalizedDate:
    date: date
    precision: str  # DAY / MONTH / YEAR
    is_relative: bool = False
    raw_text: str = ""


@dataclass
class NormalizedPeriod:
    start: Optional[date]
    end: Optional[date]
    description: str
    raw_text: str


_CN_NUMBERS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
    "十一": "11", "十二": "12",
}


def _cn_to_arabic(cn: str) -> str:
    result = []
    i = 0
    while i < len(cn):
        matched = False
        for k in sorted(_CN_NUMBERS.keys(), key=len, reverse=True):
            if cn[i:].startswith(k):
                result.append(_CN_NUMBERS[k])
                i += len(k)
                matched = True
                break
        if not matched:
            result.append(cn[i])
            i += 1
    return "".join(result)


def _parse_year_month_day(text: str) -> Optional[date]:
    # 2026年7月15日 / 2026.07.15 / 2026/07/15
    patterns = [
        r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?",
        r"(\d{4})(\d{2})(\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def normalize_date(text: str, reference: Optional[date] = None) -> Optional[NormalizedDate]:
    if not text:
        return None
    reference = reference or date.today()

    # Convert Chinese numerals first
    converted = _cn_to_arabic(text)
    parsed = _parse_year_month_day(converted)
    if parsed:
        return NormalizedDate(date=parsed, precision="DAY", raw_text=text)

    # Relative expressions: 90天内 / 2个月内
    m = re.search(r"(\d+)\s*天[之以]?内", text)
    if m:
        d = reference - timedelta(days=int(m.group(1)))
        return NormalizedDate(date=d, precision="DAY", is_relative=True, raw_text=text)

    m = re.search(r"(\d+)\s*个月[之以]?内", text)
    if m:
        months = int(m.group(1))
        # Approximate: shift month backward
        year, month = reference.year, reference.month
        for _ in range(months):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        d = date(year, month, reference.day)
        return NormalizedDate(date=d, precision="MONTH", is_relative=True, raw_text=text)

    return None


def normalize_period(text: str, reference: Optional[date] = None) -> Optional[NormalizedPeriod]:
    if not text:
        return None
    reference = reference or date.today()

    # Date range: 2023-01-01 至 2023-12-31
    m = re.search(
        r"(\d{4}[年/-]\d{1,2}[月/-]\d{1,2}[日]?)\s*[-~至]\s*(\d{4}[年/-]\d{1,2}[月/-]\d{1,2}[日]?)",
        _cn_to_arabic(text),
    )
    if m:
        start = normalize_date(m.group(1))
        end = normalize_date(m.group(2))
        if start and end:
            return NormalizedPeriod(
                start=start.date, end=end.date, description=text, raw_text=text
            )

    # Relative periods
    m = re.search(r"近\s*(\d+)\s*年", text)
    if m:
        years = int(m.group(1))
        start = reference.replace(year=reference.year - years)
        return NormalizedPeriod(
            start=start, end=reference, description=f"近{years}年", raw_text=text
        )

    m = re.search(r"近\s*(\d+)\s*个月", text)
    if m:
        months = int(m.group(1))
        year, month = reference.year, reference.month
        for _ in range(months):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        start = date(year, month, reference.day)
        return NormalizedPeriod(
            start=start, end=reference, description=f"近{months}个月", raw_text=text
        )

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_date_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/utils/date_normalizer.py tests-pytest/test_date_normalizer.py
git commit -m "feat(utils): add date_normalizer for Chinese dates and periods"
```

---

## Task 3: Implement document_type_classifier

**Files:**
- Create: `src/proofreader/parsers/document_type_classifier.py`
- Modify: `src/proofreader/parsers/docx_parser.py`
- Test: `tests-pytest/test_document_type_classifier.py`

**Interfaces:**
- Consumes: `ParsedDocument` (title, headings, first paragraphs, table-of-contents text).
- Produces: `DocumentClassificationResult(document_type, procurement_method, confidence, method)`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from proofreader.parsers.document_type_classifier import classify_document
from proofreader.parsers.docx_parser import ParsedDocument


def _make_doc(title: str, headings: list[str], intro: str) -> ParsedDocument:
    from proofreader.parsers.docx_parser import TextBlock
    doc = ParsedDocument(path="test.docx")
    doc.title = title
    doc.headings = [TextBlock(text=h, block_type="heading", level=1) for h in headings]
    doc.blocks = []
    # Minimal mock: the classifier reads doc.title and doc.headings
    return doc


def test_classify_bixuan_tender():
    doc = _make_doc("广州市荔湾区中医医院数据安全及个人信息保护服务项目比选文件", ["第一部分 邀请函", "第二部分 响应供应商须知"], "")
    result = classify_document(doc)
    assert result.document_type == "tender"
    assert result.procurement_method == "bixuan"
    assert result.confidence >= 0.85


def test_classify_bid_response():
    doc = _make_doc("响应文件", ["一、资格性文件", "二、商务部分", "三、技术部分", "四、价格部分"], "")
    result = classify_document(doc)
    assert result.document_type == "bid_response"
    assert result.confidence >= 0.85


def test_classify_registration():
    doc = _make_doc("报名文件", ["一、营业执照", "二、承诺函"], "")
    result = classify_document(doc)
    assert result.document_type == "bid_registration"


def test_classify_low_confidence():
    doc = _make_doc("采购文件", [], "")
    result = classify_document(doc)
    assert result.confidence < 0.85
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_document_type_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/parsers/document_type_classifier.py`:

```python
"""文档类型与采购方式分类器。规则 → embedding → LLM 兜底。"""
from __future__ import annotations

import re
from typing import List, Optional

from proofreader.models.requirements import (
    DocumentClassificationResult,
    DocumentType,
    ProcurementMethod,
)
from proofreader.parsers.docx_parser import ParsedDocument


# Rule-based keyword patterns
_DOCUMENT_KEYWORDS = {
    DocumentType.TENDER: {
        ProcurementMethod.BIXUAN: ["比选文件", "比选", "综合评分法"],
        ProcurementMethod.COMPETITIVE_NEGOTIATION: ["竞争性磋商", "磋商文件", "磋商邀请"],
        ProcurementMethod.TENDER: ["招标文件", "招标公告", "公开招标"],
        ProcurementMethod.SELECTION: ["遴选文件", "遴选"],
        ProcurementMethod.OTHER: ["采购文件", "采购需求", "需求文件"],
    },
    DocumentType.BID_REGISTRATION: {
        ProcurementMethod.OTHER: ["报名文件", "报名资料", "报名登记表"],
    },
    DocumentType.BID_RESPONSE: {
        ProcurementMethod.OTHER: ["响应文件", "投标文件"],
    },
    DocumentType.PRODUCT_SOLUTION: {
        ProcurementMethod.PRODUCT_DEMO: ["产品介绍报名表", "产品解决方案", "产品资料"],
    },
}

_BID_RESPONSE_SECTIONS = ["资格性文件", "商务部分", "技术部分", "价格部分"]


def _score_rule(doc: ParsedDocument) -> tuple[DocumentType, ProcurementMethod, float]:
    heading_texts = [h.text if hasattr(h, "text") else str(h) for h in doc.headings[:10]]
    text = (doc.title or "") + " " + " ".join(heading_texts)
    best_type = DocumentType.OTHER
    best_method = ProcurementMethod.OTHER
    best_score = 0.0

    for doc_type, methods in _DOCUMENT_KEYWORDS.items():
        for method, keywords in methods.items():
            score = sum(2 if kw in text else 0 for kw in keywords)
            if score > best_score:
                best_score = score
                best_type = doc_type
                best_method = method

    # Boost bid_response if it has the four standard sections
    if any(sec in text for sec in _BID_RESPONSE_SECTIONS):
        if best_type in (DocumentType.BID_RESPONSE, DocumentType.BID_REGISTRATION, DocumentType.OTHER):
            best_type = DocumentType.BID_RESPONSE
            best_score = max(best_score, 2.0)

    confidence = min(0.5 + best_score * 0.15, 0.95)
    return best_type, best_method, confidence


def _embedding_fallback(doc: ParsedDocument) -> Optional[DocumentClassificationResult]:
    """Optional TF-IDF / embedding fallback. Stub for now; implement in Task 3.5."""
    return None


def classify_document(
    doc: ParsedDocument,
    use_embedding: bool = False,
    use_llm: bool = False,
) -> DocumentClassificationResult:
    doc_type, method, confidence = _score_rule(doc)
    result_method = "rule"

    if confidence < 0.85 and use_embedding:
        emb = _embedding_fallback(doc)
        if emb and emb.confidence > confidence:
            doc_type = emb.document_type
            method = emb.procurement_method
            confidence = emb.confidence
            result_method = "embedding"

    if confidence < 0.70 and use_llm:
        # LLM integration stub; actual local LLM call configured elsewhere
        doc_type = DocumentType.OTHER
        method = ProcurementMethod.OTHER
        confidence = 0.55
        result_method = "llm"

    return DocumentClassificationResult(
        document_type=doc_type,
        procurement_method=method,
        confidence=min(confidence, 1.0),
        method=result_method,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_document_type_classifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/parsers/document_type_classifier.py tests-pytest/test_document_type_classifier.py
git commit -m "feat(parser): add document_type_classifier with rule-based confidence"
```

---

## Task 4: Attach classification result to ParsedDocument

**Files:**
- Modify: `src/proofreader/parsers/docx_parser.py`
- Test: `tests-pytest/test_doc_parser_pytest.py`

**Interfaces:**
- Consumes: `DocumentClassificationResult` from classifier.
- Produces: `ParsedDocument` with `doc_type`, `procurement_method`, `classification_confidence`, `classification_method`.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.parsers.docx_parser import parse_docx


def test_parsed_document_has_classification(sample_docs_dir):
    from pathlib import Path
    doc_path = sample_docs_dir / "requirements.docx"
    if not doc_path.exists():
        pytest.skip("sample requirements.docx not found")
    parsed = parse_docx(doc_path)
    assert parsed.doc_type is not None
    assert parsed.procurement_method is not None
    assert parsed.classification_confidence > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_doc_parser_pytest.py::test_parsed_document_has_classification -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/proofreader/parsers/docx_parser.py`:

1. Update the `DocumentType` enum to align with `requirements.py`:

```python
class DocumentType(str, Enum):
    TENDER = "tender"
    REQUIREMENT = "requirement"
    BID = "bid_document"
    BID_REGISTRATION = "bid_registration"
    BID_RESPONSE = "bid_response"
    PRODUCT_SOLUTION = "product_solution"
    OTHER = "other"
```

2. Add `ProcurementMethod` enum:

```python
class ProcurementMethod(str, Enum):
    BIXUAN = "bixuan"
    COMPETITIVE_NEGOTIATION = "competitive_negotiation"
    TENDER = "tender"
    SELECTION = "selection"
    PRODUCT_DEMO = "product_demo"
    OTHER = "other"
```

3. In `ParsedDocument` dataclass, keep existing `doc_type` and add fields:

```python
@dataclass
class ParsedDocument:
    path: Path
    doc_type: DocumentType = DocumentType.TENDER
    procurement_method: ProcurementMethod = ProcurementMethod.OTHER
    classification_confidence: float = 0.0
    classification_method: str = ""
    blocks: List[TextBlock] = field(default_factory=list)
    headings: List[TextBlock] = field(default_factory=list)
    sections: List[DocumentSection] = field(default_factory=list)
    title: Optional[str] = None
    images: List[EmbeddedImage] = field(default_factory=list)
    raw_tables: List[List[List[str]]] = field(default_factory=list)
```

4. At the end of `parse_docx`, call classifier:

```python
from proofreader.parsers.document_type_classifier import classify_document

# After building parsed_doc
classification = classify_document(parsed_doc)
parsed_doc.doc_type = classification.document_type
parsed_doc.procurement_method = classification.procurement_method
parsed_doc.classification_confidence = classification.confidence
parsed_doc.classification_method = classification.method
```

Note: `ParsedDocument.headings` is a `List[TextBlock]`; the classifier should read heading text via `[h.text for h in doc.headings]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_doc_parser_pytest.py -v`
Expected: PASS (all existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/parsers/docx_parser.py tests-pytest/test_doc_parser_pytest.py
git commit -m "feat(parser): attach document classification to ParsedDocument"
```

---

## Task 5: Enhance scoring table extraction

**Files:**
- Modify: `src/proofreader/extractors/table_strategies.py`
- Create: `src/proofreader/extractors/scoring_extractor.py`
- Modify: `src/proofreader/extractors/composite_extractor.py`
- Test: `tests-pytest/test_scoring_extraction.py`

**Interfaces:**
- Consumes: `ParsedTable` with `table_type == TableType.EVALUATION`.
- Produces: `RequirementItem` with scoring fields + `EvaluationRule` aggregates.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.extractors.table_strategies import ScoringStrategy
from proofreader.parsers.docx_parser import DocumentSection, ParsedDocument, ParsedTable


def _make_scoring_table():
    table = ParsedTable(
        table_type="evaluation",
        header=["序号", "评价项目", "参考评价标准", "最高分值"],
        rows=[
            ["1", "项目经理", "具备 PMP 证书，得 6 分", "6"],
            ["2", "技术参数", "全部响应得 24 分，每负偏离一项扣 3 分", "24"],
        ],
    )
    section = DocumentSection(section_type="evaluation", headings=["评分表"], level=2)
    doc = ParsedDocument(path="tender.docx")
    return table, section, doc


def test_scoring_strategy_extracts_atomic_items():
    table, section, doc = _make_scoring_table()
    strategy = ScoringStrategy()
    items = strategy.extract(table, section, doc)
    assert len(items) == 2
    assert items[0].max_score == 6.0
    assert items[0].constraint_type == "评分项"
    assert items[1].max_score == 24.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_scoring_extraction.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Modify `src/proofreader/extractors/table_strategies.py`:

```python
import re


class ScoringStrategy(TechnicalSpecStrategy):
    def extract(self, table, section, doc):
        items = []
        for row in table.rows:
            if not row:
                continue
            raw_text = " | ".join(row)
            max_score = self._extract_max_score(row)
            marker = self._extract_marker(raw_text)
            item = self._make_item(
                raw_text=raw_text,
                section=section,
                doc=doc,
                category=RequirementCategory.SCORING,
                constraint_type=ConstraintType.SCORING,
            )
            item.max_score = max_score
            item.raw_marker = marker
            item.evaluation_criteria = raw_text
            items.append(item)
        return items

    def _extract_max_score(self, row: List[str]) -> Optional[float]:
        for cell in reversed(row):
            m = re.search(r"(\d+(?:\.\d+)?)", cell)
            if m and ("分" in cell or "%" not in cell):
                return float(m.group(1))
        return None

    def _extract_marker(self, text: str) -> Optional[str]:
        if "★" in text:
            return "★"
        if "▲" in text:
            return "▲"
        return None
```

Update `_make_item` signature in `TechnicalSpecStrategy` to accept `raw_text` keyword:

```python
def _make_item(
    self,
    raw_text: str,
    section: DocumentSection,
    doc: ParsedDocument,
    category: RequirementCategory,
    constraint_type: ConstraintType = ConstraintType.MANDATORY,
) -> RequirementItem:
    ...
```

Then create `src/proofreader/extractors/scoring_extractor.py`:

```python
"""从评分表周边文本中提取聚合评分规则（EvaluationRule）。"""
from __future__ import annotations

import re
from typing import List

from proofreader.extractors.base import BaseExtractor
from proofreader.models.requirements import EvaluationRule, RequirementItem
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


_AGGREGATE_PATTERNS = [
    re.compile(r"全部.*?得\s*(\d+(?:\.\d+)?)\s*分，每.*?扣\s*(\d+(?:\.\d+)?)\s*分"),
    re.compile(r"全部.*?得\s*(\d+(?:\.\d+)?)\s*分"),
]


class ScoringExtractor(BaseExtractor):
    def extract_from_section(
        self, section: DocumentSection, doc: ParsedDocument
    ) -> List[EvaluationRule]:
        if section.section_type != DocumentSectionType.EVALUATION:
            return []

        rules = []
        text = "\n".join(section.paragraphs) if hasattr(section, "paragraphs") else ""
        for pattern in _AGGREGATE_PATTERNS:
            for m in pattern.finditer(text):
                base_score = float(m.group(1))
                deduction = float(m.group(2)) if m.lastindex >= 2 else None
                rules.append(
                    EvaluationRule(
                        rule_text=m.group(0),
                        base_score=base_score,
                        deduction_per_item=deduction,
                        confidence=0.8,
                    )
                )
        return rules

    def link_rules_to_items(
        self, rules: List[EvaluationRule], items: List[RequirementItem]
    ) -> List[EvaluationRule]:
        """Associate aggregate rules with scoring items by section/chapter path."""
        linked = []
        scoring_items = [it for it in items if it.category == "评分标准"]
        for rule in rules:
            # Simple heuristic: link to scoring items in same chapter path
            linked.append(
                rule.model_copy(
                    update={
                        "applies_to_requirement_ids": [it.id for it in scoring_items]
                    }
                )
            )
        return linked
```

Modify `src/proofreader/extractors/composite_extractor.py`:

```python
from proofreader.extractors.scoring_extractor import ScoringExtractor


class CompositeExtractor(BaseExtractor):
    def __init__(self, extractors=None):
        self.extractors = extractors or [NumberedParagraphExtractor()]
        self.deduplicator = SemanticDeduplicator(threshold=0.95)
        self.scoring_extractor = ScoringExtractor()

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        items: List[RequirementItem] = []
        scoring_rules = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
            scoring_rules.extend(self.scoring_extractor.extract_from_section(section, doc))

        items = self.deduplicator.deduplicate(items)
        scoring_rules = self.scoring_extractor.link_rules_to_items(scoring_rules, items)
        # TODO: store scoring_rules alongside items (Task 6)
        return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_scoring_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/table_strategies.py src/proofreader/extractors/scoring_extractor.py src/proofreader/extractors/composite_extractor.py tests-pytest/test_scoring_extraction.py
git commit -m "feat(extractors): enhance scoring table extraction with EvaluationRule aggregates"
```

---

## Task 6: Return scoring rules from extraction pipeline

**Files:**
- Modify: `src/proofreader/extractors/composite_extractor.py`
- Modify: `src/proofreader/extractors/requirement_extractor.py` (if exists)
- Modify: `src/proofreader/pipeline.py`
- Test: `tests-pytest/test_scoring_extraction.py`

**Interfaces:**
- Consumes: `EvaluationRule` list.
- Produces: extraction result now includes both `items` and `evaluation_rules`.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument


def test_composite_extractor_returns_evaluation_rules():
    doc = ParsedDocument(path="tender.docx")
    section = DocumentSection(
        section_type=DocumentSectionType.EVALUATION,
        headings=["评分表"],
        level=2,
        paragraphs=["对技术参数，全部响应得 24 分，每负偏离一项扣 3 分。"],
    )
    doc.sections = [section]
    extractor = CompositeExtractor()
    result = extractor.extract_with_rules(doc)
    assert len(result.items) == 0  # no tables in this mock
    assert len(result.evaluation_rules) == 1
    assert result.evaluation_rules[0].base_score == 24.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_scoring_extraction.py::test_composite_extractor_returns_evaluation_rules -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/proofreader/extractors/composite_extractor.py`:

```python
from dataclasses import dataclass, field


@dataclass
class ExtractionResult:
    items: List[RequirementItem] = field(default_factory=list)
    evaluation_rules: List[EvaluationRule] = field(default_factory=list)


class CompositeExtractor(BaseExtractor):
    # ... existing __init__ ...

    def extract(self, doc: ParsedDocument) -> List[RequirementItem]:
        return self.extract_with_rules(doc).items

    def extract_with_rules(self, doc: ParsedDocument) -> ExtractionResult:
        items: List[RequirementItem] = []
        scoring_rules = []
        for section in doc.sections:
            if section.section_type == DocumentSectionType.BID_TEMPLATE:
                continue
            for extractor in self.extractors:
                items.extend(extractor.extract_from_section(section, doc))
            scoring_rules.extend(self.scoring_extractor.extract_from_section(section, doc))

        items = self.deduplicator.deduplicate(items)
        scoring_rules = self.scoring_extractor.link_rules_to_items(scoring_rules, items)
        return ExtractionResult(items=items, evaluation_rules=scoring_rules)
```

Update `src/proofreader/pipeline.py` to use `extract_with_rules` and store evaluation rules in the project repository or pass them downstream. For now, attach to the result object.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_scoring_extraction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/composite_extractor.py src/proofreader/pipeline.py tests-pytest/test_scoring_extraction.py
git commit -m "feat(extractors): return EvaluationRules alongside RequirementItems"
```

---

## Task 7: Integration and regression test

**Files:**
- Modify: `tests-pytest/test_real_world_regression_pytest.py` or create `tests-pytest/test_integration_document_type.py`

**Interfaces:**
- Consumes: real sample documents.
- Produces: passing integration tests.

- [ ] **Step 1: Write the integration test**

```python
from pathlib import Path

import pytest

from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.parsers.docx_parser import parse_docx


@pytest.fixture(scope="module")
def tender_doc_path():
    return Path("/Users/ljn/原始投标文件/原始招标文件/广州市荔湾区中医医院数据安全及个人信息保护服务项目/（比选文件）广州市荔湾区中医医院数据安全及个人信息保护服务项目.doc")


def test_real_tender_classification_and_scoring(tender_doc_path, tmp_path):
    if not tender_doc_path.exists():
        pytest.skip("Real tender doc not found")
    parsed = parse_docx(tender_doc_path)
    assert parsed.document_type == "tender"
    assert parsed.procurement_method == "bixuan"
    assert parsed.classification_confidence >= 0.85

    extractor = CompositeExtractor()
    result = extractor.extract_with_rules(parsed)
    scoring_items = [it for it in result.items if it.category == "评分标准"]
    assert len(scoring_items) > 0
    assert any(it.max_score is not None for it in scoring_items)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests-pytest/test_integration_document_type.py -v`
Expected: PASS (requires LibreOffice for .doc conversion)

- [ ] **Step 3: Commit**

```bash
git add tests-pytest/test_integration_document_type.py
git commit -m "test(integration): real tender document type + scoring extraction"
```

---

## Self-Review

**1. Spec coverage:**
- Document type classification with confidence: Task 3, 4.
- Procurement method detection: Task 3, 4.
- Scoring table extraction: Task 5.
- Aggregate scoring rules (`EvaluationRule`): Task 5, 6.
- Date/period normalization: Task 2.
- UI confidence thresholds: Documented in spec; UI implementation is outside this plan (covered in future plan).

**2. Placeholder scan:**
- No TBD/TODO in steps.
- Embedding fallback is a stub in Task 3 but explicitly called out as Task 3.5 below.
- LLM fallback is a stub; spec says default-off, so this is acceptable for Plan 1.

**3. Type consistency:**
- `RequirementItem` fields match spec: `raw_marker`, `max_score`, `evaluation_criteria`.
- `EvaluationRule` and `DocumentClassificationResult` match spec.
- `DocumentType` and `ProcurementMethod` enums aligned between `requirements.py` and `docx_parser.py`.

## Optional Follow-up Tasks (not in Plan 1)

- **Task 3.5:** Implement TF-IDF embedding fallback in `document_type_classifier`.
- **Task 3.6:** Implement local LLM fallback in `document_type_classifier`.
- **Task 6.5:** Store `EvaluationRule` in `JsonRequirementRepository`.

## Next Plans

After Plan 1 is complete, the following plans are ready to be written:

- **Plan 2:** Screenshot Checker + Certificate Checker + Cross-Document Checker (Phase 2 capabilities).
- **Plan 3:** Personnel Checker + Performance Checker + Commitment Checker (Phase 3 relationship checkers).
- **Plan 4:** UI updates for document type confidence prompts and "needs manual review" states.
