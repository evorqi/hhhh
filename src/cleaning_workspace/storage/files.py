"""Job files are stored under generated ids, never under the uploaded name."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from cleaning_workspace.errors import AppError

JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def require_id(self, job_id: str) -> str:
        if not JOB_ID_RE.fullmatch(job_id or ""):
            raise AppError(
                "The job id is not valid.",
                "شناسه کار معتبر نیست.",
                code="invalid_job_id",
                status_code=400,
            )
        return job_id

    def job_dir(self, job_id: str) -> Path:
        return self.root / "jobs" / self.require_id(job_id)

    def source_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "source"

    def output_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "output"

    def report_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "report.json"

    def ledger_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "ledger.json"

    def save_source(self, job_id: str, data: bytes) -> Path:
        directory = self.job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=False)
        path = directory / "source"
        path.write_bytes(data)
        return path

    def delete_job(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
