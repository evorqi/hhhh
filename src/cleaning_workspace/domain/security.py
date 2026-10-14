"""Upload checks and CSV formula-injection guard."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from cleaning_workspace.config import Settings
from cleaning_workspace.errors import AppError

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
PLAIN_NUMBER_RE = re.compile(r"-\d+(\.\d+)?")
FORMULA_TRIGGERS = set("=+@\t\r")


@dataclass
class Detection:
    source_format: str
    has_vba: bool = False
    extension_mismatch: bool = False
    warnings: list[dict[str, str]] = field(default_factory=list)


def warning(code: str, message_en: str, message_fa: str) -> dict[str, str]:
    return {"code": code, "message_en": message_en, "message_fa": message_fa}


def safe_display_name(filename: str | None) -> str:
    name = (filename or "upload").replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = re.sub(r"[\r\n\t]", " ", name).strip()
    return (name or "upload")[:180]


def needs_formula_guard(value: str) -> bool:
    """CSV cells opened by spreadsheet apps can be interpreted as formulas.

    A plain negative number is left unchanged. Other trigger prefixes get a
    leading apostrophe at export time. That changes the stored text. It is not
    a universal guarantee for every consumer.
    """
    if not value:
        return False
    first = value[0]
    if first == "-" and PLAIN_NUMBER_RE.fullmatch(value):
        return False
    if first == "-":
        return True
    return first in FORMULA_TRIGGERS


def guard_formula_text(value: str) -> str:
    if needs_formula_guard(value):
        return "'" + value
    return value


def detect_upload(data: bytes, filename: str | None, settings: Settings) -> Detection:
    if not data:
        raise AppError(
            "The upload is empty.",
            "فایل خالی است.",
            code="empty_file",
            status_code=422,
        )
    if len(data) > settings.max_upload_bytes:
        raise AppError(
            "The upload exceeds the size limit.",
            "حجم فایل از حد مجاز بیشتر است.",
            code="file_too_large",
            status_code=413,
        )
    display = safe_display_name(filename)
    lower = display.lower()
    if lower.endswith(".xlsb"):
        raise AppError(
            "XLSB is not supported.",
            "فایل‌های XLSB پشتیبانی نمی‌شوند. خروجی XLSX یا CSV بفرستید.",
            code="unsupported_format",
            status_code=415,
        )
    if data[:8] == OLE_MAGIC or data[:4] == OLE_MAGIC[:4]:
        raise AppError(
            "Legacy XLS is not supported.",
            "فایل‌های قدیمی XLS پشتیبانی نمی‌شوند و به XLSX تغییر نام داده نمی‌شوند. فایل را با قالب XLSX یا CSV ذخیره کنید.",
            code="unsupported_xls",
            status_code=415,
        )
    if data[:2] == b"PK":
        return _detect_ooxml(data, lower, settings)
    if lower.endswith((".xlsx", ".xlsm")):
        raise AppError(
            "The file extension says spreadsheet but the bytes are not an XLSX package.",
            "پسوند فایل صفحه‌گسترده است اما محتوای آن بسته XLSX معتبر نیست.",
            code="corrupt_xlsx",
            status_code=422,
        )
    if lower.endswith(".xls"):
        raise AppError(
            "Legacy XLS is not supported.",
            "فایل‌های قدیمی XLS پشتیبانی نمی‌شوند. فایل را با قالب XLSX یا CSV ذخیره کنید.",
            code="unsupported_xls",
            status_code=415,
        )
    warnings: list[dict[str, str]] = []
    if lower.endswith((".csv", ".txt", ".tsv")) is False and "." in lower:
        warnings.append(
            warning(
                "extension_mismatch",
                "The extension was not CSV; the bytes were accepted as text because they are not a spreadsheet package.",
                "پسوند فایل CSV نبود؛ چون بسته صفحه‌گسترده نیست به‌عنوان متن بررسی می‌شود.",
            )
        )
    return Detection(source_format="csv", warnings=warnings)


def _detect_ooxml(data: bytes, lower_name: str, settings: Settings) -> Detection:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AppError(
            "The spreadsheet package is corrupt.",
            "بسته صفحه‌گسترده خراب است و باز نشد.",
            code="corrupt_xlsx",
            status_code=422,
        ) from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > settings.max_zip_members:
            raise AppError(
                "The spreadsheet archive has too many members.",
                "بایگانی صفحه‌گسترده بیش از حد عضو دارد.",
                code="archive_limits",
                status_code=422,
            )
        declared = 0
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise AppError(
                    "The spreadsheet archive contains an unsafe path.",
                    "بایگانی صفحه‌گسترده مسیر ناامن دارد.",
                    code="archive_unsafe_path",
                    status_code=422,
                )
            if info.file_size < 0:
                raise AppError(
                    "The spreadsheet archive declared an invalid size.",
                    "اندازه اعلام‌شده در بایگانی نامعتبر است.",
                    code="archive_limits",
                    status_code=422,
                )
            declared += info.file_size
            if info.file_size > settings.max_uncompressed_bytes or declared > settings.max_uncompressed_bytes:
                raise AppError(
                    "The spreadsheet expands beyond the safety limit.",
                    "حجم بازشده صفحه‌گسترده از حد مجاز بیشتر است.",
                    code="archive_limits",
                    status_code=422,
                )
        names = {info.filename.replace("\\", "/") for info in infos}
        if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
            raise AppError(
                "The ZIP package is not an XLSX workbook.",
                "این فایل ZIP یک کارپوشه XLSX نیست.",
                code="unsupported_format",
                status_code=415,
            )
        has_vba = "xl/vbaProject.bin" in names
        warnings: list[dict[str, str]] = []
        mismatch = False
        if lower_name.endswith(".csv") or lower_name.endswith(".txt"):
            mismatch = True
            warnings.append(
                warning(
                    "extension_mismatch",
                    "The file name looks like CSV but the bytes are an XLSX workbook. The workbook will be processed as XLSX.",
                    "نام فایل شبیه CSV است اما محتوا XLSX است. فایل به‌عنوان XLSX پردازش می‌شود.",
                )
            )
        if has_vba:
            warnings.append(
                warning(
                    "vba_not_executed",
                    "The workbook contains a VBA project. Macros are not executed. They are copied through when the library can preserve them.",
                    "این کارپوشه ماکرو دارد. ماکرو اجرا نمی‌شود و فقط در صورت امکان بدون تغییر کپی می‌شود.",
                )
            )
        return Detection(
            source_format="xlsx",
            has_vba=has_vba,
            extension_mismatch=mismatch,
            warnings=warnings,
        )
