"""Registered transformations. Each operation mutates only the in-memory model."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from cleaning_workspace.domain.dates import parse_date, render_date
from cleaning_workspace.domain.models import (
    Cell,
    Row,
    Sheet,
    WorkbookModel,
    cell_ref,
    derived_cell,
    detect_header_row,
    header_names,
    output_row_numbers,
    row_is_fully_empty,
)
from cleaning_workspace.domain.security import guard_formula_text
from cleaning_workspace.domain.textutil import (
    canon,
    collapse_whitespace,
    digest,
    display_value,
    is_sensitive_header,
    normalize_persian_letters,
    remove_invisible,
    translate_digits,
    trim_text,
)
from cleaning_workspace.errors import AppError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DERIVED_HEADERS = {"duplicate_status", "duplicate_group", "email_syntax"}


class ColumnsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[int] | None = None


class DateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[int] | None = None
    calendar_target: str = "keep"

    def model_post_init(self, _context: Any) -> None:
        if self.calendar_target not in {"keep", "gregorian", "jalali"}:
            raise ValueError("calendar_target is not supported")


class DuplicateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_columns: list[int] = Field(min_length=1)


class EmptyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Change:
    sheet: str
    source_row: int
    column: int
    header: str
    before: Any
    after: Any
    kind: str = "value"
    reason: str = ""


@dataclass
class Outcome:
    affected: int = 0
    unresolved: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    skipped: int = 0
    blocked_empty_rows: list[tuple[str, int]] = field(default_factory=list)


def _names(sheet: Sheet) -> dict[int, str]:
    return header_names(sheet)


def _header_label(sheet: Sheet, column: int) -> str:
    return _names(sheet).get(column, f"column_{column}")


def _iter_rows(sheet: Sheet, *, data_only: bool) -> list[Row]:
    active = sheet.active_rows()
    if not data_only:
        return active
    header = detect_header_row(sheet)
    return [row for row in active if row is not header]


def _selected(sheet: Sheet, columns: list[int] | None) -> list[int]:
    width = sheet.width()
    if columns is None:
        return list(range(1, width + 1))
    missing = [column for column in columns if column < 1 or column > max(width, column)]
    # A selected column may exist only on the header of another sheet. Check per sheet later.
    del missing
    return columns


def _replace(sheet: Sheet, row: Row, column: int, cell: Cell, new_value: Any, changes: list[Change], number_format: str | None = None) -> bool:
    format_changed = number_format is not None and number_format != cell.number_format
    if new_value == cell.value and not format_changed:
        return False
    header = _header_label(sheet, column)
    changes.append(
        Change(
            sheet=sheet.name,
            source_row=row.original_index,
            column=column,
            header=header,
            before=cell.value,
            after=new_value,
        )
    )
    cell.value = new_value
    if number_format is not None:
        cell.number_format = number_format
    return True


def _text_operation(model: WorkbookModel, params: ColumnsParams, transform: Callable[[str], str], *, data_only: bool) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        columns = set(_selected(sheet, params.columns))
        for row in _iter_rows(sheet, data_only=data_only):
            for column, cell in list(row.cells.items()):
                if params.columns is not None and column not in columns:
                    continue
                if cell.formula:
                    outcome.skipped += 1
                    continue
                if not isinstance(cell.value, str):
                    continue
                updated = transform(cell.value)
                if _replace(sheet, row, column, cell, updated, outcome.changes):
                    outcome.affected += 1
    return outcome


def op_trim(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    return _text_operation(model, params, trim_text, data_only=False)


def op_collapse(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    return _text_operation(model, params, collapse_whitespace, data_only=False)


def op_invisible(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    return _text_operation(model, params, remove_invisible, data_only=False)


def op_letters(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    return _text_operation(model, params, normalize_persian_letters, data_only=False)


def op_digits(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    return _text_operation(model, params, translate_digits, data_only=False)


def op_headers(model: WorkbookModel, _params: EmptyParams) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        if header is None:
            continue
        for column, cell in list(header.cells.items()):
            if cell.formula or not isinstance(cell.value, str):
                continue
            updated = collapse_whitespace(cell.value)
            if _replace(sheet, header, column, cell, updated, outcome.changes):
                outcome.affected += 1
    return outcome


def _merge_rows_blocked(sheet: Sheet, empty_indexes: set[int]) -> tuple[set[int], list[str]]:
    blocked: set[int] = set()
    notes: list[str] = []
    for ref in sheet.merged_ranges:
        start, _end = str(ref).split(":")
        # openpyxl range string like A1:B2. Parse row numbers.
        rows = _rows_in_range(str(ref))
        if not rows:
            continue
        overlap = rows & empty_indexes
        if not overlap:
            continue
        if rows <= empty_indexes:
            continue
        blocked |= overlap
        notes.append(str(ref))
    return blocked, notes


def _rows_in_range(ref: str) -> set[int]:
    if ":" not in ref:
        return set()
    left, right = ref.split(":", 1)
    left_row = int(re.sub(r"\D", "", left) or 0)
    right_row = int(re.sub(r"\D", "", right) or 0)
    if left_row < 1 or right_row < 1:
        return set()
    low, high = sorted((left_row, right_row))
    return set(range(low, high + 1))


def op_remove_empty(model: WorkbookModel, _params: EmptyParams) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        empty_rows = [row for row in sheet.active_rows() if row_is_fully_empty(row) and row is not header]
        blocked, merges = _merge_rows_blocked(sheet, {row.original_index for row in empty_rows})
        if merges:
            outcome.warnings.append(
                f"برخی ردیف‌های خالی برگه {sheet.name} به‌خاطر سلول ادغام‌شده حذف نشدند: {', '.join(merges)}"
            )
        for row_index in blocked:
            outcome.blocked_empty_rows.append((sheet.name, row_index))
        for row in empty_rows:
            if row.original_index in blocked:
                continue
            row.removed = True
            row.removal_reason = "fully_empty"
            outcome.affected += 1
            outcome.changes.append(
                Change(
                    sheet=sheet.name,
                    source_row=row.original_index,
                    column=0,
                    header="",
                    before=None,
                    after=None,
                    kind="removed_row",
                    reason="fully_empty",
                )
            )
    return outcome


def _key_for(row: Row, columns: list[int]) -> tuple[str, ...] | None:
    parts: list[str] = []
    for column in columns:
        cell = row.cells.get(column)
        if cell is None or cell.formula:
            parts.append("")
            continue
        value = cell.value
        if isinstance(value, str) and value.strip() == "":
            parts.append("")
        else:
            parts.append(canon(value))
    if all(part == "" for part in parts):
        return None
    return tuple(parts)


def _unique_header(sheet: Sheet, desired: str) -> tuple[int, str]:
    names = set(_names(sheet).values())
    label = desired
    suffix = 2
    while label in names:
        label = f"{desired}_{suffix}"
        suffix += 1
    return sheet.width() + 1, label


def op_mark_duplicates(model: WorkbookModel, params: DuplicateParams) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        if header is None:
            outcome.warnings.append(f"برگه {sheet.name} سرستون ندارد و نشانه‌گذاری تکراری انجام نشد.")
            continue
        if any(column > sheet.width() or column < 1 for column in params.key_columns):
            outcome.warnings.append(f"برگه {sheet.name} ستون کلید را ندارد و نشانه‌گذاری نشد.")
            continue
        data_rows = [row for row in sheet.active_rows() if row is not header and not row_is_fully_empty(row)]
        groups: dict[tuple[str, ...], list[Row]] = defaultdict(list)
        for row in data_rows:
            key = _key_for(row, params.key_columns)
            if key is None:
                continue
            groups[key].append(row)
        grouped = {row.original_index: (index == 0, group_id, row) for group_id, members in enumerate((members for members in groups.values() if len(members) > 1), start=1) for index, row in enumerate(members)}
        if not grouped:
            outcome.warnings.append(f"در برگه {sheet.name} تکراری دقیقی با این کلید پیدا نشد.")
            continue
        status_col, status_name = _unique_header(sheet, "duplicate_status")
        group_col = status_col + 1
        header.cells[status_col] = derived_cell(status_name)
        header.cells[group_col] = derived_cell("duplicate_group")
        for row in data_rows:
            marker = grouped.get(row.original_index)
            if marker is None:
                continue
            is_first, group_id, _row = marker
            status = "اولین" if is_first else "تکراری"
            row.cells[status_col] = derived_cell(status)
            row.cells[group_col] = derived_cell(group_id)
            outcome.affected += 1
            outcome.changes.append(
                Change(
                    sheet=sheet.name,
                    source_row=row.original_index,
                    column=status_col,
                    header=status_name,
                    before=None,
                    after=status,
                    reason="duplicate_mark",
                )
            )
    return outcome


def op_remove_duplicates(model: WorkbookModel, params: DuplicateParams) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        if header is None:
            raise AppError(
                "Duplicate removal needs a header row.",
                "حذف تکراری‌ها بدون ردیف سرستون انجام نمی‌شود.",
                code="missing_header",
                status_code=422,
            )
        if any(column > sheet.width() or column < 1 for column in params.key_columns):
            outcome.warnings.append(f"برگه {sheet.name} ستون کلید را ندارد و حذف تکراری روی آن انجام نشد.")
            continue
        data_rows = [row for row in sheet.active_rows() if row is not header and not row_is_fully_empty(row)]
        groups: dict[tuple[str, ...], list[Row]] = defaultdict(list)
        for row in data_rows:
            key = _key_for(row, params.key_columns)
            if key is None:
                continue
            groups[key].append(row)
        for members in groups.values():
            if len(members) < 2:
                continue
            for row in members[1:]:
                row.removed = True
                row.removal_reason = "exact_duplicate_keep_first"
                outcome.affected += 1
                outcome.changes.append(
                    Change(
                        sheet=sheet.name,
                        source_row=row.original_index,
                        column=0,
                        header="",
                        before=None,
                        after=None,
                        kind="removed_row",
                        reason="exact_duplicate_keep_first",
                    )
                )
    return outcome


def op_dates(model: WorkbookModel, params: DateParams) -> Outcome:
    outcome = Outcome()
    for sheet in model.sheets:
        selected = set(params.columns) if params.columns is not None else None
        header = detect_header_row(sheet)
        for row in sheet.active_rows():
            if row is header:
                continue
            for column, cell in list(row.cells.items()):
                if selected is not None and column not in selected:
                    continue
                if cell.formula:
                    outcome.skipped += 1
                    continue
                parsed = parse_date(cell.value)
                if parsed.status == "none":
                    continue
                if parsed.status in {"ambiguous", "invalid"}:
                    outcome.unresolved.append(
                        {
                            "sheet": sheet.name,
                            "cell": cell_ref(row.original_index, column),
                            "reason_fa": "تاریخ مبهم است و تغییر نکرد."
                            if parsed.status == "ambiguous"
                            else "تاریخ نامعتبر است و تغییر نکرد.",
                            "value": display_value(cell.value, _header_label(sheet, column)),
                        }
                    )
                    continue
                rendered = render_date(parsed, params.calendar_target)
                if rendered is None:
                    continue
                text, calendar = rendered
                if parsed.status == "excel" and calendar == "gregorian":
                    desired_format = "yyyy-mm-dd hh:mm:ss" if parsed.has_time else "yyyy-mm-dd"
                    current = (cell.number_format or "").lower()
                    if isinstance(cell.value, datetime) and current == desired_format:
                        continue
                    if _replace(sheet, row, column, cell, cell.value, outcome.changes, number_format=desired_format):
                        outcome.affected += 1
                    continue
                if isinstance(cell.value, str) and cell.value == text:
                    continue
                if _replace(sheet, row, column, cell, text, outcome.changes, number_format="@") :
                    outcome.affected += 1
    return outcome


def op_emails(model: WorkbookModel, params: ColumnsParams) -> Outcome:
    if not params.columns:
        raise AppError(
            "Email checks need a column.",
            "برای بررسی ایمیل باید ستون مشخص باشد.",
            code="missing_column",
            status_code=422,
        )
    outcome = Outcome()
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        if header is None:
            continue
        column_index, label = _unique_header(sheet, "email_syntax")
        header.cells[column_index] = derived_cell(label)
        data_rows = [row for row in sheet.active_rows() if row is not header]
        for row in data_rows:
            flags = []
            for column in params.columns:
                cell = row.cells.get(column)
                if cell is None or cell.formula or is_blank(cell.value):
                    continue
                text = str(cell.value).strip()
                flags.append("valid" if EMAIL_RE.fullmatch(text) else "invalid")
            status = ""
            if flags:
                status = "invalid" if "invalid" in flags else "valid"
            row.cells[column_index] = derived_cell(status)
            if status == "invalid":
                outcome.affected += 1
                outcome.unresolved.append(
                    {
                        "sheet": sheet.name,
                        "cell": cell_ref(row.original_index, params.columns[0]),
                        "reason_fa": "شکل ایمیل نامعتبر است. وجود آدرس بررسی نشده و مقدار حذف نشده است.",
                        "value": display_value(row.cells.get(params.columns[0]).value if row.cells.get(params.columns[0]) else "", "email"),
                    }
                )
    return outcome


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def op_csv_guard(model: WorkbookModel, _params: EmptyParams) -> Outcome:
    outcome = Outcome()
    if model.source_format != "csv":
        return outcome
    for sheet in model.sheets:
        for row in sheet.active_rows():
            for column, cell in list(row.cells.items()):
                if cell.formula or not isinstance(cell.value, str):
                    continue
                guarded = guard_formula_text(cell.value)
                if guarded != cell.value and _replace(sheet, row, column, cell, guarded, outcome.changes):
                    outcome.affected += 1
                    outcome.changes[-1].reason = "csv_formula_guard"
    if outcome.affected:
        outcome.warnings.append(
            "برخی متن‌های CSV که ممکن بود در صفحه‌گسترده فرمول شوند، یک آپستروف ابتدایی گرفتند. این کار خود متن را تغییر می‌دهد."
        )
    return outcome


def post_trim(model: WorkbookModel, params: ColumnsParams, _outcome: Outcome) -> None:
    for sheet in model.sheets:
        selected = set(params.columns) if params.columns is not None else None
        for row in sheet.active_rows():
            for column, cell in row.cells.items():
                if selected is not None and column not in selected:
                    continue
                if cell.formula or not isinstance(cell.value, str):
                    continue
                if cell.value != cell.value.strip():
                    raise AppError(
                        "Trim left edge whitespace.",
                        "پس از حذف فاصله، هنوز فاصله ابتدا یا انتها باقی مانده است.",
                        code="invariant_failed",
                        status_code=422,
                    )


def post_collapse(model: WorkbookModel, params: ColumnsParams, _outcome: Outcome) -> None:
    for sheet in model.sheets:
        selected = set(params.columns) if params.columns is not None else None
        for row in sheet.active_rows():
            for column, cell in row.cells.items():
                if selected is not None and column not in selected:
                    continue
                if isinstance(cell.value, str) and re.search(r"\s{2,}", cell.value):
                    raise AppError(
                        "Repeated whitespace remained.",
                        "پس از یکسان‌سازی فاصله، فاصله تکراری باقی مانده است.",
                        code="invariant_failed",
                        status_code=422,
                    )


def post_empty(model: WorkbookModel, _params: EmptyParams, outcome: Outcome) -> None:
    blocked = set(outcome.blocked_empty_rows)
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        for row in sheet.active_rows():
            if not row_is_fully_empty(row) or row is header:
                continue
            if (sheet.name, row.original_index) not in blocked:
                raise AppError(
                    "A fully empty row remained.",
                    "یک ردیف کاملاً خالی برخلاف طرح باقی مانده است.",
                    code="invariant_failed",
                    status_code=422,
                )


def post_remove_duplicates(model: WorkbookModel, params: DuplicateParams, _outcome: Outcome) -> None:
    for sheet in model.sheets:
        header = detect_header_row(sheet)
        seen: set[tuple[str, ...]] = set()
        for row in sheet.active_rows():
            if row is header or row_is_fully_empty(row):
                continue
            key = _key_for(row, params.key_columns)
            if key is None:
                continue
            if key in seen:
                raise AppError(
                    "A duplicate key remained.",
                    "پس از حذف، هنوز ردیف تکراری با همان کلید باقی مانده است.",
                    code="invariant_failed",
                    status_code=422,
                )
            seen.add(key)


def post_dates(model: WorkbookModel, params: DateParams, _outcome: Outcome) -> None:
    for sheet in model.sheets:
        selected = set(params.columns) if params.columns is not None else None
        header = detect_header_row(sheet)
        for row in sheet.active_rows():
            if row is header:
                continue
            for column, cell in row.cells.items():
                if selected is not None and column not in selected:
                    continue
                if cell.formula:
                    continue
                parsed = parse_date(cell.value)
                if parsed.status not in {"gregorian", "jalali", "excel"}:
                    continue
                rendered = render_date(parsed, params.calendar_target)
                if rendered is None:
                    continue
                text, calendar = rendered
                if parsed.status == "excel" and calendar == "gregorian":
                    continue
                if isinstance(cell.value, str) and cell.value != text:
                    raise AppError(
                        "A date was left in a non-canonical form.",
                        "یک تاریخ قابل‌تشخیص هنوز شکل یکسان‌شده ندارد.",
                        code="invariant_failed",
                        status_code=422,
                    )


def post_none(*_args: Any) -> None:
    return None


@dataclass(frozen=True)
class OperationSpec:
    type: str
    title_fa: str
    risk: str
    requires_approval: bool
    internal: bool
    changes_fa: str
    preserves_fa: str
    params_model: type[BaseModel]
    run: Callable[[WorkbookModel, Any], Outcome]
    postcheck: Callable[[WorkbookModel, Any, Outcome], None]


CATALOG: dict[str, OperationSpec] = {
    "trim_whitespace": OperationSpec(
        "trim_whitespace",
        "حذف فاصله ابتدا و انتها",
        "safe",
        False,
        False,
        "فاصله و نویسه فاصله ابتدا و انتهای متن حذف می‌شود.",
        "نویسه فاصله مجازی فارسی، صفر، مقدار false و متن میانی تغییر نمی‌کند.",
        ColumnsParams,
        op_trim,
        post_trim,
    ),
    "collapse_whitespace": OperationSpec(
        "collapse_whitespace",
        "یکسان‌سازی فاصله‌های تکراری",
        "safe",
        False,
        False,
        "فاصله‌های پیاپی، شامل خط جدید داخل سلول، به یک فاصله تبدیل می‌شوند.",
        "فاصله مجازی فارسی حفظ می‌شود.",
        ColumnsParams,
        op_collapse,
        post_collapse,
    ),
    "remove_invisible_characters": OperationSpec(
        "remove_invisible_characters",
        "حذف نویسه‌های نامرئی",
        "safe",
        False,
        False,
        "نویسه عرض‌صفر، BOM و نویسه‌های کنترلی غیر از فاصله مجازی حذف می‌شوند.",
        "فاصله مجازی و علامت‌های جهت متن حفظ می‌شوند.",
        ColumnsParams,
        op_invisible,
        post_none,
    ),
    "normalize_persian_letters": OperationSpec(
        "normalize_persian_letters",
        "یکسان‌سازی ی و ک",
        "safe",
        False,
        False,
        "فقط «ي» و «ى» به «ی» و «ك» به «ک» تبدیل می‌شوند.",
        "همزه، ة و سایر حروف تغییر نمی‌کنند.",
        ColumnsParams,
        op_letters,
        post_none,
    ),
    "convert_digits_to_latin": OperationSpec(
        "convert_digits_to_latin",
        "تبدیل ارقام فارسی و عربی به لاتین",
        "safe",
        False,
        False,
        "فقط شکل رقم عوض می‌شود و مقدار همچنان متن می‌ماند.",
        "صفر ابتدای شناسه حذف نمی‌شود و عدد اعشاری تفسیر نمی‌شود.",
        ColumnsParams,
        op_digits,
        post_none,
    ),
    "normalize_headers": OperationSpec(
        "normalize_headers",
        "مرتب‌سازی متن سرستون",
        "safe",
        False,
        False,
        "فاصله اضافی سرستون حذف می‌شود.",
        "نام‌ها ترجمه یا به snake_case تبدیل نمی‌شوند.",
        EmptyParams,
        op_headers,
        post_none,
    ),
    "standardize_dates": OperationSpec(
        "standardize_dates",
        "یکسان‌سازی تاریخ‌های قابل‌تشخیص",
        "safe",
        False,
        False,
        "تاریخ قطعی در همان تقویم به شکل استاندارد نوشته می‌شود، مگر هدف تقویم در طرح چیز دیگری باشد.",
        "تاریخ مبهم یا نامعتبر حدس زده نمی‌شود. ساعت غیرصفر حفظ می‌شود.",
        DateParams,
        op_dates,
        post_dates,
    ),
    "remove_fully_empty_rows": OperationSpec(
        "remove_fully_empty_rows",
        "حذف ردیف‌های کاملاً خالی",
        "safe_explicit",
        False,
        False,
        "ردیفی حذف می‌شود که همه سلول‌هایش خالی یا فقط فاصله باشند.",
        "صفر، false و ردیف نیمه‌پر حفظ می‌شوند. ردیف سرستون حذف نمی‌شود.",
        EmptyParams,
        op_remove_empty,
        post_empty,
    ),
    "mark_exact_duplicates": OperationSpec(
        "mark_exact_duplicates",
        "نشانه‌گذاری تکراری‌های دقیق",
        "safe",
        False,
        False,
        "دو ستون وضعیت و شماره گروه اضافه می‌شود. هیچ ردیفی حذف نمی‌شود.",
        "شباهت نام کافی نیست. کلید خالی گروه‌بندی نمی‌شود.",
        DuplicateParams,
        op_mark_duplicates,
        post_none,
    ),
    "remove_exact_duplicates_keep_first": OperationSpec(
        "remove_exact_duplicates_keep_first",
        "حذف تکراری دقیق با نگه‌داشتن اولین ردیف",
        "approval_required",
        True,
        False,
        "از هر گروه با کلید یکسان، ردیف‌های بعد از اولین مورد حذف می‌شوند.",
        "رکوردهای مشابه اما غیریکسان ادغام یا حذف نمی‌شوند.",
        DuplicateParams,
        op_remove_duplicates,
        post_remove_duplicates,
    ),
    "flag_invalid_emails": OperationSpec(
        "flag_invalid_emails",
        "علامت‌گذاری شکل نامعتبر ایمیل",
        "safe",
        False,
        False,
        "یک ستون email_syntax اضافه می‌شود.",
        "وجود واقعی آدرس بررسی نمی‌شود و ایمیل حذف نمی‌شود.",
        ColumnsParams,
        op_emails,
        post_none,
    ),
    "csv_formula_guard": OperationSpec(
        "csv_formula_guard",
        "محافظ فرمول در خروجی CSV",
        "safe_explicit",
        False,
        True,
        "متن‌هایی که با =، +، @ یا منفی غیرعددی شروع شوند یک آپستروف می‌گیرند.",
        "عدد منفی ساده تغییر نمی‌کند. این محافظ مخصوص CSV است و برای همه نرم‌افزارها تضمین مطلق نیست.",
        EmptyParams,
        op_csv_guard,
        post_none,
    ),
}


PUBLIC_OPERATION_TYPES = {key for key, spec in CATALOG.items() if not spec.internal}


def samples_from_changes(model: WorkbookModel, changes: list[Change], limit: int) -> list[dict[str, Any]]:
    samples = []
    for change in changes[:limit]:
        sheet = next(item for item in model.sheets if item.name == change.sheet)
        output_map = output_row_numbers(sheet)
        output_row = output_map.get(change.source_row)
        output_cell = cell_ref(output_row, change.column) if output_row and change.column else None
        redacted = is_sensitive_header(change.header)
        samples.append(
            {
                "kind": change.kind,
                "sheet": change.sheet,
                "source_cell": cell_ref(change.source_row, change.column) if change.column else f"row {change.source_row}",
                "output_cell": output_cell,
                "before": display_value(change.before, change.header),
                "after": display_value(change.after, change.header),
                "before_sha256": digest(change.before),
                "after_sha256": digest(change.after),
                "redacted": redacted,
                "reason": change.reason,
            }
        )
    return samples
