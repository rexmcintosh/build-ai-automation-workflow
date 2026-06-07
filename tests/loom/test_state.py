import pytest
from loom.state import LoomState, STATES


def test_unknown_session_is_pending(tmp_path):
    s = LoomState(tmp_path / "state.json")
    assert s.state_of("abc") == "pending"
    assert s.is_complete("abc") is False


def test_advance_and_persist(tmp_path):
    p = tmp_path / "state.json"
    LoomState(p).advance("abc", "distilled")
    assert LoomState(p).state_of("abc") == "distilled"  # reloaded from disk


def test_is_complete_at_distilled_or_later(tmp_path):
    """v0 shadow mode ends at 'distilled'; v1 ends at 'committed'.
    Sessions at distilled/weaved/committed must all be skipped on reruns."""
    s = LoomState(tmp_path / "state.json")
    assert s.is_complete("abc") is False  # pending → not complete
    s.advance("abc", "distilled")
    assert s.is_complete("abc") is True   # distilled → complete (v0 terminal)
    s.advance("abc", "weaved")
    assert s.is_complete("abc") is True   # weaved → still complete
    s.advance("abc", "committed")
    assert s.is_complete("abc") is True   # committed → complete


def test_unknown_state_raises(tmp_path):
    s = LoomState(tmp_path / "state.json")
    with pytest.raises(ValueError):
        s.advance("abc", "bogus")
    assert set(STATES) == {"pending", "distilled", "weaved", "committed"}
