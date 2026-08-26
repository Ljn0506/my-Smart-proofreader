"""统一解析中文日期与期间表达。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass
class NormalizedDate:
    date: date
    precision: str  # DAY / MONTH / YEAR
    is_relative: bool = False
    raw_text: str = ""


@dataclass
class NormalizedPeriod:
    start: Optional[date]
    end: Optional[date]
    description: str
    raw_text: str


_CN_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


_NUMBER_SEPS = re.compile(r"([^〇零一二三四五六七八九十]+)")


def _cn_number_to_int(seq: str) -> int:
    """将纯中文数字（0-99）转为整数。"""
    if "十" not in seq:
        total = 0
        for ch in seq:
            total = total * 10 + _CN_DIGITS[ch]
        return total

    parts = seq.split("十")
    if len(parts) == 2:
        before, after = parts
        if before == "" and after == "":
            return 10
        if before == "":
            return 10 + _cn_number_to_int(after)
        if after == "":
            return _cn_number_to_int(before) * 10
        return _cn_number_to_int(before) * 10 + _cn_number_to_int(after)

    # 多个"十"（如九十九）
    value = 0
    for i, part in enumerate(parts):
        if part == "":
            continue
        part_val = _cn_number_to_int(part)
        # 当前"十"段落在十进制中的位置
        power = 10 ** (len(parts) - i - 1)
        value += part_val * power
    return value


def _cn_to_arabic(text: str) -> str:
    """将字符串中的中文数字替换为阿拉伯数字。"""
    result = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _CN_DIGITS or ch == "十":
            # 收集连续中文数字
            j = i
            while j < n and (text[j] in _CN_DIGITS or text[j] == "十"):
                j += 1
            seq = text[i:j]
            result.append(str(_cn_number_to_int(seq)))
            i = j
        else:
            result.append(ch)
            i += 1
    return "".join(result)


def _parse_year_month_day(text: str) -> Optional[date]:
    # 2026年7月15日 / 2026.07.15 / 2026/07/15 / 2026-07-15
    patterns = [
        r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})[日]?",
        r"(\d{4})(\d{2})(\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
    return None


def normalize_date(text: str, reference: Optional[date] = None) -> Optional[NormalizedDate]:
    if not text:
        return None
    reference = reference or date.today()

    # 先转换中文数字
    converted = _cn_to_arabic(text)
    parsed = _parse_year_month_day(converted)
    if parsed:
        return NormalizedDate(date=parsed, precision="DAY", raw_text=text)

    # 相对表达：90天内 / 2个月内
    m = re.search(r"(\d+)\s*天[之以]?内", text)
    if m:
        d = reference - timedelta(days=int(m.group(1)))
        return NormalizedDate(date=d, precision="DAY", is_relative=True, raw_text=text)

    m = re.search(r"(\d+)\s*个月[之以]?内", text)
    if m:
        months = int(m.group(1))
        year, month = reference.year, reference.month
        for _ in range(months):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        try:
            d = date(year, month, reference.day)
        except ValueError:
            # 处理从31日回退到只有30天的月份等边界情况
            d = date(year, month, _last_day_of_month(year, month))
        return NormalizedDate(date=d, precision="MONTH", is_relative=True, raw_text=text)

    return None


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - timedelta(days=1)).day


def normalize_period(text: str, reference: Optional[date] = None) -> Optional[NormalizedPeriod]:
    if not text:
        return None
    reference = reference or date.today()

    # 日期区间：2023-01-01 至 2023-12-31
    m = re.search(
        r"(\d{4}[年./-]\d{1,2}[月./-]\d{1,2}[日]?)\s*[-~至]\s*(\d{4}[年./-]\d{1,2}[月./-]\d{1,2}[日]?)",
        _cn_to_arabic(text),
    )
    if m:
        start = normalize_date(m.group(1))
        end = normalize_date(m.group(2))
        if start and end:
            return NormalizedPeriod(
                start=start.date, end=end.date, description=text, raw_text=text
            )

    # 相对期间（先统一转换为阿拉伯数字）
    converted_text = _cn_to_arabic(text)

    m = re.search(r"近\s*(\d+)\s*年", converted_text)
    if m:
        years = int(m.group(1))
        try:
            start = reference.replace(year=reference.year - years)
        except ValueError:
            # 闰年2月29日回退到非闰年
            start = reference.replace(year=reference.year - years, day=reference.day - 1)
        return NormalizedPeriod(
            start=start, end=reference, description=f"近{years}年", raw_text=text
        )

    m = re.search(r"近\s*(\d+)\s*个月", converted_text)
    if m:
        months = int(m.group(1))
        year, month = reference.year, reference.month
        for _ in range(months):
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        try:
            start = date(year, month, reference.day)
        except ValueError:
            start = date(year, month, _last_day_of_month(year, month))
        return NormalizedPeriod(
            start=start, end=reference, description=f"近{months}个月", raw_text=text
        )

    return None
