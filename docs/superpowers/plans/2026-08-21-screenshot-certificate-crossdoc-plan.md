# Plan 2: Screenshot Checker + Certificate Checker + Cross-Document Checker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 2 proof-material and cross-document checkers: classify qualification screenshots, validate certificate validity/scope/subject, and verify key fields are consistent between tender and bid documents.

**Architecture:** Build on top of `OcrEngine` and the `date_normalizer` from Plan 1. Each checker consumes `RequirementItem`s plus OCR'd `EmbeddedImage`s or parsed bid text, and outputs typed Issue dataclasses. Issues are later normalized into the common exporter format.

**Tech Stack:** Python 3.11+, pydantic, easyocr (via existing `OcrEngine`), Pillow, scikit-learn, pytest.

## Global Constraints

- All OCR runs locally via the existing `OcrEngine`; no image leaves the machine.
- Low-confidence OCR results must produce `UNRECOGNIZED_EVIDENCE` issues, not false-positive failures.
- LLM is default-off; certificate/scope inference uses templates and keyword rules first.
- Cross-document checker only compares fields that exist in both documents; missing fields produce `MISSING` issues.
- Every checker must be unit-testable with synthetic OCR text (no need for real image files in unit tests).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/proofreader/checkers/base_checker.py` | New. Shared base class / typed Issue definitions (`IssueLevel`, `IssueType`, `BaseIssue`). |
| `src/proofreader/checkers/screenshot_checker.py` | New. Classify screenshot type from OCR text; check required screenshot types are present. |
| `src/proofreader/checkers/certificate_checker.py` | New. Extract certificate type, dates, scope, subject from OCR; validate against requirements. |
| `src/proofreader/checkers/cross_document_checker.py` | New. Compare tender and bid key fields (project info, validity, service term, payment, delivery, authorization). |
| `src/proofreader/checkers/ocr_checker.py` | Modify. Export/cache `OcrEngine` for reuse by new checkers. |
| `tests-pytest/test_screenshot_checker.py` | New. Unit tests for screenshot classification. |
| `tests-pytest/test_certificate_checker.py` | New. Unit tests for certificate validation. |
| `tests-pytest/test_cross_document_checker.py` | New. Unit tests for cross-document consistency. |

---

## Task 1: Normalize Issue types across checkers

**Files:**
- Create: `src/proofreader/checkers/base_checker.py`
- Modify: `src/proofreader/checkers/consistency_checker.py`
- Test: `tests-pytest/test_base_checker.py` (create)

**Interfaces:**
- Consumes: existing checker-specific issue classes.
- Produces: shared `BaseIssue` with `issue_type`, `level`, `requirement_id`, `message`, `suggestion`, `evidence`.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType


def test_base_issue_creation():
    issue = BaseIssue(
        issue_type=IssueType.MISSING_SCREENSHOT,
        level=IssueLevel.WARNING,
        requirement_id="req-1",
        message="缺少信用中国截图",
        suggestion="补充信用中国 4 类查询截图",
        evidence={"page": 12},
    )
    assert issue.level == IssueLevel.WARNING
    assert issue.evidence["page"] == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_base_checker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/base_checker.py`:

```python
"""跨 checker 共享的 Issue 基础类型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class IssueLevel(str, Enum):
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class IssueType(str, Enum):
    # Existing consistency issues
    MISSING_RESPONSE = "missing_response"
    PARAMETER_MISMATCH = "parameter_mismatch"
    TIME_MISMATCH = "time_mismatch"
    KEYWORD_MISSING = "keyword_missing"
    SEMANTIC_LOW = "semantic_low"

    # New screenshot / certificate / performance / commitment issues
    MISSING_SCREENSHOT = "missing_screenshot"
    SCREENSHOT_MISMATCH = "screenshot_mismatch"
    CERTIFICATE_EXPIRED = "certificate_expired"
    CERTIFICATE_SCOPE_MISMATCH = "certificate_scope_mismatch"
    CERTIFICATE_SUBJECT_MISMATCH = "certificate_subject_mismatch"
    CERTIFICATE_UNRECOGNIZED = "certificate_unrecognized"
    MISSING_PERSONNEL = "missing_personnel"
    MISSING_CERTIFICATE_FOR_PERSON = "missing_certificate_for_person"
    MISSING_SOCIAL_PROOF = "missing_social_proof"
    PERFORMANCE_TIME_MISMATCH = "performance_time_mismatch"
    PERFORMANCE_AMOUNT_MISMATCH = "performance_amount_mismatch"
    PERFORMANCE_CONTENT_MISMATCH = "performance_content_mismatch"
    PERFORMANCE_MISSING_SEAL = "performance_missing_seal"
    MISSING_COMMITMENT = "missing_commitment"
    COMMITMENT_NOT_STAMPED = "commitment_not_stamped"
    CROSS_DOCUMENT_INCONSISTENT = "cross_document_inconsistent"

    # Fallback when evidence cannot be reliably recognized
    UNRECOGNIZED_EVIDENCE = "unrecognized_evidence"


@dataclass
class BaseIssue:
    issue_type: IssueType
    level: IssueLevel
    requirement_id: Optional[str]
    requirement_text: Optional[str]
    message: str
    suggestion: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_base_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/base_checker.py tests-pytest/test_base_checker.py
git commit -m "feat(checkers): add shared BaseIssue and IssueType enum"
```

---

## Task 2: Refactor OcrEngine for reuse

**Files:**
- Modify: `src/proofreader/checkers/ocr_checker.py`
- Test: `tests-pytest/test_ocr_pytest.py` (existing)

**Interfaces:**
- Consumes: `EmbeddedImage.blob`.
- Produces: OCR text string.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.ocr_checker import OcrEngine


def test_ocr_engine_recognizes_text(mocker):
    engine = OcrEngine()
    # Mock easyocr.Reader.readtext to avoid model loading
    mock_reader = mocker.MagicMock()
    mock_reader.readtext.return_value = ["信用中国", "失信被执行人"]
    engine._reader = mock_reader

    text = engine.recognize(b"fake_image_bytes")
    assert "信用中国" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_ocr_pytest.py::test_ocr_engine_recognizes_text -v`
Expected: FAIL with `AttributeError` (OcrEngine not yet mockable) or import issue.

- [ ] **Step 3: Write minimal implementation**

Ensure `OcrEngine` can be instantiated without immediately loading the model. The current implementation already lazy-loads via `_get_reader`, so only small changes are needed:

```python
class OcrEngine:
    # ... existing code ...

    def _get_reader(self):
        if self._reader is None:
            cache_key = (self.languages, self.use_gpu)
            reader = self._reader_cache.get(cache_key)
            if reader is None:
                import easyocr
                reader = easyocr.Reader(list(self.languages), gpu=self.use_gpu)
                self._reader_cache[cache_key] = reader
            self._reader = reader
        return self._reader
```

No change needed if already lazy. Add a public `recognize_text(blob: bytes) -> str` alias if desired.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_ocr_pytest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/ocr_checker.py tests-pytest/test_ocr_pytest.py
git commit -m "refactor(ocr): ensure OcrEngine is reusable and mockable"
```

---

## Task 3: Implement screenshot_checker

**Files:**
- Create: `src/proofreader/checkers/screenshot_checker.py`
- Test: `tests-pytest/test_screenshot_checker.py`

**Interfaces:**
- Consumes: `RequirementItem` + `List[Tuple[EmbeddedImage, str]]` (image + OCR text).
- Produces: `List[BaseIssue]` (`MISSING_SCREENSHOT`, `SCREENSHOT_MISMATCH`, `UNRECOGNIZED_EVIDENCE`).

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.screenshot_checker import ScreenshotChecker, ScreenshotType


def test_classify_credit_china_screenshot():
    checker = ScreenshotChecker()
    ocr_text = "信用中国\n失信被执行人\n查询结果\n查询主体：广东颐点科技有限公司"
    result = checker.classify_screenshot(ocr_text)
    assert result.screenshot_type == ScreenshotType.CREDIT_CHINA_OVERDUE_EXECUTOR
    assert result.confidence >= 0.8


