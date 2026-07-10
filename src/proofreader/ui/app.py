"""Streamlit 桌面 UI。"""
from __future__ import annotations

import base64
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Sequence

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from proofreader.checkers.consistency_checker import ConsistencyIssue, IssueLevel, IssueType  # noqa: E402
from proofreader.exporters import (  # noqa: E402
    annotate_bid_document,
    export_batch_to_excel,
    export_to_excel,
)
from proofreader.exporters.excel_exporter import _level_text  # noqa: E402
from proofreader.extractors.bid_splitter import BidSectionType, get_blocks_by_section  # noqa: E402
from proofreader.pipeline import (  # noqa: E402
    BatchProofreadError,
    BatchResultItem,
    ProofreadBatchResult,
    ProofreadResult,
    Proofreader,
)
from proofreader.ui.highlighting import highlight_differences, html_escape  # noqa: E402


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


def save_uploaded_files(uploaded_files: Sequence, subdir: str = "") -> List[Path]:
    """保存上传的多个文件到项目临时目录，返回路径列表。

    使用 UUID 前缀避免同名文件互相覆盖；目录在 .gitignore 中已排除。
    每次新的上传批次会清理该子目录中的旧文件（本地单用户场景）。
    """
    tmp_dir = Path(".tmp_uploads")
    if subdir:
        tmp_dir = tmp_dir / subdir
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 清理旧上传文件，避免累积（本地桌面应用单用户使用）
    for old_path in tmp_dir.iterdir():
        if old_path.is_file():
            try:
                old_path.unlink()
            except OSError:
                pass

    paths: List[Path] = []
    for uploaded_file in uploaded_files:
        safe_name = Path(uploaded_file.name).name
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        path = tmp_dir / unique_name
        with open(path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        paths.append(path)
    return paths


def render_sidebar():
    st.sidebar.title("📄 智能文档校对器")
    st.sidebar.markdown("上传需求与投标文件，自动合并需求并逐项校对每份投标。")

    req_files = st.sidebar.file_uploader(
        "需求文件 (.docx / .doc)",
        type=["docx", "doc"],
        accept_multiple_files=True,
        key="req_files",
    )
    bid_files = st.sidebar.file_uploader(
        "投标文件 (.docx / .doc)",
        type=["docx", "doc"],
        accept_multiple_files=True,
        key="bid_files",
    )
    run = st.sidebar.button("开始校对", type="primary", use_container_width=True)
    reset = st.sidebar.button("重新上传文件", use_container_width=True)

    return req_files, bid_files, run, reset


def _prepare_excel_download(result: ProofreadResult | ProofreadBatchResult, exporter=export_to_excel, file_name: str = "校对报告.xlsx") -> bytes:
    """生成 Excel 清单并返回二进制内容。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / file_name
        exporter(result, path)
        return path.read_bytes()


def _prepare_batch_excel_download(batch_result: ProofreadBatchResult) -> bytes:
    """生成批量 Excel 清单并返回二进制内容。"""
    return _prepare_excel_download(
        batch_result, export_batch_to_excel, "批量校对报告.xlsx"
    )


def _download_link(data: bytes, file_name: str, mime: str, label: str, color: str = "#0d6efd") -> str:
    """生成基于 Base64 Data URI 的 HTML 下载链接，点击不触发 Streamlit rerun。"""
    b64 = base64.b64encode(data).decode()
    return (
        f'<a href="data:{mime};base64,{b64}" download="{file_name}" '
        f'style="display:inline-block; width:100%; text-align:center; padding:10px 16px; '
        f'background-color:{color}; color:white; text-decoration:none; border-radius:6px; '
        f'font-weight:500; box-sizing:border-box;" '
        f'onmouseover="this.style.opacity=\'0.9\'" onmouseout="this.style.opacity=\'1\'">'
        f"{label}</a>"
    )


def _prepare_annotated_bid(result: ProofreadResult) -> tuple[bytes, str]:
    """生成带偏离标注的投标文件副本，返回二进制内容和文件扩展名。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        ext = ".docx"
        path = Path(tmp_dir) / f"带标注的投标文件{ext}"
        annotate_bid_document(result, path)
        return path.read_bytes(), ext


@st.fragment
def _render_annotated_bid_download_button(result: ProofreadResult, bid_stem: str) -> None:
    """标注投标文件下载按钮（fragment 隔离，点击不触发全页面 rerun）。"""
    annotated_bytes, _ = _prepare_annotated_bid(result)
    st.download_button(
        label="🖍️ 导出标注投标文件",
        data=annotated_bytes,
        file_name=f"带标注的投标文件_{bid_stem}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
        type="secondary",
    )


def render_doc_tab(result: ProofreadResult):
    """渲染「文档对照」标签页内容。"""
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


def _render_issue_card_inline(issue: ConsistencyIssue) -> None:
    """在偏离分析中渲染一条问题的左右原文对照卡片。"""
    color, level_text = LEVEL_COLORS.get(issue.level, ("#6c757d", "未知"))
    type_text = ISSUE_TYPE_LABELS.get(issue.issue_type, issue.issue_type.value)

    st.markdown(
        f'<div style="display:flex; gap:8px; align-items:center; margin-bottom:8px;">'
        f'<span style="background:{color}; color:white; padding:2px 10px; border-radius:12px; font-size:12px;">{level_text}</span>'
        f'<span style="font-weight:bold; font-size:15px;">[{type_text}] {issue.issue_id}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(f"**偏离说明：**{issue.message}")
    st.markdown(f"<span style='color:#666;'>**建议：**{issue.suggestion}</span>", unsafe_allow_html=True)

    req_html, bid_html = highlight_differences(issue.requirement_text, issue.bid_text or "")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**📋 需求原文**")
        st.markdown(
            f'<div style="background:#f8f9fa; padding:12px; border-radius:6px; line-height:1.6; min-height:80px;">'
            f"{req_html}</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown("**📝 投标响应原文**")
        if issue.bid_text:
            st.markdown(
                f'<div style="background:#fff7e6; padding:12px; border-radius:6px; line-height:1.6; min-height:80px;">'
                f"{bid_html}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="background:#ffebee; padding:12px; border-radius:6px; color:#d32f2f; min-height:80px;">'
                "未找到对应响应</div>",
                unsafe_allow_html=True,
            )

    if len(issue.candidate_bid_texts) > 1:
        with st.expander(f"🔍 其他候选匹配（{len(issue.candidate_bid_texts) - 1} 个）"):
            for idx, (text, score) in enumerate(issue.candidate_bid_texts[1:], start=2):
                st.markdown(f"**候选 #{idx}**（匹配度 {score:.2f}）")
                st.markdown(
                    f'<div style="background:#f5f5f5; padding:8px; border-radius:4px; font-size:13px; line-height:1.5;">'
                    f"{html_escape(text)}</div>",
                    unsafe_allow_html=True,
                )


def render_issues_tab(result: ProofreadResult):
    """渲染「偏离分析」标签页内容：左右原文对照 + 候选匹配。"""
    st.subheader("偏离分析")

    # 筛选器
    filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 1])
    with filter_col1:
        issue_type_filter = st.multiselect(
            "按问题类型筛选",
            options=list(IssueType),
            default=list(IssueType),
            format_func=lambda x: ISSUE_TYPE_LABELS.get(x, x.value),
            key="issue_type_filter",
        )
    with filter_col2:
        level_filter = st.multiselect(
            "按严重程度筛选",
            options=list(IssueLevel),
            default=list(IssueLevel),
            format_func=_level_text,
            key="level_filter",
        )
    with filter_col3:
        show_all = st.toggle("显示全部需求", value=False, key="show_all_requirements")

    filtered_issues = [
        i for i in result.consistency_issues
        if i.issue_type in issue_type_filter and i.level in level_filter
    ]

    if not filtered_issues and not show_all:
        st.info("当前筛选条件下无偏离问题。开启「显示全部需求」可查看所有需求条目对照。")
        return

    if show_all:
        # 以需求条目为维度展示，没生成 issue 的显示为「正常/疑似未响应」
        issues_by_req: Dict[str, List[ConsistencyIssue]] = {}
        for issue in result.consistency_issues:
            issues_by_req.setdefault(issue.requirement_id, []).append(issue)

        for req in result.requirements:
            req_issues = issues_by_req.get(req.item_id, [])
            visible_issues = [i for i in req_issues if i.issue_type in issue_type_filter and i.level in level_filter]
            with st.container(border=True):
                st.markdown(f"**{req.item_id}**")
                if not visible_issues:
                    req_html, bid_html = highlight_differences(req.text, "")
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**📋 需求原文**")
                        st.markdown(
                            f'<div style="background:#f8f9fa; padding:12px; border-radius:6px; line-height:1.6;">'
                            f"{req_html}</div>",
                            unsafe_allow_html=True,
                        )
                    with c2:
                        st.markdown("**📝 投标响应原文**")
                        st.markdown(
                            '<div style="background:#eeeeee; padding:12px; border-radius:6px; color:#757575;">'
                            "未触发偏离检测或匹配度不足</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    for issue in visible_issues:
                        _render_issue_card_inline(issue)
        return

    for issue in filtered_issues:
        with st.container(border=True):
            _render_issue_card_inline(issue)
        st.divider()


def _render_batch_download_buttons(batch_result: ProofreadBatchResult):
    """批量下载链接，使用 HTML Data URI，点击不触发 Streamlit rerun。"""
    excel_bytes = _prepare_batch_excel_download(batch_result)
    st.markdown(
        _download_link(
            excel_bytes,
            "批量校对报告.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "📊 导出批量 Excel 清单",
            color="#198754",
        ),
        unsafe_allow_html=True,
    )


def render_batch_results(batch_result: ProofreadBatchResult):
    """渲染批量校对结果总览，并允许用户选择具体文件对查看详情。"""
    total = batch_result.total_pairs
    success = len(batch_result.items)
    failed = len(batch_result.errors)

    st.success(
        f"批量校对完成：共 {total} 份投标文件，成功 {success} 份，失败 {failed} 份。"
        f"累计发现 {batch_result.total_consistency_issues} 处一致性/偏离问题，"
        f"{batch_result.total_table_issues} 处表格问题，"
        f"{batch_result.total_typo_issues} 处错别字，"
        f"{batch_result.total_ocr_issues} 处截图问题。"
    )

    if batch_result.errors:
        with st.expander(f"⚠️ 失败项（{failed} 对）"):
            for err in batch_result.errors:
                req_names = "、".join(p.name for p in err.requirement_paths)
                st.error(f"{req_names} vs {err.bid_path.name}：{err.error}")

    if not batch_result.items:
        st.warning("没有成功校对的结果可展示。")
        return

    # 批量下载按钮放在文件对选择器附近，使用 fragment 避免全页面 rerun
    _render_batch_download_buttons(batch_result)

    # 使用 session state 持久化当前投标文件索引和 tab 选择
    if "selected_bid_index" not in st.session_state:
        st.session_state.selected_bid_index = 0
    if "detail_tab_index" not in st.session_state:
        st.session_state.detail_tab_index = 1  # 默认「偏离分析」

    # 防止投标文件数量变化后索引越界
    max_index = max(0, len(batch_result.items) - 1)
    if st.session_state.selected_bid_index > max_index:
        st.session_state.selected_bid_index = max_index

    # 选择投标文件查看详情
    st.selectbox(
        "选择投标文件查看详情",
        options=range(len(batch_result.items)),
        index=st.session_state.selected_bid_index,
        key="bid_selector",
        format_func=lambda idx: f"{idx + 1}. {batch_result.items[idx].bid_path.name}",
        on_change=lambda: setattr(st.session_state, "selected_bid_index", st.session_state.bid_selector),
    )
    selected_index = st.session_state.selected_bid_index
    selected_item = batch_result.items[selected_index]

    st.divider()
    req_names = "、".join(p.name for p in selected_item.requirement_paths)
    st.header(f"📁 {selected_item.bid_path.name}")
    st.caption(f"合并需求文件：{req_names}")

    # 单个投标文件下载链接
    c1, c2 = st.columns(2)
    with c1:
        excel_bytes = _prepare_excel_download(selected_item.result)
        st.markdown(
            _download_link(
                excel_bytes,
                f"校对清单_{selected_item.bid_path.stem}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "📊 导出该投标文件 Excel 清单",
                color="#198754",
            ),
            unsafe_allow_html=True,
        )
    with c2:
        _render_annotated_bid_download_button(selected_item.result, selected_item.bid_path.stem)

    # 受控 tab 选择器
    tab_labels = ["📑 文档对照", "⚠️ 偏离分析"]

    selected_tab = st.radio(
        "详情视图",
        tab_labels,
        index=st.session_state.detail_tab_index,
        key="tab_selector",
        on_change=lambda: setattr(st.session_state, "detail_tab_index", tab_labels.index(st.session_state.tab_selector)),
        horizontal=True,
        label_visibility="collapsed",
    )

    if selected_tab == "📑 文档对照":
        render_doc_tab(selected_item.result)
    else:
        render_issues_tab(selected_item.result)


def main():
    # 初始化 session state
    if "batch_result" not in st.session_state:
        st.session_state.batch_result = None

    req_files, bid_files, run, reset = render_sidebar()

    # 处理重新上传
    if reset:
        st.session_state.batch_result = None
        st.session_state.selected_bid_index = 0
        st.session_state.detail_tab_index = 1
        st.rerun()

    # 处理开始校对
    if run:
        if not req_files or not bid_files:
            st.warning("请同时上传至少一个需求文件和一个投标文件。")
            return

        total_bids = len(bid_files)
        if total_bids > 10:
            st.info(f"本次将校对 {total_bids} 份投标文件，耗时可能较长，请耐心等待。")

        req_paths = save_uploaded_files(req_files, subdir="requirements")
        bid_paths = save_uploaded_files(bid_files, subdir="bids")

        proofreader = Proofreader()
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        items: List[BatchResultItem] = []
        errors: List[BatchProofreadError] = []

        with st.status("正在执行批量校对...", expanded=True) as status:
            for idx, bid_path in enumerate(bid_paths, start=1):
                status_text.text(f"正在校对投标文件：{bid_path.name}（{idx}/{total_bids}）")
                progress_bar.progress(idx / total_bids)
                # 逐份调用公共 API，保留进度反馈
                single_result = proofreader.proofread_batch(
                    req_paths, [bid_path], cache_dir=Path(".cache")
                )
                items.extend(single_result.items)
                errors.extend(single_result.errors)
                for err in single_result.errors:
                    st.write(f"❌ {err.bid_path.name} 校对失败：{err.error}")
            status.update(label="批量校对完成", state="complete")

        st.session_state.batch_result = ProofreadBatchResult(items=items, errors=errors)
        st.rerun()

    # 展示结果
    if st.session_state.batch_result is not None:
        render_batch_results(st.session_state.batch_result)
        return

    # 默认首页
    st.title("欢迎使用智能文档校对器")
    st.markdown("""
    本工具用于校对 Word 投标文件与需求文件的内容一致性，帮助你发现：
    - 需求响应缺失或偏离
    - 技术参数、服务期限、交付时间不一致
    - 投标文件中的错别字
    - 截图是否覆盖关键需求

    支持在侧边栏上传多个需求文件和多个投标文件。系统会先梳理合并所有需求文件，再基于全部需求逐项校对每个投标文件。
    """)


if __name__ == "__main__":
    main()
