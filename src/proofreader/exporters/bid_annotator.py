"""在投标文件副本中高亮标注偏离项（精确文字标红 + Word 原生批注）。"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from lxml import etree

from proofreader.checkers.consistency_checker import (
    ConsistencyIssue,
    IssueLevel,
    IssueType,
)
from proofreader.parsers.docx_parser import convert_doc_to_docx
from proofreader.pipeline import ProofreadResult


# 子序列匹配的最大文本长度；超过此长度时回退到线性贪心匹配，避免 O(n²) 拖垮导出
_MAX_SUBSEQUENCE_TEXT_LEN = 2000


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
    段落文本过短（仅为目标的小片段）时不应命中，避免小标题/页眉被误判。
    """
    if not target_text:
        return False
    pt = _normalize(paragraph_text)
    tt = _normalize(target_text)
    if not pt:
        return False
    if pt == tt:
        return True
    # 目标完整包含于段落：最常见正确场景
    if tt in pt:
        return True
    # 段落是目标的一部分时，只有段落覆盖目标足够多内容才命中（防止小标题误匹配）
    if pt in tt and len(pt) >= len(tt) * 0.6:
        return True
    return False


def _score_paragraph_match(paragraph_text: str, target_text: str) -> float:
    """计算段落与目标文本的匹配得分，用于回退时选择最佳段落。"""
    pt = _normalize(paragraph_text)
    tt = _normalize(target_text)
    if not pt or not tt:
        return 0.0
    if pt == tt:
        return 1.0
    if tt in pt:
        return 0.9
    if pt in tt:
        return 0.7 * (len(pt) / len(tt))
    # 基于目标字符的覆盖度
    tt_chars = set(tt)
    overlap = len(set(pt) & tt_chars) / len(tt_chars) if tt_chars else 0.0
    return overlap * 0.5


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


# ---------------------------------------------------------------------------
# 精确文字标红（支持跨空格/修饰词的子序列匹配）
# ---------------------------------------------------------------------------

_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _run_text_element(run) -> str:
    """提取 <w:r> 内所有 <w:t> 的文本。"""
    return "".join(t.text or "" for t in run.iter(qn("w:t")))


def _make_run_element(text: str, rpr=None):
    """创建带文本和可选格式属性的 <w:r> 元素。"""
    if not text:
        return None
    run = OxmlElement("w:r")
    if rpr is not None:
        run.append(deepcopy(rpr))
    t = OxmlElement("w:t")
    t.text = text
    if text[0].isspace() or text[-1].isspace():
        t.set(_XML_SPACE, "preserve")
    run.append(t)
    return run


def _set_run_red_bold(run) -> None:
    """将 <w:r> 设置为红色加粗。"""
    rPr = run.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        run.insert(0, rPr)
    else:
        # 避免重复属性
        for color in list(rPr.findall(qn("w:color"))):
            rPr.remove(color)
        for bold in list(rPr.findall(qn("w:b"))):
            rPr.remove(bold)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "FF0000")
    rPr.append(color)
    bold = OxmlElement("w:b")
    bold.set(qn("w:val"), "1")
    rPr.append(bold)


def _find_shortest_subsequence_window(text: str, pattern: str) -> Tuple[int, int] | None:
    """在 text 中找出包含 pattern 作为子序列的最短窗口 [start, end]（均含）。

    例如 text="前缀800并发用户后缀", pattern="800用户" → (2, 8)，
    对应窗口 "800并发用户"，允许少量修饰词位于数字与单位之间。

    对超长文本回退到 O(n) 贪心子序列窗口，避免精心构造的长段落导致 O(n²) 挂起。
    """
    if not pattern or not text:
        return None
    n, m = len(text), len(pattern)
    if n == 0 or m == 0 or m > n:
        return None

    # 超长文本：线性贪心取第一个满足的窗口
    if n > _MAX_SUBSEQUENCE_TEXT_LEN:
        return _greedy_subsequence_window(text, pattern)

    best: Tuple[int, int] | None = None

    for start in range(n):
        if text[start] != pattern[0]:
            continue
        p_idx = 1
        for end in range(start + 1, n):
            if text[end] == pattern[p_idx]:
                p_idx += 1
                if p_idx == m:
                    if best is None or end - start < best[1] - best[0]:
                        best = (start, end)
                    break
        # 如果 start 出发无法完整匹配，后续以相同字符出发的窗口只会更长，可直接结束
        if best is None and p_idx < m:
            continue
    return best