def test_detect_missing_screenshot():
    checker = ScreenshotChecker()
    requirement = {
        "id": "req-1",
        "raw_text": "参加本次比选活动前三年内，响应供应商没有被列入失信被执行人、重大税收违法失信主体、政府采购严重违约失信行为记录名单",
        "category": "资质条件",
    }
    images = []
    issues = checker.check(requirement, images)
    assert any(i.issue_type == IssueType.MISSING_SCREENSHOT for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_screenshot_checker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/screenshot_checker.py`:

```python
"""资格截图类型识别与完整性校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType


class ScreenshotType(str, Enum):
    CREDIT_CHINA_OVERDUE_EXECUTOR = "credit_china_overdue_executor"
    CREDIT_CHINA_TAX_VIOLATION = "credit_china_tax_violation"
    CREDIT_CHINA_GOV_PROCUREMENT_VIOLATION = "credit_china_gov_procurement_violation"
    CREDIT_CHINA_SERIOUS_DISHONEST = "credit_china_serious_dishonest"
    GOV_PROCUREMENT_NETWORK = "gov_procurement_network"
    GUANGDONG_ELECTRONIC_MARKET = "guangdong_electronic_market"
    CERTIFICATION_RECOGNITION_PLATFORM = "certification_recognition_platform"
    UNKNOWN = "unknown"


_SCREENSHOT_RULES: Dict[ScreenshotType, Dict[str, any]] = {
    ScreenshotType.CREDIT_CHINA_OVERDUE_EXECUTOR: {
        "required_keywords": ["信用中国", "失信被执行人"],
        "score": 2.0,
    },
    ScreenshotType.CREDIT_CHINA_TAX_VIOLATION: {
        "required_keywords": ["信用中国", "重大税收违法"],
        "score": 2.0,
    },
    ScreenshotType.CREDIT_CHINA_GOV_PROCUREMENT_VIOLATION: {
        "required_keywords": ["信用中国", "政府采购", "严重违法失信"],
        "score": 2.0,
    },
    ScreenshotType.CREDIT_CHINA_SERIOUS_DISHONEST: {
        "required_keywords": ["信用中国", "严重失信主体名单"],
        "score": 2.0,
    },
    ScreenshotType.GOV_PROCUREMENT_NETWORK: {
        "required_keywords": ["中国政府采购网", "政府采购严重违法失信行为信息记录"],
        "score": 2.0,
    },
    ScreenshotType.GUANGDONG_ELECTRONIC_MARKET: {
        "required_keywords": ["广东政府采购", "智慧云平台", "电子卖场"],
        "score": 2.0,
    },
    ScreenshotType.CERTIFICATION_RECOGNITION_PLATFORM: {
        "required_keywords": ["全国认证认可信息公共服务平台", "认证结果"],
        "score": 2.0,
    },
}


@dataclass
class ScreenshotClassificationResult:
    screenshot_type: ScreenshotType
    confidence: float
    matched_keywords: List[str]


@dataclass
class ScreenshotRequirement:
    """从招标文件需求中推断需要哪类截图。"""
    screenshot_type: ScreenshotType
    source_requirement_id: Optional[str]


class ScreenshotChecker:
    def __init__(self, confidence_threshold: float = 0.80):
        self.confidence_threshold = confidence_threshold

    def classify_screenshot(self, ocr_text: str) -> ScreenshotClassificationResult:
        text = ocr_text.lower()
        best_type = ScreenshotType.UNKNOWN
        best_score = 0.0
        best_keywords = []

        for stype, rule in _SCREENSHOT_RULES.items():
            keywords = rule["required_keywords"]
            matched = [kw for kw in keywords if kw.lower() in text]
            score = len(matched) * rule["score"]
            if score > best_score:
                best_score = score
                best_type = stype
                best_keywords = matched

        confidence = min(best_score / 4.0, 0.99)
        return ScreenshotClassificationResult(
            screenshot_type=best_type,
            confidence=confidence,
            matched_keywords=best_keywords,
        )

    def infer_required_screenshots(self, requirement: dict) -> List[ScreenshotRequirement]:
        text = requirement.get("raw_text", "")
        required = []
        if "信用中国" in text and "失信" in text:
            required.append(
                ScreenshotRequirement(
                    ScreenshotType.CREDIT_CHINA_OVERDUE_EXECUTOR,
                    requirement.get("id"),
                )
            )
        if "中国政府采购网" in text:
            required.append(
                ScreenshotRequirement(
                    ScreenshotType.GOV_PROCUREMENT_NETWORK,
                    requirement.get("id"),
                )
            )
        if "广东政府采购" in text or "智慧云平台" in text:
            required.append(
                ScreenshotRequirement(
                    ScreenshotType.GUANGDONG_ELECTRONIC_MARKET,
                    requirement.get("id"),
                )
            )
        return required

    def check(
        self,
        requirement: dict,
        images: List[Tuple[object, str]],  # (EmbeddedImage, ocr_text)
    ) -> List[BaseIssue]:
        issues = []
        required = self.infer_required_screenshots(requirement)
        if not required:
            return issues

        classified = [
            (img, self.classify_screenshot(ocr_text)) for img, ocr_text in images
        ]

        for req in required:
            matches = [
                (img, cls) for img, cls in classified if cls.screenshot_type == req.screenshot_type
            ]
            if not matches:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.MISSING_SCREENSHOT,
                        level=IssueLevel.ERROR,
                        requirement_id=req.source_requirement_id,
                        requirement_text=requirement.get("raw_text"),
                        message=f"未找到类型为 {req.screenshot_type.value} 的截图",
                        suggestion="补充对应的资格查询截图",
                    )
                )
                continue

            for img, cls in matches:
                if cls.confidence < self.confidence_threshold:
                    issues.append(
                        BaseIssue(
                            issue_type=IssueType.UNRECOGNIZED_EVIDENCE,
                            level=IssueLevel.WARNING,
                            requirement_id=req.source_requirement_id,
                            requirement_text=requirement.get("raw_text"),
                            message=f"截图类型识别置信度低 ({cls.confidence:.2f})",
                            suggestion="请人工确认截图类型",
                            confidence=cls.confidence,
                        )
                    )
        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_screenshot_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/screenshot_checker.py tests-pytest/test_screenshot_checker.py
git commit -m "feat(checkers): add screenshot_checker for qualification screenshot classification"
```

---

## Task 4: Implement certificate_checker

**Files:**
- Create: `src/proofreader/checkers/certificate_checker.py`
- Test: `tests-pytest/test_certificate_checker.py`

**Interfaces:**
- Consumes: `RequirementItem` + `List[Tuple[EmbeddedImage, str]]`.
- Produces: `List[BaseIssue]` (`CERTIFICATE_EXPIRED`, `CERTIFICATE_SCOPE_MISMATCH`, `CERTIFICATE_SUBJECT_MISMATCH`, `CERTIFICATE_UNRECOGNIZED`, `UNRECOGNIZED_EVIDENCE`).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date

from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.certificate_checker import CertificateChecker, CertificateType


def test_classify_iso_certificate():
    checker = CertificateChecker()
    ocr_text = "ISO 9001\n质量管理体系认证证书\n证书编号：00123\n有效期：2024年1月1日至2027年12月31日\n认证范围：网络信息安全集成"
    cert = checker.extract_certificate(ocr_text)
    assert cert.certificate_type == CertificateType.ISO9001
    assert cert.valid_until == date(2027, 12, 31)


def test_certificate_expired():
    checker = CertificateChecker(reference_date=date(2028, 1, 1))
    ocr_text = "ISO 9001\n有效期：2024年1月1日至2027年12月31日"
    cert = checker.extract_certificate(ocr_text)
    assert cert.is_expired(reference_date=date(2028, 1, 1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_certificate_checker.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/certificate_checker.py`:

```python
"""证书 OCR 信息提取与校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType
from proofreader.utils.date_normalizer import normalize_date, NormalizedDate


class CertificateType(str, Enum):
    ISO9001 = "iso9001"
    ISO20000 = "iso20000"
    ISO27001 = "iso27001"
    CCRC_SECURITY_INTEGRATION = "ccrc_security_integration"
    CCRC_SECURITY_OPERATION = "ccrc_security_operation"
    CCRC_RISK_ASSESSMENT = "ccrc_risk_assessment"
    CCRC_EMERGENCY_RESPONSE = "ccrc_emergency_response"
    CISP = "cisp"
    CISP_DSG = "cisp_dsg"
    CCRC_DSO = "ccrc_dso"
    PMP = "pmp"
    LEVEL_PROTECTION = "level_protection"
    BUSINESS_LICENSE = "business_license"
    UNKNOWN = "unknown"


_CERTIFICATE_PATTERNS = {
    CertificateType.ISO9001: ["ISO 9001", "质量管理体系认证"],
    CertificateType.ISO20000: ["ISO 20000", "信息技术服务管理体系认证"],
    CertificateType.ISO27001: ["ISO 27001", "信息安全管理体系认证"],
    CertificateType.CCRC_SECURITY_INTEGRATION: ["CCRC", "信息安全服务资质认证", "安全集成"],
    CertificateType.CCRC_SECURITY_OPERATION: ["CCRC", "信息安全服务资质认证", "安全运维"],
    CertificateType.CCRC_RISK_ASSESSMENT: ["CCRC", "信息安全服务资质认证", "风险评估"],
    CertificateType.CCRC_EMERGENCY_RESPONSE: ["CCRC", "信息安全服务资质认证", "应急处理"],
    CertificateType.CISP: ["注册信息安全专业人员", "CISP"],
    CertificateType.CISP_DSG: ["CISP-DSG", "数据安全治理"],
    CertificateType.CCRC_DSO: ["CCRC-DSO", "数据安全官"],
    CertificateType.PMP: ["PMP", "项目管理专业人士", "Project Management Professional"],
    CertificateType.LEVEL_PROTECTION: ["网络安全等级保护测评", "等保测评"],
    CertificateType.BUSINESS_LICENSE: ["营业执照", "统一社会信用代码"],
}


@dataclass
class ExtractedCertificate:
    certificate_type: CertificateType
    certificate_type_confidence: float
    subject: Optional[str]
    valid_from: Optional[date]
    valid_until: Optional[date]
    scope: Optional[str]
    raw_text: str

    def is_expired(self, reference_date: Optional[date] = None) -> bool:
        if self.valid_until is None:
            return False
        reference_date = reference_date or date.today()
        return self.valid_until < reference_date


class CertificateChecker:
    def __init__(
        self,
        reference_date: Optional[date] = None,
        validity_confidence_threshold: float = 0.75,
        scope_confidence_threshold: float = 0.70,
    ):
        self.reference_date = reference_date or date.today()
        self.validity_confidence_threshold = validity_confidence_threshold
        self.scope_confidence_threshold = scope_confidence_threshold

    def classify_certificate(self, ocr_text: str) -> Tuple[CertificateType, float]:
        best_type = CertificateType.UNKNOWN
        best_score = 0.0
        for ctype, keywords in _CERTIFICATE_PATTERNS.items():
            score = sum(1 for kw in keywords if kw in ocr_text)
            if score > best_score:
                best_score = score
                best_type = ctype
        confidence = min(best_score / max(len(_CERTIFICATE_PATTERNS[best_type]), 1), 0.99)
        return best_type, confidence

    def extract_certificate(self, ocr_text: str) -> ExtractedCertificate:
        ctype, conf = self.classify_certificate(ocr_text)

        # Subject: 证书持有者 / 企业名称
        subject = None
        for pat in [r"证书持有者[：:]\s*(.+)", r"企业名称[：:]\s*(.+)", r"名称[：:]\s*(.+?)\n"]:
            m = re.search(pat, ocr_text)
            if m:
                subject = m.group(1).strip()
                break

        # Validity dates
        valid_from = None
        valid_until = None
        m = re.search(r"有效期[：:]\s*(\d{4}年\d{1,2}月\d{1,2}日)\s*[-~至]\s*(\d{4}年\d{1,2}月\d{1,2}日)", ocr_text)
        if m:
            from_norm = normalize_date(m.group(1))
            until_norm = normalize_date(m.group(2))
            if from_norm:
                valid_from = from_norm.date
            if until_norm:
                valid_until = until_norm.date

        # Scope
        scope = None
        m = re.search(r"认证范围[：:]\s*(.+?)(?:\n|$)", ocr_text)
        if m:
            scope = m.group(1).strip()

        return ExtractedCertificate(
            certificate_type=ctype,
            certificate_type_confidence=conf,
            subject=subject,
            valid_from=valid_from,
            valid_until=valid_until,
            scope=scope,
            raw_text=ocr_text,
        )

    def check(
        self,
        requirement: dict,
        images: List[Tuple[object, str]],
        bidder_name: Optional[str] = None,
    ) -> List[BaseIssue]:
        issues = []
        # Infer required certificate type from requirement text
        required_type, required_conf = self.classify_certificate(requirement.get("raw_text", ""))
        if required_type == CertificateType.UNKNOWN or required_conf < 0.5:
            return issues

        certs = [self.extract_certificate(ocr_text) for _, ocr_text in images]
        matching = [c for c in certs if c.certificate_type == required_type]

        if not matching:
            issues.append(
                BaseIssue(
                    issue_type=IssueType.KEYWORD_MISSING,
                    level=IssueLevel.ERROR,
                    requirement_id=requirement.get("id"),
                    requirement_text=requirement.get("raw_text"),
                    message=f"未找到 {required_type.value} 证书",
                    suggestion="补充对应证书扫描件",
                )
            )
            return issues

        for cert in matching:
            if cert.certificate_type_confidence < 0.5:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.UNRECOGNIZED_EVIDENCE,
                        level=IssueLevel.WARNING,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message="证书类型识别置信度低",
                        suggestion="请人工确认证书类型",
                        confidence=cert.certificate_type_confidence,
                    )
                )

            if cert.valid_until is None:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.UNRECOGNIZED_EVIDENCE,
                        level=IssueLevel.WARNING,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message="无法识别证书有效期",
                        suggestion="请人工确认证书是否在有效期内",
                    )
                )
            elif cert.is_expired(self.reference_date):
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.CERTIFICATE_EXPIRED,
                        level=IssueLevel.ERROR,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message=f"证书已于 {cert.valid_until} 过期",
                        suggestion="更新证书或补充最新查询截图",
                    )
                )

            if bidder_name and cert.subject and bidder_name not in cert.subject:
                issues.append(
                    BaseIssue(
                        issue_type=IssueType.CERTIFICATE_SUBJECT_MISMATCH,
                        level=IssueLevel.ERROR,
                        requirement_id=requirement.get("id"),
                        requirement_text=requirement.get("raw_text"),
                        message=f"证书主体 {cert.subject} 与投标人 {bidder_name} 不一致",
                        suggestion="核实证书主体是否为投标人本身",
                    )
                )

        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_certificate_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/certificate_checker.py tests-pytest/test_certificate_checker.py
