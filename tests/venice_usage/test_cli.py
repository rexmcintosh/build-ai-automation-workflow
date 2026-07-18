import json
import venice_usage.cli as cli
from venice_usage.ledger import connect

def test_log_appends_row_and_exits_zero(tmp_path, monkeypatch):
    db = tmp_path / "l.db"; monkeypatch.setenv("VENICE_USAGE_DB", str(db))
    rc = cli.main(["log", "--project", "romance", "--task-type", "draft",
                   "--model", "claude-opus-4-8", "--tokens-in", "10", "--tokens-out", "20",
                   "--source", "venice-draft.sh"])
    assert rc == 0
    assert connect(db).execute("SELECT count(*) FROM usage").fetchone()[0] == 1

def test_log_never_raises_on_bad_db(tmp_path, monkeypatch, capsys):
    # unwritable path -> still exit 0, warning on stderr
    monkeypatch.setenv("VENICE_USAGE_DB", "/proc/nonexistent/l.db")
    rc = cli.main(["log", "--project", "p", "--task-type", "t", "--model", "m"])
    assert rc == 0
    assert "venice-usage" in capsys.readouterr().err

def test_report_json_rollup(tmp_path, monkeypatch, capsys):
    db = tmp_path / "l.db"; monkeypatch.setenv("VENICE_USAGE_DB", str(db))
    cli.main(["log", "--project", "romance", "--task-type", "draft", "--model", "m", "--usd", "0.20"])
    cli.main(["log", "--project", "romance", "--task-type", "edit", "--model", "m", "--usd", "0.05"])
    rc = cli.main(["report", "--group-by", "project", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["project"] == "romance" and abs(data[0]["usd"] - 0.25) < 1e-9

def test_log_never_raises_on_malformed_arguments(tmp_path, monkeypatch, capsys):
    # A buggy call-site (missing/bad flag) must not propagate argparse's own
    # SystemExit(2) either -> still exit 0, warning on stderr. Covers the failure
    # mode test_log_never_raises_on_bad_db doesn't: parse_args() itself raising,
    # before append() (and _cmd_log's try/except) ever runs. $VENICE_USAGE_DB is
    # still isolated to tmp_path (unused on the correct/expected path, since
    # parsing fails before append() runs) so a regression can't write to the real
    # default ledger at ~/.local/state/venice-usage/ledger.db.
    monkeypatch.setenv("VENICE_USAGE_DB", str(tmp_path / "l.db"))
    rc = cli.main(["log", "--project", "p", "--task-type", "t", "--model", "m",
                   "--tokens-in", "not-a-number"])
    assert rc == 0
    assert "venice-usage" in capsys.readouterr().err

def test_log_missing_required_flag_still_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VENICE_USAGE_DB", str(tmp_path / "l.db"))
    rc = cli.main(["log", "--project", "p", "--task-type", "t"])  # --model omitted
    assert rc == 0
    assert "venice-usage" in capsys.readouterr().err
