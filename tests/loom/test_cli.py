import json
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


def test_promote_auto_skips_when_gate_refuses(monkeypatch, capsys):
    """--auto must consult the gate and NOT promote when it says no."""
    called = {"promote": 0}
    monkeypatch.setattr(cli, "auto_promote_check",
                        lambda **k: {"go": False, "reason": "staged-claude",
                                     "commits": 3, "articles": [], "staged": ["x"]})
    monkeypatch.setattr(cli, "promote", lambda **k: called.update(promote=1) or {})
    rc = cli.main(["promote", "--auto"])
    assert rc == 0
    assert called["promote"] == 0                      # did NOT promote
    assert "staged-claude" in capsys.readouterr().out


def test_promote_auto_promotes_when_gate_allows(monkeypatch):
    called = {}
    monkeypatch.setattr(cli, "auto_promote_check",
                        lambda **k: {"go": True, "reason": "", "commits": 2,
                                     "articles": ["a.md"], "staged": []})
    monkeypatch.setattr(cli, "promote", lambda **k: called.update(k) or {"applied": 0})
    assert cli.main(["promote", "--auto"]) == 0
    assert called                                       # promote ran


def test_promote_without_auto_still_promotes_directly(monkeypatch):
    called = {}
    monkeypatch.setattr(cli, "promote", lambda **k: called.update(k) or {"applied": 0})
    assert cli.main(["promote"]) == 0
    assert called


def test_hold_sets_and_clears(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "set_hold", lambda d, day: seen.update(set=day))
    monkeypatch.setattr(cli, "clear_hold", lambda d: seen.update(cleared=True))
    cli.main(["hold"])
    assert "set" in seen
    cli.main(["hold", "--clear"])
    assert seen.get("cleared") is True


def test_auto_promote_output_says_what_landed(monkeypatch, capsys):
    """The briefing line is built from this JSON. Without the article list it
    would cheerfully report '0 articles landed' after a successful promote."""
    monkeypatch.setattr(cli, "auto_promote_check",
                        lambda **k: {"go": True, "reason": "", "commits": 7,
                                     "articles": ["a.md", "b.md"], "staged": [], "dirty": False})
    monkeypatch.setattr(cli, "promote", lambda **k: {"applied": 0, "ts": "T"})
    cli.main(["promote", "--auto"])
    out = json.loads(capsys.readouterr().out)
    assert out["promoted"] is True
    assert out["articles"] == ["a.md", "b.md"]
    assert out["commits"] == 7