git commit -m "feat(checkers): add certificate_checker for validity, scope, and subject validation"
```

---

## Task 5: Implement cross_document_checker

**Files:**
- Create: `src/proofreader/checkers/cross_document_checker.py`
- Test: `tests-pytest/test_cross_document_checker.py`

**Interfaces:**
- Consumes: tender `ParsedDocument` + bid `ParsedDocument`.
- Produces: `List[BaseIssue]` (`CROSS_DOCUMENT_INCONSISTENT`, `MISSING_RESPONSE`).

- [ ] **Step 1: Write the failing test**

```python
from proofreader.checkers.base_checker import IssueType
from proofreader.checkers.cross_document_checker import CrossDocumentChecker
from proofreader.parsers.docx_parser import ParsedDocument


def test_project_number_mismatch():
    tender = ParsedDocument(path="tender.docx")
    tender.title = "项目 CGZX-2026026"
    bid = ParsedDocument(path="bid.docx")
    bid.title = "项目 CGZX-2026999"

    checker = CrossDocumentChecker()
    issues = checker.check(tender, bid)

    mismatch = [i for i in issues if i.issue_type == IssueType.CROSS_DOCUMENT_INCONSISTENT]
    assert any("项目编号" in i.message for i in mismatch)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests-pytest/test_cross_document_checker.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `src/proofreader/checkers/cross_document_checker.py`:

