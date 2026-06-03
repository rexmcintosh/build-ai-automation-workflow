from council import cli
from council.models import Panel, Member
from council.config import Settings
from tests.conftest import FakeClient


def _env(member_json):
    settings = Settings(default_panel="decision", router_model="r", chair_model="c")
    panels = {"decision": Panel("decision", "weigh", [Member("Founder", "m1", "founder")]),
              "code-review": Panel("code-review", "review", [Member("Eng", "m1", "eng")])}
    client = FakeClient(
        by_model={"m1": member_json(stance="approve", headline="go"),
                  "r": {"panel": "decision"},
                  "c": {"recommendation": "do X", "confidence": 8, "consensus": [],
                        "disagreements": [], "cross_panel_themes": []}})
    return settings, panels, client


def test_ask_runs_and_prints_recommendation(capsys, member_json):
    settings, panels, client = _env(member_json)
    rc = cli.main(["ask", "ship X?"], _settings=settings, _panels=panels, _client=client)
    assert rc == 0
    assert "do X" in capsys.readouterr().out


def test_panels_lists_names(capsys, member_json):
    settings, panels, client = _env(member_json)
    rc = cli.main(["panels"], _settings=settings, _panels=panels, _client=client)
    assert rc == 0
    out = capsys.readouterr().out
    assert "decision" in out and "code-review" in out


def test_ask_explicit_panel_overrides_router(capsys, member_json):
    settings, panels, client = _env(member_json)
    cli.main(["ask", "x", "--panel", "code-review"], _settings=settings,
             _panels=panels, _client=client)
    # the router model "r" should never have been called
    assert all(c["model"] != "r" for c in client.calls)


def test_ask_unknown_panel_errors_friendly(capsys, member_json):
    settings, panels, client = _env(member_json)
    import pytest
    with pytest.raises(SystemExit) as exc:
        cli.main(["ask", "x", "--panel", "nope"], _settings=settings,
                 _panels=panels, _client=client)
    assert exc.value.code == 2
    assert "unknown panel" in capsys.readouterr().err


def test_panels_does_not_require_api_key(capsys, monkeypatch, tmp_path):
    # Listing panels is a local-only operation: it must work with no key set,
    # via the production path (no injected client) — the client is built lazily.
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    f = tmp_path / "panels.toml"
    f.write_text('[settings]\ndefault_panel = "decision"\n\n'
                 '[panels.decision]\ndescription = "weigh"\n'
                 '[[panels.decision.members]]\nname = "Founder"\nmodel = "m1"\nsystem = "s"\n')
    rc = cli.main(["panels", "--panels", str(f)])
    assert rc == 0
    assert "decision" in capsys.readouterr().out
