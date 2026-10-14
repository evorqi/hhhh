"""Rule-based interpretation of a cleaning request.

The planner can only emit registered operations. It does not execute them.
"""

from __future__ import annotations

import re
import uuid

from cleaning_workspace.domain.operations import CATALOG
from cleaning_workspace.domain.textutil import fold_text

PRESERVE_RE = re.compile(r"از بین نبر|حفظ|اطلاعات اصلی|دست نزن|overwrite نکن|do not (delete|destroy)|preserve")
CLEAN_RE = re.compile(r"تمیز|پاکسازی|پاک سازی|cleanup|clean")
SPACE_RE = re.compile(r"فاصله|space|whitespace|trim")
EMPTY_RE = re.compile(r"خالی|empty")
ROW_RE = re.compile(r"ردیف|سطر|row")
DELETE_RE = re.compile(r"حذف|پاک کن|remove|drop")
DUP_RE = re.compile(r"تکرار|duplicate")
MARK_RE = re.compile(r"مشخص|علامت|نشان|mark|flag")
CUSTOMER_RE = re.compile(r"مشتری|customer|client")
DATE_RE = re.compile(r"تاریخ|date")
DATE_VERB_RE = re.compile(r"یکسان|استاندارد|نرمال|normalize|unify|تبدیل|convert")
GREGORIAN_RE = re.compile(r"میلادی|gregorian")
JALALI_RE = re.compile(r"شمسی|جلالی|jalali")
DIGIT_RE = re.compile(r"ارقام فارسی|ارقام عربی|اعداد فارسی|persian digits|arabic digits")
LETTER_RE = re.compile(r"حروف عربی|حروف فارسی|یکسان سازی حروف|normalize letters")
HEADER_RE = re.compile(r"سرستون|header")
EMAIL_RE = re.compile(r"ایمیل|email")
EMAIL_VERB_RE = re.compile(r"بررسی|معتبر|invalid|validate|چک")
PARTIAL_RE = re.compile(r"ناقص|نیمه خالی|partial")
MERGE_RE = re.compile(r"ادغام|merge")
PHONE_RE = re.compile(r"تلفن|موبایل|phone")
PHONE_VERB_RE = re.compile(r"یکسان|استاندارد|نرمال|normalize|پیش شماره")
IMPUTE_RE = re.compile(r"جایگزین|میانگین|impute|پر کن مقادیر خالی")
MACRO_RE = re.compile(r"ماکرو|vba|macro")
SHELL_RE = re.compile(r"\b(shell|cmd|powershell|python|sql)\b|اجرای کد|حذف فایل")


def _column_labels(profile: dict, indexes: list[int]) -> list[str]:
    labels = []
    sheets = profile.get("sheets") or []
    names = {}
    if sheets:
        for column in sheets[0].get("columns") or []:
            names[column["index"]] = column["name"]
    for index in indexes:
        labels.append(names.get(index, str(index)))
    return labels


def _all_column_indexes(profile: dict) -> list[int]:
    sheets = profile.get("sheets") or []
    if not sheets:
        return []
    return [column["index"] for column in sheets[0].get("columns") or []]


def _customer_columns(profile: dict) -> list[dict]:
    sheets = profile.get("sheets") or []
    if not sheets:
        return []
    return list(sheets[0].get("customer_columns") or [])


def _operation(op_type: str, parameters: dict, labels: list[str] | None = None) -> dict:
    spec = CATALOG[op_type]
    return {
        "id": "",
        "type": op_type,
        "title_fa": spec.title_fa,
        "risk": spec.risk,
        "requires_approval": spec.requires_approval,
        "parameters": parameters,
        "target_labels_fa": labels or [],
        "changes_fa": spec.changes_fa,
        "preserves_fa": spec.preserves_fa,
        "preview": None,
    }


