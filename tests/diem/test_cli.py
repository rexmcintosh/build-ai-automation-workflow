import json
from datetime import datetime
from pathlib import Path
import pytest
import diem.cli as cli
from diem.balance import BalanceUnavailable
from diem.config import DiemConfig
from diem.queue import QueueDir
from diem.runners import RunResult

def _cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'daily_diem = 100.0\nrepos = []\n'
                 f'state_dir = "{tmp_path / "state"}"\n'
                 f'outputs_dir = "{tmp_path / "out"}"\n')
    return p

def _summary(**kw):
    base = {"aborted": None, "floor": 15.0, "started_balance": 40.0,
            "ended_balance": 20.0, "deadline": "2026-07-04T00:50:00",
            "ran": [], "skipped": []}
    base.update(kw); return base

def test_queue_add_and_list_and_rm(tmp_path, capsys, monkeypatch):
    cfgp = _cfg_file(tmp_path)
    assert cli.main(["queue", "add", "ask", "which host?", "--panel", "decision",
                     "--config", str(cfgp)]) == 0
    q = QueueDir(tmp_path / "state")
    items = q.pending("2026-07-03T21:00:00")
    assert len(items) == 1 and items[0].banked and items[0].type == "ask"
    assert cli.main(["queue", "list", "--config", str(cfgp)]) == 0
    out = capsys.readouterr().out
    assert "ask" in out and items[0].id[:8] in out
    assert cli.main(["queue", "rm", items[0].id, "--config", str(cfgp)]) == 0
    assert q.pending("2026-07-03T21:00:00") == []

def test_queue_add_review_and_images(tmp_path):
    cfgp = _cfg_file(tmp_path)
    cli.main(["queue", "add", "review", "/r/swim", "--config", str(cfgp)])
    cli.main(["queue", "add", "images", "/r/re", "7", "--config", str(cfgp)])
    q = QueueDir(tmp_path / "state")
    by_type = {i.type: i for i in q.pending("2026-07-03T21:00:00")}
    assert by_type["review"].payload == {"repo": "/r/swim", "diff": True}
    assert by_type["images"].payload["count"] == 7

@pytest.mark.parametrize("extra_args", [
    ["review"],                                  # no repo
    ["images", "/r/re"],                         # no count
    ["images", "/r/re", "notanumber"],           # non-int count
    ["cmd"],                                      # no name
])
def test_queue_add_missing_args_exit_2(tmp_path, capsys, extra_args):
    cfgp = _cfg_file(tmp_path)
    rc = cli.main(["queue", "add", *extra_args, "--config", str(cfgp)])
    assert rc == 2
    err = capsys.readouterr().err
    assert err.strip() != "" and len(err.strip().splitlines()) == 1

def test_pause_and_resume(tmp_path):
    cfgp = _cfg_file(tmp_path)
    from diem.state import pause_until
    assert cli.main(["pause", "2", "--config", str(cfgp)]) == 0
    assert pause_until(tmp_path / "state") is not None
    assert cli.main(["resume", "--config", str(cfgp)]) == 0
    assert pause_until(tmp_path / "state") is None

def test_drain_requires_checkpoint_flag(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["drain", "--config", str(_cfg_file(tmp_path))])

def test_status_exits_zero_when_balance_unavailable(tmp_path, monkeypatch, capsys):
    cfgp = _cfg_file(tmp_path)
    monkeypatch.setattr(cli, "load_venice_key", lambda: "k")
    class Down:
        def __init__(self, *a, **k): pass
        def diem_balance(self): raise BalanceUnavailable("down")
    monkeypatch.setattr(cli, "BalanceClient", Down)
    assert cli.main(["status", "--config", str(cfgp)]) == 0
    assert "unavailable" in capsys.readouterr().out

def test_drain_writes_diem_day_jsonl_and_pings(tmp_path, monkeypatch):
    cfgp = _cfg_file(tmp_path)
    sent = []
    monkeypatch.setattr(cli, "load_venice_key", lambda: "k")
    monkeypatch.setattr(cli, "BalanceClient", lambda key: object())
    monkeypatch.setattr(cli, "run_checkpoint", lambda *a, **k: _summary())
    monkeypatch.setattr(cli, "send_telegram", lambda cfg, text: sent.append(text) or True)
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 7, 3, 23, 5))
    assert cli.main(["drain", "--checkpoint", "--config", str(cfgp)]) == 0
    jl = tmp_path / "state" / "summaries" / "2026-07-03.jsonl"   # DIEM-day label
    assert jl.exists() and len(jl.read_text().splitlines()) == 1
    assert len(sent) == 1  # first checkpoint of the night → evening ping

def test_drain_last_checkpoint_writes_morning_report(tmp_path, monkeypatch):
    cfgp = _cfg_file(tmp_path)
    sent = []
    monkeypatch.setattr(cli, "load_venice_key", lambda: "k")
    monkeypatch.setattr(cli, "BalanceClient", lambda key: object())
    monkeypatch.setattr(cli, "run_checkpoint", lambda *a, **k: _summary())
    monkeypatch.setattr(cli, "send_telegram", lambda cfg, text: sent.append(text) or True)
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 7, 3, 23, 5))
    cli.main(["drain", "--checkpoint", "--config", str(cfgp)])
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 7, 4, 0, 20))
    cli.main(["drain", "--checkpoint", "--config", str(cfgp)])
    jl = tmp_path / "state" / "summaries" / "2026-07-03.jsonl"
    assert len(jl.read_text().splitlines()) == 2      # same night, same file
    report = tmp_path / "state" / "reports" / "2026-07-03.md"
    assert report.exists()
    assert len(sent) == 2 and "Report" in sent[1]

def test_drain_report_failure_does_not_crash(tmp_path, monkeypatch, capsys):
    cfgp = _cfg_file(tmp_path)
    monkeypatch.setattr(cli, "load_venice_key", lambda: "k")
    monkeypatch.setattr(cli, "BalanceClient", lambda key: object())
    monkeypatch.setattr(cli, "run_checkpoint", lambda *a, **k: _summary())
    monkeypatch.setattr(cli, "send_telegram", lambda cfg, text: True)
    def boom(*a, **k): raise OSError("disk full")
    monkeypatch.setattr(cli, "write_morning_report", boom)
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 7, 4, 0, 20))
    assert cli.main(["drain", "--checkpoint", "--config", str(cfgp)]) == 0
