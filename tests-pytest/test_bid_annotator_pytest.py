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


def test_annotate_bid_document_adds_issue_notes(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """标注文档中应包含偏离说明文字。"""
    result = proofreader.proofread(
        sample_docs_dir / "requirements.docx",
        sample_docs_dir / "bid.docx",
    )
    output = tmp_path / "annotated_bid.docx"
    annotate_bid_document(result, output)

    doc = Document(output)
    full_text = "\n".join(p.text for p in doc.paragraphs)

    # 至少一个 issue 的说明文字应被追加到某段落
    assert any(issue.issue_id in full_text for issue in result.consistency_issues)


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

        # 批注数量不应超过有 highlight_spans 的 issue 数量
        comments_root = etree.fromstring(comments_xml.encode("utf-8"))
        w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        comment_count = len(comments_root.findall(f"{{{w_ns}}}comment"))
        valid_issue_count = sum(
            1 for i in result.consistency_issues
            if i.bid_blocks and i.highlight_spans and any(s.strip() for s in i.highlight_spans)
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


def test_annotate_bid_document_comments_are_run_level(
    sample_docs_dir: Path, proofreader: Proofreader, tmp_path: Path
) -> None:
    """批注范围应精确到包含问题文字的 run，而不是整个段落。"""
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

    # 至少有一个批注不是段落级：即 commentRangeStart 不是紧跟在 pPr 后的第一个元素
    non_paragraph_level = 0
    for paragraph, range_starts, _ in paragraphs_with_comments:
        children = list(paragraph)
        for rs in range_starts:
            rs_idx = children.index(rs)
            ppr_idx = -1
            for idx, child in enumerate(children):
                if child.tag == f"{{{W_NS}}}pPr":
                    ppr_idx = idx
                    break
            if ppr_idx == -1 or rs_idx != ppr_idx + 1:
                non_paragraph_level += 1
                break

    assert non_paragraph_level > 0, "应至少有一个批注精确限定在 run 级别，而非整个段落"


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

    valid_issues = [
        issue
        for issue in result.consistency_issues
        if issue.bid_blocks
        and issue.highlight_spans
        and any(s.strip() for s in issue.highlight_spans)
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
                for child in children[rs_idx + 1 : re_idx]
                if child.tag == f"{{{W_NS}}}r"
            )
            covered_by_cid[cid] = covered

    for cid, issue in enumerate(valid_issues):
        covered = covered_by_cid.get(cid)
        assert covered is not None, f"issue {issue.issue_id} 应有批注范围"
        covered_norm = _normalize(covered).replace(" ", "")

        def _is_subsequence(small: str, big: str) -> bool:
            it = iter(big)
            return all(ch in it for ch in small)

        matched = any(
            _is_subsequence(_normalize(span).replace(" ", ""), covered_norm)
            for span in issue.highlight_spans
            if span.strip()
        )
        assert matched, (
            f"issue {issue.issue_id} 的批注范围 {covered!r} "
            f"未包含任何 highlight_span {issue.highlight_spans}"
        )
