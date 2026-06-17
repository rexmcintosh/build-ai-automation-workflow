"""Tests for the fixit issue queue — the deterministic substrate of the fix->PR loop."""
import json

from fixit.queue import add_issue, claim_next, mark_done, mark_failed, list_pending


def test_add_then_claim_returns_the_issue(tmp_path):
    iid = add_issue(tmp_path, "Null deref in parser", "parser.py crashes on empty input")
    claimed = claim_next(tmp_path)
    assert claimed["id"] == iid
    assert claimed["title"] == "Null deref in parser"
    assert "empty input" in claimed["body"]


def test_claim_on_empty_queue_returns_none(tmp_path):
    assert claim_next(tmp_path) is None


def test_claim_removes_from_pending_no_double_claim(tmp_path):
    add_issue(tmp_path, "bug a", "x")
    first = claim_next(tmp_path)
    second = claim_next(tmp_path)
    assert first is not None
    assert second is None  # already claimed -> not handed out twice


def test_claim_is_oldest_first(tmp_path):
    a = add_issue(tmp_path, "first", "1", issue_id="0001-first")
    b = add_issue(tmp_path, "second", "2", issue_id="0002-second")
    assert claim_next(tmp_path)["id"] == a
    assert claim_next(tmp_path)["id"] == b


def test_duplicate_titles_get_distinct_ids(tmp_path):
    i1 = add_issue(tmp_path, "same title", "body one")
    i2 = add_issue(tmp_path, "same title", "body two")
    assert i1 != i2
    assert len(list_pending(tmp_path)) == 2


def test_mark_done_moves_out_of_processing(tmp_path):
    add_issue(tmp_path, "bug", "x")
    claimed = claim_next(tmp_path)
    mark_done(tmp_path, claimed["id"], result="PR #42")
    done = json.loads((tmp_path / "done" / f"{claimed['id']}.json").read_text())
    assert done["status"] == "done"
    assert done["result"] == "PR #42"


def test_mark_failed_records_error(tmp_path):
    add_issue(tmp_path, "bug", "x")
    claimed = claim_next(tmp_path)
    mark_failed(tmp_path, claimed["id"], error="tests did not pass")
    failed = json.loads((tmp_path / "failed" / f"{claimed['id']}.json").read_text())
    assert failed["status"] == "failed"
    assert "tests did not pass" in failed["error"]


def test_list_pending_excludes_claimed(tmp_path):
    add_issue(tmp_path, "a", "1")
    add_issue(tmp_path, "b", "2")
    claim_next(tmp_path)
    assert len(list_pending(tmp_path)) == 1
