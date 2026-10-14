"""Text helpers that do not guess the meaning of identifiers or dates."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
DIGIT_TRANSLATION = str.maketrans(
    {ch: str(index) for index, ch in enumerate(PERSIAN_DIGITS)}
    | {ch: str(index) for index, ch in enumerate(ARABIC_DIGITS)}
)
LETTER_TRANSLATION = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})
INVISIBLE_RE = re.compile(
    "[\u200b\u200d\u2060\ufeff\u00ad\u180e\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]"
)
WHITESPACE_RUN_RE = re.compile(r"\s+")
NULL_TOKENS = {
    "null",
    "none",
    "n/a",
    "na",
    "nil",
    "-",
    "--",
    "نامشخص",
    "خالی",
    "#n/a",
    "#na",
}


def translate_digits(value: str) -> str:
    return value.translate(DIGIT_TRANSLATION)


def normalize_persian_letters(value: str) -> str:
    return value.translate(LETTER_TRANSLATION)


def remove_invisible(value: str) -> str:
    """Remove invisible controls. ZWNJ (U+200C) and bidi marks are preserved."""
    return INVISIBLE_RE.sub("", value)


def trim_text(value: str) -> str:
    return value.strip()


def collapse_whitespace(value: str) -> str:
    return WHITESPACE_RUN_RE.sub(" ", value).strip()


def fold_text(value: str) -> str:
    text = str(value).replace("\u200c", "").replace("\u200d", "")
    text = translate_digits(normalize_persian_letters(text))
    text = text.strip().lower()
    return WHITESPACE_RUN_RE.sub(" ", text)


def canon(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 10**15:
            return str(int(value))
        return repr(value)
    return str(value)


def digest(value: Any) -> str:
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def truncate(value: Any, limit: int = 80) -> str:
    text = canon(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def is_sensitive_header(header: str) -> bool:
    folded = fold_text(header)
    hints = (
        "email",
        "ایمیل",
        "phone",
        "تلفن",
        "موبایل",
        "همراه",
        "کد ملی",
        "کدملی",
        "national",
        "password",
        "رمز",
        "حساب",
    )
    return any(hint in folded for hint in hints)


def display_value(value: Any, header: str) -> str:
    if is_sensitive_header(header):
        text = canon(value)
        if "@" in text:
            local, _, domain = text.partition("@")
            return truncate((local[:1] + "***@" + domain), 80)
        if len(text) <= 4:
            return "***"
        return text[:2] + "***" + text[-2:]
    return truncate(value)


def looks_null_token(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return fold_text(value) in NULL_TOKENS
