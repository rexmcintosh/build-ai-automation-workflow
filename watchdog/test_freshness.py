"""Unit tests for check_meet_freshness (run: pytest watchdog/test_freshness.py)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from .triage import check_meet_freshness

LIS = ZoneInfo("Europe/Lisbon")
UTC = ZoneInfo("UTC")


def _now(hour):
    return datetime.now(LIS).replace(hour=hour, minute=0).timestamp()


def _iso(now, minutes_ago):
    return datetime.fromtimestamp(now - minutes_ago * 60, tz=UTC).isoformat()


def _today(now):
    return datetime.fromtimestamp(now, tz=LIS).date().isoformat()


def _live_row(now, status, last_min=None, upd_min=5):
    return {"sr_meet_id": "1", "name": "Meet A", "ingest_status": status,
            "last_ingest_at": _iso(now, last_min) if last_min is not None else None,
            "updated_at": _iso(now, upd_min),
            "start_date": _today(now), "end_date": _today(now)}


def test_quiet_live_meet_escalates_warn_then_crit():
    now = _now(15)
    assert check_meet_freshness([_live_row(now, "polling", last_min=30)], now).level == "warn"
    assert check_meet_freshness([_live_row(now, "polling", last_min=90)], now).level == "crit"


def test_fresh_live_meet_is_ok():
    now = _now(15)
    assert check_meet_freshness([_live_row(now, "polling", last_min=5)], now).level == "ok"


def test_unlaunched_live_meet_warns_after_grace():
    now = _now(15)
    s = check_meet_freshness([_live_row(now, "discovered", upd_min=40)], now)
    assert s.level == "warn" and "awaiting launch" in s.summary


def test_recent_failed_is_crit_even_at_night():
    night = _now(3)
    s = check_meet_freshness([{"sr_meet_id": "3", "name": "C", "ingest_status": "failed",
                               "updated_at": _iso(night, 60)}], night)
    assert s.level == "crit" and "FAILED" in s.summary


def test_old_failed_and_ended_meets_are_ok():
    now = _now(15)
    rows = [
        {"sr_meet_id": "3", "name": "C", "ingest_status": "failed",
         "updated_at": _iso(now, 72 * 60)},
        {"sr_meet_id": "9", "name": "Old", "ingest_status": "queued",
         "last_ingest_at": None, "updated_at": _iso(now, 90),
         "start_date": "2026-06-01", "end_date": "2026-06-02"},
    ]
    assert check_meet_freshness(rows, now).level == "ok"


def test_outside_racing_hours_staleness_is_silent():
    night = _now(3)
    assert check_meet_freshness([_live_row(night, "polling", last_min=300)], night).level == "ok"
