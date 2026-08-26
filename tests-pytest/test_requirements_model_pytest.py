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
