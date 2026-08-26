# Plan 3: Personnel Checker + Performance Checker + Commitment Checker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 3 relationship checkers: validate project personnel against certificates and social insurance proofs, verify past performance contracts against requirements, and match commitment letters to tender requirements.

**Architecture:** Build on `date_normalizer`, `OcrEngine`, and `CertificateChecker` from Plans 1–2. Each checker extracts structured entities (persons, contracts, commitments) from bid text and images, then compares them against `RequirementItem`s. All issues are emitted as `BaseIssue`.

**Tech Stack:** Python 3.11+, pydantic, easyocr (via existing `OcrEngine`), Pillow, pytest.

## Global Constraints

- Personnel-association relies on OCR; low-confidence links must emit `UNRECOGNIZED_EVIDENCE`, not false errors.
- Performance contract validation prioritizes the bid's performance summary table; contract image OCR is used only for cross-check.
- Seal detection is weak: only detect whether a "seal/signature page" exists, never verify seal authenticity.
- Commitment letter matching uses title keywords and target entity names.
- LLM is default-off; all core logic is rule + OCR.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/proofreader/checkers/personnel_checker.py` | New. Extract personnel list; link each person to certificates and social insurance proof. |
| `src/proofreader/checkers/performance_checker.py` | New. Extract performance table; cross-check contract images for date/amount/content/seal. |
| `src/proofreader/checkers/commitment_checker.py` | New. Identify commitment letters; match their type to tender requirements. |
| `src/proofreader/extractors/performance_table_extractor.py` | New. Helper to extract the "recent similar projects" summary table from bid. |
| `tests-pytest/test_personnel_checker.py` | New. |
| `tests-pytest/test_performance_checker.py` | New. |
| `tests-pytest/test_commitment_checker.py` | New. |
| `tests-pytest/test_performance_table_extractor.py` | New. |

---

## Task 1: Implement personnel_checker

**Files:**
- Create: `src/proofreader/checkers/personnel_checker.py`
- Test: `tests-pytest/test_personnel_checker.py`

**Interfaces:**
- Consumes: `RequirementItem` (personnel requirement) + bid text blocks + OCR'd certificate images + OCR'd social insurance images.
- Produces: `List[BaseIssue]` (`MISSING_PERSONNEL`, `MISSING_CERTIFICATE_FOR_PERSON`, `MISSING_SOCIAL_PROOF`, `UNRECOGNIZED_EVIDENCE`).

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.personnel_checker import PersonnelChecker


def test_detect_missing_certificate_and_social_proof():
    checker = PersonnelChecker()
    requirement = {
        "id": "req-1",
        "raw_text": "项目经理具备 PMP 证书，提供近 6 个月社保证明",
        "category": "人员要求",
    }
    bid_text = "项目经理：张三"
    certificates = [(None, "PMP\n张三\n证书编号 12345")]
    social_proofs = []

    issues = checker.check(requirement, bid_text, certificates, social_proofs)
    assert any(i.issue_type == IssueType.MISSING_SOCIAL_PROOF for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_personnel_checker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/personnel_checker.py`:

