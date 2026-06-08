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
    assert LoomState(cfg.state_path).state_of("sess1") == "quarantined"

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
    assert LoomState(cfg.state_path).state_of("sess1") == "quarantined"


import subprocess
from loom.ledger import WeaveLedger

def _git(root, *a):
    subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)

def _live_cfg(tmp_path):
    projects = tmp_path / "projects"
    t = projects / "p1" / "sess1.jsonl"
    t.parent.mkdir(parents=True)
    t.write_text('{"type":"user","message":{"content":"Liam swims for Bullsharks"}}\n')
    wiki = tmp_path / "wiki"; wiki.mkdir()
    _git(wiki, "init", "-q"); _git(wiki, "config", "user.email", "t@t"); _git(wiki, "config", "user.name", "t")
    (wiki / "_index.md").write_text("# RexBrain — Master Index\n\n## People\n")
    _git(wiki, "add", "-A"); _git(wiki, "commit", "-qm", "seed"); _git(wiki, "checkout", "-qb", "loom-shadow")
    return run_mod.Config(
        projects_dir=projects,
        loom_dir=tmp_path / "loom",
        state_path=tmp_path / "loom" / "state.json",
        wiki_worktree=wiki,
        claude_dir=tmp_path / "claude",
        ledger_path=tmp_path / "loom" / "ledger.json",
    )

def test_live_run_weaves_and_commits(tmp_path, monkeypatch):
    cfg = _live_cfg(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    def fake_complete(role, system, user, json_mode=False):
        if role == "route":
            return '{"target":"people/liam.md","action":"create","cross_links":[]}'
        if role == "weave":
            return "# Liam\n\nLiam swims for the Bullsharks club.\n"
        return "- type: fact\n  subject: Liam\n  learning: swims for Bullsharks\n  route: wiki/people/liam"
    class B:
        def complete(self, role, system, user, json_mode=False):
            return fake_complete(role, system, user, json_mode)
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: B())
    summary = run_mod.absorb(cfg, shadow=False, backend="claude")
    assert summary["committed"] >= 1
    assert LoomState(cfg.state_path).state_of("sess1") == "committed"
    assert (cfg.wiki_worktree / "people" / "liam.md").exists()

def test_per_run_cap_defers_excess(tmp_path, monkeypatch):
    cfg = _live_cfg(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    def fake_complete(role, system, user, json_mode=False):
        if role == "route":
            import json as J
            subj = "a"
            for key in ("alpha", "beta", "gamma"):
                if key in user: subj = key
            return J.dumps({"target": f"people/{subj}.md", "action": "create", "cross_links": []})
        if role == "weave":
            return "# T\n\nbody.\n"
        return ("- type: fact\n  subject: alpha\n  learning: x\n  route: wiki/people/alpha\n"
                "- type: fact\n  subject: beta\n  learning: y\n  route: wiki/people/beta\n"
                "- type: fact\n  subject: gamma\n  learning: z\n  route: wiki/people/gamma\n")
    class B:
        def complete(self, role, system, user, json_mode=False):
            return fake_complete(role, system, user, json_mode)
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: B())
    summary = run_mod.absorb(cfg, shadow=False, backend="claude", max_targets=2)
    assert summary["committed"] == 2 and summary["deferred"] >= 1


def test_max_per_target_defers_overflow(tmp_path, monkeypatch):
    cfg = _live_cfg(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    def fake_complete(role, system, user, json_mode=False):
        if role == "route":
            return '{"target":"people/alpha.md","action":"create","cross_links":[]}'
        if role == "weave":
            return "# Alpha\n\nbody.\n"
        # distill: 5 learnings, all same subject -> all route to the SAME target
        return "\n".join(f"- type: fact\n  subject: alpha\n  learning: fact {i}\n  route: wiki/people/alpha"
                         for i in range(5))
    class B:
        def complete(self, role, system, user, json_mode=False):
            return fake_complete(role, system, user, json_mode)
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: B())
    summary = run_mod.absorb(cfg, shadow=False, backend="claude", max_targets=10, max_per_target=2)
    assert summary["committed"] == 2 and summary["deferred"] == 3   # 2 woven, 3 overflow deferred
    assert LoomState(cfg.state_path).state_of("sess1") == "distilled"  # not all settled -> retried


def test_distill_false_skips_distill(tmp_path, monkeypatch):
    cfg = _live_cfg(tmp_path)                 # has a pending sess1.jsonl
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    class B:
        def complete(self, role, system, user, json_mode=False):
            raise AssertionError("distill must not run when distill=False")
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: B())
    summary = run_mod.absorb(cfg, shadow=False, backend="venice", distill=False)
    assert summary["distilled"] == 0
    assert LoomState(cfg.state_path).state_of("sess1") == "pending"   # never distilled


def test_run_deadline_stops_processing(tmp_path, monkeypatch):
    cfg = _live_cfg(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    # fake clock: first reading (start) = 0; every later reading = 1000 -> deadline 5 is exceeded
    calls = {"n": 0}
    def clock():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 1000.0
    monkeypatch.setattr(run_mod.time, "monotonic", clock)
    class B:
        def complete(self, role, system, user, json_mode=False):
            return "- type: fact\n  subject: x\n  learning: y\n  route: wiki/people/x"
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: B())
    summary = run_mod.absorb(cfg, shadow=False, backend="claude", deadline_seconds=5)
    assert summary["deadline_hit"] is True
    assert summary["distilled"] == 0          # distill loop broke before processing


def test_cached_route_is_reused_not_recomputed(tmp_path, monkeypatch):
    from loom.ledger import WeaveLedger
    cfg = _live_cfg(tmp_path)
    monkeypatch.setattr(run_mod, "scan_clean", lambda p: True)
    # 1) distill sess1 -> one learning, session 'distilled', artifact written
    class D:
        def complete(self, role, system, user, json_mode=False):
            assert role == "distill"
            return "- type: fact\n  subject: x\n  learning: y\n  route: wiki/people/x"
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: D())
    run_mod.absorb(cfg, shadow=True)
    # 2) pre-seed a cached route for sess1#0 in the ledger
    WeaveLedger(cfg.ledger_path).plan("sess1#0", "people/cached.md", "create")
    # 3) weave with a backend that ASSERTS if route is recomputed -> must reuse the cached route
    class W:
        def complete(self, role, system, user, json_mode=False):
            assert role != "route", "route must not be recomputed for a cached learning"
            return "# Cached\n\nbody.\n"
    monkeypatch.setattr(run_mod, "get_backend", lambda name, api_key=None: W())
    summary = run_mod.absorb(cfg, shadow=False, backend="claude", distill=False)
    assert summary["committed"] == 1
    assert (cfg.wiki_worktree / "people" / "cached.md").exists()   # woven to the cached target
