from proofreader.extractors.composite_extractor import CompositeExtractor
from proofreader.extractors.table_strategies import ScoringStrategy
from proofreader.parsers.docx_parser import DocumentSection, DocumentSectionType, ParsedDocument, ParsedTable


def _make_scoring_table():
    table = ParsedTable(
        table_type="evaluation",
        header=["序号", "评价项目", "参考评价标准", "最高分值"],
        rows=[
            ["1", "项目经理", "具备 PMP 证书，得 6 分", "6"],
            ["2", "技术参数", "全部响应得 24 分，每负偏离一项扣 3 分", "24"],
        ],
    )
    section = DocumentSection(
        section_type=DocumentSectionType.EVALUATION,
        title="评分表",
        level=2,
        start_index=0,
        end_index=2,
        headings=["评分表"],
        paragraphs=[],
        tables=[table],
    )
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


def test_composite_extractor_returns_evaluation_rules():
    doc = ParsedDocument(path="tender.docx")
    section = DocumentSection(
        section_type=DocumentSectionType.EVALUATION,
        title="评分表",
        level=2,
        start_index=0,
        end_index=1,
        headings=["评分表"],
        paragraphs=[],
        tables=[],
    )
    doc.sections = [section]
    extractor = CompositeExtractor()
    result = extractor.extract_with_rules(doc)
    assert len(result.items) == 0  # no tables in this mock
    assert len(result.evaluation_rules) == 0  # no paragraph text with aggregate rule


def test_composite_extractor_extracts_aggregate_rule_from_paragraphs():
    doc = ParsedDocument(path="tender.docx")
    from proofreader.parsers.docx_parser import TextBlock

    section = DocumentSection(
        section_type=DocumentSectionType.EVALUATION,
        title="评分表",
        level=2,
        start_index=0,
        end_index=1,
        headings=["评分表"],
        paragraphs=[
            TextBlock(
                text="对技术参数，全部响应得 24 分，每负偏离一项扣 3 分。",
                block_type="paragraph",
                level=0,
            )
        ],
        tables=[],
    )
    doc.sections = [section]
    extractor = CompositeExtractor()
    result = extractor.extract_with_rules(doc)
    assert len(result.items) == 0
    assert len(result.evaluation_rules) == 1
    assert result.evaluation_rules[0].base_score == 24.0
    assert result.evaluation_rules[0].deduction_per_item == 3.0
