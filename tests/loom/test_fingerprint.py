# tests/loom/test_fingerprint.py
from loom.fingerprint import (
    learning_id, markers_in, with_markers, trailer_line, ids_from_trailers,
)

def test_learning_id_format():
    assert learning_id("sess1", 0) == "sess1#0"

def test_with_markers_is_idempotent_and_parseable():
    body = "# Liam\n\nSwims for Bullsharks.\n"
    once = with_markers(body, ["sess1#0"])
    assert markers_in(once) == {"sess1#0"}
    twice = with_markers(once, ["sess1#0", "sess2#1"])      # upsert, no dup block
    assert markers_in(twice) == {"sess1#0", "sess2#1"}
    assert twice.count("<!-- loom-woven:") == 1             # single marker block

def test_markers_in_empty_when_absent():
    assert markers_in("# Liam\n\nbody\n") == set()

def test_trailer_round_trips():
    line = trailer_line(["sess1#0", "sess2#1"])
    assert line.startswith("Loom-Woven:")
    commit_msg = f"weave: people/liam\n\n{line}\n"
    assert ids_from_trailers(commit_msg) == {"sess1#0", "sess2#1"}

def test_ids_from_trailers_handles_multiple_commits():
    blob = "weave a\n\nLoom-Woven: a#0\n\x00weave b\n\nLoom-Woven: b#1 b#2\n"
    assert ids_from_trailers(blob) == {"a#0", "b#1", "b#2"}
