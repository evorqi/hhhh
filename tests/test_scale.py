import time

from cleaning_workspace.domain.engine import execute
from cleaning_workspace.domain.planner import build_plan
from cleaning_workspace.domain.profiling import profile_workbook
from cleaning_workspace.domain.readers import read_model
from cleaning_workspace.domain.security import detect_upload
from cleaning_workspace.config import Settings


def test_two_thousand_rows_trim_and_mark(tmp_path):
    lines = ["نام,کد,مبلغ"]
    for index in range(2000):
        code = f"{index:05d}"
        if index in {10, 11}:
            lines.append(f"  علی  ,{code},0")
        elif index % 50 == 0:
            lines.append(",,")
        else:
            lines.append(f"کاربر {index},{code},1000")
    data = ("\n".join(lines) + "\n").encode()
    path = tmp_path / "wide.csv"
    path.write_bytes(data)
    settings = Settings(data_dir=tmp_path, web_dir=tmp_path)
    started = time.perf_counter()
    model = read_model(path, detect_upload(data, "wide.csv", settings), settings)
    profile = profile_workbook(model)
    plan = build_plan("فاصله اضافی را بردار، ردیف‌های کاملا خالی را حذف کن و تکراری‌ها را مشخص کن", profile)
    execute(model, plan, approved=False)
    elapsed = time.perf_counter() - started
    assert elapsed < 8
    active = model.sheets[0].active_rows()
    assert any(row.cells.get(1) and row.cells[1].value == "علی" for row in active)
    assert any(row.cells.get(2) and row.cells[2].value == "00010" for row in active)
    assert len(active) < 2001