def _greedy_subsequence_window(text: str, pattern: str) -> Tuple[int, int] | None:
    """O(n) 贪心找到 pattern 作为子序列在 text 中的第一个窗口。"""
    p_idx = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == pattern[p_idx]:
            if start == -1:
                start = i
            p_idx += 1
            if p_idx == len(pattern):
                return (start, i)
    return None


def _find_contiguous_span_in_runs(paragraph, span_text: str):
    """
    在段落的 <w:r> 序列中定位 span_text，返回覆盖目标文字的最小连续片段。

    优先按「去除空格后的连续子串」匹配；失败时采用「最短子序列窗口」匹配，
    兼容 highlight_span 与文档实际文字之间存在少量修饰词的情况，
    例如 span="800用户" 可匹配到 "800 并发用户"，但拒绝跨句/跨大段漂移。
    """
    span_norm = _normalize(span_text).replace(" ", "")
    if not span_norm:
        return None

    runs = [c for c in paragraph if c.tag == qn("w:r")]
    if not runs:
        return None

    run_texts = [_run_text_element(r) for r in runs]
    # 记录每个非空格字符所在的 run 与原始偏移
    norm_to_raw = []
    for r_idx, raw in enumerate(run_texts):
        for offset, ch in enumerate(raw):
            if not ch.isspace():
                norm_to_raw.append((r_idx, offset, ch))
    if not norm_to_raw:
        return None

    para_norm = "".join(ch for _, _, ch in norm_to_raw)

    # 1) 优先连续子串匹配
    start = para_norm.find(span_norm)
    if start >= 0:
        end = start + len(span_norm) - 1
    else:
        # 2) 最短子序列窗口匹配，限制窗口不能过大，防止跨无关文字漂移
        window = _find_shortest_subsequence_window(para_norm, span_norm)
        if window is None:
            return None
        start, end = window
        window_len = end - start + 1
        span_len = len(span_norm)
        # 允许最多 span 长度 2 倍或 +4 个额外字符，取较大者
        max_window_len = max(span_len * 2, span_len + 4)
        if window_len > max_window_len:
            return None

    start_run, start_offset, _ = norm_to_raw[start]
    end_run, end_offset, _ = norm_to_raw[end]
    end_offset += 1  # 不包含结束位置

    return {
        "runs": runs,
        "run_texts": run_texts,
        "start_run": start_run,
        "start_offset": start_offset,
        "end_run": end_run,
        "end_offset": end_offset,
    }


def _isolate_span_runs(paragraph, info) -> List:
    """将 info 定位到的连续文字拆分为独立的 <w:r>，返回这些 run。"""
    start_run = info["start_run"]
    start_offset = info["start_offset"]
    end_run = info["end_run"]
    end_offset = info["end_offset"]
    runs = info["runs"]
    run_texts = info["run_texts"]

    new_runs: List = []
    covering: List = []
    for r_idx in range(start_run, end_run + 1):
        raw = run_texts[r_idx]
        rpr = runs[r_idx].find(qn("w:rPr"))
        if r_idx == start_run and r_idx == end_run:
            pieces = [raw[:start_offset], raw[start_offset:end_offset], raw[end_offset:]]
            cover_idx = 1
        elif r_idx == start_run:
            pieces = [raw[:start_offset], raw[start_offset:]]
            cover_idx = 1 if start_offset > 0 else 0
        elif r_idx == end_run:
            pieces = [raw[:end_offset], raw[end_offset:]]
            cover_idx = 0
        else:
            pieces = [raw]
            cover_idx = 0

        built = [_make_run_element(piece, rpr) for piece in pieces if piece]
        new_runs.extend(built)

        actual_idx = sum(1 for piece in pieces[:cover_idx] if piece)
        if actual_idx < len(built):
            covering.append(built[actual_idx])

    insert_pos = list(paragraph).index(runs[start_run])
    for run in new_runs:
        paragraph.insert(insert_pos, run)
        insert_pos += 1
    for r_idx in range(end_run, start_run - 1, -1):
        paragraph.remove(runs[r_idx])
    return covering


