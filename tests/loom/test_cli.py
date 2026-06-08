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

def test_backfill_uses_venice_skips_distill_and_caps(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "absorb",
                        lambda cfg, **k: seen.update(k) or {"committed": 0})
    rc = cli.main(["backfill", "--max-targets", "3", "--max-per-target", "2"])
    assert rc == 0
    assert seen["backend"] == "venice" and seen["shadow"] is False
    assert seen["max_targets"] == 3 and seen["max_per_target"] == 2
    assert seen["distill"] is False          # backfill never distills

def test_absorb_live_flag_uses_claude_and_distills(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "absorb",
                        lambda cfg, **k: seen.update(k) or {"committed": 0})
    cli.main(["absorb", "--live"])
    assert seen["backend"] == "claude" and seen["shadow"] is False
    assert seen.get("distill", True) is True   # absorb distills (default)

def test_promote_and_rollback_dispatch(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli, "promote", lambda **k: calls.setdefault("promote", k) or {"applied": 1})
    monkeypatch.setattr(cli, "rollback", lambda **k: calls.setdefault("rollback", k) or {"restored": 1})
    assert cli.main(["promote"]) == 0
    assert cli.main(["rollback", "--ts", "20260608T010101"]) == 0
    assert "promote" in calls and calls["rollback"]["ts"] == "20260608T010101"