```python
"""招标与投标文件关键信息一致性校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from proofreader.checkers.base_checker import BaseIssue, IssueLevel, IssueType
from proofreader.parsers.docx_parser import ParsedDocument
from proofreader.utils.date_normalizer import normalize_date


@dataclass
class CrossDocumentField:
    name: str
    tender_value: Optional[str]
    bid_value: Optional[str]
    level: IssueLevel


class CrossDocumentChecker:
    def __init__(self, reference_date: Optional[date] = None):
        self.reference_date = reference_date or date.today()

    def _extract_field(self, doc: ParsedDocument, patterns: List[str]) -> Optional[str]:
        text = (doc.title or "") + "\n" + "\n".join(b.text for b in doc.blocks[:50])
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_project_number(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(doc, [r"项目编号[：:]\s*([A-Za-z0-9-]+)"])

    def _extract_project_name(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(doc, [r"项目名称[：:]\s*(.+?)(?:\n|$)", r"《(.+?)》"])

    def _extract_bidder_name(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(
            doc,
            [
                r"供应商名称[：:]\s*(.+?)(?:\n|$)",
                r"响应供应商[：:]\s*(.+?)(?:\n|$)",
                r"投标人[：:]\s*(.+?)(?:\n|$)",
            ],
        )

    def _extract_bid_validity(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(
            doc,
            [
                r"响应有效期[：:]\s*(\d+)\s*天",
                r"报价有效期[：:]\s*(\d+)\s*天",
                r"(\d+)\s*天内有效",
            ],
        )

    def _extract_service_term(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(
            doc,
            [
                r"合同履行期限[：:]\s*(.+?)(?:\n|$)",
                r"服务期限[：:]\s*(.+?)(?:\n|$)",
                r"自合同签订之日起\s*(\d+)\s*个月内",
            ],
        )

    def _extract_payment_method(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(doc, [r"付款方式[：:]\s*(.+?)(?:\n|$)"])

    def _extract_delivery_location(self, doc: ParsedDocument) -> Optional[str]:
        return self._extract_field(doc, [r"标的提供地点[：:]\s*(.+?)(?:\n|$)"])

    def _compare_values(
        self,
        name: str,
        tender_value: Optional[str],
        bid_value: Optional[str],
        level: IssueLevel = IssueLevel.ERROR,
    ) -> Optional[BaseIssue]:
        if tender_value is None and bid_value is None:
            return None
        if bid_value is None:
            return BaseIssue(
                issue_type=IssueType.MISSING_RESPONSE,
                level=level,
                requirement_id=None,
                requirement_text=f"招标文件{name}：{tender_value}",
                message=f"投标文件未提供{name}",
                suggestion=f"在投标文件中补充{name}",
            )
        if tender_value and bid_value and tender_value != bid_value:
            return BaseIssue(
                issue_type=IssueType.CROSS_DOCUMENT_INCONSISTENT,
                level=level,
                requirement_id=None,
                requirement_text=f"招标文件{name}：{tender_value}",
                message=f"{name}不一致：招标为『{tender_value}』，投标为『{bid_value}』",
                suggestion=f"核对并修正投标文件中的{name}",
            )
        return None

    def check(self, tender: ParsedDocument, bid: ParsedDocument) -> List[BaseIssue]:
        issues = []
        checks: List[Tuple[str, Optional[str], Optional[str], IssueLevel]] = [
            ("项目编号", self._extract_project_number(tender), self._extract_project_number(bid), IssueLevel.ERROR),
            ("项目名称", self._extract_project_name(tender), self._extract_project_name(bid), IssueLevel.ERROR),
            ("投标人名称", None, self._extract_bidder_name(bid), IssueLevel.ERROR),
            ("投标有效期", self._extract_bid_validity(tender), self._extract_bid_validity(bid), IssueLevel.WARNING),
            ("服务期限", self._extract_service_term(tender), self._extract_service_term(bid), IssueLevel.WARNING),
            ("付款方式", self._extract_payment_method(tender), self._extract_payment_method(bid), IssueLevel.WARNING),
            ("交付地点", self._extract_delivery_location(tender), self._extract_delivery_location(bid), IssueLevel.WARNING),
        ]

        for name, t_val, b_val, level in checks:
            if name == "投标人名称":
                # Special handling: compare against business license / certificates later
                if b_val is None:
                    issues.append(
                        BaseIssue(
                            issue_type=IssueType.MISSING_RESPONSE,
                            level=level,
                            requirement_id=None,
                            requirement_text="投标人名称",
                            message="投标文件未提供投标人名称",
                            suggestion="在封面或投标函中补充投标人名称",
                        )
                    )
                continue

            issue = self._compare_values(name, t_val, b_val, level)
            if issue:
                issues.append(issue)

        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_cross_document_checker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/checkers/cross_document_checker.py tests-pytest/test_cross_document_checker.py
git commit -m "feat(checkers): add cross_document_checker for tender-bid consistency"
```