def _mark_spans_red(paragraph, spans: List[str]) -> None:
    """将段落中匹配 spans 的文字精确标红加粗（按字符子序列匹配，兼容空格/修饰词差异）。"""
    if not spans:
        return
    for span in spans:
        span = span.strip()
        if not span:
            continue
        info = _find_contiguous_span_in_runs(paragraph._p, span)
        if info is None:
            continue
        covering = _isolate_span_runs(paragraph._p, info)
        for run in covering:
            _set_run_red_bold(run)


# ---------------------------------------------------------------------------
# Word 原生批注（comments）支持 — 段落级范围，确保 Word/WPS 稳定显示
# ---------------------------------------------------------------------------

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _insert_comment_range_into_paragraph(
    paragraph,
    issue_idx: int,
    w_ns: str,
) -> None:
    """在段落的段落级范围内插入 commentRangeStart/End 和 commentReference。"""
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


def _select_response_cell_paragraph(table_row, w_ns: str):
    """
    在表格行中选择最可能是「响应内容」的单元格段落。

    策略：
    - 若最末单元格是短合规标识（符合/是/否/满足），取倒数第二列；
    - 否则，在排除首列（序号/产品名）后取最长文本的单元格。
    """
    cells = list(table_row.iter(f"{{{w_ns}}}tc"))
    if not cells:
        return None

    cell_texts = []
    for cell in cells:
        texts = [t.text or "" for t in cell.iter(f"{{{w_ns}}}t")]
        cell_texts.append("".join(texts).strip())

    if len(cells) == 1:
        target_idx = 0
    elif len(cells) == 2:
        target_idx = 1
    else:
        # 最末列是合规标识时，取倒数第二列
        last = cell_texts[-1]
        if len(last) <= 4 and last in ("符合", "是", "否", "满足", "不满足"):
            target_idx = len(cells) - 2
        else:
            # 排除首列后取最长
            longest_idx = max(range(1, len(cells)), key=lambda i: len(cell_texts[i]))
            target_idx = longest_idx

    target_cell = cells[target_idx]
    paragraphs = [c for c in target_cell if c.tag == f"{{{w_ns}}}p"]
    return paragraphs[0] if paragraphs else None


def _find_table_row_element_by_text(
    body, target_text: str, w_ns: str, highlight_spans: List[str] | None = None
):
    """在 body 的表格行中按文本匹配找到对应的 <w:tr>，优先精确匹配并利用高亮片段定位响应行。"""
    # parser 生成的表格行文本用 " | " 连接单元格，XML 中没有分隔符，统一去掉后再比较
    target_norm = _normalize(target_text.replace(" | ", "")).replace(" ", "")
    if not target_norm:
        return None

    candidates = []
    for tbl in body.iter(f"{{{w_ns}}}tbl"):
        for tr in tbl.iter(f"{{{w_ns}}}tr"):
            row_text = "".join(t.text or "" for t in tr.iter(f"{{{w_ns}}}t"))
            row_norm = _normalize(row_text).replace(" ", "")
            if target_norm == row_norm:
                candidates.append((tr, 0))
            elif target_norm in row_norm or row_norm in target_norm:
                candidates.append((tr, 1))

    if not candidates:
        return None

    # 优先精确匹配；存在多个候选时，用 highlight_span 在响应单元格中的出现情况进一步定位
    def _row_score(tr):
        if not highlight_spans:
            return 1
        cell_para = _select_response_cell_paragraph(tr, w_ns)
        if cell_para is None:
            return 1
        para_text = "".join(t.text or "" for t in cell_para.iter(f"{{{w_ns}}}t"))
        para_norm = _normalize(para_text).replace(" ", "")
        for span in highlight_spans:
            if _normalize(span).replace(" ", "") in para_norm:
                return 0
        return 1

    candidates.sort(key=lambda item: (item[1], _row_score(item[0])))
    return candidates[0][0]


