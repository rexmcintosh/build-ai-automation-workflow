from loom.discovery import session_id_for, find_pending
from loom.state import LoomState

def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n")

def test_session_id_is_stem(tmp_path):
    assert session_id_for(tmp_path / "proj" / "abc-123.jsonl") == "abc-123"

def test_find_pending_excludes_committed(tmp_path):
    projects = tmp_path / "projects"
    _touch(projects / "p1" / "a.jsonl")
    _touch(projects / "p2" / "b.jsonl")
    state = LoomState(tmp_path / "state.json")
    state.advance("a", "committed")
    pending = find_pending(projects, state)
    assert [p.name for p in pending] == ["b.jsonl"]

def test_find_pending_excludes_quarantined(tmp_path):
    projects = tmp_path / "projects"
    _touch(projects / "p1" / "a.jsonl")
    _touch(projects / "p2" / "b.jsonl")
    state = LoomState(tmp_path / "state.json")
    state.advance("a", "quarantined")
    pending = find_pending(projects, state)
    assert [p.name for p in pending] == ["b.jsonl"]
