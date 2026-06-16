"""Tests for the watchdog runner glue (state load/save, report formatting).

The signal collection itself does real I/O and is verified by a live dry-run;
here we test the deterministic plumbing around it.
"""
import json

from watchdog.run import format_report, load_state, save_state
from watchdog.triage import CheckStatus


def test_load_state_missing_file_returns_empty(tmp_path):
    assert load_state(tmp_path / "nope.json") == {}


def test_save_then_load_roundtrips(tmp_path):
    p = tmp_path / "state.json"
    save_state(p, {"disk": {"level": "crit", "ts": 123}})
    assert load_state(p) == {"disk": {"level": "crit", "ts": 123}}


def test_load_state_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert load_state(p) == {}  # never let a corrupt state file crash the poll


def test_format_report_includes_name_summary_and_evidence():
    fired = [CheckStatus("disk", "crit", "root filesystem 96% full", evidence="/dev/sda1 96% /")]
    report = format_report(fired)
    assert "disk" in report
    assert "96% full" in report
    assert "/dev/sda1" in report


def test_format_report_orders_crit_before_warn():
    fired = [
        CheckStatus("a", "warn", "warn-thing"),
        CheckStatus("b", "crit", "crit-thing"),
    ]
    report = format_report(fired)
    assert report.index("crit-thing") < report.index("warn-thing")
