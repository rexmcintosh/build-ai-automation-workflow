import json
from pathlib import Path
import pytest
import diem.cli as cli
from diem.config import DiemConfig
from diem.queue import QueueDir

def _cfg_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'daily_diem = 100.0\nrepos = []\n'
                 f'state_dir = "{tmp_path / "state"}"\n'
                 f'outputs_dir = "{tmp_path / "out"}"\n')
    return p

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
