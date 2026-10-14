from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cleaning_workspace.api.app import create_app
from cleaning_workspace.config import Settings
from cleaning_workspace.services.jobs import JobService

EXAMPLE = "این فایل رو تمیز کن، تاریخ‌ها رو یکسان کن، فاصله‌های اضافی رو بردار، ردیف‌های کاملاً خالی رو حذف کن و مشتری‌های تکراری رو مشخص کن. اطلاعات اصلی رو از بین نبر."


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", web_dir=Path("web"), retention_hours=24, access_token=None)


@pytest.fixture
def service(settings: Settings) -> JobService:
    return JobService(settings)


@pytest.fixture
def client(settings: Settings, service: JobService) -> TestClient:
    return TestClient(create_app(settings, service))
