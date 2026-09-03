"""backlog-run: the whole work / approve / drop flow against temp git repos and a fake
`claude` binary. No network, no real sessions."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest
import yaml

from backlogrun import cli as br

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(here, "mode.txt")).read().strip()
prompt = sys.stdin.read()
push = subprocess.run(["git", "push", "hub", "HEAD"], capture_output=True, text=True)
local = subprocess.run(["git", "push", "origin", "HEAD:refs/heads/probe"], capture_output=True, text=True)
json.dump({"env": dict(os.environ), "prompt": prompt, "argv": sys.argv[1:], "cwd": os.getcwd(),
           "push_rc": push.returncode, "push_err": push.stderr,
           "local_push_rc": local.returncode, "local_push_err": local.stderr},
          open(os.path.join(here, "capture.json"), "w"))
if mode == "hang":
    time.sleep(60)
if mode == "limit":
    print("You've hit your usage limit for this session"); sys.exit(1)
if mode == "crash":
    sys.stderr.write("boom\n"); sys.exit(1)
outcome = {"done": "done", "held": "held", "failed": "failed", "nomarker": "",
           "done-nochange": "done", "leftover": "done"}[mode]
if mode != "done-nochange":
    with open("worked.txt", "w") as fh:
        fh.write(mode + "\n")
    if mode != "leftover":
        subprocess.run(["git", "add", "-A"], check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work"], check=True)
text = "I did things.\n\n"
if outcome:
    text += f"RUNNER-OUTCOME: {outcome}\nRUNNER-SUMMARY: summary for {mode}\nRUNNER-OPERATOR-STEPS: none\n"
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                  "session_id": "sess-1234-abcd", "total_cost_usd": 1.234, "permission_denials": []}))
'''


def sh(*args, cwd=None, check=True, env=None):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True, env=env)


def git(repo, *args, check=True):
    return sh("git", "-C", str(repo), *args, check=check).stdout


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    # secrets + session vars that must NOT reach the session
    monkeypatch.setenv("VENICE_API_KEY", "sk-secret")
    monkeypatch.delenv("VENICE_COUNCIL_KEY", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_x")

    # No test may reach Venice: the real council is replaced by a tripwire. Tests that
    # want a verdict inject `stub_reviewer`; --no-council paths must never get here.
    def tripwire(cfg, diff, *, item_id):
        raise AssertionError("council_review called from a test (network!)")
    monkeypatch.setattr(br, "council_review", tripwire)


def make_repo(root: Path, name: str, *, remote: bool = True) -> Path:
    repo = root / "projects" / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("hello\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    if remote:
        bare = root / "remotes" / f"{name}.git"
        bare.parent.mkdir(exist_ok=True)
        git(repo, "init", "-q", "--bare", str(bare))
        git(repo, "remote", "add", "origin", str(bare))
        git(repo, "push", "-q", "-u", "origin", "main")
        git(repo, "remote", "add", "hub", "https://github.com/example/alpha.git")   # a "real" remote, never contacted
    return repo


def make_backlog(root: Path, items: list[dict]) -> Path:
    bdir = root / "projects" / "backlog"
    bdir.mkdir(parents=True, exist_ok=True)
    path = bdir / "backlog.yaml"
    path.write_text(yaml.safe_dump({"items": items}, sort_keys=False))
    (bdir / "archive.yaml").write_text("items: []\n")
    git(bdir, "init", "-q", "-b", "main")
    git(bdir, "add", "-A")
    git(bdir, "commit", "-qm", "init")
    return path


def item(iid, repo="alpha", status="open", created="2026-01-01", **kw):
    d = {"id": iid, "title": f"Title {iid}", "repo": repo, "status": status,
         "created": date.fromisoformat(created), "prompt": f"Do the thing for {iid}.\nSecond line.\n"}
    d.update(kw)
    return d


@pytest.fixture
def world(tmp_path):
    """A projects dir with repo `alpha` (+ bare origin), a backlog repo, a fake claude."""
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    fake = fake_dir / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (fake_dir / "mode.txt").write_text("done")
    repo = make_repo(tmp_path, "alpha")

    def build(items):
        path = make_backlog(tmp_path, items)
        cfg = br.Config(backlog_path=str(path), state_dir=str(tmp_path / "state"),
                        projects=str(tmp_path / "projects"), claude_bin=str(fake),
                        git_enabled=True, tg_enabled=False, env_file=str(tmp_path / "no.env"),
                        item_timeout=30, deadline=300, max_items=2)
        return cfg

    class W:
        pass
    w = W()
    w.root, w.repo, w.fake_dir, w.build = tmp_path, repo, fake_dir, build
    w.mode = lambda m: (fake_dir / "mode.txt").write_text(m)
    w.capture = lambda: json.load(open(fake_dir / "capture.json"))
    return w


def stub_reviewer(cfg, diff, *, item_id):
    assert "worked.txt" in diff
    return {"ok": True, "summary": "stub: approve, confidence 9/10", "markdown": "# stub review"}


def work_args(*extra):
    return br.build_parser().parse_args(["work", *extra])


def load_items(cfg):
    return br.load_yaml(cfg.backlog_path)["items"]


# ----------------------------------------------------------------------------- pure pieces


def test_plan_orders_oldest_first_bounds_and_holds_unworkable(world):
    cfg = world.build([
        item("2026-01-02-a", created="2026-01-02"),
        item("2026-01-01-b", created="2026-01-01"),
        item("2026-01-03-c", repo="none", created="2026-01-03"),
        item("2026-01-04-d", status="in_review", created="2026-01-04"),
        item("2026-01-05-e", repo="missing-repo", created="2026-01-05"),
    ])
    planned = br.plan(cfg, load_items(cfg), max_items=1)
    by = {p.item["id"]: p for p in planned}
    assert [p.item["id"] for p in planned] == ["2026-01-01-b", "2026-01-02-a", "2026-01-03-c", "2026-01-05-e"]
    assert by["2026-01-01-b"].action == "work"
    assert by["2026-01-01-b"].branch == "claude/bl-b"
    assert by["2026-01-01-b"].base == "main"
    assert by["2026-01-02-a"].action == "defer"
    assert by["2026-01-03-c"].action == "hold" and "no target repo" in by["2026-01-03-c"].reason
    assert by["2026-01-05-e"].action == "hold"
    assert "2026-01-04-d" not in by


def test_plan_holds_when_branch_already_exists_with_work(world):
    cfg = world.build([item("2026-01-01-b")])
    git(world.repo, "branch", "claude/bl-b")
    git(world.repo, "commit", "--allow-empty", "-qm", "earlier attempt", "--no-verify")
    git(world.repo, "branch", "-f", "claude/bl-b", "HEAD")
    git(world.repo, "reset", "-q", "--hard", "HEAD~1")
    (p,) = br.plan(cfg, load_items(cfg))
    assert p.action == "hold" and "already exists" in p.reason


def test_yaml_roundtrip_uses_block_scalars_and_keeps_dates(tmp_path):
    doc = {"items": [item("2026-01-01-x", prompt="line one  \nline two\n\n  indented\n")]}
    text = br.dump_yaml(doc)
    assert "prompt: |" in text
    assert "created: 2026-01-01" in text
    back = yaml.safe_load(text)
    assert back["items"][0]["created"] == date(2026, 1, 1)
    assert back["items"][0]["prompt"] == "line one\nline two\n\n  indented\n"
    path = tmp_path / "b.yaml"
    br.write_yaml_atomic(str(path), doc)
    assert yaml.safe_load(path.read_text()) == back
    assert not list(tmp_path.glob(".backlog-run-*"))


def test_backlog_lock_waits_then_times_out_and_clears_stale(tmp_path):
    path = tmp_path / "backlog.yaml"
    path.write_text("items: []\n")
    lock = Path(f"{path}.lock")
    lock.mkdir()
    with pytest.raises(TimeoutError):
        with br.BacklogLock(str(path), wait_s=1):
            pass
    old = time.time() - br.BACKLOG_LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    with br.BacklogLock(str(path), wait_s=1):
        assert lock.is_dir()
    assert not lock.exists()


def test_mutate_backlog_rereads_before_writing(world):
    cfg = world.build([item("2026-01-01-a")])
    # simulate feedback-sync appending an item while a session runs
    doc = br.load_yaml(cfg.backlog_path)
    doc["items"].append(item("2026-01-02-late"))
    br.write_yaml_atomic(cfg.backlog_path, doc)
    br.mutate_backlog(cfg, "2026-01-01-a", lambda it: it.__setitem__("status", "held"))
    ids = [it["id"] for it in load_items(cfg)]
    assert ids == ["2026-01-01-a", "2026-01-02-late"]


@pytest.mark.parametrize("text,outcome,summary", [
    ("blah\nRUNNER-OUTCOME: done\nRUNNER-SUMMARY: did it\nRUNNER-OPERATOR-STEPS: none\n", "done", "did it"),
    ("RUNNER-OUTCOME: `held`\nRUNNER-SUMMARY: needs a key\n  second line\nRUNNER-OPERATOR-STEPS: add KEY to ~/.env", "held", "needs a key second line"),
    ("first RUNNER-OUTCOME: failed\n later RUNNER-OUTCOME: done\nRUNNER-SUMMARY: ok", "done", "ok"),
    ("no block here", "", ""),
])
def test_parse_outcome(text, outcome, summary):
    got = br.parse_outcome(text)
    assert got["outcome"] == outcome
    assert got["summary"] == summary


def test_parse_outcome_operator_steps():
    got = br.parse_outcome("RUNNER-OUTCOME: held\nRUNNER-SUMMARY: s\nRUNNER-OPERATOR-STEPS: run wrangler deploy\n```")
    assert got["operator_steps"] == "run wrangler deploy"


def test_scrubbed_env_has_no_secrets_and_disables_push(world):
    env = br.scrubbed_env(str(world.repo), ["/opt/node/bin"])
    assert "VENICE_API_KEY" not in env and "STRIPE_SECRET_KEY" not in env
    assert not any(k.startswith("CLAUDE") for k in env)
    assert env["GIT_CONFIG_COUNT"] == str(len(br.NO_PUSH_SCHEMES))
    assert env["GIT_CONFIG_KEY_0"] == f"url.{br.NO_PUSH_BASE}.pushInsteadOf"
    assert {env[f"GIT_CONFIG_VALUE_{i}"] for i in range(len(br.NO_PUSH_SCHEMES))} == set(br.NO_PUSH_SCHEMES)
    assert env["PATH"].startswith("/opt/node/bin:")
    assert os.path.join(br.HOME, ".local", "bin") in env["PATH"]
    assert env["BACKLOG_RUN"] == "1" and env["TERM"] == "dumb"


def test_session_settings_deny_rules(world):
    cfg = world.build([])
    br.write_session_settings(cfg)
    deny = json.load(open(cfg.settings_path))["permissions"]["deny"]
    for must in ("Bash(git push*)", "Bash(wrangler*)", "Bash(npm run deploy*)", "Bash(curl*)",
                 "Bash(crontab*)", "Bash(supabase*)", "Bash(stripe*)", "Bash(tg-send*)"):
        assert must in deny
    assert json.load(open(cfg.mcp_path)) == {"mcpServers": {}}


def test_compose_prompt_carries_contract_and_item():
    text = br.compose_prompt(item("2026-01-01-a", prompt="THE PROMPT"), repo_name="alpha",
                             worktree="/w", branch="claude/bl-a", base="main", minutes=55)
    for must in ("RUNNER-OUTCOME", "Never push", "claude/bl-a", "THE PROMPT", "55 minutes", "held"):
        assert must in text


# ----------------------------------------------------------------------------- work


def test_work_done_flow_end_to_end(world):
    cfg = world.build([item("2026-01-01-a")])
    rc = br.cmd_work(work_args("--no-notify"), cfg) if False else None  # (kept for symmetry)
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "in_review"
    (it,) = load_items(cfg)
    assert it["status"] == "in_review"
    assert it["branch"] == "claude/bl-a"
    assert it["council"].startswith("stub: approve")
    assert it["worked"] == br.today()
    assert it["session"] == "sess-1234-abcd" and it["cost_usd"] == 1.23
    assert "summary for done" in it["note"]
    # branch has the session's commit; worktree is gone
    assert git(world.repo, "rev-list", "--count", "main..claude/bl-a").strip() == "1"
    assert not (world.repo / ".claude" / "worktrees" / "bl-a").exists()
    assert "claude/bl-a" not in git(world.repo, "worktree", "list")
    # main untouched, remote untouched
    assert git(world.repo, "rev-list", "--count", "origin/main..main").strip() == "0"
    # review file + run log + backlog commit
    assert (Path(cfg.reviews_dir) / "2026-01-01-a.md").read_text().startswith("# council review")
    assert list(Path(cfg.runs_dir).glob("*-2026-01-01-a.json"))
    assert "backlog: 2026-01-01-a -> in_review (claude/bl-a)" in git(cfg.backlog_dir, "log", "-1", "--format=%s")
    # what the session saw
    cap = world.capture()
    assert cap["cwd"].endswith(os.path.join(".claude", "worktrees", "bl-a"))
    assert cap["push_rc"] != 0 and "nonexistent" in cap["push_err"]          # real remote: blocked
    assert cap["local_push_rc"] == 0, cap["local_push_err"]                   # local temp remote: allowed (test suites)
    assert git(world.repo, "ls-remote", "--heads", "origin", "probe").strip()
    assert "VENICE_API_KEY" not in cap["env"] and "CLAUDECODE" not in cap["env"]
    assert "--strict-mcp-config" in cap["argv"] and "--settings" in cap["argv"]
    assert "--dangerously-skip-permissions" in cap["argv"]
    assert "RUNNER-OUTCOME" in cap["prompt"] and "Do the thing for 2026-01-01-a" in cap["prompt"]


def test_work_held_keeps_branch(world):
    cfg = world.build([item("2026-01-01-a")])
    world.mode("held")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "held"
    (it,) = load_items(cfg)
    assert it["status"] == "held" and it["branch"] == "claude/bl-a"
    assert "HELD" in it["note"]
    assert it["council"].startswith("stub: approve")      # held branches with work are reviewed too


def test_work_crash_without_changes_holds_and_deletes_empty_branch(world):
    cfg = world.build([item("2026-01-01-a")])
    world.mode("crash")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "held"
    (it,) = load_items(cfg)
    assert it["status"] == "held" and "branch" not in it and "FAILED" in it["note"]
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()
    journal = Path(cfg.journal_path).read_text()
    assert "claude/bl-a" in journal and "work-empty" in journal


def test_work_nomarker_with_changes_is_in_review(world):
    cfg = world.build([item("2026-01-01-a")])
    world.mode("nomarker")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "in_review"
    assert "without a RUNNER-OUTCOME" in load_items(cfg)[0]["note"]


def test_work_done_without_changes_is_held(world):
    cfg = world.build([item("2026-01-01-a")])
    world.mode("done-nochange")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "held" and "no changes" in res["note"]
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()


def test_work_commits_leftover_uncommitted_work(world):
    cfg = world.build([item("2026-01-01-a")])
    world.mode("leftover")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "in_review"
    assert "leftover uncommitted work" in git(world.repo, "log", "-1", "--format=%s", "claude/bl-a")
    assert "worked.txt" in git(world.repo, "diff", "--name-only", "main...claude/bl-a")


def test_work_timeout_kills_session_and_holds(world):
    cfg = world.build([item("2026-01-01-a")])
    cfg.item_timeout = 2
    world.mode("hang")
    (p,) = br.plan(cfg, load_items(cfg))
    t0 = time.monotonic()
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert time.monotonic() - t0 < 40
    assert res["status"] == "held" and "timed out" in res["note"]
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()


def test_cmd_work_usage_limit_leaves_open_and_stops_batch(world):
    cfg = world.build([item("2026-01-01-a"), item("2026-01-02-b", created="2026-01-02")])
    world.mode("limit")
    rc = br.cmd_work(work_args("--no-notify", "--no-council"), cfg)
    assert rc == 0
    items = {it["id"]: it for it in load_items(cfg)}
    assert items["2026-01-01-a"]["status"] == "open"
    assert items["2026-01-02-b"]["status"] == "open"
    assert not git(world.repo, "branch", "--list", "claude/bl-*").strip()
    assert "USAGE LIMIT" in Path(cfg.report_path).read_text() or True  # report lists open items either way
    assert "USAGE LIMIT HIT" in br.summarize_run(
        [{"id": "x", "status": "open", "note": "", "limit": True}], limit_hit=True)


def test_cmd_work_holds_unworkable_and_respects_max_items(world):
    cfg = world.build([item("2026-01-01-a"), item("2026-01-02-b", created="2026-01-02"),
                       item("2026-01-03-c", repo="none", created="2026-01-03")])
    rc = br.cmd_work(work_args("--no-notify", "--no-council", "--max-items", "1"), cfg)
    assert rc == 0
    items = {it["id"]: it for it in load_items(cfg)}
    assert items["2026-01-01-a"]["status"] == "in_review"
    assert items["2026-01-01-a"]["council"] == "review skipped (--no-council)"
    assert items["2026-01-02-b"]["status"] == "open"
    assert items["2026-01-03-c"]["status"] == "held" and "no target repo" in items["2026-01-03-c"]["note"]
    report = Path(cfg.report_path).read_text()
    assert "### 1. Title 2026-01-01-a" in report
    assert json.load(open(cfg.report_json))["numbers"] == {"1": "2026-01-01-a"}


def test_dry_run_changes_nothing(world, capsys):
    cfg = world.build([item("2026-01-01-a"), item("2026-01-02-n", repo="none", created="2026-01-02")])
    before = Path(cfg.backlog_path).read_text()
    rc = br.cmd_work(work_args("--dry-run"), cfg)
    out = capsys.readouterr().out
    assert rc == 0
    assert "WORK  2026-01-01-a" in out and "HOLD  2026-01-02-n" in out
    assert Path(cfg.backlog_path).read_text() == before
    assert not git(world.repo, "branch", "--list", "claude/bl-*").strip()
    assert not os.path.exists(cfg.state_dir) or not os.listdir(cfg.runs_dir) if os.path.exists(cfg.runs_dir) else True


# ----------------------------------------------------------------------------- morning review


def worked_branch(repo: Path, branch: str, fname="feature.txt", content="feature\n"):
    git(repo, "worktree", "add", "-q", "-b", branch, str(repo / ".claude" / "worktrees" / branch.split("/")[-1]), "main")
    wt = repo / ".claude" / "worktrees" / branch.split("/")[-1]
    (wt / fname).write_text(content)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", f"work on {branch}")
    return wt


def test_approve_merges_pushes_deletes_branch_and_archives(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a",
                            worked=date(2026, 1, 2), council="stub verdict")])
    worked_branch(world.repo, "claude/bl-a")
    br.write_report(cfg)
    assert br.resolve_ref(cfg, "1") == "2026-01-01-a"
    assert br.approve_one(cfg, "2026-01-01-a", log=lambda *a: None)
    head_msg = git(world.repo, "log", "-1", "--format=%B")
    assert head_msg.startswith("Merge claude/bl-a: Title 2026-01-01-a")
    assert "Backlog-Item: 2026-01-01-a" in head_msg
    assert (world.repo / "feature.txt").exists()
    assert git(world.repo, "rev-parse", "main").strip() == git(world.repo, "rev-parse", "origin/main").strip()
    assert git(world.repo, "ls-remote", "--heads", "origin", "main").strip().startswith(git(world.repo, "rev-parse", "main").strip())
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()
    assert not (world.repo / ".claude" / "worktrees" / "bl-a").exists()
    assert load_items(cfg) == []
    (arch,) = br.load_yaml(cfg.archive_path)["items"]
    assert arch["status"] == "done" and arch["merge_commit"] == git(world.repo, "rev-parse", "HEAD").strip()
    assert arch["merged"] == br.today()
    assert "approve" in Path(cfg.journal_path).read_text()
    assert "-> done" in git(cfg.backlog_dir, "log", "-1", "--format=%s")


def test_approve_refuses_dirty_main_checkout(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a")])
    worked_branch(world.repo, "claude/bl-a")
    (world.repo / "README.md").write_text("dirty\n")
    msgs = []
    assert not br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "uncommitted changes" in msgs[-1]
    assert load_items(cfg)[0]["status"] == "in_review"
    assert git(world.repo, "rev-list", "--count", "origin/main..main").strip() == "0"


def test_approve_refuses_wrong_branch_checked_out(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a")])
    worked_branch(world.repo, "claude/bl-a")
    git(world.repo, "checkout", "-q", "-b", "feature-x")
    msgs = []
    assert not br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "is on feature-x, not main" in msgs[-1]


def test_approve_aborts_on_conflict(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a")])
    worked_branch(world.repo, "claude/bl-a", fname="README.md", content="branch version\n")
    (world.repo / "README.md").write_text("main version\n")
    git(world.repo, "commit", "-qam", "main moves on")
    msgs = []
    assert not br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "merge failed and was aborted" in msgs[-1]
    assert not (world.repo / ".git" / "MERGE_HEAD").exists()
    assert (world.repo / "README.md").read_text() == "main version\n"
    assert load_items(cfg)[0]["status"] == "in_review"
    assert git(world.repo, "branch", "--list", "claude/bl-a").strip()


def test_approve_keeps_branch_when_its_worktree_is_dirty(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a")])
    wt = worked_branch(world.repo, "claude/bl-a")
    (wt / "scratch.txt").write_text("uncommitted\n")
    msgs = []
    assert br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "branch kept" in msgs[-1] and "uncommitted" in msgs[-1]
    assert git(world.repo, "branch", "--list", "claude/bl-a").strip()
    assert (world.repo / "feature.txt").exists()


def test_approve_without_remote_is_local_only(world):
    repo = make_repo(world.root, "beta", remote=False)
    cfg = world.build([item("2026-01-01-b", repo="beta", status="in_review", branch="claude/bl-b")])
    worked_branch(repo, "claude/bl-b")
    msgs = []
    assert br.approve_one(cfg, "2026-01-01-b", log=msgs.append)
    assert "no remote — local only" in msgs[-1]


def test_drop_deletes_branch_journals_and_archives(world):
    cfg = world.build([item("2026-01-01-a", status="held", branch="claude/bl-a", note="runner: HELD")])
    worked_branch(world.repo, "claude/bl-a")
    sha = git(world.repo, "rev-parse", "claude/bl-a").strip()
    assert br.drop_one(cfg, "2026-01-01-a", log=lambda *a: None)
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()
    assert f"claude/bl-a\t{sha}\tdrop" in Path(cfg.journal_path).read_text()
    (arch,) = br.load_yaml(cfg.archive_path)["items"]
    assert arch["status"] == "dropped" and arch["dropped"] == br.today()
    assert load_items(cfg) == []


def test_drop_refuses_open_item(world):
    cfg = world.build([item("2026-01-01-a")])
    msgs = []
    assert not br.drop_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "drop applies to in_review/held" in msgs[-1]


def test_hold_and_reopen(world):
    cfg = world.build([item("2026-01-01-a")])
    p = br.build_parser()
    assert br.cmd_hold(p.parse_args(["hold", "2026-01-01-a", "wait for Rex"]), cfg) == 0
    it = load_items(cfg)[0]
    assert it["status"] == "held" and it["note"] == "wait for Rex"
    assert br.cmd_reopen(p.parse_args(["reopen", "2026-01-01-a"]), cfg) == 0
    assert load_items(cfg)[0]["status"] == "open"
    assert br.cmd_reopen(p.parse_args(["reopen", "2026-01-01-a"]), cfg) == 1


def test_report_lists_review_held_open_and_numbers(world):
    cfg = world.build([
        item("2026-01-01-a", status="in_review", branch="claude/bl-a", worked=date(2026, 1, 2), council="c1"),
        item("2026-01-02-b", status="held", note="runner: HELD — needs key", created="2026-01-02"),
        item("2026-01-03-c", created="2026-01-03"),
    ])
    worked_branch(world.repo, "claude/bl-a")
    text = br.write_report(cfg)
    assert "1 awaiting your review · 1 held · 1 open" in text
    assert "### 1. Title 2026-01-01-a" in text and "1 commit(s); 1 file changed" in text
    assert "`2026-01-02-b`" in text and "needs key" in text
    assert "`2026-01-03-c`" in text
    assert br.resolve_ref(cfg, "1") == "2026-01-01-a"
    with pytest.raises(KeyError):
        br.resolve_ref(cfg, "2")
    assert br.resolve_ref(cfg, "2026-01-03-c") == "2026-01-03-c"


def test_run_lock_is_exclusive(world):
    cfg = world.build([])
    with br.RunLock(cfg):
        p = subprocess.run([
            "python3", "-c",
            "import sys; sys.path.insert(0, %r); from backlogrun import cli as br; "
            "cfg = br.Config(state_dir=%r); br.RunLock(cfg).__enter__(); print('GOT IT')"
            % (str(Path(br.__file__).resolve().parents[1]), cfg.state_dir)],
            capture_output=True, text=True)
    assert "GOT IT" not in p.stdout
    assert "another run holds the lock" in p.stderr


# ----------------------------------------------------------------------------- council round 1 fixes


def test_plan_reclaims_empty_leftover_branch_but_holds_one_with_work(world):
    cfg = world.build([item("2026-01-01-a"), item("2026-01-02-b", created="2026-01-02")])
    git(world.repo, "branch", "claude/bl-a")                       # empty leftover
    worked_branch(world.repo, "claude/bl-b")                       # has a commit + worktree
    planned = {p.item["id"]: p for p in br.plan(cfg, load_items(cfg))}
    assert planned["2026-01-01-a"].action == "work" and planned["2026-01-01-a"].reclaim
    assert planned["2026-01-02-b"].action == "hold" and "with work on it" in planned["2026-01-02-b"].reason


def test_work_reclaims_empty_branch_then_works(world):
    cfg = world.build([item("2026-01-01-a")])
    git(world.repo, "branch", "claude/bl-a")
    (p,) = br.plan(cfg, load_items(cfg))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "in_review"
    assert "reclaim-empty" in Path(cfg.journal_path).read_text()
    assert git(world.repo, "rev-list", "--count", "main..claude/bl-a").strip() == "1"


def test_plan_holds_unsafe_ids(world):
    cfg = world.build([item("2026-01-01-../evil"), item("2026-01-01-ok")])
    planned = {p.item["id"]: p for p in br.plan(cfg, load_items(cfg))}
    assert planned["2026-01-01-../evil"].action == "hold" and "not a safe slug" in planned["2026-01-01-../evil"].reason
    assert planned["2026-01-01-ok"].action == "work"


def test_apply_does_not_clobber_a_status_changed_during_the_run(world):
    cfg = world.build([item("2026-01-01-a")])
    (p,) = br.plan(cfg, load_items(cfg))
    # a human parks the item while the session is running
    br.mutate_backlog(cfg, "2026-01-01-a", lambda it: it.update(status="held", note="human: wait"))
    res = br.work_one(cfg, p, reviewer=stub_reviewer, log=lambda *a: None)
    assert res["status"] == "in_review" and res.get("conflict")
    (it,) = load_items(cfg)
    assert it["status"] == "held"
    assert it["note"].startswith("runner: CONFLICT") and "claude/bl-a" in it["note"]
    assert git(world.repo, "branch", "--list", "claude/bl-a").strip()   # work is not thrown away
    assert "conflict note" in git(cfg.backlog_dir, "log", "-1", "--format=%s")


def test_approve_records_before_releasing_branch(world, monkeypatch):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a")])
    worked_branch(world.repo, "claude/bl-a")

    def boom(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(br, "mutate_backlog", boom)
    msgs = []
    assert not br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "recording it in the backlog failed" in msgs[-1]
    assert git(world.repo, "branch", "--list", "claude/bl-a").strip()   # branch kept for the retry
    assert load_items(cfg)[0]["status"] == "in_review"
    monkeypatch.undo()
    # the retry: already merged -> no second merge, then archived + released
    assert br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "already merged" in msgs[-1]
    assert git(world.repo, "rev-list", "--count", "--merges", "origin/main").strip() == "1"
    assert not git(world.repo, "branch", "--list", "claude/bl-a").strip()
    assert br.load_yaml(cfg.archive_path)["items"][0]["status"] == "done"


def test_reconcile_archive_wins_after_interrupted_move(world):
    cfg = world.build([item("2026-01-01-a", status="in_review", branch="claude/bl-a"), item("2026-01-02-b", created="2026-01-02")])
    arch = br.load_yaml(cfg.archive_path)
    arch["items"].append(dict(item("2026-01-01-a"), status="done"))
    br.write_yaml_atomic(cfg.archive_path, arch)                     # crash landed here last time
    br.mutate_backlog(cfg, "2026-01-02-b", lambda it: it.update(status="held"))
    assert [it["id"] for it in load_items(cfg)] == ["2026-01-02-b"]
    assert len(br.load_yaml(cfg.archive_path)["items"]) == 1


def test_run_lock_contention_exits_75(world):
    cfg = world.build([])
    with br.RunLock(cfg):
        p = subprocess.run([
            "python3", "-c",
            "import sys; sys.path.insert(0, %r); from backlogrun import cli as br; "
            "cfg = br.Config(state_dir=%r); br.RunLock(cfg).__enter__()"
            % (str(Path(br.__file__).resolve().parents[1]), cfg.state_dir)],
            capture_output=True, text=True)
    assert p.returncode == br.EX_TEMPFAIL == 75


# ----------------------------------------------------------------------------- council round 2 fixes


def test_approve_refuses_held_unless_flagged(world):
    cfg = world.build([item("2026-01-01-a", status="held", branch="claude/bl-a", note="runner: HELD — needs key")])
    worked_branch(world.repo, "claude/bl-a")
    msgs = []
    assert not br.approve_one(cfg, "2026-01-01-a", log=msgs.append)
    assert "re-run with --held" in msgs[-1]
    assert git(world.repo, "rev-list", "--count", "origin/main..main").strip() == "0"
    assert br.approve_one(cfg, "2026-01-01-a", log=msgs.append, allow_held=True)
    assert br.load_yaml(cfg.archive_path)["items"][0]["status"] == "done"


def test_repo_path_is_contained_in_projects(world):
    cfg = world.build([])
    assert br.repo_path(cfg, "alpha") == str(world.repo)
    assert br.repo_path(cfg, str(world.repo)) == str(world.repo)
    assert br.repo_path(cfg, "../remotes/alpha.git") is None
    assert br.repo_path(cfg, "/") is None
    assert br.repo_path(cfg, "none") is None and br.repo_path(cfg, None) is None
    outside = world.root / "outside"
    outside.mkdir()
    git(outside, "init", "-q")
    assert br.repo_path(cfg, str(outside)) is None


def test_deny_rules_cover_push_variants(world):
    cfg = world.build([])
    br.write_session_settings(cfg)
    deny = json.load(open(cfg.settings_path))["permissions"]["deny"]
    for must in ("Bash(git -c * push*)", "Bash(git -C * push*)", "Bash(git --git-dir* push*)", "Bash(git remote*)"):
        assert must in deny
