"""Job orchestration. Status changes only after the corresponding work runs."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from cleaning_workspace.ai.client import request_answers
from cleaning_workspace.config import Settings
from cleaning_workspace.domain.engine import execute
from cleaning_workspace.domain.export import export_workbook
from cleaning_workspace.domain.planner import build_plan
from cleaning_workspace.domain.profiling import profile_workbook
from cleaning_workspace.domain.readers import read_model
from cleaning_workspace.domain.security import Detection, detect_upload, safe_display_name
from cleaning_workspace.domain.validate import sha256_file, validate_artifact
from cleaning_workspace.errors import AppError
from cleaning_workspace.storage.files import FileStore
from cleaning_workspace.storage.repository import Repository, expiry_from, iso, utcnow

logger = logging.getLogger("cleaning_workspace.jobs")

AiClient = Callable[[Settings, str, list[dict]], dict[str, str]]

PLAN_STATES = {
    "awaiting_request",
    "plan_ready",
    "clarification_required",
    "approval_required",
    "failed",
    "validation_failed",
}
EXECUTE_STATES = {"plan_ready", "approval_required"}
CANCEL_STATES = PLAN_STATES - {"failed", "validation_failed"}
DONE_STATES = {"completed", "completed_with_limitations"}
ARTIFACTS = {"source", "output", "report", "ledger"}


def _loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


class JobService:
    def __init__(self, settings: Settings, ai_client: AiClient | None = None) -> None:
        self.settings = settings
        self.files = FileStore(settings.data_dir)
        self.repo = Repository(settings.data_dir / "workspace.sqlite3")
        self.ai_client = ai_client or request_answers
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock(self, job_id: str) -> threading.Lock:
        with self._guard:
            if job_id not in self._locks:
                self._locks[job_id] = threading.Lock()
            return self._locks[job_id]

    def purge(self) -> None:
        now = utcnow()
        for record in self.repo.due(now):
            self.files.delete_job(record["id"])
            self.repo.transition(
                record["id"],
                "expired",
                "مهلت نگهداری تمام شد و فایل‌ها حذف شدند.",
                inspection_json=None,
                profile_json=None,
                plan_json=None,
                result_json=None,
                error_code="expired",
                error_message_fa="مهلت نگهداری این کار تمام شده است.",
                error_message_en="This job has expired.",
            )
            logger.info("job expired %s", record["id"])

    def create(self, filename: str | None, data: bytes) -> dict[str, Any]:
        self.purge()
        if len(data) > self.settings.max_upload_bytes:
            raise AppError(
                "The upload exceeds the size limit.",
                "حجم فایل از حد مجاز بیشتر است.",
                code="file_too_large",
                status_code=413,
            )
        detection = detect_upload(data, filename, self.settings)
        job_id = str(uuid.uuid4())
        now = utcnow()
        path = self.files.save_source(job_id, data)
        digest = sha256_file(path)
        self.repo.insert_job(
            {
                "id": job_id,
                "status": "uploaded",
                "original_filename": safe_display_name(filename),
                "detected_format": detection.source_format,
                "size_bytes": len(data),
                "source_sha256": digest,
                "created_at": iso(now),
                "updated_at": iso(now),
                "expires_at": iso(expiry_from(now, self.settings.retention_hours)),
            }
        )
        try:
            self.repo.transition(job_id, "validating", "قالب فایل بررسی شد.")
            model = read_model(path, detection, self.settings)
            self.repo.transition(job_id, "profiling", "برگه‌ها خوانده شدند و نمایه ساخته می‌شود.")
            profile = profile_workbook(model)
            inspection = _inspection(model, safe_display_name(filename), len(data), digest)
            self.repo.transition(
                job_id,
                "awaiting_request",
                "فایل آماده دریافت درخواست است.",
                inspection_json=inspection,
                profile_json=profile,
                detected_format=model.source_format,
            )
            logger.info("job ready %s format=%s bytes=%s", job_id, model.source_format, len(data))
        except AppError as exc:
            self.repo.transition(
                job_id,
                "failed",
                exc.message_fa,
                error_code=exc.code,
                error_message_fa=exc.message_fa,
                error_message_en=exc.message_en,
            )
            logger.info("job failed during intake %s code=%s", job_id, exc.code)
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        self.purge()
        self.files.require_id(job_id)
        record = self.repo.get_job(job_id)
        if record is None or record["status"] == "expired":
            raise AppError("The job was not found.", "این کار پیدا نشد یا مهلتش تمام شده است.", code="not_found", status_code=404)
        return _public_job(record, self.repo.events(job_id), self.settings)

    def plan(self, job_id: str, request_text: str, clarifications: dict[str, str] | None = None) -> dict[str, Any]:
        self.purge()
        job_id = self.files.require_id(job_id)
        with self._lock(job_id):
            record = self._require_active(job_id)
            if record["status"] not in PLAN_STATES or not record.get("profile_json"):
                raise AppError(
                    "This job cannot accept a plan.",
                    "در این وضعیت نمی‌توان طرح ساخت.",
                    code="invalid_state",
                    status_code=409,
                )
            profile = json.loads(record["profile_json"])
            answers = _clean_clarifications(clarifications or {})
            ai_answers: dict[str, str] = {}
            ai_note = "تفسیر درخواست با قواعد داخلی انجام شد. ارائه‌دهنده مدل پیکربندی نشده است."
            preliminary = build_plan(request_text, profile, answers, ai_configured=self.settings.ai_configured)
            if preliminary["clarifications"] and self.settings.ai_configured:
                ai_answers = self.ai_client(self.settings, request_text, preliminary["clarifications"])
                if ai_answers:
                    ai_note = "مدل فقط مجاز بود یکی از گزینه‌های همین سؤال را انتخاب کند."
                else:
                    ai_note = "مدل در دسترس نبود یا پاسخش خارج از گزینه‌های مجاز بود. قواعد داخلی استفاده شد."
            plan = build_plan(
                request_text,
                profile,
                answers,
                ai_answers or None,
                ai_configured=self.settings.ai_configured,
                ai_note_fa=ai_note,
            )
            if not plan["blocking"] and plan["operations"]:
                model = read_model(self.files.source_path(job_id), _detection_from_job(record, profile), self.settings)
                preview = execute(model, plan, approved=True)
                by_id = {item["id"]: item for item in preview["operations"]}
                for operation in plan["operations"]:
                    stats = by_id.get(operation["id"])
                    if stats is None:
                        continue
                    operation["preview"] = {
                        "affected_count": stats["affected_count"],
                        "unresolved_count": stats["unresolved_count"],
                        "warnings": stats["warnings"],
                        "samples": stats["samples"][:5],
                    }
            if plan["blocking"]:
                status = "clarification_required"
                detail = "طرح به پاسخ یک ابهام نیاز دارد."
            elif plan["requires_approval"]:
                status = "approval_required"
                detail = "طرح عملیات حذفی دارد و به تأیید صریح نیاز دارد."
            else:
                status = "plan_ready"
                detail = "طرح آماده اجراست."
            self.repo.transition(job_id, status, detail, plan_json=plan, result_json=None, error_code=None, error_message_fa=None, error_message_en=None)
            logger.info("plan %s job=%s ops=%s blocking=%s", plan["id"], job_id, len(plan["operations"]), plan["blocking"])
            return self.get(job_id)

    def execute(self, job_id: str, plan_id: str, approve_destructive: bool) -> dict[str, Any]:
        self.purge()
        job_id = self.files.require_id(job_id)
        with self._lock(job_id):
            record = self._require_active(job_id)
            if record["status"] in DONE_STATES:
                existing = _loads(record.get("result_json")) or {}
                if existing.get("plan_id") == plan_id:
                    return self.get(job_id)
                raise AppError(
                    "This job is already complete.",
                    "این کار قبلاً تمام شده است.",
                    code="invalid_state",
                    status_code=409,
                )
            if record["status"] not in EXECUTE_STATES:
                raise AppError(
                    "The job is not ready to execute.",
                    "کار هنوز آماده اجرا نیست.",
                    code="invalid_state",
                    status_code=409,
                )
            plan = _loads(record.get("plan_json"))
            if not plan or plan.get("id") != plan_id:
                raise AppError(
                    "The plan id does not match the reviewed plan.",
                    "شناسه طرح با طرح بررسی‌شده یکی نیست. طرح را دوباره بسازید.",
                    code="plan_mismatch",
                    status_code=409,
                )
            if plan.get("requires_approval") and not approve_destructive:
                raise AppError(
                    "A destructive operation was not approved.",
                    "عملیات حذفی بدون تأیید صریح اجرا نمی‌شود.",
                    code="approval_required",
                    status_code=409,
                )
            source = self.files.source_path(job_id)
            detection = _detection_from_job(record, _loads(record["profile_json"]))
            self.repo.transition(job_id, "executing", "عملیات‌های تأییدشده در حال اجرا هستند.")
            try:
                model = read_model(source, detection, self.settings)
                execution = execute(model, plan, approved=approve_destructive)
                self.repo.transition(job_id, "verifying", "وارسی نتیجه در حافظه تمام شد.")
                output = self.files.output_path(job_id)
                self.repo.transition(job_id, "exporting", "فایل خروجی در مسیر جدا نوشته می‌شود.")
                export_workbook(source, model, output)
                validation = validate_artifact(
                    source=source,
                    source_sha256=record["source_sha256"],
                    output=output,
                    detection=detection,
                    execution=execution,
                    settings=self.settings,
                )
            except AppError as exc:
                self.files.output_path(job_id).unlink(missing_ok=True)
                status = "validation_failed" if exc.code == "invariant_failed" else "failed"
                self.repo.transition(
                    job_id,
                    status,
                    exc.message_fa,
                    error_code=exc.code,
                    error_message_fa=exc.message_fa,
                    error_message_en=exc.message_en,
                )
                logger.info("execute failed job=%s code=%s", job_id, exc.code)
                return self.get(job_id)
            limitations = _limitations(plan, execution)
            report = _report(record, plan, execution, validation, limitations)
            ledger = {
                "job_id": job_id,
                "plan_id": plan["id"],
                "interpreter": plan.get("interpreter"),
                "source_sha256": record["source_sha256"],
                "source_unchanged": validation["ok"],
                "operations": execution["operations"],
                "net_change_count": len(execution["net_changes"]),
                "net_changes": execution["net_changes"][:2000],
                "net_changes_truncated": len(execution["net_changes"]) > 2000,
                "validation": validation,
            }
            self.files.report_path(job_id).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            self.files.ledger_path(job_id).write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
            if not validation["ok"]:
                output.unlink(missing_ok=True)
                self.repo.transition(
                    job_id,
                    "validation_failed",
                    "خروجی وارسی نهایی را رد کرد و برای دریافت ارائه نشد.",
                    result_json={"plan_id": plan["id"], "validation": validation, "report_ready": True, "ledger_ready": True},
                    error_code="validation_failed",
                    error_message_fa="خروجی نهایی تأیید نشد و فایل نتیجه ارائه نمی‌شود.",
                    error_message_en="Final validation failed. The output file is not available.",
                )
                logger.info("validation failed job=%s", job_id)
                return self.get(job_id)
            status = "completed_with_limitations" if limitations else "completed"
            detail = "خروجی تأیید شد، با محدودیت‌های ثبت‌شده." if limitations else "خروجی تأیید شد."
            self.repo.transition(
                job_id,
                status,
                detail,
                result_json={
                    "plan_id": plan["id"],
                    "validation": validation,
                    "report": report,
                    "output_ready": True,
                    "report_ready": True,
                    "ledger_ready": True,
                },
                error_code=None,
                error_message_fa=None,
                error_message_en=None,
            )
            logger.info("job completed %s status=%s", job_id, status)
            return self.get(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.purge()
        job_id = self.files.require_id(job_id)
        with self._lock(job_id):
            record = self._require_active(job_id)
            if record["status"] not in CANCEL_STATES:
                raise AppError(
                    "This job can no longer be cancelled.",
                    "این کار دیگر قابل لغو نیست.",
                    code="invalid_state",
                    status_code=409,
                )
            self.repo.transition(job_id, "cancelled", "کار قبل از اجرا لغو شد.")
            return self.get(job_id)

    def artifact(self, job_id: str, name: str) -> tuple[Path, str, str]:
        self.purge()
        job_id = self.files.require_id(job_id)
        if name not in ARTIFACTS:
            raise AppError("Unknown artifact.", "این خروجی شناخته نشده است.", code="not_found", status_code=404)
        record = self._require_active(job_id)
        result = _loads(record.get("result_json")) or {}
        if name == "source":
            path = self.files.source_path(job_id)
            filename = safe_display_name(record["original_filename"])
            media = "application/octet-stream"
        elif name == "output":
            if record["status"] not in DONE_STATES or not result.get("output_ready"):
                raise AppError(
                    "The output is not available.",
                    "فایل نتیجه هنوز آماده دریافت نیست.",
                    code="artifact_unavailable",
                    status_code=409,
                )
            path = self.files.output_path(job_id)
            extension = ".csv" if record["detected_format"] == "csv" else ".xlsx"
            inspection = _loads(record.get("inspection_json")) or {}
            if inspection.get("has_vba"):
                extension = ".xlsm"
            stem = Path(safe_display_name(record["original_filename"])).stem or "cleaned"
            filename = f"{stem}-cleaned{extension}"
            media = "text/csv; charset=utf-8" if extension == ".csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif name == "report":
            path = self.files.report_path(job_id)
            filename = "report.json"
            media = "application/json"
        else:
            path = self.files.ledger_path(job_id)
            filename = "ledger.json"
            media = "application/json"
        if not path.exists():
            raise AppError("The artifact is gone.", "این فایل دیگر موجود نیست.", code="artifact_unavailable", status_code=404)
        return path, filename, media

    def _require_active(self, job_id: str) -> dict[str, Any]:
        record = self.repo.get_job(job_id)
        if record is None or record["status"] == "expired":
            raise AppError("The job was not found.", "این کار پیدا نشد یا مهلتش تمام شده است.", code="not_found", status_code=404)
        return record


def _detection_from_job(record: dict[str, Any], profile: dict | None) -> Detection:
    inspection = _loads(record.get("inspection_json")) or {}
    return Detection(
        source_format=record.get("detected_format") or (profile or {}).get("source_format") or "csv",
        has_vba=bool(inspection.get("has_vba")),
        extension_mismatch=False,
        warnings=[],
    )


def _inspection(model: Any, filename: str, size: int, digest: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "size_bytes": size,
        "sha256": digest,
        "source_format": model.source_format,
        "encoding": model.encoding,
        "delimiter": model.delimiter if model.source_format == "csv" else None,
        "had_bom": model.had_bom,
        "date1904": model.date1904,
        "has_vba": model.has_vba,
        "defined_name_count": model.defined_name_count,
        "external_link_count": model.external_link_count,
        "warnings": model.warnings,
        "output_extension": model.output_extension,
        "sheets": [
            {
                "name": sheet.name,
                "hidden": sheet.hidden,
                "actual_max_row": sheet.actual_max_row,
                "actual_max_col": sheet.actual_max_col,
                "declared_max_row": sheet.declared_max_row,
                "declared_max_col": sheet.declared_max_col,
                "formula_count": sheet.formula_count,
                "merged_ranges": sheet.merged_ranges,
                "chart_count": sheet.chart_count,
                "image_count": sheet.image_count,
                "comment_count": sheet.comment_count,
                "hyperlink_count": sheet.hyperlink_count,
                "validation_count": sheet.validation_count,
                "table_count": sheet.table_count,
                "hidden_row_count": sheet.hidden_row_count,
                "hidden_col_count": sheet.hidden_col_count,
            }
            for sheet in model.sheets
        ],
    }


def _clean_clarifications(values: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if len(values) > 10:
        raise AppError("Too many clarifications.", "تعداد پاسخ‌ها بیش از حد است.", code="invalid_request", status_code=422)
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AppError("Clarifications must be text.", "پاسخ ابهام باید متن باشد.", code="invalid_request", status_code=422)
        if len(key) > 40 or len(value) > 200:
            raise AppError("Clarification is too long.", "پاسخ ابهام بیش از حد بلند است.", code="invalid_request", status_code=422)
        cleaned[key] = value
    return cleaned


def _limitations(plan: dict, execution: dict) -> list[str]:
    notes = list(plan.get("unsupported") or [])
    messages = [item["message_fa"] if isinstance(item, dict) else str(item) for item in notes]
    for operation in execution.get("operations") or []:
        messages.extend(operation.get("warnings") or [])
        if operation.get("unresolved_count"):
            messages.append(f"{operation['title_fa']}: {operation['unresolved_count']} مورد حل‌نشده ثبت شد.")
    return messages


def _report(record: dict, plan: dict, execution: dict, validation: dict, limitations: list[str]) -> dict[str, Any]:
    return {
        "title_fa": "گزارش پاک‌سازی داده",
        "job_id": record["id"],
        "plan_id": plan.get("id"),
        "interpreter": plan.get("interpreter"),
        "source_sha256": record["source_sha256"],
        "source_unchanged": all(check["ok"] for check in validation.get("checks") or [] if check["name"] == "source_unchanged"),
        "validation_passed": validation.get("ok"),
        "validation": validation,
        "operations": [
            {
                "id": item["id"],
                "type": item["type"],
                "title_fa": item["title_fa"],
                "status": item["status"],
                "affected_count": item["affected_count"],
                "unresolved_count": item["unresolved_count"],
                "warnings": item["warnings"],
            }
            for item in execution.get("operations") or []
        ],
        "limitations": limitations,
        "unsupported": plan.get("unsupported") or [],
        "preservation_fa": plan.get("preservation_fa") or [],
    }


def _public_job(record: dict[str, Any], events: list[dict[str, Any]], settings: Settings) -> dict[str, Any]:
    result = _loads(record.get("result_json"))
    return {
        "id": record["id"],
        "status": record["status"],
        "original_filename": record["original_filename"],
        "detected_format": record.get("detected_format"),
        "size_bytes": record["size_bytes"],
        "source_sha256": record["source_sha256"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "expires_at": record["expires_at"],
        "inspection": _loads(record.get("inspection_json")),
        "profile": _loads(record.get("profile_json")),
        "plan": _loads(record.get("plan_json")),
        "result": result,
        "error": None
        if not record.get("error_code")
        else {
            "code": record.get("error_code"),
            "message_fa": record.get("error_message_fa"),
            "message_en": record.get("error_message_en"),
        },
        "events": events,
        "ai_configured": settings.ai_configured,
    }


def content_disposition(filename: str) -> str:
    ascii_name = "".join(char if 32 <= ord(char) < 127 and char not in {'"', "\\"} else "_" for char in filename)
    if not ascii_name.strip("._"):
        ascii_name = "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
