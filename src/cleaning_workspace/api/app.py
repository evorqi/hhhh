"""HTTP API and the local workspace UI."""

from __future__ import annotations

import hmac
import logging

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from cleaning_workspace import __version__
from cleaning_workspace.config import Settings
from cleaning_workspace.errors import AppError
from cleaning_workspace.services.jobs import JobService, content_disposition

logger = logging.getLogger("cleaning_workspace.api")


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1, max_length=4000)
    clarifications: dict[str, str] = Field(default_factory=dict)


class ExecuteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(min_length=1, max_length=80)
    approve_destructive: bool = False


def create_app(settings: Settings, service: JobService | None = None) -> FastAPI:
    app = FastAPI(title="Smart Excel and Data Cleaning Workspace", version=__version__)
    job_service = service or JobService(settings)

    @app.middleware("http")
    async def access_token(request: Request, call_next):
        if settings.access_token and request.url.path.startswith("/api/"):
            if request.url.path not in {"/api/health", "/api/meta"}:
                supplied = request.headers.get("x-workspace-token", "")
                if not hmac.compare_digest(supplied.encode("utf-8"), settings.access_token.encode("utf-8")):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": {
                                "code": "unauthorized",
                                "message_fa": "دسترسی مجاز نیست.",
                                "message_en": "Unauthorized.",
                            }
                        },
                    )
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message_fa": exc.message_fa, "message_en": exc.message_en}},
        )

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception):
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message_fa": "خطای داخلی رخ داد. جزئیات فنی به کاربر نشان داده نمی‌شود.",
                    "message_en": "Internal error.",
                }
            },
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/meta")
    def meta():
        return {
            "product": "cleaning-workspace",
            "version": __version__,
            "auth_required": settings.access_token is not None,
            "ai_configured": settings.ai_configured,
            "ai_note_fa": (
                "برای رفع ابهام، فقط متن درخواست و شناسه گزینه‌ها به نشانی پیکربندی‌شده فرستاده می‌شود، نه کل فایل."
                if settings.ai_configured
                else "پردازش روی همین رایانه و بدون مدل بیرونی انجام می‌شود."
            ),
            "formats": ["csv", "xlsx", "xlsm"],
            "unsupported_formats": ["xls", "xlsb"],
            "max_upload_bytes": settings.max_upload_bytes,
            "max_rows": settings.max_rows,
            "max_cols": settings.max_cols,
            "max_sheets": settings.max_sheets,
            "retention_hours": settings.retention_hours,
            "limitations_fa": [
                "XLS و XLSB پذیرفته نمی‌شوند.",
                "فرمول‌ها محاسبه نمی‌شوند و با مقدار ذخیره‌شده جایگزین نمی‌شوند.",
                "ماکرو اجرا نمی‌شود.",
                "ردیف نیمه‌خالی حذف نمی‌شود.",
                "تاریخ مبهم حدس زده نمی‌شود و تقویم‌ها بدون درخواست صریح به هم تبدیل نمی‌شوند.",
                "تکراری‌های مشابه ادغام نمی‌شوند. پیش‌فرض، نشانه‌گذاری تطابق دقیق است.",
                "شماره تلفن بدون قاعده کشور استاندارد نمی‌شود.",
            ],
        }

    @app.post("/api/jobs", status_code=201)
    async def create_job(file: UploadFile = File(...)):
        chunks: list[bytes] = []
        total = 0
        while True:
            piece = await file.read(1024 * 1024)
            if not piece:
                break
            total += len(piece)
            if total > settings.max_upload_bytes:
                raise AppError(
                    "The upload exceeds the size limit.",
                    "حجم فایل از حد مجاز بیشتر است.",
                    code="file_too_large",
                    status_code=413,
                )
            chunks.append(piece)
        return job_service.create(file.filename, b"".join(chunks))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return job_service.get(job_id)

    @app.post("/api/jobs/{job_id}/plan")
    def create_plan(job_id: str, body: PlanBody):
        return job_service.plan(job_id, body.request, body.clarifications)

    @app.post("/api/jobs/{job_id}/execute")
    def execute_job(job_id: str, body: ExecuteBody):
        return job_service.execute(job_id, body.plan_id, body.approve_destructive)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return job_service.cancel(job_id)

    @app.get("/api/jobs/{job_id}/artifacts/{name}")
    def download(job_id: str, name: str):
        path, filename, media = job_service.artifact(job_id, name)
        return FileResponse(path, media_type=media, filename=filename, content_disposition_type="attachment", headers={"Content-Disposition": content_disposition(filename)})

    web = settings.web_dir
    if web.exists():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
