"""Profiling reports candidates. It does not change cells."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from cleaning_workspace.domain.dates import parse_date
from cleaning_workspace.domain.models import (
    Row,
    Sheet,
    WorkbookModel,
    detect_header_row,
    header_names,
    is_blank_value,
    non_empty_count,
    row_is_fully_empty,
)
from cleaning_workspace.domain.textutil import (
    canon,
    fold_text,
    looks_null_token,
    remove_invisible,
    translate_digits,
    truncate,
)

EMAIL_HINTS = ("email", "ایمیل", "e-mail")
PHONE_HINTS = ("phone", "mobile", "تلفن", "موبایل", "همراه")
ID_HINTS = ("شناسه", "کد ملی", "کدملی", "کدپستی", "کد پستی", "شماره حساب", "invoice", "postal", "account")
CUSTOMER_CONTAINS = ("مشتری", "customer", "client")
CUSTOMER_EXACT = {"نام", "name", "full name", "نام و نام خانوادگی"}


def header_tags(label: str) -> list[str]:
    folded = fold_text(label)
    tags: list[str] = []
    if any(hint in folded for hint in CUSTOMER_CONTAINS) or folded in CUSTOMER_EXACT:
        tags.append("customer")
    if any(hint in folded for hint in EMAIL_HINTS):
        tags.append("email")
    if any(hint in folded for hint in PHONE_HINTS):
        tags.append("phone")
    if "تاریخ" in folded or folded == "date" or folded.endswith(" date"):
        tags.append("date")
    if any(hint in folded for hint in ID_HINTS) or folded in {"id", "code", "کد"}:
        tags.append("identifier")
    return tags


def _data_rows(sheet: Sheet) -> list[Row]:
    active = sheet.active_rows()
    header = detect_header_row(sheet)
    if header is None:
        return active
    return [row for row in active if row is not header]


def _duplicate_extra(rows: list[Row], columns: list[int]) -> int:
    groups: Counter[tuple[str, ...]] = Counter()
    for row in rows:
        if row_is_fully_empty(row):
            continue
        parts = []
        for column in columns:
            cell = row.cells.get(column)
            value = None if cell is None or cell.formula else cell.value
            if isinstance(value, str) and value.strip() == "":
                value = None
            parts.append(canon(value))
        if all(part == "" for part in parts):
            continue
        groups[tuple(parts)] += 1
    return sum(count - 1 for count in groups.values() if count > 1)


def profile_workbook(model: WorkbookModel) -> dict:
    sheets = []
    suggestions = []
    whitespace_cells = 0
    empty_rows = 0
    duplicate_extra = 0
    for sheet in model.sheets:
        profile = _profile_sheet(sheet)
        sheets.append(profile)
        whitespace_cells += profile["whitespace_cells"]
        empty_rows += profile["fully_empty_rows"]
        duplicate_extra += profile["exact_duplicate_extra_rows"]
    if whitespace_cells:
        suggestions.append("فاصله‌های اضافی را بردار")
    if empty_rows:
        suggestions.append("ردیف‌های کاملاً خالی را حذف کن")
    if duplicate_extra:
        suggestions.append("ردیف‌های تکراری را مشخص کن")
    suggestion = None
    if suggestions:
        suggestion = "این فایل را تمیز کن، " + "، ".join(suggestions) + ". اطلاعات اصلی را از بین نبر."
    return {
        "source_format": model.source_format,
        "sheet_count": len(model.sheets),
        "whitespace_cells": whitespace_cells,
        "fully_empty_rows": empty_rows,
        "exact_duplicate_extra_rows": duplicate_extra,
        "suggested_request_fa": suggestion,
        "sheets": sheets,
    }


def _profile_sheet(sheet: Sheet) -> dict:
    names = header_names(sheet)
    header = detect_header_row(sheet)
    data_rows = _data_rows(sheet)
    width = sheet.width()
    columns = []
    whitespace_cells = 0
    for column in range(1, width + 1):
        column_profile = _profile_column(sheet, column, names.get(column, f"column_{column}"), data_rows)
        whitespace_cells += column_profile["edge_whitespace"] + column_profile["repeated_whitespace"]
        columns.append(column_profile)
    fully_empty = sum(1 for row in sheet.rows if row_is_fully_empty(row))
    partial = 0
    expected = non_empty_count(header) if header is not None else width
    for row in data_rows:
        filled = non_empty_count(row)
        if 0 < filled < expected:
            partial += 1
    key_columns = list(range(1, width + 1))
    return {
        "name": sheet.name,
        "hidden": sheet.hidden,
        "header_row": header.original_index if header is not None else None,
        "row_count": len(sheet.rows),
        "data_row_count": len(data_rows),
        "fully_empty_rows": fully_empty,
        "partially_empty_rows": partial,
        "width": width,
        "formula_count": sheet.formula_count,
        "merged_ranges": sheet.merged_ranges,
        "whitespace_cells": whitespace_cells,
        "exact_duplicate_extra_rows": _duplicate_extra(data_rows, key_columns),
        "columns": columns,
        "customer_columns": [
            {"index": column["index"], "name": column["name"]}
            for column in columns
            if "customer" in column["tags"]
        ],
    }


def _profile_column(sheet: Sheet, column: int, name: str, data_rows: list[Row]) -> dict:
    values = []
    formulas = 0
    for row in data_rows:
        cell = row.cells.get(column)
        if cell is None:
            values.append(None)
            continue
        if cell.formula:
            formulas += 1
            values.append(None)
            continue
        values.append(cell.value)
    empty = sum(1 for value in values if is_blank_value(value))
    whitespace_only = sum(1 for value in values if isinstance(value, str) and value != "" and value.strip() == "")
    edge = 0
    repeated = 0
    invisible = 0
    persian_or_arabic_digits = 0
    arabic_letters = 0
    null_tokens = 0
    gregorian = 0
    jalali = 0
    ambiguous = 0
    invalid_dates = 0
    present = [value for value in values if not is_blank_value(value)]
    distinct = len({canon(value) for value in present})
    type_counts: Counter[str] = Counter()
    for value in present:
        if isinstance(value, str):
            if value != value.strip():
                edge += 1
            if "  " in value or "\n" in value or "\t" in value or "\u00a0" in value:
                repeated += 1
            if remove_invisible(value) != value:
                invisible += 1
            if translate_digits(value) != value:
                persian_or_arabic_digits += 1
            if any(char in value for char in "يكى"):
                arabic_letters += 1
            if looks_null_token(value):
                null_tokens += 1
        kind = _candidate_type(value)
        type_counts[kind] += 1
        parsed = parse_date(value)
        if parsed.status == "gregorian" or parsed.status == "excel":
            gregorian += 1
        elif parsed.status == "jalali":
            jalali += 1
        elif parsed.status == "ambiguous":
            ambiguous += 1
        elif parsed.status == "invalid":
            invalid_dates += 1
    majority = type_counts.most_common(1)[0][0] if type_counts else "empty"
    consistency = 0.0
    if present:
        consistency = type_counts[majority] / len(present)
    tags = header_tags(name)
    identifier_risk = "identifier" in tags and any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present)
    samples = [truncate(value, 40) for value in present[:3]]
    return {
        "index": column,
        "name": name,
        "tags": tags,
        "non_empty": len(present),
        "empty": empty,
        "whitespace_only": whitespace_only,
        "distinct": distinct,
        "edge_whitespace": edge,
        "repeated_whitespace": repeated,
        "invisible_characters": invisible,
        "persian_or_arabic_digits": persian_or_arabic_digits,
        "arabic_letter_variants": arabic_letters,
        "null_token_candidates": null_tokens,
        "formula_cells": formulas,
        "candidate_type": majority,
        "type_consistency": round(consistency, 3),
        "gregorian_dates": gregorian,
        "jalali_dates": jalali,
        "ambiguous_dates": ambiguous,
        "invalid_dates": invalid_dates,
        "identifier_stored_as_number": identifier_risk,
        "samples": samples,
    }


def _candidate_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed.status in {"gregorian", "jalali", "excel"}:
            return "date_text"
        if "@" in value and "." in value.split("@")[-1]:
            return "email"
        return "text"
    return "unknown"
