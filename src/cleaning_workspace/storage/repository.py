"""SQLite persistence for job metadata. File bytes live beside the database."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime) -> str:
    return value.isoformat()


class Repository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    detected_format TEXT,
                    size_bytes INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    error_code TEXT,
                    error_message_fa TEXT,
                    error_message_en TEXT,
                    inspection_json TEXT,
                    profile_json TEXT,
                    plan_json TEXT,
                    result_json TEXT
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    detail_fa TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_expires ON jobs(expires_at);
                """
            )
            self._conn.commit()

    def insert_job(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, status, original_filename, detected_format, size_bytes, source_sha256,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["status"],
                    record["original_filename"],
                    record.get("detected_format"),
                    record["size_bytes"],
                    record["source_sha256"],
                    record["created_at"],
                    record["updated_at"],
                    record["expires_at"],
                ),
            )
            self._conn.execute(
                "INSERT INTO job_events (job_id, status, created_at, detail_fa) VALUES (?, ?, ?, ?)",
                (record["id"], record["status"], record["created_at"], "فایل ذخیره شد."),
            )
            self._conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, created_at, detail_fa FROM job_events WHERE job_id = ? ORDER BY id",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(self, job_id: str, status: str, detail_fa: str, **fields: Any) -> None:
        now = iso(utcnow())
        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [status, now]
        for key, value in fields.items():
            if key.endswith("_json") and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?", values)
            self._conn.execute(
                "INSERT INTO job_events (job_id, status, created_at, detail_fa) VALUES (?, ?, ?, ?)",
                (job_id, status, now, detail_fa),
            )
            self._conn.commit()

    def due(self, now: datetime) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE expires_at < ? AND status != 'expired'",
                (iso(now),),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_expires_at(self, job_id: str, when: datetime) -> None:
        with self._lock:
            self._conn.execute("UPDATE jobs SET expires_at = ? WHERE id = ?", (iso(when), job_id))
            self._conn.commit()


def expiry_from(now: datetime, hours: int) -> datetime:
    return now + timedelta(hours=hours)
