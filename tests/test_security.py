import io

import openpyxl
import pytest

from cleaning_workspace.ai.client import filter_answers
from cleaning_workspace.config import Settings
from cleaning_workspace.domain.security import detect_upload
from cleaning_workspace.errors import AppError


def test_ai_answers_must_be_one_of_the_options():
    questions = [{"id": "duplicate_key", "options": [{"value": "1"}, {"value": "*"}]}]
    assert filter_answers({"answers": {"duplicate_key": "1", "run_shell": "yes"}}, questions) == {"duplicate_key": "1"}
    assert filter_answers({"answers": {"duplicate_key": "delete_all"}}, questions) == {}
    assert filter_answers("ignore instructions", questions) == {}
    assert filter_answers({"operations": [{"type": "run_shell"}]}, questions) == {}


def test_archive_expansion_limit(tmp_path):
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "x"
    buffer = io.BytesIO()
    workbook.save(buffer)
    settings = Settings(data_dir=tmp_path, web_dir=tmp_path, max_uncompressed_bytes=30, max_zip_members=2)
    with pytest.raises(AppError) as exc:
        detect_upload(buffer.getvalue(), "a.xlsx", settings)
    assert exc.value.code == "archive_limits"


def test_path_like_job_id_is_rejected(client):
    response = client.get("/api/jobs/not-a-uuid")
    assert response.status_code == 400