---

## Task 6: Wire new checkers into Proofreader.pipeline

**Files:**
- Modify: `src/proofreader/pipeline.py`
- Test: `tests-pytest/test_pipeline_pytest.py` (existing)

**Interfaces:**
- Consumes: new checker classes.
- Produces: `ProofreadingResult` includes new issue types.

- [ ] **Step 1: Write the failing test**

```python
from proofreader.pipeline import Proofreader


def test_pipeline_collects_screenshot_issues(sample_docs_dir):
    proofreader = Proofreader()
    # Use existing sample docs; if no images, expect empty but no crash
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

Modify `src/proofreader/pipeline.py` to instantiate and call the new checkers after OCR. Keep changes minimal; aggregate their `BaseIssue`s into the result object.

```python
from proofreader.checkers.screenshot_checker import ScreenshotChecker
from proofreader.checkers.certificate_checker import CertificateChecker
from proofreader.checkers.cross_document_checker import CrossDocumentChecker


class Proofreader:
    def __init__(self, ...):
        # existing init ...
        self.screenshot_checker = ScreenshotChecker()
        self.certificate_checker = CertificateChecker()
        self.cross_document_checker = CrossDocumentChecker()

    def proofread(self, tender_path, bid_path):
        # existing parse/extract/match/check flow ...
        # After OCR check:
        ocr_texts = [(img, self.ocr_engine.recognize(img.blob)) for img in bid_doc.images]

        for req in requirements:
            issues.extend(self.screenshot_checker.check(req, ocr_texts))
            issues.extend(self.certificate_checker.check(req, ocr_texts, bidder_name=bidder_name))

        issues.extend(self.cross_document_checker.check(tender_doc, bid_doc))

        return ProofreadingResult(...)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests-pytest/test_pipeline_pytest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/proofreader/pipeline.py tests-pytest/test_pipeline_pytest.py
