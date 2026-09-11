from __future__ import annotations
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

def default_db() -> Path:
    # Resolve at CALL time (not import) so $VENICE_USAGE_DB set later — e.g. by a
    # test's monkeypatch.setenv — is honored.
    env = os.environ.get("VENICE_USAGE_DB")
    if env:  # absent OR empty-string -> use the default path
        return Path(env)
    return Path.home() / ".local/state/venice-usage/ledger.db"

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
  source     TEXT,
  ext_id     TEXT
);
CREATE INDEX IF NOT EXISTS ix_usage_ts ON usage(ts);
CREATE INDEX IF NOT EXISTS ix_usage_proj_task ON usage(project, task_type);
"""

# ext_id is the idempotency key for rows that arrive from somewhere else — today
# that is the CI merge gate, whose runner-local ledger is destroyed with the job
# (see venice_usage/portable.py). It is NULL for every locally-appended row, so
# the uniqueness constraint has to be partial: two identical local rows are a
# legitimate two calls, but the same CI row ingested twice is one call.
_EXT_INDEX = ('CREATE UNIQUE INDEX IF NOT EXISTS ux_usage_ext_id '
              'ON usage(ext_id) WHERE ext_id IS NOT NULL')


def _migrate(conn) -> None:
    """Add ext_id to a ledger written before this column existed. Cheap enough
    to run on every connect (one PRAGMA), and the only safe place to put it —
    callers open a fresh connection per append."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(usage)")}
    if cols and "ext_id" not in cols:
        conn.execute("ALTER TABLE usage ADD COLUMN ext_id TEXT")

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()

def connect(db_path=None) -> sqlite3.Connection:
    db = Path(db_path) if db_path else default_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.execute(_EXT_INDEX)
    conn.commit()
    return conn

def append(*, project, task_type, model, tokens_in=0, tokens_out=0,
           usd=None, source=None, ts=None, ext_id=None, db_path=None) -> int:
    """Append one usage row; returns its rowid, or 0 when an ext_id row was
    already present (INSERT OR IGNORE). ext_id makes re-ingesting the same CI
    artifact a no-op instead of double-counting the spend."""
    ts = ts or _utcnow_iso()
    if usd is None:
        from .pricing import estimate_usd
        usd = estimate_usd(model, int(tokens_in), int(tokens_out))
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO"
            " usage(ts,project,task_type,model,tokens_in,tokens_out,usd,source,ext_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (ts, project, task_type, model, int(tokens_in), int(tokens_out), usd,
             source, ext_id))
        conn.commit()
        return cur.lastrowid if cur.rowcount else 0

_GROUP_COLS = {"project", "task_type", "model", "source"}

def query_rollup(*, since=None, until=None, project=None,
                 group_by=("project", "task_type"), db_path=None) -> list[dict]:
    if isinstance(group_by, str):
        raise ValueError("group_by must be a sequence of columns, not a string")
    group_by = tuple(group_by)
    if not group_by:
        raise ValueError("group_by must name at least one column")
    bad = [c for c in group_by if c not in _GROUP_COLS]
    if bad:
        raise ValueError(f"invalid group_by column(s): {bad}")
    where, params = [], []
    if since:   where.append("ts >= ?"); params.append(since)
    if until:   where.append("ts <= ?"); params.append(until)
    if project: where.append("project = ?"); params.append(project)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    cols = ", ".join(group_by)
    sql = (f"SELECT {cols}, COUNT(*) AS calls, "
           "COALESCE(SUM(tokens_in),0) AS tokens_in, "
           "COALESCE(SUM(tokens_out),0) AS tokens_out, "
           "COALESCE(SUM(usd),0.0) AS usd "
           f"FROM usage{clause} GROUP BY {cols} ORDER BY usd DESC")
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    # SQLite SUM() over REAL accumulates binary floating-point error (e.g. 0.09+0.01
    # -> 0.09999999999999999); round to the same 6-decimal precision pricing.py's
    # estimate_usd() already uses, so aggregated usd matches cent-level expectations.
    for r in rows:
        r["usd"] = round(r["usd"], 6)
    return rows
