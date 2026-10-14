"""In-memory workbook model. The source file is never modified through this model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cleaning_workspace.domain.textutil import canon


def column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be positive")
    letters: list[str] = []
    number = index
    while number:
        number, remainder = divmod(number - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def cell_ref(row: int, column: int) -> str:
    return f"{column_letter(column)}{row}"


@dataclass
class Cell:
    value: Any = None
    formula: str | None = None
    number_format: str | None = None
    original_value: Any = None
    original_number_format: str | None = None


def make_cell(
    value: Any = None,
    *,
    formula: str | None = None,
    number_format: str | None = None,
) -> Cell:
    stored = None if formula else value
    return Cell(
        value=stored,
        formula=formula,
        number_format=number_format,
        original_value=stored,
        original_number_format=number_format,
    )


def derived_cell(value: Any, number_format: str | None = "@") -> Cell:
    """A cell created by an operation. Its original value is empty."""
    return Cell(value=value, number_format=number_format, original_value=None, original_number_format=None)


@dataclass
class Row:
    original_index: int
    cells: dict[int, Cell] = field(default_factory=dict)
    removed: bool = False
    removal_reason: str | None = None


@dataclass
class Sheet:
    name: str
    rows: list[Row] = field(default_factory=list)
    hidden: bool = False
    merged_ranges: list[str] = field(default_factory=list)
    chart_count: int = 0
    image_count: int = 0
    comment_count: int = 0
    hyperlink_count: int = 0
    validation_count: int = 0
    table_count: int = 0
    hidden_row_count: int = 0
    hidden_col_count: int = 0
    declared_max_row: int = 0
    declared_max_col: int = 0
    actual_max_row: int = 0
    actual_max_col: int = 0
    formula_count: int = 0

    def active_rows(self) -> list[Row]:
        return [row for row in self.rows if not row.removed]

    def width(self) -> int:
        width = 0
        for row in self.rows:
            if row.cells:
                width = max(width, max(row.cells))
        return width


@dataclass
class WorkbookModel:
    source_format: str
    sheets: list[Sheet]
    delimiter: str = ","
    encoding: str | None = None
    had_bom: bool = False
    date1904: bool = False
    has_vba: bool = False
    defined_name_count: int = 0
    external_link_count: int = 0
    extension_mismatch: bool = False
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def output_extension(self) -> str:
        if self.source_format == "csv":
            return ".csv"
        if self.has_vba:
            return ".xlsm"
        return ".xlsx"


def is_blank_value(value: Any) -> bool:
    """Whitespace-only text is blank. Zero, False, and null-like tokens are not."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def row_is_fully_empty(row: Row) -> bool:
    if any(cell.formula for cell in row.cells.values()):
        return False
    return all(is_blank_value(cell.value) for cell in row.cells.values())


def non_empty_count(row: Row) -> int:
    count = 0
    for cell in row.cells.values():
        if cell.formula or not is_blank_value(cell.value):
            count += 1
    return count


def detect_header_row(sheet: Sheet) -> Row | None:
    active = sheet.active_rows()
    if not active:
        return None
    window = active[:5]
    counts = [non_empty_count(row) for row in window]
    if len(counts) >= 2 and counts[0] <= 1 and counts[1] >= 2:
        return window[1]
    best_index = max(range(len(counts)), key=lambda index: counts[index])
    return window[best_index]


def header_names(sheet: Sheet) -> dict[int, str]:
    header = detect_header_row(sheet)
    if header is None:
        return {}
    names: dict[int, str] = {}
    used: set[str] = set()
    width = sheet.width()
    for column in range(1, width + 1):
        cell = header.cells.get(column)
        raw = ""
        if cell and cell.formula:
            raw = cell.formula
        elif cell is not None:
            raw = canon(cell.value).strip()
        label = raw or f"column_{column_letter(column)}"
        base = label
        suffix = 2
        while label in used:
            label = f"{base}__{suffix}"
            suffix += 1
        used.add(label)
        names[column] = label
    return names


def output_row_numbers(sheet: Sheet) -> dict[int, int]:
    mapping: dict[int, int] = {}
    number = 1
    for row in sheet.rows:
        if row.removed:
            continue
        mapping[row.original_index] = number
        number += 1
    return mapping


def active_header_position(sheet: Sheet) -> int | None:
    header = detect_header_row(sheet)
    if header is None:
        return None
    for index, row in enumerate(sheet.active_rows()):
        if row is header:
            return index
    return None
