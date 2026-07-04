import subprocess
from pathlib import Path
from types import SimpleNamespace
from diem.config import DiemConfig
from diem.queue import new_item
from diem.runners import run_item

NOW = "2026-07-03T21:00:00"

class FakeRun:
    """Records subprocess calls; scripted (returncode, stdout) per call."""
    def __init__(self, results=None, raise_timeout=False):
        self.calls = []
        self.results = list(results or [])
        self.raise_timeout = raise_timeout
    def __call__(self, argv, **kw):
        self.calls.append({"argv": argv, **kw})
        if self.raise_timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
        rc, out = self.results.pop(0) if self.results else (0, "ok-output")
        return SimpleNamespace(returncode=rc, stdout=out, stderr="")

def _cfg(tmp_path):
    return DiemConfig(daily_diem=100.0, repos=[],
                      state_dir=tmp_path / "state", outputs_dir=tmp_path / "out",
                      loom_repo=tmp_path / "loomrepo",
                      loom_cmd=["python", "-m", "loom.cli", "backfill"],
                      cmd_whitelist={"teasers": {"repo": str(tmp_path / "re"),
                                                 "argv": ["python", "make.py"]}})

def test_ask_invokes_council_and_saves_output(tmp_path):
    fr = FakeRun()
    it = new_item("ask", {"question": "q?", "panel": "decision"}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {"VENICE_API_KEY": "k"},
                   deadline_epoch=10_000.0, run=fr, clock=lambda: 0.0)
    assert res.ok
    assert fr.calls[0]["argv"] == ["council", "ask", "q?", "--panel", "decision",
                                   "--format", "md"]
    assert fr.calls[0]["env"]["VENICE_API_KEY"] == "k"
    assert Path(res.output_path).read_text() == "ok-output"

def test_review_diff_runs_in_repo(tmp_path):
    fr = FakeRun()
    it = new_item("review", {"repo": "/r/swim", "diff": True}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok and fr.calls[0]["cwd"] == "/r/swim"
    assert fr.calls[0]["argv"] == ["council", "review", "--diff", "--format", "md"]

def test_review_range_pipes_git_diff_to_stdin(tmp_path):
    fr = FakeRun(results=[(0, "THE DIFF"), (0, "verdict")])
    it = new_item("review", {"repo": "/r/swim", "range": "a..b", "head": "b"},
                  created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok
    assert fr.calls[0]["argv"] == ["git", "-C", "/r/swim", "diff", "a..b"]
    assert fr.calls[1]["argv"] == ["council", "review", "-", "--format", "md"]
    assert fr.calls[1]["input"] == "THE DIFF"

def test_review_range_empty_diff_short_circuits(tmp_path):
    fr = FakeRun(results=[(0, "")])
    it = new_item("review", {"repo": "/r/swim", "range": "a..b", "head": "b"},
                  created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok and len(fr.calls) == 1  # council never called on empty diff

def test_images_payload_command_ignored(tmp_path):
    """Payload-supplied command must never be honored — argv comes solely
    from the target repo's standing order, even when a (malicious) payload
    command is present."""
    repo = tmp_path / "re"; (repo / ".diem").mkdir(parents=True)
    (repo / ".diem" / "standing-order.json").write_text(
        '{"target": 9, "candidates_dir": "c", "command": ["python", "make.py"]}')
    fr = FakeRun()
    it = new_item("images", {"repo": str(repo), "count": 5,
                             "command": ["evil"]}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok
    assert fr.calls[0]["argv"] == ["python", "make.py", "--count", "5"]
    assert fr.calls[0]["cwd"] == str(repo)

def test_backfill_uses_loom_cmd(tmp_path):
    fr = FakeRun()
    it = new_item("backfill", {"max_targets": 2}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok
    assert fr.calls[0]["argv"] == ["python", "-m", "loom.cli", "backfill",
                                   "--max-targets", "2"]

def test_cmd_requires_whitelist(tmp_path):
    fr = FakeRun()
    ok = new_item("cmd", {"name": "teasers"}, created=NOW)
    bad = new_item("cmd", {"name": "rm-rf"}, created=NOW)
    assert run_item(ok, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                    run=fr, clock=lambda: 0.0).ok
    res = run_item(bad, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert not res.ok and "whitelist" in res.error

def test_timeout_and_nonzero_are_failures_not_exceptions(tmp_path):
    it = new_item("ask", {"question": "q", "panel": "decision"}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=FakeRun(raise_timeout=True), clock=lambda: 0.0)
    assert not res.ok and "timeout" in res.error.lower()
    res2 = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                    run=FakeRun(results=[(2, "boom")]), clock=lambda: 0.0)
    assert not res2.ok and "exit 2" in res2.error

def test_images_falls_back_to_standing_order(tmp_path):
    repo = tmp_path / "re"; (repo / ".diem").mkdir(parents=True)
    (repo / ".diem" / "standing-order.json").write_text(
        '{"target": 9, "candidates_dir": "c", "command": ["python", "so.py"]}')
    fr = FakeRun()
    it = new_item("images", {"repo": str(repo), "count": 2}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=fr, clock=lambda: 0.0)
    assert res.ok and fr.calls[0]["argv"] == ["python", "so.py", "--count", "2"]

def test_images_no_command_no_standing_order_fails_cleanly(tmp_path):
    it = new_item("images", {"repo": str(tmp_path / "nowhere"), "count": 2}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=FakeRun(), clock=lambda: 0.0)
    assert not res.ok and res.error == "images item has no command and no standing order"

def test_images_standing_order_without_command_fails_cleanly(tmp_path):
    repo = tmp_path / "re"; (repo / ".diem").mkdir(parents=True)
    (repo / ".diem" / "standing-order.json").write_text('{"target": 9}')
    it = new_item("images", {"repo": str(repo), "count": 2}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=FakeRun(), clock=lambda: 0.0)
    assert not res.ok and res.error == "images item has no command and no standing order"

def test_images_string_command_rejected(tmp_path):
    it = new_item("images", {"repo": "/r", "count": 2, "command": "python x.py"}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=FakeRun(), clock=lambda: 0.0)
    assert not res.ok and "no command" in res.error

def test_images_non_dict_standing_order_fails_cleanly(tmp_path):
    repo = tmp_path / "re"; (repo / ".diem").mkdir(parents=True)
    (repo / ".diem" / "standing-order.json").write_text('["not", "a", "dict"]')
    it = new_item("images", {"repo": str(repo), "count": 2}, created=NOW)
    res = run_item(it, _cfg(tmp_path), {}, deadline_epoch=10_000.0,
                   run=FakeRun(), clock=lambda: 0.0)
    assert not res.ok and res.error == "images item has no command and no standing order"
