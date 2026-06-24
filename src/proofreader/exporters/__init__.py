"""报告导出模块。"""
from __future__ import annotations

from proofreader.exporters.excel_exporter import export_to_excel
from proofreader.exporters.word_exporter import export_to_word

__all__ = ["export_to_word", "export_to_excel"]