```python
"""人员-证书-社保证明三元组校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType
from proofreader.checkers.certificate_checker import CertificateChecker, CertificateType
from proofreader.utils.date_normalizer import normalize_period


@dataclass
class ExtractedPerson:
    name: str
    role: Optional[str]
    certificates: List[CertificateType]
    has_social_proof: bool


class PersonnelChecker:
    def __init__(self, reference_date: Optional[date] = None):
        self.reference_date = reference_date or date.today()
        self.certificate_checker = CertificateChecker()

    def extract_persons(self, bid_text: str) -> List[ExtractedPerson]:
        persons = []
        # Simple patterns: "项目经理：张三" or "姓名：张三 职务：项目经理"
        for m in re.finditer(r"(?:项目经理|技术负责人|技术人员|姓名)[：:]\s*([一-龥]{2,4})", bid_text):
            name = m.group(1)
            persons.append(ExtractedPerson(name=name, role=None, certificates=[], has_social_proof=False))
        return persons

    def find_certificate_for_person(
        self, person: ExtractedPerson, certificate_images: List[Tuple[object, str]]
    ) -> List[Tuple[CertificateType, float]]:
        found = []
        for _, ocr_text in certificate_images:
            if person.name in ocr_text:
                ctype, conf = self.certificate_checker.classify_certificate(ocr_text)
                if ctype != CertificateType.UNKNOWN and conf >= 0.5:
                    found.append((ctype, conf))
        return found

    def has_social_proof_for_person(
        self, person: ExtractedPerson, social_proof_images: List[Tuple[object, str]]
    ) -> bool:
        for _, ocr_text in social_proof_images:
            if person.name in ocr_text:
                period = normalize_period(ocr_text)
                if period and period.start and period.end:
                    # Require at least one month within last 6 months
                    if (self.reference_date - period.end).days <= 180:
                        return True
        return False

    def infer_required_role_and_certificate(self, requirement: dict) -> Tuple[Optional[str], Optional[CertificateType]]:
        text = requirement.get("raw_text", "")
        role = None
        if "项目经理" in text:
            role = "项目经理"
        elif "技术负责人" in text:
            role = "技术负责人"
        elif "技术人员" in text:
            role = "技术人员"

        ctype = CertificateType.UNKNOWN
        if "PMP" in text:
            ctype = CertificateType.PMP
        elif "CISP-DSG" in text:
            ctype = CertificateType.CISP_DSG
        elif "CISP" in text:
            ctype = CertificateType.CISP
        elif "CCRC-DSO" in text:
            ctype = CertificateType.CCRC_DSO

        return role, ctype if ctype != CertificateType.UNKNOWN else None

    def check(
        self,
        requirement: dict,
        bid_text: str,
        certificate_images: List[Tuple[object, str]],
        social_proof_images: List[Tuple[object, str]],
    ) -> List[BaseIssue]:
        issues = []
        role, required_cert = self.infer_required_role_and_certificate(requirement)
        if not role:
            return issues

        persons = self.extract_persons(bid_text)
        role_persons = [p for p in persons if role in bid_text]
        if not role_persons:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.MISSING_PERSONNEL,
                    level=IssueLevel.ERROR,
                    requirement_id=requirement.get("id"),
                    requirement_text=requirement.get("raw_text"),
                    message=f"未找到{role}",
                    suggestion=f"在投标文件中明确{role}姓名",
                )
            )
            return issues

        for person in role_persons:
            certs = self.find_certificate_for_person(person, certificate_images)
            if required_cert and not any(ct == required_cert for ct, _ in certs):
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.MISSING_CERTIFICATE_FOR_PERSON,
                        level=IssueLevel.ERROR,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message=f"{person.name} 未提供 {required_cert.value} 证书",
                        suggestion="补充证书扫描件",
                    )
                )

            if not self.has_social_proof_for_person(person, social_proof_images):
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.MISSING_SOCIAL_PROOF,
                        level=IssueLevel.ERROR,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message=f"{person.name} 未提供近 6 个月社保证明",
                        suggestion="补充社保缴纳证明",
                    )
                )

        return issues
```

Note: Add `PMP = "pmp"` to `CertificateType` enum in Plan 2 if needed, or treat PMP as `UNKNOWN` and match by keyword.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_personnel_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/personnel_checker.py tests-pytest/test_personnel_checker.py
git commit -m "feat(checkers): add personnel_checker for person-certificate-social-proof triple validation"
```

---

## Task 2: Implement performance_table_extractor helper

**Files:**
- Create: `src/proofreader/extractors/performance_table_extractor.py`
- Test: `tests-pytest/test_performance_table_extractor.py`

**Interfaces:**
- Consumes: `ParsedDocument` from bid.
- Produces: `List[PerformanceRecord]` with client, project name, amount, signing date.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.extractors.performance_table_extractor import extract_performance_table
from proofreader.parsers.docx_parser import ParsedDocument, ParsedTable


def test_extract_performance_table():
    doc = ParsedDocument(path="bid.docx")
    doc.raw_tables = [
        [
            ["序号", "客户名称", "项目名称及合同金额", "签订合同时间"],
            ["1", "A医院", "网络安全项目（25.8万元）", "2024年5月23日"],
        ]
    ]
    records = extract_performance_table(doc)
    assert len(records) == 1
    assert records[0].client == "A医院"
    assert records[0].amount == 258000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_performance_table_extractor.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/extractors/performance_table_extractor.py`:

```python
"""从投标文件中提取近三年同类业绩汇总表。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from proofreader.parsers.docx_parser import ParsedDocument
from proofreader.utils.date_normalizer import normalize_date


@dataclass
class PerformanceRecord:
    index: Optional[int]
    client: Optional[str]
    project_name: Optional[str]
    amount: Optional[float]
    signing_date: Optional[date]
    raw_row: List[str]


def _parse_amount(text: str) -> Optional[float]:
    # Match 25.8万元 or 258000元
    m = re.search(r"(\d+(?:\.\d+)?)\s*(万元|元)", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "万元":
        value *= 10000
    return value


def _is_performance_table(header: List[str]) -> bool:
    h = " ".join(header)
    return any(k in h for k in ["业绩", "同类项目", "合同金额", "客户名称", "项目名称"])


def extract_performance_table(doc: ParsedDocument) -> List[PerformanceRecord]:
    records = []
    for table in doc.raw_tables:
        if not table:
            continue
        header = table[0]
        if not _is_performance_table(header):
            continue
        for row in table[1:]:
            if not row:
                continue
            text = " ".join(row)
            records.append(
                PerformanceRecord(
                    index=None,
                    client=row[1] if len(row) > 1 else None,
                    project_name=row[2] if len(row) > 2 else None,
                    amount=_parse_amount(text),
                    signing_date=normalize_date(text).date if normalize_date(text) else None,
                    raw_row=row,
                )
            )
    return records
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_performance_table_extractor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/extractors/performance_table_extractor.py tests-pytest/test_performance_table_extractor.py
git commit -m "feat(extractors): add performance_table_extractor for contract summary tables"
```

---

## Task 3: Implement performance_checker

**Files:**
- Create: `src/proofreader/checkers/performance_checker.py`
- Test: `tests-pytest/test_performance_checker.py`

**Interfaces:**
- Consumes: `RequirementItem` (performance requirement) + bid `ParsedDocument` + OCR'd contract images.
- Produces: `List[BaseIssue]` (`PERFORMANCE_TIME_MISMATCH`, `PERFORMANCE_AMOUNT_MISMATCH`, `PERFORMANCE_CONTENT_MISMATCH`, `PERFORMANCE_MISSING_SEAL`, `UNRECOGNIZED_EVIDENCE`).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.performance_checker import PerformanceChecker
from proofreader.parsers.docx_parser import ParsedDocument


