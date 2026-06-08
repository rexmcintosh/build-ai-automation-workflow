import textwrap
import pytest
from council.config import load_panels, get_api_key, Settings, truncate

TOML = textwrap.dedent("""
[settings]
default_panel = "decision"
router_model = "rmodel"
chair_model = "cmodel"
byte_cap = 50

[panels.decision]
description = "weigh a choice"
default_rigor = "daily"
[[panels.decision.members]]
name = "Founder"
model = "m1"
system = "be a founder"
""")


def test_load_panels(tmp_path):
    f = tmp_path / "panels.toml"
    f.write_text(TOML)
    settings, panels = load_panels(f)
    assert isinstance(settings, Settings)
    assert settings.default_panel == "decision"
    assert panels["decision"].members[0].name == "Founder"
    assert panels["decision"].default_rigor == "daily"


def test_get_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "abc")
    assert get_api_key() == "abc"


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        get_api_key()


def test_truncate_keeps_head_and_tail():
    out = truncate("x" * 100, cap=20)
    assert "truncated" in out
    assert len(out.encode()) < 100


def test_real_panels_include_spec_review():
    # loads the SHIPPED council/panels.toml (no path arg)
    settings, panels = load_panels()
    assert "spec-review" in panels
    p = panels["spec-review"]
    assert [m.name for m in p.members] == [
        "Editor", "Domain Skeptic", "Implementer", "Pre-mortem Adversary"]
    assert all(m.model and m.system for m in p.members)  # no empty models/personas
