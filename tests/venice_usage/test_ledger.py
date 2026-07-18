from venice_usage.ledger import append, connect

def test_append_writes_one_row(tmp_path):
    db = tmp_path / "l.db"
    rid = append(project="romance", task_type="draft", model="claude-opus-4-8",
                 tokens_in=1000, tokens_out=2000, usd=0.17, source="venice-draft.sh",
                 ts="2026-07-18T10:00:00", db_path=db)
    assert rid == 1
    rows = connect(db).execute(
        "SELECT project,task_type,model,tokens_in,tokens_out,usd,source,ts FROM usage").fetchall()
    assert rows == [("romance","draft","claude-opus-4-8",1000,2000,0.17,"venice-draft.sh","2026-07-18T10:00:00")]

def test_append_creates_parent_dir_and_is_append_only(tmp_path):
    db = tmp_path / "nested" / "dir" / "l.db"
    append(project="council", task_type="review", model="m", db_path=db)
    append(project="council", task_type="ask", model="m", db_path=db)
    n = connect(db).execute("SELECT count(*) FROM usage").fetchone()[0]
    assert n == 2  # append-only, both rows retained

def test_defaults_zero_tokens_and_null_usd(tmp_path):
    db = tmp_path / "l.db"
    append(project="p", task_type="t", model="m", db_path=db)
    row = connect(db).execute("SELECT tokens_in,tokens_out,usd FROM usage").fetchone()
    assert row == (0, 0, None)  # unknown price -> NULL usd (stub estimate_usd)

def test_default_db_resolved_from_env_at_call_time(tmp_path, monkeypatch):
    # db_path omitted -> connect()/append() must resolve $VENICE_USAGE_DB LIVE, not a
    # frozen import-time snapshot. Set it AFTER import to prove call-time resolution.
    target = tmp_path / "env.db"
    monkeypatch.setenv("VENICE_USAGE_DB", str(target))
    append(project="p", task_type="t", model="m")            # no db_path
    assert target.exists()
    assert connect().execute("SELECT count(*) FROM usage").fetchone()[0] == 1

def test_auto_timestamp_is_iso_utc_second_precision(tmp_path):
    import re
    db = tmp_path / "l.db"
    append(project="p", task_type="t", model="m", db_path=db)  # ts omitted -> _utcnow_iso()
    ts = connect(db).execute("SELECT ts FROM usage").fetchone()[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts)  # UTC, second precision, no offset
