"""投标文件偏离标注导出测试。"""
from __future__ import annotations

from pathlib import Path

from docx import Document

from proofreader.exporters import annotate_bid_document
from proofreader.pipeline import Proofreader


def test_annotate_bid_document_creates_file(sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path) -> None:
    """标注函数应生成可打开的 docx 文件。"""
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    assert len(result.consistency_issues) > 0, "样例数据应存在偏离问题"

    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    assert output.exists()
    doc = Document(output)
    assert len(doc.paragraphs) > 0


def test_annotate_bid_document_no_inline_issue_notes(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """正文段落中不应插入红色说明小字，issue 详情应仅存在于 Word 批注中。"""
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    doc = Document(output)
    # body 段落文本中不应出现 issue_id（缺失响应汇总页在文档末尾，不属于原始正文）
    body_text = "\n".join(p.text for p in doc.paragraphs)
    assert not any(issue.issue_id in body_text for issue in result.consistency_issues)

    # issue 详情仍应出现在 Word 批注 XML 中
    import zipfile

    with zipfile.ZipFile(output, "r") as zf:
        assert "word/comments.xml" in zf.namelist()
        comments_xml = zf.read("word/comments.xml").decode("utf-8")
        assert any(issue.issue_id in comments_xml for issue in result.consistency_issues)


def test_annotate_bid_document_highlights_paragraphs(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """偏离段落应被设置底纹。"""
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    doc = Document(output)
    highlighted_count = 0
    for paragraph in doc.paragraphs:
        pPr = paragraph._p.get_or_add_pPr()
        shd = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd")
        if shd is not None and shd.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill"):
            highlighted_count += 1

    assert highlighted_count > 0


def test_annotate_bid_document_marks_red_spans(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """偏离的具体文字应被标红加粗。"""
    from docx.shared import RGBColor

    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    doc = Document(output)
    red_run_count = 0
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            if run.font.color and run.font.color.rgb == RGBColor(255, 0, 0):
                red_run_count += 1

    assert red_run_count > 0


def test_annotate_bid_document_adds_word_comments(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """生成的 docx 应包含 Word 批注 XML，且一个问题一个批注。"""
    import zipfile
    from lxml import etree

    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    with zipfile.ZipFile(output, "r") as zf:
        names = zf.namelist()
        assert "word/comments.xml" in names
        comments_xml = zf.read("word/comments.xml").decode("utf-8")
        # 至少一个 issue 的批注内容应存在
        assert any(issue.issue_id in comments_xml for issue in result.consistency_issues)

        # 批注数量不应超过能定位到正文段落的 issue 数量
        comments_root = etree.fromstring(comments_xml.encode("utf-8"))
        w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        comment_count = len(comments_root.findall(f"{{{w_ns}}}comment"))
        valid_issue_count = sum(
            1 for i in result.consistency_issues
            if i.bid_blocks and i.bid_blocks[0].para_index is not None
        )
        assert 0 < comment_count <= valid_issue_count

        # 批注范围标记应出现在 document.xml 中
        document_xml = zf.read("word/document.xml").decode("utf-8")
        assert "w:commentRangeStart" in document_xml
        assert "w:commentRangeEnd" in document_xml


def test_match_paragraph_rejects_empty_paragraph() -> None:
    """空段落不应与任何非空目标文本匹配，防止批注全部堆到首页空白段落。"""
    from proofreader.exporters.bid_annotator import _match_paragraph

    assert not _match_paragraph("", "投标响应文字")
    assert not _match_paragraph("   \n", "投标响应文字")
    assert _match_paragraph("投标响应文字内容", "投标响应文字")


def test_annotate_bid_document_comments_are_paragraph_level(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """批注范围应为段落级，确保 Word/WPS 稳定显示批注气泡。"""
    import zipfile
    from lxml import etree

    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    with zipfile.ZipFile(output, "r") as zf:
        doc_root = etree.fromstring(zf.read("word/document.xml"))

    # 收集所有有批注的段落
    paragraphs_with_comments = []
    for paragraph in doc_root.iter(f"{{{W_NS}}}p"):
        range_starts = paragraph.findall(f"{{{W_NS}}}commentRangeStart")
        range_ends = paragraph.findall(f"{{{W_NS}}}commentRangeEnd")
        if range_starts and range_ends:
            paragraphs_with_comments.append((paragraph, range_starts, range_ends))

    assert paragraphs_with_comments, "应至少有一个段落包含批注范围标记"

    # 所有批注都应为段落级：commentRangeStart 紧跟在 pPr 后（或无 pPr 时位于段落开头）
    for paragraph, range_starts, _ in paragraphs_with_comments:
        children = list(paragraph)
        ppr_idx = -1
        for idx, child in enumerate(children):
            if child.tag == f"{{{W_NS}}}pPr":
                ppr_idx = idx
                break
        expected_rs_idx = ppr_idx + 1 if ppr_idx >= 0 else 0
        for rs in range_starts:
            rs_idx = children.index(rs)
            assert rs_idx == expected_rs_idx, (
                "发现非段落级批注范围，可能影响 Word/WPS 兼容性"
            )


def test_annotate_bid_document_comments_cover_highlight_spans(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """批注范围覆盖的文字应包含对应 issue 的 highlight_span。"""
    import zipfile
    from lxml import etree

    from proofreader.exporters.bid_annotator import _normalize

    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(output, "r") as zf:
        doc_root = etree.fromstring(zf.read("word/document.xml"))

    # 与 _inject_comments_into_docx 中 valid_issues 的定义保持一致：
    # 能定位到正文段落的 issue
    valid_issues = [
        issue
        for issue in result.consistency_issues
        if issue.bid_blocks and issue.bid_blocks[0].para_index is not None
    ]

    covered_by_cid: dict[int, str] = {}
    for paragraph in doc_root.iter(f"{{{W_NS}}}p"):
        for rs in paragraph.findall(f"{{{W_NS}}}commentRangeStart"):
            cid = int(rs.get(f"{{{W_NS}}}id"))
            re = paragraph.find(f"{{{W_NS}}}commentRangeEnd[@{{{W_NS}}}id='{cid}']")
            if re is None:
                continue
            children = list(paragraph)
            rs_idx = children.index(rs)
            re_idx = children.index(re)
            covered = "".join(
                "".join(t.text or "" for t in child.iter(f"{{{W_NS}}}t"))
                for child in children[rs_idx + 1: re_idx]
                if child.tag == f"{{{W_NS}}}r"
            )
            covered_by_cid[cid] = covered

    for cid, issue in enumerate(valid_issues):
        covered = covered_by_cid.get(cid)
        assert covered is not None, f"issue {issue.issue_id} 应有批注范围"

        # 无 highlight_spans 的 issue（如 SEMANTIC_LOW）使用段落级批注，无需检查覆盖文字
        highlight_spans = [s for s in (issue.highlight_spans or []) if s.strip()]
        if not highlight_spans:
            continue

        covered_norm = _normalize(covered).replace(" ", "")

        def _is_subsequence(small: str, big: str) -> bool:
            it = iter(big)
            return all(ch in it for ch in small)

        matched = any(
            _is_subsequence(_normalize(span).replace(" ", ""), covered_norm)
            for span in highlight_spans
        )
        assert matched, (
            f"issue {issue.issue_id} 的批注范围 {covered!r} "
            f"未包含任何 highlight_span {issue.highlight_spans}"
        )


def test_annotate_bid_document_table_row_red_spans_and_comments(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """表格行 issue 应对单元格文字标红，并在响应单元格生成 Word 批注。"""
    from docx import Document
    from docx.shared import RGBColor
    import zipfile
    from lxml import etree

    # 构造一个表格行会被识别为 issue 的场景：需求要求 5 年，表格响应 3 年
    req_path = tmp_path / "table_req.docx"
    bid_path = tmp_path / "table_bid.docx"
    out_path = tmp_path / "table_annotated.docx"

    req_doc = Document()
    req_doc.add_paragraph("需求文件")
    req_doc.add_paragraph("1. 服务期限不少于 5 年。")
    req_doc.save(req_path)

    bid_doc = Document()
    bid_doc.add_paragraph("投标文件")
    table = bid_doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "响应值"
    table.cell(1, 0).text = "服务期限"
    table.cell(1, 1).text = "3 年"
    bid_doc.save(bid_path)

    result = proofreader.proofread(req_path, bid_path)
    # 确认表格行被作为最佳匹配块
    table_issues = [
        i for i in result.consistency_issues
        if i.bid_blocks and i.bid_blocks[0].block_type == "table_row"
    ]
    if not table_issues:
        # 若语义匹配未落到表格行，则此测试无意义
        return

    annotate_bid_document(result, out_path)

    # 检查单元格中是否有红色高亮
    annotated = Document(out_path)
    red_run_count = 0
    for table in annotated.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        if run.font.color and run.font.color.rgb == RGBColor(255, 0, 0):
                            red_run_count += 1
    assert red_run_count > 0, "表格单元格中应存在标红文字"

    # 表格行 issue 应生成 Word 批注
    with zipfile.ZipFile(out_path, "r") as zf:
        assert "word/comments.xml" in zf.namelist(), "应为表格行 issue 生成 comments.xml"
        comments_root = etree.fromstring(zf.read("word/comments.xml"))
        w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        comment_count = len(comments_root.findall(f"{{{w_ns}}}comment"))
        assert comment_count > 0, "表格行 issue 应至少生成一个批注"
        comments_xml = zf.read("word/comments.xml").decode("utf-8")
        assert any(i.issue_id in comments_xml for i in table_issues), "批注内容应包含 table_row issue 的 issue_id"

        # 批注范围标记应出现在表格单元格段落中
        doc_root = etree.fromstring(zf.read("word/document.xml"))
        table_rows_with_comments = 0
        for tbl in doc_root.iter(f"{{{w_ns}}}tbl"):
            for tr in tbl.iter(f"{{{w_ns}}}tr"):
                for tc in tr.iter(f"{{{w_ns}}}tc"):
                    for para in tc.iter(f"{{{w_ns}}}p"):
                        if para.find(f"{{{w_ns}}}commentRangeStart") is not None:
                            table_rows_with_comments += 1
                            break
        assert table_rows_with_comments > 0, "表格单元格中应出现批注范围标记"


def test_annotate_bid_document_empty_paragraph_mapping(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """含空段落和表格时，批注仍应落在正确的正文段落。"""
    from docx import Document
    from docx.shared import RGBColor
    import zipfile
    from lxml import etree

    req_path = tmp_path / "empty_para_req.docx"
    bid_path = tmp_path / "empty_para_bid.docx"
    out_path = tmp_path / "empty_para_annotated.docx"

    req_doc = Document()
    req_doc.add_paragraph("需求文件")
    req_doc.add_paragraph("1. 服务期限不少于 5 年。")
    req_doc.save(req_path)

    bid_doc = Document()
    bid_doc.add_paragraph("投标文件")
    bid_doc.add_paragraph("")  # 空段落
    table = bid_doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "响应值"
    table.cell(1, 0).text = "服务期限"
    table.cell(1, 1).text = "3 年"
    bid_doc.add_paragraph("服务期限为 3 年。")  # 目标段落
    bid_doc.add_paragraph("其他说明。")
    bid_doc.save(bid_path)

    result = proofreader.proofread(req_path, bid_path)
    # 筛选指向正文段落的 issue（排除表格行）
    body_issues = [
        i for i in result.consistency_issues
        if i.bid_blocks and i.bid_blocks[0].para_index is not None
    ]
    if not body_issues:
        return

    annotate_bid_document(result, out_path)

    annotated = Document(out_path)
    # 目标段落应被标红或设置底纹
    # paragraph[1] 为空，table 不占 paragraph，paragraph[2]=投标文件，paragraph[3]=目标段落
    target_para = annotated.paragraphs[3]
    has_highlight = False
    for run in target_para.runs:
        if run.font.color and run.font.color.rgb == RGBColor(255, 0, 0):
            has_highlight = True
            break
    pPr = target_para._p.get_or_add_pPr()
    shd = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd")
    if shd is not None and shd.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}fill"):
        has_highlight = True
    assert has_highlight, "目标正文段落应存在高亮"

    # Word 批注范围应出现在目标段落
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(out_path, "r") as zf:
        doc_root = etree.fromstring(zf.read("word/document.xml"))
        body = doc_root.find(f"{{{W_NS}}}body")
        paras = [c for c in body if c.tag == f"{{{W_NS}}}p"]
        target_text = "".join(t.text or "" for t in paras[3].iter(f"{{{W_NS}}}t"))
        assert "服务期限为 3 年" in target_text
        assert paras[3].find(f"{{{W_NS}}}commentRangeStart") is not None


def test_mark_spans_red_matches_subsequence_span() -> None:
    """highlight_span 中的关键词在正文中不连续时，仍应精确标红对应文字。"""
    from docx import Document
    from docx.shared import RGBColor

    from proofreader.exporters.bid_annotator import _mark_spans_red

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("前缀 ")
    p.add_run("800 并发用户")
    p.add_run(" 后缀")
    _mark_spans_red(p, ["800用户"])

    red_text = "".join(
        r.text for r in p.runs if r.font.color and r.font.color.rgb == RGBColor(255, 0, 0)
    )
    assert "800 并发用户" in red_text
    assert "前缀" not in red_text
    assert "后缀" not in red_text


def test_annotate_bid_document_table_row_marks_response_cell_only(
    proofreader: Proofreader, tmp_path: Path
) -> None:
    """表格行 issue 应仅标红响应单元格，而非全部单元格。"""
    from docx import Document
    from docx.shared import RGBColor

    req_path = tmp_path / "table_response_req.docx"
    bid_path = tmp_path / "table_response_bid.docx"
    out_path = tmp_path / "table_response_annotated.docx"

    req_doc = Document()
    req_doc.add_paragraph("需求文件")
    req_doc.add_paragraph("1. 服务期限不少于 5 年。")
    req_doc.save(req_path)

    bid_doc = Document()
    bid_doc.add_paragraph("投标文件")
    table = bid_doc.add_table(rows=2, cols=3)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "响应值"
    table.cell(0, 2).text = "合规"
    table.cell(1, 0).text = "服务期限"
    table.cell(1, 1).text = "3 年"
    table.cell(1, 2).text = "符合"
    bid_doc.save(bid_path)

    result = proofreader.proofread(req_path, bid_path)
    table_issues = [
        i for i in result.consistency_issues
        if i.bid_blocks and i.bid_blocks[0].block_type == "table_row"
    ]
    if not table_issues:
        return

    annotate_bid_document(result, out_path)

    annotated = Document(out_path)
    for table in annotated.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            if "服务期限" not in row_text:
                continue
            red_cells = []
            for idx, cell in enumerate(row.cells):
                for p in cell.paragraphs:
                    for run in p.runs:
                        if run.font.color and run.font.color.rgb == RGBColor(255, 0, 0):
                            red_cells.append(idx)
                            break
            assert red_cells == [1], f"应只标红响应单元格，实际标红单元格: {red_cells}"


def test_comment_text_includes_requirement_id_and_suggestion(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """批注正文应包含需求 ID、问题描述和建议，避免「只写结论不写理由」。"""
    import zipfile

    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    with zipfile.ZipFile(output, "r") as zf:
        comments_xml = zf.read("word/comments.xml").decode("utf-8")

    for issue in result.consistency_issues:
        if not issue.bid_blocks:
            continue
        # 有标红文字的 issue 应出现在批注中，并包含需求ID与建议
        if issue.highlight_spans:
            assert issue.issue_id in comments_xml
            assert f"需求 {issue.requirement_id}" in comments_xml
            assert f"问题：{issue.message}" in comments_xml
            assert f"建议：{issue.suggestion}" in comments_xml


def test_semantic_low_without_span_is_not_annotated(
    tmp_path: Path,
) -> None:
    """无具体标红文字的低置信度 SEMANTIC_LOW 不应生成 Word 批注，避免无效批注泛滥。"""
    import zipfile

    from proofreader.checkers.consistency_checker import (
        ConsistencyIssue,
        IssueLevel,
        IssueType,
    )
    from proofreader.exporters.bid_annotator import _inject_comments_into_docx

    # 构造一个 SEMANTIC_LOW 且 highlight_spans 为空的 issue
    issue = ConsistencyIssue(
        issue_id="ISS-SEM",
        issue_type=IssueType.SEMANTIC_LOW,
        level=IssueLevel.WARNING,
        requirement_id="R1",
        requirement_text="需求",
        bid_text="投标",
        message="疑似未充分响应该需求（匹配度 0.20）",
        suggestion="补充响应",
        bid_blocks=[_FakeTextBlock(para_index=0)],
        highlight_spans=[],
    )

    # 准备一个最小 docx
    from docx import Document

    doc = Document()
    doc.add_paragraph("投标响应文字")
    doc_path = tmp_path / "sem.docx"
    doc.save(doc_path)

    _inject_comments_into_docx(doc_path, [issue], {"ISS-SEM": 0})

    with zipfile.ZipFile(doc_path, "r") as zf:
        assert "word/comments.xml" not in zf.namelist()


def test_match_paragraph_rejects_short_fragment() -> None:
    """段落仅为目标文本的很小片段时不应误匹配，避免批注挂到小标题。"""
    from proofreader.exporters.bid_annotator import _match_paragraph

    # 小标题只包含目标的前两个字，不应命中
    assert not _match_paragraph("服务", "服务期限不少于 5 年")
    # 段落完整包含目标关键内容时应命中
    assert _match_paragraph("服务期限不少于 5 年的具体要求如下", "服务期限不少于 5 年")


def test_mark_spans_red_rejects_loose_subsequence() -> None:
    """highlight_span 的字符在段落中跨度过大时不应被错误标红。"""
    from docx import Document
    from docx.shared import RGBColor

    from proofreader.exporters.bid_annotator import _mark_spans_red

    doc = Document()
    p = doc.add_paragraph()
    p.add_run("前缀 ")
    p.add_run("800 个高并发在线用户")
    p.add_run(" 后缀")
    _mark_spans_red(p, ["800用户"])

    red_text = "".join(
        r.text for r in p.runs if r.font.color and r.font.color.rgb == RGBColor(255, 0, 0)
    )
    # 中间间隔字符过多，不应被错误标红
    assert "800" not in red_text
    assert "用户" not in red_text


class _FakeTextBlock:
    """用于测试的最小 TextBlock 替身。"""

    def __init__(self, para_index: int | None = 0):
        self.para_index = para_index
        self.block_type = "paragraph"
        self.text = "投标响应文字"


def test_find_shortest_subsequence_window_long_fallback() -> None:
    """超长文本应回退到 O(n) 贪心子序列窗口，避免 O(n²) 挂起。"""
    from proofreader.exporters.bid_annotator import _find_shortest_subsequence_window

    # 构造长度超过 _MAX_SUBSEQUENCE_TEXT_LEN 的文本
    filler = "x" * 2100
    text = f"前缀{filler}目标开始{'间隔' * 10}结束{filler}后缀"
    window = _find_shortest_subsequence_window(text, "目标开始结束")
    assert window is not None
    start, end = window
    assert text[start:end + 1].startswith("目标开始")
    assert "结束" in text[start:end + 1]
