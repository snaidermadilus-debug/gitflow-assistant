from lib.dates import today_iso


def test_today_iso_returns_iso_date():
    value = today_iso()
    assert len(value) == 10
    assert value[:4].isdigit()
    assert value[4] == "-" and value[7] == "-"
