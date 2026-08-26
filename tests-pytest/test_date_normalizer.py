"""Tests for the date_normalizer utility."""
from __future__ import annotations

from datetime import date

from proofreader.utils.date_normalizer import normalize_date, normalize_period


def test_normalize_absolute_date():
    assert normalize_date("2026年7月15日").date == date(2026, 7, 15)
    assert normalize_date("2026.07.15").date == date(2026, 7, 15)
    assert normalize_date("2026/07/15").date == date(2026, 7, 15)


def test_normalize_chinese_numeral_date():
    result = normalize_date("二〇二六年七月十五日")
    assert result.date == date(2026, 7, 15)


def test_normalize_relative_period():
    result = normalize_period("近三年")
    assert result.start is not None
    assert result.end is not None
    assert (result.end - result.start).days >= 365 * 3 - 1


def test_normalize_invalid_date():
    assert normalize_date("not a date") is None


def test_normalize_days_relative():
    result = normalize_date("90天内")
    assert result is not None
    assert result.is_relative
    assert result.date is not None


def test_normalize_months_relative_period():
    result = normalize_period("近6个月")
    assert result.start is not None
    assert result.end is not None
    assert (result.end - result.start).days >= 6 * 30 - 1


def test_normalize_date_range():
    result = normalize_period("2023年1月1日至2023年12月31日")
    assert result.start == date(2023, 1, 1)
    assert result.end == date(2023, 12, 31)


def test_normalize_invalid_calendar_dates():
    """不存在的日历日期应返回 None，而非抛出异常。"""
    assert normalize_date("2026年2月30日") is None
    assert normalize_date("2026年4月31日") is None
    assert normalize_date("2026年13月1日") is None


def test_normalize_period_no_match():
    """无法识别的期间字符串应返回 None。"""
    assert normalize_period("完全不是期间") is None
    assert normalize_period("") is None