def build_plan(
    request: str,
    profile: dict,
    clarifications: dict[str, str] | None = None,
    ai_answers: dict[str, str] | None = None,
    *,
    ai_configured: bool = False,
    ai_note_fa: str | None = None,
) -> dict:
    answers = dict(ai_answers or {})
    answers.update(clarifications or {})
    text = fold_text(request or "")
    unsupported: list[dict[str, str]] = []
    notes: list[str] = []
    preservation = [
        "فایل اصلی بازنویسی نمی‌شود و خروجی فایل جداگانه‌ای است.",
        "هیچ کد، فرمول، ماکرو یا دستور دلخواهی از متن درخواست اجرا نمی‌شود.",
    ]
    operations: list[dict] = []

    if not text or not re.search(r"\w|[\u0600-\u06ff]", text):
        unsupported.append({"message_fa": "درخواست خالی است."})

    preserve = bool(PRESERVE_RE.search(text))
    if preserve:
        preservation.append("به‌خاطر قید حفظ اطلاعات، حذف تکراری‌ها انجام نمی‌شود.")

    wants_clean = bool(CLEAN_RE.search(text))
    wants_space = wants_clean or bool(SPACE_RE.search(text))
    wants_empty = bool(ROW_RE.search(text) and EMPTY_RE.search(text) and DELETE_RE.search(text))
    if wants_empty and PARTIAL_RE.search(text):
        unsupported.append(
            {"message_fa": "حذف ردیف‌های نیمه‌خالی در این نسخه انجام نمی‌شود. فقط ردیف کاملاً خالی قابل حذف است."}
        )
    wants_dup = bool(DUP_RE.search(text))
    wants_mark = bool(wants_dup and (MARK_RE.search(text) or not DELETE_RE.search(text)))
    wants_remove_dup = bool(wants_dup and DELETE_RE.search(text) and not MARK_RE.search(text))
    if wants_remove_dup and preserve:
        wants_remove_dup = False
        wants_mark = True
        notes.append("به‌جای حذف تکراری‌ها، فقط نشانه‌گذاری می‌شود چون حفظ اطلاعات اصلی خواسته شده است.")
    wants_customer = bool(wants_dup and CUSTOMER_RE.search(text))
    wants_dates = bool(DATE_RE.search(text) and DATE_VERB_RE.search(text))
    wants_digits = bool(DIGIT_RE.search(text))
    wants_letters = bool(LETTER_RE.search(text))
    wants_headers = bool(HEADER_RE.search(text) and DATE_VERB_RE.search(text))
    wants_email = bool(EMAIL_RE.search(text) and EMAIL_VERB_RE.search(text))

    if MACRO_RE.search(text):
        unsupported.append({"message_fa": "اجرای ماکرو یا VBA پشتیبانی نمی‌شود."})
    if SHELL_RE.search(text):
        unsupported.append({"message_fa": "اجرای کد، SQL یا دستور سیستمی از داخل درخواست ممکن نیست."})
    if IMPUTE_RE.search(text):
        unsupported.append({"message_fa": "جایگزینی یا حدس مقدار خالی انجام نمی‌شود."})
    if MERGE_RE.search(text):
        unsupported.append({"message_fa": "ادغام رکوردهای متعارض پیاده‌سازی نشده است. فقط تطابق دقیق نشانه‌گذاری یا، با تأیید، حذف می‌شود."})
    if PHONE_RE.search(text) and PHONE_VERB_RE.search(text):
        unsupported.append(
            {"message_fa": "شماره تلفن بدون کشور مشخص استاندارد نمی‌شود و رقمی ساخته نمی‌شود. فاصله اضافی در صورت درخواست جداگانه حذف می‌شود."}
        )
    if re.search(r"جداکننده|اعشار|thousands|decimal separator", text):
        unsupported.append(
            {"message_fa": "جداکننده هزارگان یا اعشار مبهم تفسیر نمی‌شود. مقدارهایی مثل 1,234 بدون قاعده صریح دست نمی‌خورند."}
        )

    clarifications: list[dict] = []
    if wants_clean or wants_space:
        if wants_clean:
            operations.append(_operation("remove_invisible_characters", {"columns": None}))
        operations.append(_operation("collapse_whitespace", {"columns": None}))
        operations.append(_operation("trim_whitespace", {"columns": None}))
    if wants_letters:
        operations.append(_operation("normalize_persian_letters", {"columns": None}))
    if wants_digits:
        operations.append(_operation("convert_digits_to_latin", {"columns": None}))
    if wants_headers:
        operations.append(_operation("normalize_headers", {}))
    if wants_dates:
        gregorian = bool(GREGORIAN_RE.search(text))
        jalali = bool(JALALI_RE.search(text))
        target = "keep"
        pending_calendar = gregorian and jalali and "calendar_target" not in answers
        if pending_calendar:
            clarifications.append(
                {
                    "id": "calendar_target",
                    "question_fa": "تاریخ‌ها به کدام تقویم یکسان شوند؟",
                    "options": [
                        {"value": "keep", "label_fa": "هر تاریخ در تقویم خودش بماند"},
                        {"value": "gregorian", "label_fa": "همه به میلادی ISO"},
                        {"value": "jalali", "label_fa": "همه به شمسی"},
                    ],
                }
            )
        else:
            if "calendar_target" in answers:
                target = answers["calendar_target"]
            elif gregorian:
                target = "gregorian"
            elif jalali:
                target = "jalali"
            if target not in {"keep", "gregorian", "jalali"}:
                target = "keep"
            operations.append(_operation("standardize_dates", {"columns": None, "calendar_target": target}))
            if target == "keep":
                notes.append("تقویم‌ها به هم تبدیل نمی‌شوند. تاریخ مبهم بدون حدس باقی می‌ماند.")
            else:
                notes.append("تبدیل تقویم فقط برای تاریخ‌هایی انجام می‌شود که شکلشان قطعی و معتبر باشد.")
    if wants_email:
        email_columns = []
        for column in (profile.get("sheets") or [{}])[0].get("columns") or []:
            if "email" in column.get("tags", []):
                email_columns.append(column["index"])
        if not email_columns:
            clarifications.append(
                {
                    "id": "email_column",
                    "question_fa": "کدام ستون ایمیل بررسی شود؟",
                    "options": [
                        {"value": str(column["index"]), "label_fa": column["name"]}
                        for column in (profile.get("sheets") or [{}])[0].get("columns") or []
                    ],
                }
            )
        chosen = answers.get("email_column")
        if chosen and chosen.isdigit():
            email_columns = [int(chosen)]
        if email_columns and not any(item["id"] == "email_column" for item in clarifications):
            operations.append(
                _operation(
                    "flag_invalid_emails",
                    {"columns": email_columns},
                    _column_labels(profile, email_columns),
                )
            )
    if wants_empty:
        operations.append(_operation("remove_fully_empty_rows", {}))
        notes.append("ردیف نیمه‌خالی حذف نمی‌شود، حتی اگر بعضی سلول‌هایش خالی باشند.")

    duplicate_indexes: list[int] | None = None
    if wants_dup:
        if wants_customer:
            candidates = _customer_columns(profile)
            chosen = answers.get("duplicate_key")
            if chosen == "*":
                duplicate_indexes = _all_column_indexes(profile)
            elif chosen and chosen.isdigit():
                duplicate_indexes = [int(chosen)]
            elif len(candidates) == 1:
                duplicate_indexes = [candidates[0]["index"]]
            else:
                options = [{"value": str(item["index"]), "label_fa": item["name"]} for item in candidates]
                options.append({"value": "*", "label_fa": "همه ستون‌ها با هم (تطابق کامل ردیف)"})
                for column in (profile.get("sheets") or [{}])[0].get("columns") or []:
                    if all(option["value"] != str(column["index"]) for option in options):
                        options.append({"value": str(column["index"]), "label_fa": column["name"]})
                clarifications.append(
                    {
                        "id": "duplicate_key",
                        "question_fa": "تکراری بودن مشتری با کدام ستون مشخص شود؟",
                        "options": options,
                    }
                )
        else:
            duplicate_indexes = _all_column_indexes(profile)
        if duplicate_indexes:
            labels = _column_labels(profile, duplicate_indexes)
            if wants_remove_dup:
                operations.append(
                    _operation(
                        "remove_exact_duplicates_keep_first",
                        {"key_columns": duplicate_indexes},
                        labels,
                    )
                )
            elif wants_mark:
                operations.append(
                    _operation("mark_exact_duplicates", {"key_columns": duplicate_indexes}, labels)
                )

    if not operations and not clarifications:
        clarifications.append(
            {
                "id": "request_unclear",
                "question_fa": "کدام کار انجام شود؟ درخواست با عملیات‌های شناخته‌شده هم‌خوان نبود.",
                "options": [
                    {"value": "trim", "label_fa": "حذف فاصله اضافی"},
                    {"value": "empty", "label_fa": "حذف ردیف کاملاً خالی"},
                    {"value": "mark", "label_fa": "نشانه‌گذاری ردیف تکراری"},
                ],
            }
        )
    choice = answers.get("request_unclear")
    if choice and not any(op["type"] in {"trim_whitespace", "remove_fully_empty_rows", "mark_exact_duplicates"} for op in operations):
        if choice == "trim":
            operations.insert(0, _operation("collapse_whitespace", {"columns": None}))
            operations.insert(1, _operation("trim_whitespace", {"columns": None}))
        elif choice == "empty":
            operations.insert(0, _operation("remove_fully_empty_rows", {}))
        elif choice == "mark" and _all_column_indexes(profile):
            indexes = _all_column_indexes(profile)
            operations.insert(0, _operation("mark_exact_duplicates", {"key_columns": indexes}, _column_labels(profile, indexes)))
        clarifications = [item for item in clarifications if item["id"] != "request_unclear"]

    if any(operation["type"] != "csv_formula_guard" for operation in operations) and profile.get("source_format") == "csv":
        if not any(operation["type"] == "csv_formula_guard" for operation in operations):
            operations.append(_operation("csv_formula_guard", {}))
            notes.append("در خروجی CSV، متن شبه‌فرمول یک آپستروف می‌گیرد. این تغییر امنیتی روی خود متن اعمال می‌شود.")

    for number, operation in enumerate(operations, start=1):
        operation["id"] = f"op-{number}"

    blocking = any(item["id"] != "request_unclear" or not operations for item in clarifications)
    # A clarification still in the list blocks execution.
    blocking = bool(clarifications)
    requires_approval = any(operation["requires_approval"] for operation in operations)
    if not operations:
        summary = "هنوز عملیاتی برای اجرا مشخص نشده است."
    else:
        summary = "طرح پیشنهادی: " + "؛ ".join(operation["title_fa"] for operation in operations) + "."
    interpreter = "rules_with_ai_clarification" if ai_answers else "rule_based"
    return {
        "id": str(uuid.uuid4()),
        "interpreter": interpreter,
        "ai_configured": ai_configured,
        "ai_used": bool(ai_answers),
        "ai_note_fa": ai_note_fa,
        "summary_fa": summary,
        "operations": operations,
        "unsupported": unsupported,
        "clarifications": clarifications,
        "blocking": blocking,
        "requires_approval": requires_approval,
        "preservation_fa": preservation,
        "notes_fa": notes,
        "request": request,
    }
