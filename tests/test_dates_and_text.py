from datetime import datetime

from cleaning_workspace.domain.dates import parse_date, render_date
from cleaning_workspace.domain.textutil import collapse_whitespace, remove_invisible, trim_text


def test_known_jalali_pairs_and_leap_days():
    assert parse_date("1403/01/01").status == "jalali"
    assert render_date(parse_date("1403/01/01"), "gregorian")[0] == "2024-03-20"
    assert render_date(parse_date("2024-03-20"), "jalali")[0] == "1403/01/01"
    assert parse_date("1403/12/30").status == "jalali"
    assert parse_date("1404/12/30").status == "invalid"
    assert parse_date("2024-02-29").status == "gregorian"
    assert parse_date("2023-02-29").status == "invalid"
    assert parse_date("01/02/2024").status == "ambiguous"
    assert parse_date("13/02/2024").status == "gregorian"
    assert parse_date("02/13/2024").status == "gregorian"
    assert render_date(parse_date("1403/01/01"), "keep")[0] == "1403/01/01"
    assert render_date(parse_date("۱۴۰۳/۱۲/۳۰"), "keep")[0] == "1403/12/30"


def test_excel_midnight_keeps_time_in_value_and_text_keeps_clock():
    parsed = parse_date(datetime(2024, 3, 20, 14, 30, 0))
    assert parsed.has_time is True
    parsed_midnight = parse_date(datetime(2024, 3, 20, 0, 0, 0))
    assert parsed_midnight.has_time is False
    assert render_date(parse_date("2024-03-20 14:30:00"), "keep")[0] == "2024-03-20T14:30:00"


def test_trim_is_idempotent_and_keeps_zwnj():
    assert trim_text(trim_text("  a  ")) == trim_text("  a  ")
    assert collapse_whitespace("می\u200c  روم") == "می\u200c روم"
    assert remove_invisible("a\u200bb") == "ab"
    assert remove_invisible("نیم\u200cفاصله") == "نیم\u200cفاصله"
