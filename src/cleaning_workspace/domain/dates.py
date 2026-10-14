"""Date classification. Ambiguous dates are never guessed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import jdatetime

from cleaning_workspace.domain.textutil import translate_digits

YMD_RE = re.compile(
    r"^(\d{4})[\/\-.](\d{2})[\/\-.](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$"
)
DMY_RE = re.compile(
    r"^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$"
)


@dataclass(frozen=True)
class DateParse:
    status: str
    year: int = 0
    month: int = 0
    day: int = 0
    hour: int = 0
    minute: int = 0
    second: int = 0
    has_time: bool = False
    source_calendar: str = ""


def _time_parts(groups: tuple[str | None, str | None, str | None]) -> tuple[bool, int, int, int] | None:
    hour, minute, second = groups
    if hour is None:
        return False, 0, 0, 0
    hh = int(hour)
    mm = int(minute or 0)
    ss = int(second or 0)
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        return None
    return True, hh, mm, ss


def _valid_gregorian(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _valid_jalali(year: int, month: int, day: int) -> bool:
    try:
        jdatetime.date(year, month, day)
    except ValueError:
        return False
    return True


def parse_date(value: Any) -> DateParse:
    if isinstance(value, datetime):
        has_time = not (value.hour == 0 and value.minute == 0 and value.second == 0)
        return DateParse(
            "excel",
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            has_time,
            "gregorian",
        )
    if isinstance(value, date):
        return DateParse("excel", value.year, value.month, value.day, source_calendar="gregorian")
    if not isinstance(value, str):
        return DateParse("none")
    text = translate_digits(value.strip())
    if not text:
        return DateParse("none")
    ymd = YMD_RE.fullmatch(text)
    if ymd:
        year, month, day = int(ymd.group(1)), int(ymd.group(2)), int(ymd.group(3))
        clock = _time_parts((ymd.group(4), ymd.group(5), ymd.group(6)))
        if clock is None:
            return DateParse("invalid")
        has_time, hour, minute, second = clock
        if 1900 <= year <= 2100 and _valid_gregorian(year, month, day):
            return DateParse("gregorian", year, month, day, hour, minute, second, has_time, "gregorian")
        if 1200 <= year <= 1600 and _valid_jalali(year, month, day):
            return DateParse("jalali", year, month, day, hour, minute, second, has_time, "jalali")
        return DateParse("invalid")
    dmy = DMY_RE.fullmatch(text)
    if not dmy:
        return DateParse("none")
    first, second, year = int(dmy.group(1)), int(dmy.group(2)), int(dmy.group(3))
    clock = _time_parts((dmy.group(4), dmy.group(5), dmy.group(6)))
    if clock is None:
        return DateParse("invalid")
    has_time, hour, minute, sec = clock
    if first > 12 and second > 12:
        return DateParse("invalid")
    if first <= 12 and second <= 12:
        return DateParse("ambiguous")
    if first > 12:
        day, month = first, second
    else:
        month, day = first, second
    if 1900 <= year <= 2100 and _valid_gregorian(year, month, day):
        return DateParse("gregorian", year, month, day, hour, minute, sec, has_time, "gregorian")
    if 1200 <= year <= 1600 and _valid_jalali(year, month, day):
        return DateParse("jalali", year, month, day, hour, minute, sec, has_time, "jalali")
    return DateParse("invalid")


def gregorian_text(parsed: DateParse) -> str:
    base = f"{parsed.year:04d}-{parsed.month:02d}-{parsed.day:02d}"
    if parsed.has_time:
        return (
            f"{base}T{parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}"
        )
    return base


def jalali_text(year: int, month: int, day: int, parsed: DateParse) -> str:
    base = f"{year:04d}/{month:02d}/{day:02d}"
    if parsed.has_time:
        return f"{base} {parsed.hour:02d}:{parsed.minute:02d}:{parsed.second:02d}"
    return base


def to_gregorian_parts(parsed: DateParse) -> tuple[int, int, int]:
    if parsed.source_calendar == "jalali" or parsed.status == "jalali":
        converted = jdatetime.date(parsed.year, parsed.month, parsed.day).togregorian()
        return converted.year, converted.month, converted.day
    return parsed.year, parsed.month, parsed.day


def to_jalali_parts(parsed: DateParse) -> tuple[int, int, int]:
    if parsed.source_calendar == "jalali" or parsed.status == "jalali":
        return parsed.year, parsed.month, parsed.day
    converted = jdatetime.date.fromgregorian(date=date(parsed.year, parsed.month, parsed.day))
    return converted.year, converted.month, converted.day


def render_date(parsed: DateParse, target: str) -> tuple[str, str] | None:
    """Return canonical text and calendar actually written, or None if unchanged path is excel format-only."""
    if parsed.status in {"none", "ambiguous", "invalid"}:
        return None
    if target == "keep":
        target_calendar = "jalali" if parsed.status == "jalali" else "gregorian"
    elif target == "gregorian":
        target_calendar = "gregorian"
    elif target == "jalali":
        target_calendar = "jalali"
    else:
        raise ValueError(target)
    if target_calendar == "gregorian":
        year, month, day = to_gregorian_parts(parsed)
        rendered = DateParse(
            "gregorian",
            year,
            month,
            day,
            parsed.hour,
            parsed.minute,
            parsed.second,
            parsed.has_time,
            "gregorian",
        )
        return gregorian_text(rendered), "gregorian"
    year, month, day = to_jalali_parts(parsed)
    return jalali_text(year, month, day, parsed), "jalali"
