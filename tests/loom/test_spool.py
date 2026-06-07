from loom.spool import spool_copy


def test_spool_copies_once_and_is_idempotent(tmp_path):
    src = tmp_path / "proj" / "a.jsonl"
    src.parent.mkdir(parents=True)
    src.write_text("data")
    spool = tmp_path / "spool"
    dest1 = spool_copy(src, spool)
    assert dest1.exists() and dest1.read_text() == "data"
    src.write_text("CHANGED")          # source mutates
    dest2 = spool_copy(src, spool)     # must NOT overwrite the immutable copy
    assert dest1 == dest2
    assert dest2.read_text() == "data"
