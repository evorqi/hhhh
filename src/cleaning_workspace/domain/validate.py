"""Independent checks against the written artifact and the untouched source."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cleaning_workspace.config import Settings
from cleaning_workspace.domain.models import WorkbookModel, detect_header_row, row_is_fully_empty
from cleaning_workspace.domain.operations import _key_for
from cleaning_workspace.domain.readers import read_model
from cleaning_workspace.domain.security import Detection, needs_formula_guard
from cleaning_workspace.domain.textutil import digest
from cleaning_workspace.errors import AppError


def sha256_file(path: Path) -> str:
    digest_obj = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest_obj.update(chunk)
    return digest_obj.hexdigest()


def validate_artifact(
    *,
    source: Path,
    source_sha256: str,
    output: Path,
    detection: Detection,
    execution: dict,
    settings: Settings,
) -> dict:
    checks: list[dict] = []

    def record(name: str, ok: bool, detail_fa: str) -> None:
        checks.append({"name": name, "ok": ok, "detail_fa": detail_fa})

    current_source = sha256_file(source)
    record(
        "source_unchanged",
        current_source == source_sha256,
        "هش فایل اصلی با مقدار زمان بارگذاری یکسان است." if current_source == source_sha256 else "فایل اصلی تغییر کرده است.",
    )
    exists = output.exists() and output.is_file()
    record("output_exists", exists, "فایل خروجی وجود دارد." if exists else "فایل خروجی ساخته نشده است.")
    if not exists:
        return {"ok": False, "checks": checks}
    size = output.stat().st_size
    record("output_nonempty", size > 0, f"اندازه خروجی {size} بایت است." if size > 0 else "فایل خروجی خالی است.")
    signature_ok = _signature_ok(output, detection.source_format)
    record(
        "output_signature",
        signature_ok,
        "امضای قالب خروجی با قالب مورد انتظار می‌خواند." if signature_ok else "امضای قالب خروجی معتبر نیست.",
    )
    try:
        reopened = read_model(output, detection, settings)
    except AppError as exc:
        record("reopen", False, exc.message_fa)
        return {"ok": False, "checks": checks}
    record("reopen", True, "فایل خروجی دوباره باز شد.")
    expected_counts = execution.get("output_row_counts") or {}
    rows_ok = all(len(sheet.active_rows()) == expected_counts.get(sheet.name) for sheet in reopened.sheets)
    record(
        "row_counts",
        rows_ok,
        "تعداد ردیف خروجی با نتیجه اجرا یکی است." if rows_ok else "تعداد ردیف خروجی با نتیجه اجرا فرق دارد.",
    )
    if detection.source_format == "xlsx":
        expected_formulas = execution.get("formula_counts") or {}
        formulas_ok = all(sheet.formula_count == expected_formulas.get(sheet.name, sheet.formula_count) for sheet in reopened.sheets)
        record(
            "formulas_preserved",
            formulas_ok,
            "تعداد فرمول‌ها حفظ شده است." if formulas_ok else "تعداد فرمول‌های خروجی با ورودی فرق دارد.",
        )
    hash_ok, hash_detail = _check_hashes(reopened, execution.get("net_changes") or [])
    record("ledger_values", hash_ok, hash_detail)
    for invariant in execution.get("invariants") or []:
        name, ok, detail = _check_invariant(reopened, invariant, detection.source_format)
        record(name, ok, detail)
    return {"ok": all(item["ok"] for item in checks), "checks": checks, "output_bytes": size}


def _signature_ok(path: Path, source_format: str) -> bool:
    data = path.read_bytes()[:8]
    if source_format == "xlsx":
        return data[:2] == b"PK"
    return not data.startswith(b"PK") and not data.startswith(bytes.fromhex("D0CF11E0"))


def _check_hashes(model: WorkbookModel, changes: list[dict]) -> tuple[bool, str]:
    value_changes = [change for change in changes if change.get("kind") == "value" and change.get("output_cell")]
    if len(value_changes) > 2000:
        head = value_changes[:250]
        tail = value_changes[-250:]
        selected = head + tail
        truncated = True
    else:
        selected = value_changes
        truncated = False
    lookup = {}
    for sheet in model.sheets:
        for offset, row in enumerate(sheet.active_rows(), start=1):
            for column, cell in row.cells.items():
                from cleaning_workspace.domain.models import cell_ref

                lookup[(sheet.name, cell_ref(offset, column))] = cell.value
    mismatches = 0
    for change in selected:
        actual = lookup.get((change["sheet"], change["output_cell"]))
        if digest(actual) != change["after_sha256"]:
            mismatches += 1
    if mismatches:
        return False, f"{mismatches} مقدار خروجی با دفتر تغییرات نمی‌خواند."
    suffix = " بررسی مقدارها به‌خاطر حجم، روی ابتدا و انتهای فهرست بوده است." if truncated else ""
    return True, f"{len(selected)} مقدار خروجی با دفتر تغییرات خوانده شد.{suffix}"


def _check_invariant(model: WorkbookModel, invariant: dict, source_format: str) -> tuple[str, bool, str]:
    kind = invariant.get("type")
    if kind == "no_edge_whitespace":
        columns = invariant.get("columns")
        selected = set(columns) if columns else None
        for sheet in model.sheets:
            for row in sheet.active_rows():
                for column, cell in row.cells.items():
                    if selected is not None and column not in selected:
                        continue
                    if isinstance(cell.value, str) and cell.value != cell.value.strip():
                        return kind, False, "در خروجی هنوز فاصله ابتدا یا انتها وجود دارد."
        return kind, True, "متن‌های هدف در خروجی فاصله ابتدا یا انتها ندارند."
    if kind == "no_unexpected_empty_rows":
        blocked = {(item[0], item[1]) if not isinstance(item, dict) else (item.get("sheet"), item.get("row")) for item in invariant.get("blocked") or []}
        # Blocked rows keep their original indexes, which no longer match output indexes.
        # The in-memory postcondition already ran. Here we only fail if an empty non-header row exists
        # while nothing was blocked.
        for sheet in model.sheets:
            header = detect_header_row(sheet)
            for row in sheet.active_rows():
                if row is header or not row_is_fully_empty(row):
                    continue
                if not blocked:
                    return kind, False, "در خروجی ردیف کاملاً خالی باقی مانده است."
        return kind, True, "ردیف کاملاً خالیِ غیرمجاز در خروجی نیست."
    if kind == "no_duplicate_keys":
        keys = [int(column) for column in invariant.get("key_columns") or []]
        for sheet in model.sheets:
            header = detect_header_row(sheet)
            seen = set()
            for row in sheet.active_rows():
                if row is header or row_is_fully_empty(row):
                    continue
                if any(column > sheet.width() for column in keys):
                    continue
                key = _key_for(row, keys)
                if key is None:
                    continue
                if key in seen:
                    return kind, False, "در خروجی هنوز ردیف تکراری با همان کلید وجود دارد."
                seen.add(key)
        return kind, True, "کلید تکراریِ دقیق در خروجی باقی نمانده است."
    if kind == "csv_guard" and source_format == "csv":
        for sheet in model.sheets:
            for row in sheet.active_rows():
                for cell in row.cells.values():
                    if isinstance(cell.value, str) and needs_formula_guard(cell.value):
                        return kind, False, "یک سلول CSV هنوز می‌تواند به‌عنوان فرمول خوانده شود."
        return kind, True, "سلول‌های خطرناک CSV محافظت شده‌اند."
    return str(kind), True, "این وارسی برای این خروجی موردی نداشت."
