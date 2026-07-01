"""Runnable check for the parser + report rules. `python3 test_tt.py`."""
from datetime import date, datetime

import tt

T = datetime.fromisoformat


def test_parse_line():
    assert tt.parse_line("2026-07-01T09:00:00-04:00 START a1b2 backend work") == \
        (T("2026-07-01T09:00:00-04:00"), "START", "a1b2", "backend work")
    assert tt.parse_line("2026-07-01T10:00:00-04:00 STOP a1b2")[3] == ""
    assert tt.parse_line("") is None
    assert tt.parse_line("garbage line") is None


def test_pairing_interleaved():
    events = [tt.parse_line(l) for l in [
        "2026-07-01T09:00:00-04:00 START a1b2 A",
        "2026-07-01T09:05:00-04:00 START c3d4 B",
        "2026-07-01T10:00:00-04:00 STOP a1b2",       # closes A, not "the latest"
        "2026-07-01T11:00:00-04:00 STOP c3d4",
    ]]
    by = {s["sid"]: s for s in tt.pair_sessions(events)}
    assert (by["a1b2"]["stop"] - by["a1b2"]["start"]).total_seconds() == 3600
    assert (by["c3d4"]["stop"] - by["c3d4"]["start"]).total_seconds() == 6900


def test_open_session_live_vs_historical():
    open_sess = [{"sid": "a1b2", "task": "X", "start": T("2026-01-01T07:00:00-04:00"), "stop": None}]
    now = T("2026-07-01T12:00:00-04:00")
    rate = {"amount": 120, "currency": "USD"}

    # historical report (end < today): excluded, zero total, warned
    rows, totals, warns = tt.build_report(open_sess, date(2026, 1, 1), date(2026, 1, 31), rate, now, now.date())
    assert rows[0]["excluded"] and rows[0]["end"] == "OPEN"
    assert totals["secs"] == 0 and len(warns) == 1

    # live report (end >= today): counts to now, no warning
    rows, totals, warns = tt.build_report(open_sess, date(2026, 1, 1), date(2026, 7, 1), rate, now, now.date())
    assert not rows[0]["excluded"] and totals["secs"] > 0 and not warns


def test_amount_and_fmt():
    assert tt.fmt_hms(3661) == "01:01:01"
    assert tt.fmt_hms(147 * 3600 + 55 * 60) == "147:55:00"
    sess = [{"sid": "z", "task": "T", "start": T("2026-05-10T09:00:00-04:00"),
             "stop": T("2026-05-10T11:00:00-04:00")}]
    rows, totals, _ = tt.build_report(sess, date(2026, 5, 1), date(2026, 5, 31),
                                      {"amount": 120, "currency": "USD"}, T("2026-07-01T00:00:00-04:00"), date(2026, 7, 1))
    assert rows[0]["amount"] == 240.0 and totals["amount"] == 240.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all passed")