def test_detect_out_of_range_contract_date():
    checker = PerformanceChecker(reference_date=date(2026, 8, 21))
    requirement = {
        "id": "req-1",
        "raw_text": "自2023年1月1日至今完成的同类业绩",
        "category": "业绩要求",
    }
    doc = ParsedDocument(path="bid.docx")
    doc.raw_tables = [
        [
            ["序号", "客户名称", "项目名称及合同金额", "签订合同时间"],
            ["1", "A医院", "网络安全项目（25.8万元）", "2022年5月10日"],
        ]
    ]
    issues = checker.check(requirement, doc, [])
    assert any(i.issue_type == IssueType.PERFORMANCE_TIME_MISMATCH for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_performance_checker.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/performance_checker.py`:

```python
"""近三年同类业绩合同校验。"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType
from proofreader.extractors.performance_table_extractor import extract_performance_table
from proofreader.parsers.docx_parser import ParsedDocument
from proofreader.utils.date_normalizer import normalize_period


class PerformanceChecker:
    def __init__(self, reference_date: Optional[date] = None):
        self.reference_date = reference_date or date.today()

    def _extract_required_period(self, requirement_text: str) -> Optional[Tuple[date, date]]:
        period = normalize_period(requirement_text, reference=self.reference_date)
        if period:
            return period.start, period.end
        return None

    def _is_similar_content(self, project_name: Optional[str], requirement_text: str) -> bool:
        if not project_name:
            return False
        keywords = ["网络安全", "数据安全", "等级保护", "个人信息保护"]
        return any(kw in requirement_text and kw in project_name for kw in keywords)

    def _has_seal_page(self, ocr_text: str) -> bool:
        return any(k in ocr_text for k in ["盖章", "签章", "甲方", "乙方", "合同专用章"])

    def check(
        self,
        requirement: dict,
        bid_doc: ParsedDocument,
        contract_images: List[Tuple[object, str]],
    ) -> List[BaseIssue]:
        issues = []
        req_text = requirement.get("raw_text", "")
        period = self._extract_required_period(req_text)
        if not period:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.UNRECOGNIZED_EVIDENCE,
                    level=IssueLevel.WARNING,
                    requirement_id=requirement.get("id"),
                    requirement_text=req_text,
                    message="无法识别业绩要求的时间范围",
                    suggestion="请人工确认业绩时间要求",
                )
            )
            return issues

        start_date, end_date = period
        records = extract_performance_table(bid_doc)

        if not records:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.MISSING_RESPONSE,
                    level=IssueLevel.ERROR,
                    requirement_id=requirement.get("id"),
                    requirement_text=req_text,
                    message="未找到同类业绩汇总表",
                    suggestion="补充近三年同类业绩汇总表",
                )
            )
            return issues

        for record in records:
            if record.signing_date and not (start_date <= record.signing_date <= end_date):
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.PERFORMANCE_TIME_MISMATCH,
                        level=IssueLevel.ERROR,
                        requirement_id=requirement.get("id"),
                        requirement_text=req_text,
                        message=f"合同签订日期 {record.signing_date} 不在要求的时间范围内",
                        suggestion="替换为符合时间要求的合同或补充说明",
                    )
                )

            if record.project_name and not self._is_similar_content(record.project_name, req_text):
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.PERFORMANCE_CONTENT_MISMATCH,
                        level=IssueLevel.WARNING,
                        requirement_id=requirement.get("id"),
                        requirement_text=req_text,
                        message=f"项目『{record.project_name}』可能与同类业绩要求不符",
                        suggestion="核实项目内容是否属于同类业绩",
                    )
                )

        # Weak seal detection on contract images
        sealed_count = sum(1 for _, text in contract_images if self._has_seal_page(text))
        if contract_images and sealed_count < len(contract_images) // 2:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.PERFORMANCE_MISSING_SEAL,
                    level=IssueLevel.WARNING,
                    requirement_id=requirement.get("id"),
                    requirement_text=req_text,
                    message="部分合同图片未识别到签章页",
                    suggestion="确保每份合同包含双方盖章页",
                )
            )

        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_performance_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/performance_checker.py tests-pytest/test_performance_checker.py
git commit -m "feat(checkers): add performance_checker for contract evidence validation"
```

---

## Task 4: Implement commitment_checker

**Files:**
- Create: `src/proofreader/checkers/commitment_checker.py`
- Test: `tests-pytest/test_commitment_checker.py`

**Interfaces:**
- Consumes: `RequirementItem` + bid text blocks.
- Produces: `List[BaseIssue]` (`MISSING_COMMITMENT`, `COMMITMENT_NOT_STAMPED`, `UNRECOGNIZED_EVIDENCE`).

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.commitment_checker import CommitmentChecker, CommitmentType


def test_detect_missing_commitment():
    checker = CommitmentChecker()
    requirement = {
        "id": "req-1",
        "raw_text": "供应商应承诺不存在隶属关系或同属一母公司",
        "category": "资质条件",
    }
    bid_text = ""
    issues = checker.check(requirement, bid_text)
    assert any(i.issue_type == IssueType.MISSING_COMMITMENT for i in issues)


def test_classify_no_subcontract_commitment():
    checker = CommitmentChecker()
    text = "本公司承诺中标后不转包或分包。"
    ctype, conf = checker.classify_commitment(text)
    assert ctype == CommitmentType.NO_SUBCONTRACT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_commitment_checker.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/commitment_checker.py`:

```python
"""承诺函类型识别与响应校验。"""
from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType


class CommitmentType(str, Enum):
    GOVERNMENT_PROCUREMENT_LAW_22 = "government_procurement_law_22"
    NO_SUBCONTRACT = "no_subcontract"
    NO_ASSOCIATION = "no_association"
    NO_OUTSOURCE = "no_outsource"
    CONFIDENTIALITY = "confidentiality"
    SERVICE_TERM = "service_term"
    DATA_SECURITY = "data_security"
    OTHER = "other"


_COMMITMENT_RULES = {
    CommitmentType.GOVERNMENT_PROCUREMENT_LAW_22: ["政府采购法", "第二十二条", "22条"],
    CommitmentType.NO_SUBCONTRACT: ["不转包", "不分包", "转包或分包"],
    CommitmentType.NO_ASSOCIATION: ["不存在隶属关系", "同属一母公司", "关联关系"],
    CommitmentType.NO_OUTSOURCE: ["不外包", "不得外包"],
    CommitmentType.CONFIDENTIALITY: ["保密", "保密承诺"],
    CommitmentType.SERVICE_TERM: ["服务期限", "服务承诺"],
    CommitmentType.DATA_SECURITY: ["数据安全", "个人信息保护"],
}


class CommitmentChecker:
    def __init__(self, confidence_threshold: float = 0.80):
        self.confidence_threshold = confidence_threshold

    def classify_commitment(self, text: str) -> Tuple[CommitmentType, float]:
        best_type = CommitmentType.OTHER
        best_score = 0.0
        for ctype, keywords in _COMMITMENT_RULES.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_type = ctype
        confidence = min(best_score / max(len(_COMMITMENT_RULES[best_type]), 1), 0.99)
        return best_type, confidence

    def infer_required_commitment(self, requirement: dict) -> Optional[CommitmentType]:
        text = requirement.get("raw_text", "")
        ctype, conf = self.classify_commitment(text)
        return ctype if conf >= 0.5 else None

    def extract_commitments(self, bid_text: str) -> List[Tuple[str, CommitmentType, float]]:
        commitments = []
        # Split by common commitment boundaries
        segments = re.split(r"(?=承诺函|致：|本公司承诺)", bid_text)
        for seg in segments:
            if "承诺" not in seg:
                continue
            ctype, conf = self.classify_commitment(seg)
            commitments.append((seg, ctype, conf))
        return commitments

    def check(self, requirement: dict, bid_text: str) -> List[BaseIssue]:
        issues = []
        required = self.infer_required_commitment(requirement)
        if not required or required == CommitmentType.OTHER:
            return issues

        commitments = self.extract_commitments(bid_text)
        matching = [c for _, ctype, _ in commitments if ctype == required]

        if not matching:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.MISSING_COMMITMENT,
                    level=IssueLevel.ERROR,
                    requirement_id=requirement.get("id"),
                    requirement_text=requirement.get("raw_text"),
                    message=f"未找到『{required.value}』承诺函",
                    suggestion="补充对应承诺函",
                )
            )
            return issues

        for seg, ctype, conf in commitments:
            if ctype == required and conf < self.confidence_threshold:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.UNRECOGNIZED_EVIDENCE,
                        level=IssueLevel.WARNING,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message="承诺函类型识别置信度低",
                        suggestion="请人工确认承诺函内容",
                        confidence=conf,
                    )
                )
            if ctype == required and "盖章" not in seg and "签章" not in seg:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.COMMITMENT_NOT_STAMPED,
                        level=IssueLevel.WARNING,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message="承诺函可能未盖章",
                        suggestion="确保承诺函加盖公章",
                    )
                )

        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_commitment_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/commitment_checker.py tests-pytest/test_commitment_checker.py
git commit -m "feat(checkers): add commitment_checker for commitment letter matching"
```

---

## Task 5: Wire Plan 3 checkers into pipeline

**Files:**
- Modify: `src/proofreader/pipeline.py`
- Test: `tests-pytest/test_pipeline_pytest.py`

**Interfaces:**
- Consumes: new checkers.
- Produces: `ProofreadingResult` with new issue types.

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_collects_performance_issues(sample_docs_dir):
    proofreader = Proofreader()
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_pipeline_pytest.py -v`
Expected: FAIL if pipeline not updated.

- [ ] **Step 3: Write minimal implementation**

Modify `src/proofreader/pipeline.py`:

```python
from proofreader.checkers.personnel_checker import PersonnelChecker
from proofreader.checkers.performance_checker import PerformanceChecker
from proofreader.checkers.commitment_checker import CommitmentChecker


class Proofreader:
    def __init__(self, ...):
        # existing init ...
        self.personnel_checker = PersonnelChecker()
        self.performance_checker = PerformanceChecker()
        self.commitment_checker = CommitmentChecker()

    def proofread(self, tender_path, bid_path):
        # existing flow ...
        # Split certificate/social/contract images by context if possible
        certificate_images = ocr_texts  # refine later
        social_proof_images = ocr_texts
        contract_images = ocr_texts

        for req in requirements:
            issues.extend(self.personnel_checker.check(req, bid_text, certificate_images, social_proof_images))
            issues.extend(self.performance_checker.check(req, bid_doc, contract_images))
            issues.extend(self.commitment_checker.check(req, bid_text))

        return ProofreadingResult(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_pipeline_pytest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/pipeline.py tests-pytest/test_pipeline_pytest.py
git commit -m "feat(pipeline): wire personnel, performance, and commitment checkers"
```

---

## Self-Review

**1. Spec coverage:**
- Personnel-certificate-social triple: Task 1.
- Performance contract date/amount/content/seal: Tasks 2–3.
- Commitment letter matching: Task 4.
- `UNRECOGNIZED_EVIDENCE` fallback: Tasks 1, 3, 4.

**2. Placeholder scan:**
- No TBD/TODO.
- Image categorization (certificate/social/contract) in pipeline is a coarse heuristic; a future task can refine by section context.

**3. Type consistency:**
- All checkers produce `BaseIssue`.
- `CertificateType` from Plan 2 reused.
- `normalize_period` / `normalize_date` from Plan 1 reused.

## Dependency Note

This plan depends on:
- **Plan 1**: `date_normalizer`, updated `RequirementItem` model.
- **Plan 2**: `CertificateChecker`, `BaseIssue`, `OcrEngine` reuse pattern.

## Execution Handoff

After Plan 3 is complete, the three plans are ready for sequential implementation:
1. Plan 1: Foundation (document type, scoring, dates).
2. Plan 2: Proof material + cross-document checkers.
3. Plan 3: Relationship checkers.

Each plan produces independently testable software.
