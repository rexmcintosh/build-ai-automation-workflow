# tests/diem/test_drain.py
from datetime import datetime
from pathlib import Path
import pytest
from diem.config import DiemConfig, Checkpoint
from diem.drain import run_checkpoint, floor_for, next_deadline
from diem.queue import QueueDir, new_item
from diem.runners import RunResult
from diem.state import Estimates, Reviewed, set_pause

NOW = datetime(2026, 7, 3, 23, 5)
NOW_ISO = "2026-07-03T23:05:00"

class FakeBalance:
    """Scripted balance readings; drains by `burn` per run when scripted list empties."""
    def __init__(self, readings):
        self.readings = list(readings)
        self.calls = 0
    def diem_balance(self):
        self.calls += 1
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]

class FakeRunner:
    def __init__(self, results=None):
        self.ran = []
        self.results = results or {}
    def __call__(self, item, **kw):
        self.ran.append(item)
        return self.results.get(item.id, RunResult(True, 60.0, output_path="/o"))

def _cfg(tmp_path, **kw):
    base = dict(daily_diem=100.0, repos=[], state_dir=tmp_path / "state",
                outputs_dir=tmp_path / "out",
                checkpoints=[Checkpoint("21:00", 0.40), Checkpoint("23:00", 0.15),
                             Checkpoint("00:15", 0.0)])
    base.update(kw)
    return DiemConfig(**base)

def _bits(tmp_path, cfg):
    q = QueueDir(cfg.state_dir)
    return (q, Estimates(cfg.state_dir / "estimates.json", cfg.seeds),
            Reviewed(cfg.state_dir / "reviewed.json"))

def test_floor_for_picks_latest_checkpoint():
    cfg = _cfg(Path("/tmp/x"))
    assert floor_for(cfg, datetime(2026, 7, 3, 21, 30)) == 40.0
    assert floor_for(cfg, datetime(2026, 7, 3, 23, 5)) == 15.0
    assert floor_for(cfg, datetime(2026, 7, 4, 0, 20)) == 0.0
    assert floor_for(cfg, datetime(2026, 7, 3, 20, 0)) == 40.0  # pre-first: conservative
    # after midnight but before 00:15, last-fired checkpoint is yesterday 23:00
    assert floor_for(cfg, datetime(2026, 7, 4, 0, 5)) == 15.0

def test_next_deadline_before_and_after_midnight():
    cfg = _cfg(Path("/tmp/x"))
    assert next_deadline(cfg, datetime(2026, 7, 3, 23, 5)) == datetime(2026, 7, 4, 0, 50)
    assert next_deadline(cfg, datetime(2026, 7, 4, 0, 20)) == datetime(2026, 7, 4, 0, 50)
    assert next_deadline(cfg, datetime(2026, 7, 4, 0, 55)) == datetime(2026, 7, 4, 0, 50)
    assert next_deadline(cfg, datetime(2026, 7, 4, 1, 30)) == datetime(2026, 7, 5, 0, 50)

def test_drains_until_floor(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    for n in range(3):
        q.add(new_item("ask", {"question": f"q{n}", "panel": "decision"}, created=NOW_ISO))
    # floor at 23:05 = 15.0; readings: 40 → run → 25 → run → 14 (≤ floor, stop)
    bal = FakeBalance([40.0, 25.0, 25.0, 14.0, 14.0])
    r = FakeRunner()
    summary = run_checkpoint(cfg, now=NOW, balance=bal, queue=q,
                             estimates=est, reviewed=rev, runner=r)
    assert len(r.ran) == 2 and summary["aborted"] is None
    assert len(q.pending(NOW_ISO)) == 1  # third ask survives for the 00:15 pass

def test_balance_unavailable_aborts(tmp_path):
    from diem.balance import BalanceUnavailable
    class Down:
        def diem_balance(self):
            raise BalanceUnavailable("nope")
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    q.add(new_item("ask", {"question": "q", "panel": "decision"}, created=NOW_ISO))
    summary = run_checkpoint(cfg, now=NOW, balance=Down(), queue=q,
                             estimates=est, reviewed=rev, runner=FakeRunner())
    assert summary["aborted"] == "balance_unavailable"
    assert len(q.pending(NOW_ISO)) == 1  # nothing consumed

def test_deadline_skips_long_jobs(tmp_path):
    cfg = _cfg(tmp_path, seeds={"images": {"cost": 1.0, "duration_s": 3600},
                                "ask": {"cost": 1.0, "duration_s": 60}})
    q, est, rev = _bits(tmp_path, cfg)
    q.add(new_item("images", {"repo": "/r", "count": 9,
                              "command": ["x"]}, created=NOW_ISO))
    q.add(new_item("ask", {"question": "q", "panel": "decision"}, created=NOW_ISO))
    late = datetime(2026, 7, 4, 0, 30)  # 20 min to 00:50 deadline
    r = FakeRunner()
    summary = run_checkpoint(cfg, now=late, balance=FakeBalance([50.0, 40.0, 40.0]),
                             queue=q, estimates=est, reviewed=rev, runner=r)
    assert [i.type for i in r.ran] == ["ask"]  # images (60 min est) skipped
    assert any(s["reason"] == "deadline" for s in summary["skipped"])

def test_paused_aborts(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    set_pause(cfg.state_dir, "2026-07-04T01:00:00")
    summary = run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0]), queue=q,
                             estimates=est, reviewed=rev, runner=FakeRunner())
    assert summary["aborted"] == "paused"