def _build_comment_text(issue: ConsistencyIssue) -> str:
    """生成 Word 批注正文：包含需求ID、涉及文字、问题、建议。"""
    lines = [f"[{issue.issue_id}] 需求 {issue.requirement_id}"]
    spans = [s.strip() for s in (issue.highlight_spans or []) if s.strip()]
    if spans:
        lines.append(f"涉及文字：{'、'.join(spans)}")
    lines.append(f"问题：{issue.message}")
    if issue.suggestion:
        lines.append(f"建议：{issue.suggestion}")
    return "\n".join(lines)


def _should_annotate_issue(issue: ConsistencyIssue, issue_paragraph_index: Dict[str, int]) -> bool:
    """判断 issue 是否值得生成 Word 批注：过滤空理由、低置信度、无法定位的 issue。"""
    if not issue.bid_blocks or not issue.message or not issue.message.strip():
        return False

    block = issue.bid_blocks[0]
    # 正文段落必须能定位
    if block.block_type != "table_row":
        if block.para_index is None or issue.issue_id not in issue_paragraph_index:
            return False

    # 过滤无具体标红文字的低置信度语义 issue，避免产生大量「疑似未响应」的无效批注
    if issue.issue_type == IssueType.SEMANTIC_LOW:
        spans = [s.strip() for s in (issue.highlight_spans or []) if s.strip()]
        if not spans:
            return False

    return True


def _inject_comments_into_docx(
    docx_path: Path,
    issues: List[ConsistencyIssue],
    issue_paragraph_index: Dict[str, int],
) -> None:
    """
    向已保存的 docx 文件中注入 Word 原生批注。

    - 对能定位到正文段落的 issue 生成批注（一个问题一个批注）。
    - 对表格行 issue，在响应单元格内生成批注。
    - 批注范围统一为段落级，确保 Word/WPS 都能稳定显示批注气泡。
    - 自动过滤低置信度、无明确理由的 issue，减少无效批注。
    """
    # 过滤有效 issue：必须有 bid_blocks、非空理由、非低置信度噪声
    valid_issues = [
        issue for issue in issues if _should_annotate_issue(issue, issue_paragraph_index)
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
            text = _build_comment_text(issue)
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
                el.get("PartName") == "/word/comments.xml"
                and el.get("ContentType") == comments_ct
                for el in ct_root
            )
            if not already:
                override = etree.SubElement(ct_root, f"{{{ct_ns}}}Override")
                override.set("PartName", "/word/comments.xml")
                override.set("ContentType", comments_ct)
                ct_tree.write(str(content_types_path), xml_declaration=True, encoding="UTF-8", standalone=True)

        # 5. 在 document.xml 中插入批注范围（段落级，稳定兼容）
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
            block = issue.bid_blocks[0]

            if block.para_index is not None:
                # 正文段落
                preferred_idx = issue_paragraph_index.get(issue.issue_id)
                if preferred_idx is None or not (0 <= preferred_idx < len(body_paragraphs)):
                    continue
                paragraph = body_paragraphs[preferred_idx]
                _insert_comment_range_into_paragraph(paragraph, issue_idx, w_ns)
            elif block.block_type == "table_row":
                # 表格行：找到对应 <w:tr>，在响应单元格段落中插入批注
                table_row = _find_table_row_element_by_text(
                    body, block.text, w_ns, issue.highlight_spans
                )
                if table_row is None:
                    continue
                cell_para = _select_response_cell_paragraph(table_row, w_ns)
                if cell_para is None:
                    continue
                _insert_comment_range_into_paragraph(cell_para, issue_idx, w_ns)

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