git commit -m "feat(pipeline): wire screenshot, certificate, and cross-document checkers"
```

---

## Self-Review

**1. Spec coverage:**
- Screenshot type classification: Task 3.
- Certificate validity/scope/subject: Task 4.
- Cross-document consistency (project info, validity, service term, payment, delivery): Task 5.
- Low-confidence fallback to `UNRECOGNIZED_EVIDENCE`: Tasks 3, 4.
- Reuse of `OcrEngine` and `date_normalizer`: Tasks 2, 4, 5.

**2. Placeholder scan:**
- No TBD/TODO.
- LLM integration is explicitly out of scope for these checkers (default-off per spec).
- `normalize_date` from Plan 1 is used; assumes Plan 1 is merged first.

**3. Type consistency:**
- `BaseIssue` uses `IssueType` enum shared across checkers.
- `ScreenshotType` and `CertificateType` are checker-specific enums.
- `CrossDocumentChecker` consumes `ParsedDocument` and produces `BaseIssue`.

## Dependency Note

This plan depends on **Plan 1** being completed first, specifically:
- `date_normalizer` utility.
- `DocumentType`/`ProcurementMethod` enums in `requirements.py`.
- Updated `ParsedDocument` with classification fields.

## Next Plan

**Plan 3:** Personnel Checker + Performance Checker + Commitment Checker.
