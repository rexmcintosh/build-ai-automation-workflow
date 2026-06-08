from loom import cli

def test_default_config_paths():
    cfg = cli.default_config()
    assert str(cfg.projects_dir).endswith(".claude/projects")
    assert str(cfg.state_path).endswith("loom/state.json")

def test_default_config_has_v1_paths():
    cfg = cli.default_config()
    assert str(cfg.wiki_worktree).endswith("wiki-loom-shadow")
    assert str(cfg.ledger_path).endswith("loom/weave_ledger.json")
    assert str(cfg.claude_dir).endswith(".claude")

def test_backfill_uses_venice_and_cap(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "absorb",
                        lambda cfg, shadow, backend, max_targets, today="", deadline_seconds=None: seen.update(
                            backend=backend, shadow=shadow, max_targets=max_targets) or {"committed": 0})
    rc = cli.main(["backfill", "--max-targets", "3"])
    assert rc == 0 and seen == {"backend": "venice", "shadow": False, "max_targets": 3}

def test_absorb_live_flag_uses_claude(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "absorb",
                        lambda cfg, shadow, backend, max_targets, today="", deadline_seconds=None: seen.update(
                            backend=backend, shadow=shadow) or {"committed": 0})
    cli.main(["absorb", "--live"])
    assert seen == {"backend": "claude", "shadow": False}

def test_promote_and_rollback_dispatch(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli, "promote", lambda **k: calls.setdefault("promote", k) or {"applied": 1})
    monkeypatch.setattr(cli, "rollback", lambda **k: calls.setdefault("rollback", k) or {"restored": 1})
    assert cli.main(["promote"]) == 0
    assert cli.main(["rollback", "--ts", "20260608T010101"]) == 0
    assert "promote" in calls and calls["rollback"]["ts"] == "20260608T010101"
