"""Streamlit 桌面 UI。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from proofreader.checkers.consistency_checker import ConsistencyIssue, IssueLevel, IssueType  # noqa: E402
from proofreader.exporters import export_to_excel, export_to_word  # noqa: E402
from proofreader.extractors.bid_splitter import BidSectionType, get_blocks_by_section  # noqa: E402
from proofreader.pipeline import ProofreadResult, Proofreader  # noqa: E402


st.set_page_config(page_title="智能文档校对器", layout="wide")

st.markdown(
    """
    <style>
    .issue-card { padding: 12px; margin: 8px 0; border-radius: 6px; background: #f8f9fa; border-left: 5px solid #ccc; }
    .issue-card:hover { background: #e9ecef; }
    .req-box { background: #e7f3ff; padding: 10px; border-radius: 4px; margin: 6px 0; }
    .bid-box { background: #fff7e6; padding: 10px; border-radius: 4px; margin: 6px 0; }
    .badge { font-size: 12px; padding: 2px 8px; border-radius: 12px; color: white; }
    .highlight { background-color: #ffeb3b; padding: 2px 4px; border-radius: 3px; }
    </style>
    """,
    unsafe_allow_html=True,
)


LEVEL_COLORS = {
    IssueLevel.ERROR: ("#dc3545", "严重"),
    IssueLevel.WARNING: ("#ffc107", "警告"),
    IssueLevel.INFO: ("#0dcaf0", "提示"),
}

ISSUE_TYPE_LABELS = {
    IssueType.MISSING_RESPONSE: "缺失响应",
    IssueType.PARAMETER_MISMATCH: "参数不一致",
    IssueType.TIME_MISMATCH: "时间/期限不一致",
    IssueType.KEYWORD_MISSING: "关键词缺失",
    IssueType.SEMANTIC_LOW: "疑似未响应",
}


def save_uploaded_file(uploaded_file) -> Path:
    tmp_dir = Path(".tmp_uploads")
    tmp_dir.mkdir(exist_ok=True)
    path = tmp_dir / uploaded_file.name
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path


def render_sidebar():
    st.sidebar.title("📄 智能文档校对器")
    st.sidebar.markdown("上传需求文件与投标文件，自动检查内容一致性。")

    req_file = st.sidebar.file_uploader("需求文件 (.docx)", type=["docx"], key="req_file")
    bid_file = st.sidebar.file_uploader("投标文件 (.docx)", type=["docx"], key="bid_file")
    run = st.sidebar.button("开始校对", type="primary", use_container_width=True)

    return req_file, bid_file, run


def render_doc_panel(title: str, blocks, height: int = 600):
    """渲染文档原文面板。"""
    st.subheader(title)
    html_lines = []
    for block in blocks:
        text = block.text.replace("\n", "<br>")
        if block.block_type == "heading":
            html_lines.append(f"<h{block.level}>{text}</h{block.level}>")
        else:
            html_lines.append(f"<p>{text}</p>")
    st.markdown("\n".join(html_lines), unsafe_allow_html=True)


def render_issue_card(issue: ConsistencyIssue):
    color, level_text = LEVEL_COLORS.get(issue.level, ("#6c757d", "未知"))
    type_text = ISSUE_TYPE_LABELS.get(issue.issue_type, issue.issue_type.value)

    st.markdown(
        f"""
        <div class="issue-card" style="border-left-color: {color};">
            <span class="badge" style="background: {color};">{level_text}</span>
            <b> {type_text}</b>
            <div style="margin-top:6px;"><b>问题：</b>{issue.message}</div>
            <div style="margin-top:6px;"><b>建议：</b>{issue.suggestion}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"""
            <div class="req-box">
                <b>📋 需求条目（{issue.requirement_id}）</b><br>
                {issue.requirement_text.replace(chr(10), '<br>')}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        bid_html = issue.bid_text.replace(chr(10), "<br>") if issue.bid_text else "<i>未找到对应响应</i>"
        st.markdown(
            f"""
            <div class="bid-box">
                <b>📝 投标响应</b><br>
                {bid_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _prepare_download(result: ProofreadResult, exporter) -> tuple[bytes, str]:
    """生成报告文件并返回二进制内容和文件扩展名。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ext = ".docx" if exporter is export_to_word else ".xlsx"
        path = Path(tmp_dir) / f"校对报告{ext}"
        exporter(result, path)
        return path.read_bytes(), ext


def render_results(result: ProofreadResult):
    st.success(
        f"校对完成：共发现 {len(result.consistency_issues)} 处一致性/偏离问题，"
        f"{len(result.table_issues)} 处表格问题，{len(result.typo_issues)} 处错别字，"
        f"{len(result.ocr_issues)} 处截图问题。"
    )

    c1, c2 = st.columns(2)
    with c1:
        word_bytes, _ = _prepare_download(result, export_to_word)
        st.download_button(
            label="📄 导出 Word 报告",
            data=word_bytes,
            file_name="校对报告.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    with c2:
        excel_bytes, _ = _prepare_download(result, export_to_excel)
        st.download_button(
            label="📊 导出 Excel 清单",
            data=excel_bytes,
            file_name="校对报告.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    tab_doc, tab_issues = st.tabs(["📑 文档对照", "⚠️ 问题清单"])

    with tab_doc:
        c1, c2, c3 = st.columns([2, 2, 1.5])
        with c1:
            st.subheader("需求文件")
            for req in result.requirements:
                with st.container(border=True):
                    st.markdown(f"**{req.item_id}**")
                    st.markdown(req.text.replace("\n", "  \n"))
                    if req.constraint_keywords:
                        st.caption("约束词：" + "、".join(req.constraint_keywords[:8]))

        with c2:
            st.subheader("投标文件")
            section_tab = st.radio(
                "选择部分",
                ["全部", "商务", "技术", "价格"],
                horizontal=True,
                label_visibility="collapsed",
            )
            section_map = {
                "全部": None,
                "商务": BidSectionType.BUSINESS,
                "技术": BidSectionType.TECHNICAL,
                "价格": BidSectionType.PRICE,
            }
            section_type = section_map[section_tab]
            if section_type is None:
                blocks = result.bid_doc.blocks
            else:
                blocks = get_blocks_by_section(result.bid_sections, section_type)

            for block in blocks[:300]:
                if block.block_type == "heading":
                    st.markdown(f"**{block.text}**")
                else:
                    st.markdown(block.text.replace("\n", "  \n"))

        with c3:
            st.subheader("问题概览")
            issues_by_req: Dict[str, List[ConsistencyIssue]] = {}
            for issue in result.consistency_issues:
                issues_by_req.setdefault(issue.requirement_id, []).append(issue)

            for req_id, issues in issues_by_req.items():
                with st.expander(f"{req_id}（{len(issues)} 个问题）"):
                    for issue in issues:
                        color, _ = LEVEL_COLORS.get(issue.level, ("#6c757d", "未知"))
                        st.markdown(
                            f"<span style='color:{color}; font-weight:bold;'>●</span> "
                            f"{ISSUE_TYPE_LABELS.get(issue.issue_type, issue.issue_type.value)}",
                            unsafe_allow_html=True,
                        )
                        st.caption(issue.message[:60] + "...")

            if result.typo_issues:
                with st.expander(f"错别字（{len(result.typo_issues)} 个）"):
                    for typo in result.typo_issues[:30]:
                        st.markdown(f"**{typo.word}** → {typo.suggestion}")

            if result.ocr_issues:
                with st.expander(f"截图问题（{len(result.ocr_issues)} 个）"):
                    for ocr in result.ocr_issues:
                        ctx = f"（位于：{ocr.context_block.text[:40]}...）" if ocr.context_block else ""
                        st.markdown(f"图片 #{ocr.image_index} {ctx}：{ocr.message[:80]}...")

            if result.table_issues:
                with st.expander(f"表格问题（{len(result.table_issues)} 个）"):
                    for table in result.table_issues:
                        st.markdown(f"**{table.issue_id}**：{table.message[:80]}...")

    with tab_issues:
        if result.consistency_issues:
            st.subheader("一致性 / 偏离问题")
            for issue in result.consistency_issues:
                render_issue_card(issue)
                st.divider()

        if result.typo_issues:
            st.subheader("错别字")
            for typo in result.typo_issues:
                st.markdown(f"- **{typo.word}** → {typo.suggestion}（{typo.message}）")

        if result.ocr_issues:
            st.subheader("截图 OCR 问题")
            for ocr in result.ocr_issues:
                if ocr.context_block:
                    ctx_text = ocr.context_block.text.replace(chr(10), " ")[:80]
                    ctx = f"<br><i>位置：{ctx_text}...</i>"
                else:
                    ctx = ""
                st.markdown(
                    f"- 图片 #{ocr.image_index}：{ocr.message}{ctx}",
                    unsafe_allow_html=True,
                )

        if result.table_issues:
            st.subheader("表格比对问题")
            for table in result.table_issues:
                with st.container(border=True):
                    st.markdown(f"**{table.issue_id}**：{table.message}")
                    st.markdown(f"*建议：{table.suggestion}*")
                    if table.details:
                        with st.expander("查看差异详情"):
                            for detail in table.details:
                                st.markdown(f"- {detail}")


def main():
    req_file, bid_file, run = render_sidebar()

    if not run:
        st.title("欢迎使用智能文档校对器")
        st.markdown("""
        本工具用于校对 Word 投标文件与需求文件的内容一致性，帮助你发现：
        - 需求响应缺失或偏离
        - 技术参数、服务期限、交付时间不一致
        - 投标文件中的错别字
        - 截图是否覆盖关键需求
        """)
        return

    if not req_file or not bid_file:
        st.warning("请同时上传需求文件和投标文件。")
        return

    with st.spinner("正在解析文档并执行校对，请稍候..."):
        req_path = save_uploaded_file(req_file)
        bid_path = save_uploaded_file(bid_file)

        proofreader = Proofreader()
        result = proofreader.proofread(req_path, bid_path)

    render_results(result)


if __name__ == "__main__":
    main()
