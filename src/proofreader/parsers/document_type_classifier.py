"""文档类型与采购方式分类器。规则 → embedding → LLM 兜底。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from proofreader.models.requirements import (
    DocumentClassificationResult,
    DocumentType,
    ProcurementMethod,
)
from proofreader.parsers.docx_parser import ParsedDocument


# 基于关键词的规则库
_DOCUMENT_KEYWORDS = {
    DocumentType.TENDER: {
        ProcurementMethod.BIXUAN: ["比选文件", "比选", "综合评分法"],
        ProcurementMethod.COMPETITIVE_NEGOTIATION: ["竞争性磋商", "磋商文件", "磋商邀请"],
        ProcurementMethod.TENDER: ["招标文件", "招标公告", "公开招标"],
        ProcurementMethod.SELECTION: ["遴选文件", "遴选"],
        ProcurementMethod.OTHER: ["采购文件"],
    },
    DocumentType.REQUIREMENT: {
        ProcurementMethod.OTHER: ["采购需求", "需求文件", "需求说明书"],
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
    path_hint = ""
    if doc.path:
        p = Path(doc.path) if isinstance(doc.path, str) else doc.path
        path_hint = p.stem
    text = (doc.title or "") + " " + " ".join(heading_texts) + " " + path_hint
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

    # 若出现标准投标文件四大部分，则提升为 bid_response
    matching_sections = sum(1 for sec in _BID_RESPONSE_SECTIONS if sec in text)
    if matching_sections >= 2:
        if best_type in (DocumentType.BID_RESPONSE, DocumentType.BID_REGISTRATION, DocumentType.OTHER):
            best_type = DocumentType.BID_RESPONSE
            best_score = max(best_score, float(matching_sections))

    confidence = min(0.5 + best_score * 0.15, 0.95)
    return best_type, best_method, confidence


def _embedding_fallback(doc: ParsedDocument) -> Optional[DocumentClassificationResult]:
    """可选的 TF-IDF / embedding 兜底；当前为占位实现。"""
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
        raise NotImplementedError(
            "LLM fallback for document classification is not implemented; "
            "set use_llm=False or implement a local model backend."
        )

    return DocumentClassificationResult(
        document_type=doc_type,
        procurement_method=method,
        confidence=min(confidence, 1.0),
        method=result_method,
    )
