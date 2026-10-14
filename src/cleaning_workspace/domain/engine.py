"""Execute a validated plan. Unknown operation types never run."""

from __future__ import annotations

from cleaning_workspace.domain.models import WorkbookModel, cell_ref, header_names, output_row_numbers
from cleaning_workspace.domain.operations import CATALOG, samples_from_changes
from cleaning_workspace.domain.textutil import canon, digest, display_value, is_sensitive_header
from cleaning_workspace.errors import AppError


def execute(model: WorkbookModel, plan: dict, *, approved: bool) -> dict:
    if plan.get("blocking"):
        raise AppError(
            "The plan still needs clarification.",
            "طرح هنوز ابهام باز دارد و اجرا نشده است.",
            code="clarification_required",
            status_code=409,
        )
    if not plan.get("operations"):
        raise AppError(
            "The plan has no operations.",
            "طرح هیچ عملیات مجازی ندارد.",
            code="empty_plan",
            status_code=409,
        )
    results = []
    invariants = []
    for operation in plan["operations"]:
        op_type = operation.get("type")
        spec = CATALOG.get(op_type)
        if spec is None:
            raise AppError(
                "The plan contains an unregistered operation.",
                "طرح عملیات ثبت‌نشده دارد و اجرا متوقف شد.",
                code="unregistered_operation",
                status_code=422,
            )
        if spec.requires_approval and not approved:
            raise AppError(
                "A destructive operation was not approved.",
                "عملیات حذفی بدون تأیید صریح اجرا نمی‌شود.",
                code="approval_required",
                status_code=409,
            )
        try:
            params = spec.params_model.model_validate(operation.get("parameters") or {})
        except Exception as exc:
            raise AppError(
                "Operation parameters are invalid.",
                "پارامترهای عملیات معتبر نیست و اجرا متوقف شد.",
                code="invalid_parameters",
                status_code=422,
            ) from exc
        outcome = spec.run(model, params)
        spec.postcheck(model, params, outcome)
        stored = samples_from_changes(model, outcome.changes, limit=200)
        results.append(
            {
                "id": operation.get("id"),
                "type": spec.type,
                "title_fa": spec.title_fa,
                "status": "applied",
                "affected_count": outcome.affected,
                "skipped_count": outcome.skipped,
                "unresolved_count": len(outcome.unresolved),
                "unresolved": outcome.unresolved[:100],
                "warnings": outcome.warnings,
                "samples": stored[:20],
                "samples_truncated": len(outcome.changes) > len(stored) or len(stored) > 20,
                "blocked_empty_rows": outcome.blocked_empty_rows,
            }
        )
        if spec.type == "trim_whitespace":
            invariants.append({"type": "no_edge_whitespace", "columns": operation.get("parameters", {}).get("columns")})
        if spec.type == "remove_fully_empty_rows":
            invariants.append({"type": "no_unexpected_empty_rows", "blocked": outcome.blocked_empty_rows})
        if spec.type == "remove_exact_duplicates_keep_first":
            invariants.append({"type": "no_duplicate_keys", "key_columns": operation.get("parameters", {}).get("key_columns")})
        if spec.type == "csv_formula_guard":
            invariants.append({"type": "csv_guard"})
    return {
        "operations": results,
        "net_changes": _net_changes(model),
        "invariants": invariants,
        "output_row_counts": {sheet.name: len(sheet.active_rows()) for sheet in model.sheets},
        "formula_counts": {sheet.name: sheet.formula_count for sheet in model.sheets},
    }


def _net_changes(model: WorkbookModel) -> list[dict]:
    changes = []
    for sheet in model.sheets:
        mapping = output_row_numbers(sheet)
        labels = header_names(sheet)
        for row in sheet.rows:
            if row.removed:
                changes.append(
                    {
                        "kind": "removed_row",
                        "sheet": sheet.name,
                        "source_row": row.original_index,
                        "reason": row.removal_reason,
                    }
                )
                continue
            output_row = mapping.get(row.original_index)
            for column, cell in row.cells.items():
                if cell.formula:
                    continue
                value_changed = canon(cell.value) != canon(cell.original_value)
                format_changed = (cell.number_format or "") != (cell.original_number_format or "")
                if not value_changed and not format_changed:
                    continue
                header = labels.get(column, "")
                changes.append(
                    {
                        "kind": "value",
                        "sheet": sheet.name,
                        "source_cell": cell_ref(row.original_index, column),
                        "output_cell": cell_ref(output_row, column) if output_row else None,
                        "before": display_value(cell.original_value, header),
                        "after": display_value(cell.value, header),
                        "before_sha256": digest(cell.original_value),
                        "after_sha256": digest(cell.value),
                        "redacted": is_sensitive_header(header),
                        "format_changed": format_changed,
                    }
                )
    return changes