def _select_response_cell_index(row) -> int | None:
    """在 python-docx 表格行中选择最可能是「响应内容」的单元格下标。"""
    cells = list(row.cells)
    if not cells:
        return None
    cell_texts = [cell.text.strip() for cell in cells]
    if len(cells) == 1:
        return 0
    if len(cells) == 2:
        return 1
    last = cell_texts[-1]
    if len(last) <= 4 and last in ("符合", "是", "否", "满足", "不满足"):
        return len(cells) - 2
    return max(range(1, len(cells)), key=lambda i: len(cell_texts[i]))


def _mark_table_row_spans(doc, issue: ConsistencyIssue) -> bool:
    """在表格行中匹配 issue 的 bid_blocks 文字，并仅对响应单元格中的 highlight_span 标红。

    表格行还会在 _inject_comments_into_docx 中生成 Word 批注，这里仅做视觉高亮辅助。
    """
    if not issue.bid_blocks:
        return False
    target_text = issue.bid_blocks[0].text
    if not target_text:
        return False
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells)
            if _match_paragraph(row_text, target_text):
                target_idx = _select_response_cell_index(row)
                if target_idx is None:
                    continue
                target_cell = row.cells[target_idx]
                if target_cell.paragraphs:
                    _mark_spans_red(target_cell.paragraphs[0], issue.highlight_spans)
                return True
    return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def annotate_bid_document(result: ProofreadResult, output_path: Path | str) -> Path:
    """
    生成一份带偏离标注的投标文件副本。

    - 对包含偏离的段落设置背景色高亮。
    - 对 highlight_spans 中的具体文字标红加粗。
    - 注入 Word 原生批注（comments）承载 issue 详情；批注范围统一为段落级，
      确保 Word/WPS 都能稳定显示批注气泡，不往正文插入说明文字。
    - 表格行 issue 同样在响应单元格内生成 Word 批注，并对具体文字标红。
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

    # 按段落收集需要标注的 issues，并记录每个 issue 对应的 body 段落索引
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
        block = issue.bid_blocks[0]

        # 优先使用 para_index（真实的 body paragraph 下标）直接定位
        if block.para_index is not None and 0 <= block.para_index < len(doc.paragraphs):
            if _match_paragraph(doc.paragraphs[block.para_index].text, target_text):
                issues_by_paragraph.setdefault(block.para_index, []).append(issue)
                issue_paragraph_index[issue.issue_id] = block.para_index
                matched = True

        # 回退：在 doc.paragraphs 范围内按文本相似度选择最佳段落，避免首个命中导致的错位
        if not matched:
            best_idx: int | None = None
            best_score = 0.0
            for p_idx, paragraph in enumerate(doc.paragraphs):
                score = _score_paragraph_match(paragraph.text, target_text)
                if score > best_score:
                    best_score = score
                    best_idx = p_idx
            # 只有得分足够高才接受，防止无关段落被误标
            if best_idx is not None and best_score >= 0.5:
                issues_by_paragraph.setdefault(best_idx, []).append(issue)
                issue_paragraph_index[issue.issue_id] = best_idx
                matched = True

        # 段落未命中，尝试在表格行中匹配并标红
        if not matched and block.block_type == "table_row":
            _mark_table_row_spans(doc, issue)

    # 对匹配到的正文段落执行标注
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

    # 注入 Word 原生批注
    _inject_comments_into_docx(output_path, result.consistency_issues, issue_paragraph_index)

    return output_path