def test_failure_requeues_then_archives(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    it = new_item("ask", {"question": "q", "panel": "decision"}, created=NOW_ISO)
    q.add(it)
    fail = FakeRunner({it.id: RunResult(False, 5.0, error="exit 2: boom")})
    run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0, 50.0, 50.0]), queue=q,
                   estimates=est, reviewed=rev, runner=fail)
    pend = q.pending(NOW_ISO)
    assert len(pend) == 1 and pend[0].attempts == 1  # requeued once
    run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0, 50.0, 50.0]), queue=q,
                   estimates=est, reviewed=rev, runner=fail)
    assert q.pending(NOW_ISO) == []  # attempts == max_attempts → archived failed

def test_review_range_success_advances_reviewed_sha(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    rev.set("/r/a", "old")
    q.add(new_item("review", {"repo": "/r/a", "range": "old..new", "head": "new"},
                   created=NOW_ISO))
    run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0, 49.0, 49.0]), queue=q,
                   estimates=est, reviewed=rev, runner=FakeRunner())
    assert rev.get("/r/a") == "new"

def test_filler_backfill_tops_up_empty_queue(tmp_path):
    cfg = _cfg(tmp_path, backfill_max_per_night=2, backfill_chunk=3)
    q, est, rev = _bits(tmp_path, cfg)
    r = FakeRunner()
    run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0, 40.0, 30.0, 20.0, 14.0]),
                   queue=q, estimates=est, reviewed=rev, runner=r)
    assert 1 <= len(r.ran) <= 2
    assert all(i.type == "backfill" and i.payload["max_targets"] == 3 for i in r.ran)
    assert q.night_count("backfill", "2026-07-03T01:00:00") <= 2  # cap respected

def test_late_checkpoint_in_gap_aborts(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    q.add(new_item("ask", {"question": "q", "panel": "decision"}, created=NOW_ISO))
    r = FakeRunner()
    summary = run_checkpoint(cfg, now=datetime(2026, 7, 4, 0, 55),
                             balance=FakeBalance([80.0]), queue=q,
                             estimates=est, reviewed=rev, runner=r)
    assert summary["aborted"] == "past_deadline" and r.ran == []
    assert len(q.pending(NOW_ISO)) == 1  # nothing consumed

def test_post_reset_run_aborts(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    summary = run_checkpoint(cfg, now=datetime(2026, 7, 4, 1, 30),
                             balance=FakeBalance([100.0]), queue=q,
                             estimates=est, reviewed=rev, runner=FakeRunner())
    assert summary["aborted"] == "no_checkpoint_fired"

def test_mid_day_run_aborts(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    summary = run_checkpoint(cfg, now=datetime(2026, 7, 3, 20, 0),
                             balance=FakeBalance([100.0]), queue=q,
                             estimates=est, reviewed=rev, runner=FakeRunner())
    assert summary["aborted"] == "no_checkpoint_fired"

def test_skipped_entries_unique(tmp_path):
    cfg = _cfg(tmp_path, seeds={"images": {"cost": 1.0, "duration_s": 3600},
                                "ask": {"cost": 1.0, "duration_s": 60}})
    q, est, rev = _bits(tmp_path, cfg)
    q.add(new_item("images", {"repo": "/r", "count": 9, "command": ["x"]}, created=NOW_ISO))
    q.add(new_item("ask", {"question": "a", "panel": "decision"}, created=NOW_ISO))
    q.add(new_item("ask", {"question": "b", "panel": "decision"}, created=NOW_ISO))
    summary = run_checkpoint(cfg, now=datetime(2026, 7, 4, 0, 30),
                             balance=FakeBalance([50.0, 45.0, 45.0, 40.0, 40.0]),
                             queue=q, estimates=est, reviewed=rev, runner=FakeRunner())
    ids = [s["id"] for s in summary["skipped"]]
    assert len(ids) == len(set(ids))

def test_estimates_recorded_from_balance_delta(tmp_path):
    cfg = _cfg(tmp_path)
    q, est, rev = _bits(tmp_path, cfg)
    q.add(new_item("ask", {"question": "q", "panel": "decision"}, created=NOW_ISO))
    run_checkpoint(cfg, now=NOW, balance=FakeBalance([50.0, 47.0, 14.0]), queue=q,
                   estimates=est, reviewed=rev, runner=FakeRunner())
    cost, _dur = est.estimate("ask")
    assert cost == pytest.approx(0.5 + 0.3 * (3.0 - 0.5))  # EMA toward observed 3.0


# --- UTC / midnight-reset (00:00 UTC epoch) config ---

def _utc_cfg(**kw):
    return _cfg(Path("/tmp/x"), reset="00:00", deadline="23:50",
                checkpoints=[Checkpoint("21:00", 0.40), Checkpoint("23:00", 0.15),
                             Checkpoint("23:45", 0.0)], **kw)

def test_next_deadline_midnight_reset():
    cfg = _utc_cfg()
    # evening: deadline is 23:50 the same evening, just before the 00:00 reset
    assert next_deadline(cfg, datetime(2026, 7, 3, 23, 5)) == datetime(2026, 7, 3, 23, 50)
    assert next_deadline(cfg, datetime(2026, 7, 3, 21, 0)) == datetime(2026, 7, 3, 23, 50)
    # just after the reset: deadline rolls to the coming night
    assert next_deadline(cfg, datetime(2026, 7, 4, 0, 30)) == datetime(2026, 7, 4, 23, 50)

def test_floor_for_utc_evening_checkpoints():
    cfg = _utc_cfg()
    assert floor_for(cfg, datetime(2026, 7, 3, 20, 0)) == 40.0  # pre-first: conservative
    assert floor_for(cfg, datetime(2026, 7, 3, 21, 30)) == 40.0
    assert floor_for(cfg, datetime(2026, 7, 3, 23, 5)) == 15.0
    assert floor_for(cfg, datetime(2026, 7, 3, 23, 50)) == 0.0
