"""在投标文件副本中高亮标注偏离项（精确文字标红 + Word 原生批注）。"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from lxml import etree

from proofreader.checkers.consistency_checker import ConsistencyIssue, IssueLevel
from proofreader.parsers.docx_parser import convert_doc_to_docx
from proofreader.pipeline import ProofreadResult


# 偏离级别对应底纹颜色（十六进制）
LEVEL_FILL_COLORS = {
    IssueLevel.ERROR: "F8D7DA",    # 浅红
    IssueLevel.WARNING: "FFF3CD",  # 浅黄
    IssueLevel.INFO: "D1ECF1",     # 浅蓝
}


def _normalize(text: str) -> str:
    """归一化文本用于匹配：去首尾空白、合并连续空白。"""
    return " ".join(text.strip().split())


def _match_paragraph(paragraph_text: str, target_text: str) -> bool:
    """判断段落文本是否与目标文本匹配。

    空段落不应匹配任何非空目标，否则会导致所有批注都堆到首页空白段落上。
    """
    if not target_text:
        return False
    pt = _normalize(paragraph_text)
    tt = _normalize(target_text)
    if not pt:
        return False
    if pt == tt:
        return True
    if tt in pt or pt in tt:
        return True
    return False


def _set_paragraph_shading(paragraph, fill_color: str) -> None:
    """设置段落底纹颜色。"""
    pPr = paragraph._p.get_or_add_pPr()
    # 移除已有的 shd 元素，避免重复
    for child in list(pPr):
        if child.tag == qn("w:shd"):
            pPr.remove(child)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill_color)
    pPr.append(shd)


def _mark_spans_red(paragraph, spans: List[str]) -> None:
    """将段落中包含 spans 文字的 run 标红加粗（兼容空格差异）。"""
    if not spans:
        return
    for run in paragraph.runs:
        run_norm = _normalize(run.text).replace(" ", "")
        for span in spans:
            span_norm = _normalize(span).replace(" ", "")
            if span_norm and span_norm in run_norm:
                run.font.color.rgb = RGBColor(255, 0, 0)
                run.font.bold = True
                break


def _add_issue_note(paragraph, issue: ConsistencyIssue) -> None:
    """在段落末尾追加红色小字说明（作为批注的补充）。"""
    paragraph.add_run().add_break()
    note_text = f"[{issue.issue_id}] 需求 {issue.requirement_id}：{issue.message}（{issue.suggestion}）"
    run = paragraph.add_run(note_text)
    run.font.color.rgb = RGBColor(211, 47, 47)  # 红色
    run.font.size = Pt(9)


# ---------------------------------------------------------------------------
# Word 原生批注（comments）支持
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_run_range_for_span(
    paragraph, span_text: str, w_ns: str
) -> Tuple[int, int] | None:
    """
    在段落的 w:r run 中定位包含 span_text 的 run 范围。

    返回的是在 paragraph 子元素列表中的 (start_child_index, end_child_index)。
    如果找不到或 span_text 为空，返回 None。
    匹配时使用归一化文本（去除多余空格），兼容 run 之间有空格的情况。
    """
    if not span_text:
        return None

    span_norm = _normalize(span_text).replace(" ", "")
    if not span_norm:
        return None

    # 收集所有带文本的 w:r 子元素及其归一化文本
    run_infos: List[Tuple[int, object, str]] = []
    for idx, child in enumerate(paragraph):
        if child.tag != f"{{{w_ns}}}r":
            continue
        texts = [t.text or "" for t in child.iter(f"{{{w_ns}}}t")]
        run_text = "".join(texts)
        run_norm = _normalize(run_text).replace(" ", "")
        run_infos.append((idx, child, run_norm))

    if not run_infos:
        return None

    # 构建归一化段落文本及每个 run 的结束位置
    para_norm = ""
    boundaries: List[Tuple[int, int]] = []
    for idx, _run, run_norm in run_infos:
        para_norm += run_norm
        boundaries.append((len(para_norm), idx))

    pos = para_norm.find(span_norm)
    if pos < 0:
        return None

    start_pos = pos
    end_pos = pos + len(span_norm) - 1  # 包含结束位置

    start_run_idx: int | None = None
    end_run_idx: int | None = None
    for boundary_pos, run_idx in boundaries:
        if start_run_idx is None and boundary_pos > start_pos:
            start_run_idx = run_idx
        if end_run_idx is None and boundary_pos > end_pos:
            end_run_idx = run_idx
            break

    if start_run_idx is None or end_run_idx is None:
        return None
    return start_run_idx, end_run_idx


_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _make_run_with_text(text: str, rpr, w_ns: str):
    """创建包含指定文本的 w:r 元素，并复制原 rPr 格式。"""
    if not text:
        return None
    run = etree.Element(f"{{{w_ns}}}r")
    if rpr is not None:
        run.append(deepcopy(rpr))
    t = etree.SubElement(run, f"{{{w_ns}}}t")
    t.text = text
    if text[0].isspace() or text[-1].isspace():
        t.set(_XML_SPACE, "preserve")
    return run


def _replace_runs_with_splits(
    paragraph,
    runs: List,
    start_run_idx: int,
    end_run_idx: int,
    splits: List[List[str]],
    w_ns: str,
) -> List:
    """将段落中 [start_run_idx, end_run_idx] 范围内的 run 按 splits 拆分并替换。"""
    first_run = runs[start_run_idx]
    insert_pos = list(paragraph).index(first_run)
    new_runs: List = []
    for r_idx, pieces in enumerate(
        (splits[i] for i in range(end_run_idx - start_run_idx + 1)), start=start_run_idx
    ):
        rpr = runs[r_idx].find(f"{{{w_ns}}}rPr")
        for piece in pieces:
            new_run = _make_run_with_text(piece, rpr, w_ns)
            if new_run is not None:
                paragraph.insert(insert_pos, new_run)
                insert_pos += 1
                new_runs.append(new_run)
    # 删除原 run（从后往前，避免索引变化）
    for r_idx in range(end_run_idx, start_run_idx - 1, -1):
        paragraph.remove(runs[r_idx])
    return new_runs


def _isolate_span_runs(paragraph, span_text: str, w_ns: str) -> bool:
    """
    拆分段落中的 w:r，使 span_text 独占一段连续的 run。

    返回是否成功完成拆分。拆分后的 run 会尽量保留原文格式（复制 rPr）。
    """
    span_norm = _normalize(span_text).replace(" ", "")
    if not span_norm:
        return False

    runs = [c for c in paragraph if c.tag == f"{{{w_ns}}}r"]
    if not runs:
        return False

    run_texts: List[str] = []
    norm_to_raw: List[Tuple[int, int]] = []
    for r_idx, run in enumerate(runs):
        raw = "".join(t.text or "" for t in run.iter(f"{{{w_ns}}}t"))
        run_texts.append(raw)
        for offset, ch in enumerate(raw):
            if not ch.isspace():
                norm_to_raw.append((r_idx, offset))

    if not norm_to_raw:
        return False

    para_norm = "".join(ch for ch in "".join(run_texts) if not ch.isspace())
    pos = para_norm.find(span_norm)
    if pos < 0:
        return False

    start_norm = pos
    end_norm = pos + len(span_norm)  # 不包含

    start_run, start_offset = norm_to_raw[start_norm]
    if end_norm >= len(norm_to_raw):
        end_run = len(runs) - 1
        end_offset = len(run_texts[end_run])
    else:
        end_run, end_offset = norm_to_raw[end_norm]

    splits: List[List[str]] = []
    for r_idx in range(start_run, end_run + 1):
        raw = run_texts[r_idx]
        if r_idx == start_run and r_idx == end_run:
            splits.append([raw[:start_offset], raw[start_offset:end_offset], raw[end_offset:]])
        elif r_idx == start_run:
            splits.append([raw[:start_offset], raw[start_offset:]])
        elif r_idx == end_run:
            splits.append([raw[:end_offset], raw[end_offset:]])
        else:
            splits.append([raw])

    _replace_runs_with_splits(paragraph, runs, start_run, end_run, splits, w_ns)
    return True


def _find_contiguous_span(paragraph, span_text: str, w_ns: str) -> str | None:
    """
    将 span_text 在段落中定位为一串实际连续出现的文字。

    部分 highlight_span 只包含关键词（如 "800用户"），而文档中实际写作
    "800 并发用户"，字符不连续。本函数按顺序匹配 span 中的每个字符，
    返回包含这些字符的最短连续文本（包含中间文字），以便精确拆分 run。
    """
    span_norm = _normalize(span_text).replace(" ", "")
    if not span_norm:
        return None

    runs = [c for c in paragraph if c.tag == f"{{{w_ns}}}r"]
    if not runs:
        return None

    norm_to_raw: List[Tuple[int, int, str]] = []
    run_texts: List[str] = []
    for r_idx, run in enumerate(runs):
        raw = "".join(t.text or "" for t in run.iter(f"{{{w_ns}}}t"))
        run_texts.append(raw)
        for offset, ch in enumerate(raw):
            if not ch.isspace():
                norm_to_raw.append((r_idx, offset, ch))

    if not norm_to_raw:
        return None

    para_norm = "".join(ch for _, _, ch in norm_to_raw)

    # 按顺序定位 span 中每个字符
    start = para_norm.find(span_norm[0])
    if start < 0:
        return None
    cur = start
    for ch in span_norm[1:]:
        nxt = para_norm.find(ch, cur + 1)
        if nxt < 0:
            return None
        cur = nxt
    end = cur

    start_run, start_offset, _ = norm_to_raw[start]
    if end + 1 >= len(norm_to_raw):
        end_run = len(runs) - 1
        end_offset = len(run_texts[end_run])
    else:
        end_run, end_offset, _ = norm_to_raw[end + 1]

    pieces: List[str] = []
    for r_idx in range(start_run, end_run + 1):
        raw = run_texts[r_idx]
        if r_idx == start_run and r_idx == end_run:
            pieces.append(raw[start_offset:end_offset])
        elif r_idx == start_run:
            pieces.append(raw[start_offset:])
        elif r_idx == end_run:
            pieces.append(raw[:end_offset])
        else:
            pieces.append(raw)
    return "".join(pieces)


def _build_comments_xml(comments: List[Tuple[int, str, str]]) -> bytes:
    """生成 comments.xml 内容。comments: [(id, author, text), ...]。"""
    root = etree.Element(f"{{{_W_NS}}}comments", nsmap={"w": _W_NS, "r": _R_NS})
    for cid, author, text in comments:
        comment = etree.SubElement(
            root,
            f"{{{_W_NS}}}comment",
            {
                f"{{{_W_NS}}}id": str(cid),
                f"{{{_W_NS}}}author": author,
                f"{{{_W_NS}}}date": _now_iso(),
                f"{{{_W_NS}}}initials": author[:1],
            },
        )
        p = etree.SubElement(comment, f"{{{_W_NS}}}p")
        r = etree.SubElement(p, f"{{{_W_NS}}}r")
        t = etree.SubElement(r, f"{{{_W_NS}}}t")
        t.text = text
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _inject_comments_into_docx(
    docx_path: Path,
    issues: List[ConsistencyIssue],
    issue_paragraph_index: Dict[str, int] | None = None,
) -> None:
    """
    向已保存的 docx 文件中注入 Word 原生批注。

    - 只对有 highlight_spans 的 issue 生成批注（一个问题一个批注）。
    - 批注范围优先精确限定在包含问题文字的 run 上；
      如果无法在 run 中定位，则回退到段落级范围。
    - issue_paragraph_index 用于按段落下标精确定位，避免文本重复时找错段落。
    """
    # 过滤有效 issue：必须有 bid_blocks 且 highlight_spans 非空
    valid_issues = [
        issue for issue in issues
        if issue.bid_blocks
        and issue.highlight_spans
        and any(s.strip() for s in issue.highlight_spans)
    ]
    if not valid_issues:
        return

    work_dir = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(docx_path, "r") as zin:
            for member in zin.namelist():
                if os.path.isabs(member) or ".." in Path(member).parts:
                    raise ValueError(f"Invalid zip member path: {member}")
            zin.extractall(work_dir)

        doc_xml_path = work_dir / "word" / "document.xml"
        rels_path = work_dir / "word" / "_rels" / "document.xml.rels"
        comments_path = work_dir / "word" / "comments.xml"
        content_types_path = work_dir / "[Content_Types].xml"

        if not doc_xml_path.exists():
            return

        # 1. 准备批注数据
        comments_data: List[Tuple[int, str, str]] = []
        for idx, issue in enumerate(valid_issues):
            text = f"[{issue.issue_id}] 需求 {issue.requirement_id}\n{issue.message}\n建议：{issue.suggestion}"
            comments_data.append((idx, "智能校对器", text))

        # 2. 写入 comments.xml
        comments_path.write_bytes(_build_comments_xml(comments_data))

        # 3. 更新 document.xml.rels
        rels_tree = etree.parse(str(rels_path))
        rels_root = rels_tree.getroot()
        ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        existing_ids = [
            int(el.get("Id", "rId0")[3:])
            for el in rels_root.findall("rel:Relationship", ns)
            if el.get("Id", "").startswith("rId")
        ]
        next_rid = max(existing_ids) + 1 if existing_ids else 1
        rel = etree.SubElement(rels_root, f"{{{ns['rel']}}}Relationship")
        rel.set("Id", f"rId{next_rid}")
        rel.set("Type", _REL_COMMENTS)
        rel.set("Target", "comments.xml")
        rels_tree.write(str(rels_path), xml_declaration=True, encoding="UTF-8", standalone=True)

        # 4. 更新 [Content_Types].xml
        if content_types_path.exists():
            ct_tree = etree.parse(str(content_types_path))
            ct_root = ct_tree.getroot()
            ct_ns = ct_root.nsmap.get(None, "http://schemas.openxmlformats.org/package/2006/content-types")
            comments_ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
            already = any(
                el.get("Extension") == "xml" and el.get("ContentType") == comments_ct
                for el in ct_root
            )
            if not already:
                override = etree.SubElement(ct_root, f"{{{ct_ns}}}Override")
                override.set("PartName", "/word/comments.xml")
                override.set(
                    "ContentType",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
                )
                ct_tree.write(str(content_types_path), xml_declaration=True, encoding="UTF-8", standalone=True)

        # 5. 在 document.xml 中精确插入批注引用
        doc_tree = etree.parse(str(doc_xml_path))
        doc_root = doc_tree.getroot()
        w_ns = doc_root.nsmap.get("w", _W_NS)

        body = doc_root.find(f"{{{w_ns}}}body")
        body_paragraphs = (
            [c for c in body if c.tag == f"{{{w_ns}}}p"]
            if body is not None
            else []
        )

        for issue_idx, issue in enumerate(valid_issues):
            target_text = issue.bid_blocks[0].text
            paragraph = None

            # 优先使用已知段落下标（body 段落），避免按文本匹配到空白/错误段落
            preferred_idx = (issue_paragraph_index or {}).get(issue.issue_id)
            if preferred_idx is not None and 0 <= preferred_idx < len(body_paragraphs):
                paragraph = body_paragraphs[preferred_idx]

            # 回退：按文本在所有段落中匹配
            if paragraph is None:
                for para in doc_root.iter(f"{{{w_ns}}}p"):
                    para_text = "".join(t.text or "" for t in para.iter(f"{{{w_ns}}}t"))
                    if _match_paragraph(para_text, target_text):
                        paragraph = para
                        break

            if paragraph is None:
                continue

            placed = False
            # 优先尝试把批注范围精确限定在 highlight_span 对应的文字上
            for span in issue.highlight_spans:
                span = span.strip()
                if not span:
                    continue
                # highlight_span 可能与文档实际文字不完全连续（如 "800用户" vs "800 并发用户"），
                # 先找到包含这些字符的最短连续文本
                contiguous_span = _find_contiguous_span(paragraph, span, w_ns)
                if not contiguous_span:
                    continue
                # 拆分 run，使目标文字独占一个/多个连续 run
                if not _isolate_span_runs(paragraph, contiguous_span, w_ns):
                    continue
                run_range = _find_run_range_for_span(paragraph, contiguous_span, w_ns)
                if run_range is None:
                    continue
                start_run_idx, end_run_idx = run_range

                range_start = OxmlElement("w:commentRangeStart")
                range_start.set(qn("w:id"), str(issue_idx))
                paragraph.insert(start_run_idx, range_start)

                # 插入 range_start 后，end_run_idx 对应的 run 向后移动 1 位
                range_end = OxmlElement("w:commentRangeEnd")
                range_end.set(qn("w:id"), str(issue_idx))
                ref_run = OxmlElement("w:r")
                ref = OxmlElement("w:commentReference")
                ref.set(qn("w:id"), str(issue_idx))
                ref_run.append(ref)
                paragraph.insert(end_run_idx + 2, range_end)
                paragraph.insert(end_run_idx + 3, ref_run)
                placed = True
                break

            if not placed:
                # 回退：段落级范围
                insert_pos = 0
                for idx, child in enumerate(paragraph):
                    if child.tag == f"{{{w_ns}}}pPr":
                        insert_pos = idx + 1
                        break

                range_start = OxmlElement("w:commentRangeStart")
                range_start.set(qn("w:id"), str(issue_idx))
                paragraph.insert(insert_pos, range_start)

                range_end = OxmlElement("w:commentRangeEnd")
                range_end.set(qn("w:id"), str(issue_idx))
                ref_run = OxmlElement("w:r")
                ref = OxmlElement("w:commentReference")
                ref.set(qn("w:id"), str(issue_idx))
                ref_run.append(ref)
                paragraph.append(range_end)
                paragraph.append(ref_run)

        doc_tree.write(str(doc_xml_path), xml_declaration=True, encoding="UTF-8", standalone=True)

        # 6. 重新打包
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for root, _, files in os.walk(work_dir):
                for file in files:
                    file_path = Path(root) / file
                    arcname = str(file_path.relative_to(work_dir))
                    zout.write(file_path, arcname)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def annotate_bid_document(result: ProofreadResult, output_path: Path | str) -> Path:
    """
    生成一份带偏离标注的投标文件副本。

    - 对包含偏离的段落设置背景色高亮。
    - 对 highlight_spans 中的具体文字标红加粗。
    - 在段落末尾追加红色说明文字。
    - 注入 Word 原生批注（comments）。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bid_source = result.bid_doc.path
    if output_path.resolve() == bid_source.resolve():
        raise ValueError("标注输出路径不能与源投标文件相同，请选择其他路径。")

    # 处理 .doc：先转换为 .docx 临时文件
    if bid_source.suffix.lower() == ".doc":
        with tempfile.TemporaryDirectory(prefix="smart_proofreader_bid_convert_") as tmp_convert_dir:
            converted = convert_doc_to_docx(bid_source, Path(tmp_convert_dir))
            shutil.copy(converted, output_path)
    else:
        shutil.copy(bid_source, output_path)

    doc = Document(str(output_path))

    # 按段落收集需要标注的 issues，并记录每个 issue 对应的段落索引
    issues_by_paragraph: Dict[int, List[ConsistencyIssue]] = {}
    issue_paragraph_index: Dict[str, int] = {}
    missing_response_issues: List[ConsistencyIssue] = []
    for issue in result.consistency_issues:
        if not issue.bid_blocks:
            missing_response_issues.append(issue)
            continue
        target_text = issue.bid_blocks[0].text
        if not target_text:
            continue

        matched = False
        block_index = issue.bid_blocks[0].index

        # 优先使用 block.index 直接定位段落，避免文本重复时匹配错误
        if 0 <= block_index < len(doc.paragraphs):
            if _match_paragraph(doc.paragraphs[block_index].text, target_text):
                issues_by_paragraph.setdefault(block_index, []).append(issue)
                issue_paragraph_index[issue.issue_id] = block_index
                matched = True

        # 回退：按文本模糊匹配
        if not matched:
            for p_idx, paragraph in enumerate(doc.paragraphs):
                if _match_paragraph(paragraph.text, target_text):
                    issues_by_paragraph.setdefault(p_idx, []).append(issue)
                    issue_paragraph_index[issue.issue_id] = p_idx
                    matched = True
                    break

        # 段落未命中，尝试在表格单元格中匹配
        if not matched:
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if _match_paragraph(cell.text, target_text):
                            # 表格单元格直接标红并追加说明
                            _mark_spans_red(cell.paragraphs[0], issue.highlight_spans)
                            _add_issue_note(cell.paragraphs[0], issue)
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    break

    # 对匹配到的段落执行标注
    for p_idx, issues in issues_by_paragraph.items():
        paragraph = doc.paragraphs[p_idx]
        # 取最高级别作为底纹颜色
        most_severe = min(
            issues,
            key=lambda i: (
                i.level != IssueLevel.ERROR,
                i.level != IssueLevel.WARNING,
                i.level != IssueLevel.INFO,
            ),
        )
        fill_color = LEVEL_FILL_COLORS.get(most_severe.level, "FFF3CD")
        _set_paragraph_shading(paragraph, fill_color)

        # 精确文字标红
        all_spans: List[str] = []
        for issue in issues:
            all_spans.extend(issue.highlight_spans)
        _mark_spans_red(paragraph, all_spans)

        for issue in issues:
            _add_issue_note(paragraph, issue)

    # 对缺失响应的需求在文档末尾追加汇总页
    if missing_response_issues:
        doc.add_page_break()
        title_para = doc.add_paragraph()
        title_run = title_para.add_run("未响应需求汇总")
        title_run.font.bold = True
        title_run.font.size = Pt(14)
        title_run.font.color.rgb = RGBColor(220, 53, 69)

        for issue in missing_response_issues:
            p = doc.add_paragraph()
            run = p.add_run(
                f"[{issue.issue_id}] 需求 {issue.requirement_id}\n"
                f"需求内容：{issue.requirement_text}\n"
                f"问题：{issue.message}\n"
                f"建议：{issue.suggestion}"
            )
            run.font.color.rgb = RGBColor(220, 53, 69)
            run.font.size = Pt(10)

    doc.save(str(output_path))

    # 注入 Word 原生批注（对缺失响应也生成批注，便于在汇总页查看）
    _inject_comments_into_docx(output_path, result.consistency_issues, issue_paragraph_index)

    return output_path
