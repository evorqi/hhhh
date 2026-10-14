"""Runtime configuration. Secrets are read from the environment and masked in repr."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    web_dir: Path
    max_upload_bytes: int = 20 * 1024 * 1024
    max_uncompressed_bytes: int = 80 * 1024 * 1024
    max_zip_members: int = 2000
    max_rows: int = 50_000
    max_cols: int = 200
    max_sheets: int = 30
    max_cells: int = 1_000_000
    retention_hours: int = 24
    access_token: str | None = None
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(__file__).resolve().parents[2]
        data_dir = Path(os.environ.get("CLEANING_DATA_DIR", root / "data")).expanduser()
        web_dir = Path(os.environ.get("CLEANING_WEB_DIR", root / "web")).expanduser()
        return cls(
            data_dir=data_dir,
            web_dir=web_dir,
            max_upload_bytes=_int_env("CLEANING_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
            max_uncompressed_bytes=_int_env("CLEANING_MAX_UNCOMPRESSED_BYTES", 80 * 1024 * 1024),
            max_rows=_int_env("CLEANING_MAX_ROWS", 50_000),
            max_cols=_int_env("CLEANING_MAX_COLS", 200),
            max_sheets=_int_env("CLEANING_MAX_SHEETS", 30),
            max_cells=_int_env("CLEANING_MAX_CELLS", 1_000_000),
            retention_hours=_int_env("CLEANING_RETENTION_HOURS", 24),
            access_token=_optional_env("WORKSPACE_ACCESS_TOKEN"),
            ai_base_url=_optional_env("CLEANING_AI_BASE_URL"),
            ai_api_key=_optional_env("CLEANING_AI_API_KEY"),
            ai_model=_optional_env("CLEANING_AI_MODEL"),
            host=os.environ.get("CLEANING_HOST", "127.0.0.1"),
            port=_int_env("CLEANING_PORT", 8000),
        )

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_base_url and self.ai_api_key and self.ai_model)

    def masked(self) -> dict[str, object]:
        return {
            "data_dir": str(self.data_dir),
            "max_upload_bytes": self.max_upload_bytes,
            "max_uncompressed_bytes": self.max_uncompressed_bytes,
            "max_rows": self.max_rows,
            "max_cols": self.max_cols,
            "max_sheets": self.max_sheets,
            "max_cells": self.max_cells,
            "retention_hours": self.retention_hours,
            "access_token_set": self.access_token is not None,
            "ai_configured": self.ai_configured,
            "ai_model": self.ai_model if self.ai_configured else None,
            "host": self.host,
            "port": self.port,
        }
