from __future__ import annotations
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

def default_db() -> Path:
    # Resolve at CALL time (not import) so $VENICE_USAGE_DB set later — e.g. by a
    # test's monkeypatch.setenv — is honored.
    return Path(os.environ.get(
        "VENICE_USAGE_DB", str(Path.home() / ".local/state/venice-usage/ledger.db")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT    NOT NULL,
  project    TEXT    NOT NULL,
  task_type  TEXT    NOT NULL,
  model      TEXT    NOT NULL,
  tokens_in  INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  usd        REAL,
  source     TEXT
);
CREATE INDEX IF NOT EXISTS ix_usage_ts ON usage(ts);
CREATE INDEX IF NOT EXISTS ix_usage_proj_task ON usage(project, task_type);
"""

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()

def connect(db_path=None) -> sqlite3.Connection:
    db = Path(db_path) if db_path else default_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    return conn

def append(*, project, task_type, model, tokens_in=0, tokens_out=0,
           usd=None, source=None, ts=None, db_path=None) -> int:
    ts = ts or _utcnow_iso()
    if usd is None:
        from .pricing import estimate_usd
        usd = estimate_usd(model, int(tokens_in), int(tokens_out))
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO usage(ts,project,task_type,model,tokens_in,tokens_out,usd,source)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ts, project, task_type, model, int(tokens_in), int(tokens_out), usd, source))
        conn.commit()
        return cur.lastrowid
