import json
from pathlib import Path
from loom import run as run_mod
from loom.state import LoomState

def _setup(tmp_path):
    projects = tmp_path / "projects"
    t = projects / "p1" / "sess1.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user","message":{"content":"Liam swims for Bullsharks"}}\n')
    cfg = run_mod.Config(
        projects_dir=projects,
        loom_dir=tmp_path / "loom",
        state_path=tmp_path / "loom" / "state.json",
    )
    return cfg

def test_shadow_run_distills_and_marks_state(tmp_path, monkeypatch):
    cfg = _setup(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)            # gate passes
    monkeypatch.setattr(run_mod.llm, "run",
                        lambda prompt, model, **k: "- type: fact\n  subject: Liam\n  learning: swims\n  route: wiki/people/liam")
    summary = run_mod.absorb(cfg, shadow=True)
    state = LoomState(cfg.state_path)
    assert state.state_of("sess1") == "distilled"           # shadow stops after distill+propose
    assert (cfg.loom_dir / "learnings" / "sess1.md").exists()
    assert summary["distilled"] == 1 and summary["quarantined"] == 0

def test_gate_hit_quarantines_and_skips(tmp_path, monkeypatch):
    cfg = _setup(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: False)           # gate fails
    called = {"llm": False}
    monkeypatch.setattr(run_mod.llm, "run", lambda *a, **k: called.__setitem__("llm", True))
    summary = run_mod.absorb(cfg, shadow=True)
    assert called["llm"] is False                                          # never fed an LLM
    assert summary["quarantined"] == 1 and summary["distilled"] == 0
    assert LoomState(cfg.state_path).state_of("sess1") == "pending"

def test_shadow_run_is_idempotent(tmp_path, monkeypatch):
    cfg = _setup(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    monkeypatch.setattr(run_mod.llm, "run", lambda prompt, model, **k: "- type: fact\n  learning: x")
    first = run_mod.absorb(cfg, shadow=True)
    second = run_mod.absorb(cfg, shadow=True)
    assert first["distilled"] == 1
    assert second["distilled"] == 0          # already distilled → skipped, not re-distilled


def test_stage2_gate_hit_leaves_no_unscanned_artifact(tmp_path, monkeypatch):
    cfg = _setup(tmp_path)
    # transcript (in projects/) passes; learnings artifact (in loom/) fails
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: "projects" in str(p))
    monkeypatch.setattr(run_mod.llm, "run", lambda prompt, model, **k: "- type: fact\n  learning: x")
    summary = run_mod.absorb(cfg, shadow=True)
    assert summary["quarantined"] == 1 and summary["distilled"] == 0
    assert not (cfg.loom_dir / "learnings" / "sess1.md").exists()      # nothing unscanned left
    assert not (cfg.loom_dir / "learnings" / "sess1.tmp").exists()     # temp cleaned up
    assert (cfg.loom_dir / "quarantine" / "sess1.md").exists()         # preserved for forensics
    assert LoomState(cfg.state_path).state_of("sess1") == "pending"
