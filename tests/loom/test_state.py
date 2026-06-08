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


def test_is_complete_only_when_committed(tmp_path):
    """Only 'committed' is fully complete; distilled/weaved must still be resumed by v1."""
    s = LoomState(tmp_path / "state.json")
    assert s.is_complete("abc") is False  # pending → not complete
    s.advance("abc", "distilled")
    assert s.is_complete("abc") is False  # distilled → NOT complete; v1 must resume
    s.advance("abc", "weaved")
    assert s.is_complete("abc") is False  # weaved → NOT complete; v1 must still commit
    s.advance("abc", "committed")
    assert s.is_complete("abc") is True   # committed → fully done


def test_unknown_state_raises(tmp_path):
    s = LoomState(tmp_path / "state.json")
    with pytest.raises(ValueError):
        s.advance("abc", "bogus")
    assert set(STATES) == {"pending", "distilled", "weaved", "committed", "quarantined"}


def test_quarantined_is_a_valid_state(tmp_path):
    s = LoomState(tmp_path / "state.json")
    s.advance("q1", "quarantined")
    assert LoomState(tmp_path / "state.json").state_of("q1") == "quarantined"


def test_quarantined_is_not_complete(tmp_path):
    s = LoomState(tmp_path / "state.json")
    s.advance("q1", "quarantined")
    assert s.is_complete("q1") is False


def test_states_set_includes_quarantined():
    assert set(STATES) == {"pending", "distilled", "weaved", "committed", "quarantined"}
