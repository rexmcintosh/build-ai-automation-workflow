#!/usr/bin/env python3
"""backlog-run — the 3am backlog runner + morning-review tooling.

Works `status: open` items from ~/projects/backlog/backlog.yaml unattended. Each item
runs as a COLD headless Claude Code session inside its own git worktree on a fresh
`claude/bl-<slug>` branch of the item's repo; the resulting diff is council-reviewed
and the item is left `in_review` (or `held`) for the human's morning review.

Subcommands:
  work      nightly: pick open items (oldest first, bounded), work each, review, mark.
  report    write + print the morning report (numbered, for approve/drop by number).
  list      one line per active item.
  show      item fields + saved council review + diff stat.
  diff      full diff base...branch for a worked item.
  approve   merge a worked branch into the repo's default branch, push, delete the
            branch, archive the item as done. A HUMAN command — never run by the clock.
  drop      delete a worked branch (journaled), archive the item as dropped.
  hold      open/in_review -> held (with a note).     reopen   held -> open.

Safety contract (~/projects/backlog/README.md), enforced here and tagged C1..C4:
  C1 Branch-contained. Every item is worked in its own worktree on claude/bl-<slug>.
     `work` never pushes, merges, or touches any other branch. Only `approve`, an
     explicit human command, merges and pushes.
  C2 No outward-facing or irreversible actions. The session gets: (a) a scrubbed
     environment — no secrets, no Claude-session variables; (b) `git push` disabled
     structurally (every remote's pushurl overridden via GIT_CONFIG_* env, which
     outranks all config files); (c) deny rules for push/deploy/send/spend commands,
     enforced even under --dangerously-skip-permissions (verified 2026-09-03);
     (d) no MCP servers (--strict-mcp-config with an empty config); (e) the contract in
     its prompt with a HELD escape hatch. Whatever it cannot finish inside the branch
     becomes `held` with a note — the runner never performs the outward step itself.
  C3 Every worked diff is council-reviewed (the council package, in-process, same panel
     as `council review --diff`); the verdict — or the review failure — is recorded on
     the item.
  C4 `work` only ever moves open -> in_review | held. Nothing else, ever.
Also: fail closed per item (one failure never aborts the batch); bounded (max items,
per-item timeout + budget, global deadline); one run at a time (flock); backlog.yaml is
re-read under feedback-sync's lock directory immediately before every write, so a
session-long stale copy can never clobber items appended meanwhile.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from sessiongc.cli import GitError, default_branch_ref, git, git_ok, parse_worktrees

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, "projects")
BRANCH_PREFIX = "claude/bl-"
WORKTREE_DIRNAME = ".claude/worktrees"
BACKLOG_LOCK_STALE_S = 10 * 60      # same policy as scripts/feedback-sync.ts (sat-prep)
BACKLOG_LOCK_WAIT_S = 120
ACTIVE_STATES = ("open", "in_review", "held")
TG_CHAT_DEFAULT = "7735693897"
USAGE_LIMIT_RE = re.compile(r"hit your session limit|usage limit|limit reached|rate limit",
                            re.IGNORECASE)
# Tolerant of markdown dress-up: `**RUNNER-OUTCOME:** done`, `RUNNER-OUTCOME: \`held\``, etc.
OUTCOME_RE = re.compile(r"RUNNER-OUTCOME\**:\**\s*[`*_]*(done|held|failed)", re.IGNORECASE)
SUMMARY_RE = re.compile(r"RUNNER-SUMMARY\**:?\**\s*(.*?)(?=\n\s*\**RUNNER-[A-Z-]+|\Z)", re.IGNORECASE | re.DOTALL)
STEPS_RE = re.compile(r"RUNNER-OPERATOR-STEPS\**:?\**\s*(.*?)(?=\n\s*\**RUNNER-[A-Z-]+|\n\s*```|\Z)",
                      re.IGNORECASE | re.DOTALL)

# C2(c): deny rules handed to the session via --settings. Prefix globs; each blocks a
# family of outward or irreversible commands. `git push` is ALSO blocked structurally
# (pushurl guard) — this list is the second layer and covers everything else.
DENY_RULES = [
    "Bash(git push*)", "Bash(git -C * push*)", "Bash(git -c * push*)", "Bash(git -C * -c * push*)",
    "Bash(git --git-dir* push*)", "Bash(git --work-tree* push*)",
    "Bash(git remote*)", "Bash(git -C * remote*)",
    "Bash(gh pr*)", "Bash(gh release*)", "Bash(gh repo*)", "Bash(gh api*)",
    "Bash(wrangler*)", "Bash(npx wrangler*)", "Bash(pnpm wrangler*)", "Bash(yarn wrangler*)",
    "Bash(npm run deploy*)", "Bash(pnpm run deploy*)", "Bash(pnpm deploy*)", "Bash(yarn deploy*)",
    "Bash(netlify*)", "Bash(npx netlify*)", "Bash(vercel*)", "Bash(npx vercel*)",
    "Bash(supabase*)", "Bash(npx supabase*)", "Bash(stripe*)",
    "Bash(curl*)", "Bash(wget*)", "Bash(ssh*)", "Bash(scp*)", "Bash(rsync*)",
    "Bash(crontab*)", "Bash(systemctl*)", "Bash(sudo*)", "Bash(docker*)",
    "Bash(tg-send*)", "Bash(*/tg-send*)", "Bash(mail*)", "Bash(sendmail*)",
    "Bash(pipx install*)", "Bash(pipx reinstall*)", "Bash(pipx uninstall*)",
]

# ----------------------------------------------------------------------------- config


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass
class Config:
    """Defaults are read from the environment at construction time (not import time)."""
    backlog_path: str = field(default_factory=lambda: _env("BACKLOG_PATH", os.path.join(PROJECTS, "backlog", "backlog.yaml")))
    state_dir: str = field(default_factory=lambda: _env("BACKLOG_RUN_STATE", os.path.join(PROJECTS, ".backlog-run")))
    projects: str = field(default_factory=lambda: _env("BACKLOG_RUN_PROJECTS", PROJECTS))
    claude_bin: str = field(default_factory=lambda: _env("BACKLOG_RUN_CLAUDE", ""))
    git_enabled: bool = field(default_factory=lambda: os.environ.get("BACKLOG_RUN_GIT") != "0")
    tg_enabled: bool = field(default_factory=lambda: os.environ.get("BACKLOG_RUN_TG") != "0")
    tg_chat: str = field(default_factory=lambda: _env("BACKLOG_RUN_TG_CHAT", TG_CHAT_DEFAULT))
    tg_send: str = field(default_factory=lambda: _env(
        "BACKLOG_RUN_TG_SEND", os.path.join(PROJECTS, "build-ai-automation-workflow", "bin", "tg-send")))
    env_file: str = field(default_factory=lambda: _env("BACKLOG_RUN_ENV_FILE", os.path.join(HOME, ".env")))
    model: str = ""
    budget_usd: float = 20.0
    item_timeout: int = 3600
    deadline: int = 3 * 3600
    max_items: int = 2
    keep_worktree: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def archive_path(self) -> str:
        return os.path.join(os.path.dirname(self.backlog_path), "archive.yaml")

    @property
    def backlog_dir(self) -> str:
        return os.path.dirname(self.backlog_path)

    @property
    def runs_dir(self) -> str:
        return os.path.join(self.state_dir, "runs")

    @property
    def reviews_dir(self) -> str:
        return os.path.join(self.state_dir, "reviews")

    @property
    def report_path(self) -> str:
        return os.path.join(self.state_dir, "report.md")

    @property
    def report_json(self) -> str:
        return os.path.join(self.state_dir, "report.json")

    @property
    def journal_path(self) -> str:
        return os.path.join(self.state_dir, "journal.log")

    @property
    def lock_path(self) -> str:
        return os.path.join(self.state_dir, "lock")

    @property
    def settings_path(self) -> str:
        return os.path.join(self.state_dir, "claude-settings.json")

    @property
    def mcp_path(self) -> str:
        return os.path.join(self.state_dir, "mcp-empty.json")


def ensure_state(cfg: Config) -> None:
    for d in (cfg.state_dir, cfg.runs_dir, cfg.reviews_dir):
        os.makedirs(d, exist_ok=True)


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> date:
    return datetime.now(timezone.utc).date()


EX_TEMPFAIL = 75


class RunLock:
    """One mutating command (`work`/`approve`/`drop`/`hold`/`reopen`) at a time — flock on
    the state dir. Contention exits 75 (EX_TEMPFAIL) so a skipped nightly run is visible
    in cron.log as a failure, not a silent success."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def __enter__(self):
        ensure_state(self.cfg)
        self._fh = open(self.cfg.lock_path, "w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("backlog-run: another run holds the lock; exiting (75).", file=sys.stderr)
            sys.exit(EX_TEMPFAIL)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()


# ----------------------------------------------------------------------------- backlog yaml


class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data: str):
    if "\n" in data:
        # Literal block scalars keep prompts readable (and match what /close and
        # feedback-sync append). PyYAML refuses block style for strings with a space
        # before a newline, so trailing whitespace per line is trimmed — cosmetic only.
        cleaned = "\n".join(ln.rstrip() for ln in data.split("\n"))
        return dumper.represent_scalar("tag:yaml.org,2002:str", cleaned, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_presenter)


def dump_yaml(doc: dict) -> str:
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=100, default_flow_style=False)


def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {"items": []}
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    if not isinstance(doc, dict) or not isinstance(doc.get("items", []), list):
        raise ValueError(f"{path}: expected a mapping with an `items` list")
    doc.setdefault("items", [])
    return doc


def _canon(obj):
    """What `dump_yaml` will actually preserve: multi-line strings lose trailing spaces."""
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canon(v) for v in obj]
    if isinstance(obj, str) and "\n" in obj:
        return "\n".join(ln.rstrip() for ln in obj.split("\n"))
    return obj


def write_yaml_atomic(path: str, doc: dict) -> None:
    """Dump to a sibling temp file, prove it parses back to the same data, then rename
    over the target."""
    text = dump_yaml(doc)
    if yaml.safe_load(text) != _canon(doc):
        raise ValueError(f"refusing to write {path}: dump does not round-trip")
    fd, tmp = tempfile.mkstemp(prefix=".backlog-run-", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class BacklogLock:
    """The lock DIRECTORY feedback-sync (sat-prep) uses: `<backlog.yaml>.lock`, mkdir is
    atomic, stale after 10 min. Both writers honour it, so a 03:00 feedback-sync tick
    and the runner can never interleave a read-modify-write."""

    def __init__(self, backlog_path: str, wait_s: int = BACKLOG_LOCK_WAIT_S):
        self.lock = f"{backlog_path}.lock"
        self.wait_s = wait_s

    def __enter__(self):
        deadline = time.monotonic() + self.wait_s
        while True:
            try:
                os.mkdir(self.lock)
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.stat(self.lock).st_mtime
                except FileNotFoundError:
                    continue
                if age > BACKLOG_LOCK_STALE_S:
                    shutil.rmtree(self.lock, ignore_errors=True)
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"could not acquire {self.lock} (held for {int(age)}s)")
                time.sleep(1)

    def __exit__(self, *exc):
        shutil.rmtree(self.lock, ignore_errors=True)


def find_item(doc: dict, item_id: str) -> dict | None:
    for it in doc.get("items", []):
        if it.get("id") == item_id:
            return it
    return None


def _reconcile(doc: dict, arch: dict) -> list[str]:
    """An archive move is two file writes (archive first). If a crash landed between
    them, an id is in both files; the archive wins. Returns the ids it removed."""
    archived = {it.get("id") for it in arch.get("items", [])}
    dupes = [it.get("id") for it in doc.get("items", []) if it.get("id") in archived]
    if dupes:
        doc["items"] = [it for it in doc["items"] if it.get("id") not in archived]
    return dupes


def mutate_backlog(cfg: Config, item_id: str, fn, *, archive_as: str | None = None) -> dict:
    """Lock -> re-read -> apply fn(item) -> (optionally move to archive) -> atomic write.
    Returns the updated item. The re-read is the point: never write from a stale copy.
    fn may raise to abort (nothing is written)."""
    with BacklogLock(cfg.backlog_path):
        doc = load_yaml(cfg.backlog_path)
        arch = load_yaml(cfg.archive_path)
        for dupe in _reconcile(doc, arch):
            print(f"backlog-run: {dupe} was in both files (interrupted archive move); archive wins", file=sys.stderr)
        item = find_item(doc, item_id)
        if item is None:
            raise KeyError(f"item {item_id} not found in {cfg.backlog_path}")
        fn(item)
        if archive_as:
            item["status"] = archive_as
            doc["items"] = [it for it in doc["items"] if it.get("id") != item_id]
            arch["items"].append(item)
            write_yaml_atomic(cfg.archive_path, arch)   # archive first: a crash here duplicates, never loses
        write_yaml_atomic(cfg.backlog_path, doc)
        return item


def backlog_commit(cfg: Config, message: str, *, push: bool = False) -> str:
    """Commit backlog.yaml/archive.yaml in the backlog repo. `work` never pushes (C1 —
    feedback-sync's pushIfAhead publishes it within 15 min); approve/drop, being human
    commands, may. Best-effort: a git problem is reported, never fatal."""
    if not cfg.git_enabled:
        return "git skipped (BACKLOG_RUN_GIT=0)"
    repo = cfg.backlog_dir
    if not git_ok(repo, "rev-parse", "--is-inside-work-tree"):
        return "git skipped (backlog is not a git repo)"
    try:
        git(repo, "add", "--", cfg.backlog_path, cfg.archive_path)
        if not git(repo, "status", "--porcelain", "--", cfg.backlog_path, cfg.archive_path).strip():
            return "nothing to commit"
        git(repo, "commit", "-q", "-m", message)
    except GitError as e:
        return f"git commit failed: {e}"
    if push:
        if not git_ok(repo, "push", "-q"):
            return "committed; push failed"
        return "committed + pushed"
    return "committed (push left to feedback-sync)"


# ----------------------------------------------------------------------------- items / plan


SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def slug_of(item_id: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", item_id) or item_id


def safe_slug(item_id: str) -> bool:
    """Ids come from a trusted file, but they become branch names and paths: allow only
    a plain slug (no slashes, dots-only segments, `..`, leading `-`, spaces)."""
    s = slug_of(str(item_id))
    return bool(SAFE_SLUG_RE.match(s)) and ".." not in s and not s.endswith(".lock")


def branch_for(item_id: str) -> str:
    return BRANCH_PREFIX + slug_of(item_id)


def _branch_is_empty_and_free(repo: str, branch: str, base: str) -> bool:
    """A leftover claude/bl-* branch with no commits beyond base and no worktree holds
    no work — it may be reclaimed (deleted, journaled) instead of blocking the item."""
    if any(wt.get("branch") == branch for wt in parse_worktrees(repo)):
        return False
    ahead = git(repo, "rev-list", "--count", f"{base}..{branch}", check=False).strip()
    return ahead == "0"


def repo_path(cfg: Config, repo: str | None) -> str | None:
    """`repo` -> the main checkout under the projects dir, or None. Contained: the
    resolved path must live inside the projects dir (no `..`, no absolute escapes)."""
    if not repo or str(repo).strip().lower() in ("none", "null", ""):
        return None
    repo = str(repo).strip()
    root = os.path.realpath(cfg.projects)
    path = os.path.realpath(repo if os.path.isabs(repo) else os.path.join(root, repo))
    if not path.startswith(root + os.sep):
        return None
    return path if os.path.isdir(os.path.join(path, ".git")) else None


@dataclass
class Planned:
    item: dict
    action: str            # work | hold | defer
    reason: str = ""
    repo: str = ""
    branch: str = ""
    worktree: str = ""
    base: str = ""
    reclaim: bool = False  # work, but first delete an empty leftover branch of the same name


def plan(cfg: Config, items: list[dict], *, only: list[str] | None = None,
         repo_filter: str | None = None, max_items: int | None = None) -> list[Planned]:
    """Decide what tonight's run would do, without doing it. Oldest `created` first
    (file order breaks ties). Unworkable items (no repo dir, branch/worktree already
    present) become `hold` — cheap, unbounded. Workable ones are `work` up to
    max_items; the rest are `defer` (still open, next night)."""
    max_items = cfg.max_items if max_items is None else max_items
    opens = [it for it in items if it.get("status") == "open"]
    if only:
        opens = [it for it in opens if it.get("id") in set(only)]
    if repo_filter:
        opens = [it for it in opens if str(it.get("repo")) == repo_filter]
    opens.sort(key=lambda it: str(it.get("created") or ""))
    out: list[Planned] = []
    worked = 0
    for it in opens:
        iid = str(it.get("id"))
        if not safe_slug(iid):
            out.append(Planned(it, "hold", f"id {iid!r} is not a safe slug for a branch/path; rename it"))
            continue
        rp = repo_path(cfg, it.get("repo"))
        if rp is None:
            out.append(Planned(it, "hold", f"no target repo directory for repo: {it.get('repo')!r}; needs you"))
            continue
        branch = branch_for(iid)
        wt = os.path.join(rp, WORKTREE_DIRNAME, branch[len("claude/"):])
        base = default_branch_ref(rp)
        if not base or base.startswith("origin/"):
            out.append(Planned(it, "hold", f"cannot resolve a local default branch in {os.path.basename(rp)}", repo=rp))
            continue
        reclaim = False
        if git_ok(rp, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"):
            if _branch_is_empty_and_free(rp, branch, base):
                reclaim = True
            else:
                out.append(Planned(it, "hold", f"branch {branch} already exists in {os.path.basename(rp)} with work on it (earlier attempt?)",
                                   repo=rp, branch=branch))
                continue
        if os.path.exists(wt) and not reclaim:
            out.append(Planned(it, "hold", f"worktree path already exists: {wt}", repo=rp, branch=branch, worktree=wt))
            continue
        if worked >= max_items:
            out.append(Planned(it, "defer", f"beyond --max-items {max_items}", repo=rp, branch=branch, worktree=wt, base=base))
            continue
        worked += 1
        out.append(Planned(it, "work", "reclaims an empty leftover branch first" if reclaim else "",
                           repo=rp, branch=branch, worktree=wt, base=base, reclaim=reclaim))
    return out


# ----------------------------------------------------------------------------- session


NO_PUSH_BASE = "/nonexistent/backlog-run-no-push/"
# Every scheme a real remote uses (git matches insteadOf prefixes case-sensitively, so the
# upper-case spellings are listed too). Local-path remotes (temp repos in test suites) are
# deliberately NOT rewritten, so `git push` to a tmp bare repo inside a test still works.
NO_PUSH_SCHEMES = ("https://", "http://", "git@", "ssh://", "git://",
                   "HTTPS://", "HTTP://", "GIT@", "SSH://", "GIT://")


def _is_local_remote(url: str) -> bool:
    u = url.strip()
    return u.startswith(("/", "./", "../", "~", "file://")) or (os.sep in u and "://" not in u and "@" not in u and ":" not in u.split(os.sep)[0])


def scrubbed_env(repo: str, extra_path: list[str] | None = None) -> dict:
    """C2(a)+(b): a whitelist environment for the session. No secrets from the
    parent (no *_KEY, *TOKEN*, CLAUDE*), and git pushes to real remotes disabled two
    ways: `url.<dead-path>.pushInsteadOf` for every real URL scheme (covers remotes added
    later) plus `remote.<name>.pushurl=<dead-path>` for each of the repo's own non-local
    remotes (covers any URL form). Fetches keep the real URL. Local-path remotes are left
    alone on purpose (test suites push to temp repos) — accepted risk: a production repo
    with a filesystem remote could be pushed to; none exist under ~/projects (2026-09-03).
    GIT_CONFIG_* is command-line-level config, so no config FILE can undo it (a
    `git -c remote.X.pushurl=…` could — that is what the deny rules are for)."""
    env = {
        "HOME": HOME, "USER": os.environ.get("USER", "dev"), "LOGNAME": os.environ.get("LOGNAME", os.environ.get("USER", "dev")),
        "LANG": os.environ.get("LANG", "C.UTF-8"), "LC_ALL": os.environ.get("LC_ALL", ""), "TERM": "dumb",
        "SHELL": os.environ.get("SHELL", "/bin/bash"), "TZ": os.environ.get("TZ", "UTC"),
        "BACKLOG_RUN": "1", "CI": "1",
    }
    env = {k: v for k, v in env.items() if v}
    parts = list(extra_path or [])
    for p in (os.path.join(HOME, ".local", "bin"), "/usr/local/bin", "/usr/bin", "/bin"):
        if p not in parts:
            parts.append(p)
    env["PATH"] = ":".join(parts)
    entries: list[tuple[str, str]] = [(f"url.{NO_PUSH_BASE}.pushInsteadOf", scheme) for scheme in NO_PUSH_SCHEMES]
    # Belt and braces for the repo's OWN real remotes, whatever their URL form (covers
    # scp-style `user@host:path` that is not literally git@): pushurl -> dead path.
    for name in git(repo, "remote", check=False).split():
        url = git(repo, "remote", "get-url", name, check=False).strip()
        if url and not _is_local_remote(url):
            entries.append((f"remote.{name}.pushurl", NO_PUSH_BASE.rstrip("/")))
    for n, (k, v) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{n}"] = k
        env[f"GIT_CONFIG_VALUE_{n}"] = v
    env["GIT_CONFIG_COUNT"] = str(len(entries))
    return env


def tool_path_dirs() -> list[str]:
    """Directories the session needs on PATH: where node/npm and claude actually live."""
    dirs = []
    for tool in ("node", "claude", "bun", "python3", "git"):
        found = shutil.which(tool)
        if found:
            d = os.path.dirname(os.path.realpath(found)) if tool != "claude" else os.path.dirname(found)
            if d not in dirs:
                dirs.append(d)
    return dirs


def claude_bin(cfg: Config) -> str:
    if cfg.claude_bin:
        return cfg.claude_bin
    found = shutil.which("claude")
    if found:
        return found
    for cand in (os.path.join(HOME, ".local", "bin", "claude"), "/usr/local/bin/claude"):
        if os.path.isfile(cand):
            return cand
    return "claude"


def write_session_settings(cfg: Config) -> None:
    ensure_state(cfg)
    with open(cfg.settings_path, "w") as fh:
        json.dump({"permissions": {"deny": DENY_RULES}}, fh, indent=1)
    with open(cfg.mcp_path, "w") as fh:
        json.dump({"mcpServers": {}}, fh)


def compose_prompt(item: dict, *, repo_name: str, worktree: str, branch: str, base: str,
                   minutes: int) -> str:
    return f"""You are `backlog-run`, an unattended nightly Claude Code session. Nobody is watching and nobody can answer questions. Work the backlog item below to completion on your own, or stop cleanly.

Where you are: the git worktree `{worktree}` of the repo `{repo_name}`, on branch `{branch}` (created from `{base}` for this item). This directory is yours: edit and commit here.

Rules. They are enforced by the runner and are not negotiable:
1. Work only inside this worktree. Do not modify anything outside it: not the repo's main checkout, not other repos, not ~/.claude, ~/.env, crontab, systemd units, or ~/projects/backlog.
2. Commit as you go on the current branch with clear messages. Never push, never merge into another branch, never open a PR, never create or delete other branches. `git push` is disabled; do not try to work around it.
3. No outward-facing or irreversible actions: no deploys (wrangler, netlify, vercel, `npm run deploy`, ...), no emails, Telegram, Slack or other messages, no purchases, no writes to live databases, DNS, Stripe, Supabase, Cloudflare or any external service. Reading docs and public pages is fine.
4. If finishing the item genuinely requires such an action, do every branch-contained part first (code, tests, docs, a runbook for the remaining step), then stop and report `held` with the exact remaining step.
5. Follow the repo's own CLAUDE.md and conventions. If the repo has tests or lint, run them and leave them green. Do not run interactive commands or anything that waits for input.
6. Do not ask questions. Make the sensible call, and state each assumption in your summary.
7. Keep the change scoped to the item. No drive-by refactors.
8. You have about {minutes} minutes. If you cannot finish, commit what is coherent and report `held` with what remains.
9. This is a single headless pass: when your turn ends, the session ends. Never start background tasks or agents and then stop to wait for them. Run everything in the foreground and finish in one pass.
10. The repo's human review and merge protocol does not apply here: do not post a merge recommendation, do not wait for a "do it", do not run pre-merge review steps meant for a human loop. The runner reviews the branch and a human decides in the morning.
11. Scratch files go in the system temp directory, never in the worktree. Leave no untracked files behind: anything left is committed to the branch as-is and shows up in review.

End your final message with exactly this block. The runner parses it:

RUNNER-OUTCOME: done | held | failed
RUNNER-SUMMARY: <1-3 lines: what changed, what you ran, assumptions>
RUNNER-OPERATOR-STEPS: <none, or what a human must do after merging>

Use `done` when the item is complete on this branch. Use `held` when a human decision or an outward action is required to finish. Use `failed` when you could not make useful progress; say why.

--- BACKLOG ITEM {item.get('id')} ---
Title: {item.get('title')}
Repo: {item.get('repo')}
Created: {item.get('created')}

{str(item.get('prompt') or '').rstrip()}
"""


def parse_outcome(text: str) -> dict:
    """Pull the RUNNER-* block out of the session's final message (last occurrence wins)."""
    text = text or ""
    outcomes = OUTCOME_RE.findall(text)
    outcome = outcomes[-1].lower() if outcomes else ""
    summaries = SUMMARY_RE.findall(text)
    steps = STEPS_RE.findall(text)
    clean = lambda s: re.sub(r"\s+", " ", s.strip().strip("`*_ ").strip())[:600]  # noqa: E731
    return {
        "outcome": outcome,
        "summary": clean(summaries[-1]) if summaries else "",
        "operator_steps": clean(steps[-1]) if steps else "",
    }


def run_session(cfg: Config, prompt: str, *, cwd: str, env: dict, timeout: int) -> dict:
    """Run `claude -p` cold in the worktree. Returns a dict: rc, timed_out, stdout,
    stderr, data (parsed --output-format json or None)."""
    argv = [claude_bin(cfg), "-p", "-", "--output-format", "json", "--dangerously-skip-permissions",
            "--settings", cfg.settings_path, "--strict-mcp-config", "--mcp-config", cfg.mcp_path]
    if cfg.model:
        argv += ["--model", cfg.model]
    if cfg.budget_usd and cfg.budget_usd > 0:
        argv += ["--max-budget-usd", str(cfg.budget_usd)]
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    timed_out = False
    try:
        out, err = proc.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
    data = None
    for candidate in (out or "", *reversed((out or "").splitlines())):
        candidate = candidate.strip()
        if candidate.startswith("{"):
            try:
                data = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
    return {"rc": proc.returncode, "timed_out": timed_out, "stdout": out or "", "stderr": err or "", "data": data}


# ----------------------------------------------------------------------------- council


def load_env_keys(cfg: Config, names: tuple[str, ...] = ("VENICE_COUNCIL_KEY", "VENICE_API_KEY")) -> None:
    """Cron has no ~/.env in its environment; read ONLY the Venice keys into THIS
    process (the session env is whitelisted separately and never sees them)."""
    if any(os.environ.get(n) for n in names) or not os.path.isfile(cfg.env_file):
        return
    with open(cfg.env_file, encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            if k in names and k not in os.environ:
                os.environ[k] = v.strip().strip("'\"")


def council_review(cfg: Config, diff_text: str, *, item_id: str) -> dict:
    """C3: the same code-review panel `council review --diff` runs, in-process. Returns
    {ok, summary, markdown}. Never raises — a review failure is itself the verdict."""
    try:
        load_env_keys(cfg)
        from council.config import get_api_key, load_panels, truncate
        from council.engine import run_panel
        from council.render import render_markdown
        from council.synthesize import synthesize
        from council.venice import VeniceClient
        settings, panels = load_panels(None)
        try:
            key = get_api_key()
        except SystemExit:
            return {"ok": False, "summary": "REVIEW FAILED: no Venice key (VENICE_COUNCIL_KEY/VENICE_API_KEY)", "markdown": ""}
        client = VeniceClient(key, timeout=settings.timeout)
        panel = panels["code-review"]
        ctx = truncate(f"Review this:\n\n{diff_text}", settings.byte_cap)
        results = run_panel(panel, ctx, client, task_type="chat")
        syn = synthesize(ctx, results, client, chair_model=settings.chair_model, task_type="chat")
        md = render_markdown(ctx[:120], syn, results, rigor=panel.default_rigor)
        rec = re.sub(r"\s+", " ", (syn.recommendation or "").strip())
        blocking = len(getattr(syn, "blocking_findings", []) or [])
        summary = (f"{today().isoformat()} council code-review (Venice panel): {rec[:400]}"
                   f" — confidence {syn.confidence}/10" + (f"; {blocking} blocking" if blocking else ""))
        if getattr(syn, "error", None):
            summary = f"{today().isoformat()} council code-review: synthesis unavailable ({syn.error}); see review file"
        return {"ok": True, "summary": summary, "markdown": md}
    except Exception as e:  # noqa: BLE001 — the verdict IS the failure
        return {"ok": False, "summary": f"REVIEW FAILED: {type(e).__name__}: {str(e)[:300]}", "markdown": ""}


# ----------------------------------------------------------------------------- work


def journal(cfg: Config, repo: str, branch: str, sha: str, action: str) -> None:
    ensure_state(cfg)
    with open(cfg.journal_path, "a") as fh:
        fh.write(f"{now_stamp()}\t{repo}\t{branch}\t{sha}\t{action}\n")


def _remove_worktree(repo: str, path: str) -> None:
    if os.path.exists(path):
        git(repo, "worktree", "remove", "--force", path, check=False)
    git(repo, "worktree", "prune", check=False)


def _delete_branch(cfg: Config, repo: str, branch: str, action: str) -> bool:
    sha = git(repo, "rev-parse", branch, check=False).strip()
    if not sha:
        return False
    journal(cfg, repo, branch, sha, action)
    return git_ok(repo, "branch", "-D", branch)


def work_one(cfg: Config, p: Planned, *, reviewer=None, log=print) -> dict:
    """Work one planned item end-to-end. Returns {id, status, note, ...}. Never raises."""
    # reviewer: None -> the council; False -> skipped (--no-council); callable -> injected (tests)
    if reviewer is None:
        reviewer = council_review
    item, iid = p.item, str(p.item["id"])
    result = {"id": iid, "status": "open", "note": "", "branch": "", "council": "", "cost": 0.0, "session": ""}
    started = time.monotonic()
    ensure_state(cfg)
    if not (os.path.exists(cfg.settings_path) and os.path.exists(cfg.mcp_path)):
        write_session_settings(cfg)
    try:
        git(p.repo, "worktree", "prune", check=False)
        if p.reclaim:
            _remove_worktree(p.repo, p.worktree)
            if not _delete_branch(cfg, p.repo, p.branch, "reclaim-empty"):
                raise GitError(f"could not reclaim empty leftover branch {p.branch}")
        git(p.repo, "worktree", "add", "-q", "-b", p.branch, p.worktree, p.base)
    except GitError as e:
        result.update(status="held", note=f"runner: could not create worktree/branch: {e}")
        _apply(cfg, result)
        return result
    try:
        env = scrubbed_env(p.repo, tool_path_dirs())
        prompt = compose_prompt(item, repo_name=os.path.basename(p.repo), worktree=p.worktree,
                                branch=p.branch, base=p.base, minutes=max(5, cfg.item_timeout // 60 - 5))
        log(f"  session: {p.branch} in {p.worktree} (timeout {cfg.item_timeout}s)")
        run = run_session(cfg, prompt, cwd=p.worktree, env=env, timeout=cfg.item_timeout)
        stamp = now_stamp().replace(":", "")
        with open(os.path.join(cfg.runs_dir, f"{stamp}-{iid}.json"), "w") as fh:
            json.dump({"argv_note": "claude -p (json)", "rc": run["rc"], "timed_out": run["timed_out"],
                       "data": run["data"], "stderr": run["stderr"][-20000:],
                       "stdout_tail": run["stdout"][-20000:] if run["data"] is None else ""}, fh, indent=1)
        data = run["data"] or {}
        result["session"] = str(data.get("session_id") or "")
        try:
            result["cost"] = round(float(data.get("total_cost_usd") or 0.0), 2)
        except (TypeError, ValueError):
            result["cost"] = 0.0
        final_text = str(data.get("result") or "")
        parsed = parse_outcome(final_text)
        denials = data.get("permission_denials") or []
        blob = "\n".join([run["stdout"][-4000:], run["stderr"][-4000:], final_text[-4000:]])

        # leftover uncommitted work -> commit it so the branch holds everything, and say so
        leftover = [ln[3:] for ln in git(p.worktree, "status", "--porcelain", check=False).splitlines() if ln.strip()]
        leftover_note = ""
        if leftover:
            git(p.worktree, "add", "-A", check=False)
            git(p.worktree, "-c", "user.name=backlog-run", "-c", "user.email=backlog-run@localhost",
                "commit", "-q", "-m", f"backlog-run: leftover uncommitted work for {iid}", check=False)
            shown = ", ".join(leftover[:5]) + (f" … +{len(leftover) - 5}" if len(leftover) > 5 else "")
            leftover_note = f" Leftover uncommitted files were committed as-is ({len(leftover)}): {shown}."
        ahead = git(p.repo, "rev-list", "--count", f"{p.base}..{p.branch}", check=False).strip()
        has_diff = ahead.isdigit() and int(ahead) > 0
        mins = int((time.monotonic() - started) // 60)
        tail = f" [{mins} min, ${result['cost']:.2f}, session {result['session'][:8]}]" if result["session"] else f" [{mins} min]"
        denial_note = (f" Denied tool calls: {len(denials)}." if denials else "") + leftover_note

        if run["timed_out"]:
            kind, why = "failed", f"timed out after {cfg.item_timeout}s"
        elif run["rc"] != 0 or data.get("is_error"):
            if USAGE_LIMIT_RE.search(blob):
                kind, why = "limit", "Claude usage limit hit"
            else:
                kind, why = "failed", f"claude exited {run['rc']}: {(run['stderr'] or final_text)[-300:].strip()}"
        elif parsed["outcome"] in ("done", "held", "failed"):
            kind, why = parsed["outcome"], parsed["summary"]
        else:
            kind, why = "nomarker", ("session ended without a RUNNER-OUTCOME block (its last words: "
                                     + re.sub(r"\s+", " ", final_text.strip())[:160] + ")")

        if kind == "limit":
            if has_diff:
                result.update(status="held", branch=p.branch,
                              note=f"runner: usage limit hit mid-work; partial work is on the branch.{tail}")
            else:
                result.update(status="open", note="runner: usage limit hit before any work; left open")
            result["limit"] = True
        elif kind in ("failed",):
            if has_diff:
                result.update(status="held", branch=p.branch, note=f"runner: FAILED — {why}. Partial work kept on the branch.{denial_note}{tail}")
            else:
                result.update(status="held", note=f"runner: FAILED — {why}. No changes produced.{denial_note}{tail}")
        elif kind == "held":
            steps = f" Remaining: {parsed['operator_steps']}" if parsed["operator_steps"] and parsed["operator_steps"].lower() != "none" else ""
            if has_diff:
                result.update(status="held", branch=p.branch, note=f"runner: HELD — {why}{steps}{denial_note}{tail}")
            else:
                result.update(status="held", note=f"runner: HELD (no changes) — {why}{steps}{denial_note}{tail}")
        elif kind == "nomarker":
            if has_diff:
                result.update(status="in_review", branch=p.branch, note=f"runner: {why}; branch has changes, treating as done.{denial_note}{tail}")
            else:
                result.update(status="held", note=f"runner: {why} and produced no changes.{denial_note}{tail}")
        else:  # done
            if has_diff:
                steps = f" Operator steps after merge: {parsed['operator_steps']}" if parsed["operator_steps"] and parsed["operator_steps"].lower() != "none" else ""
                result.update(status="in_review", branch=p.branch, note=f"runner: {why}{steps}{denial_note}{tail}")
            else:
                result.update(status="held", note=f"runner: reported done but produced no changes — {why}{denial_note}{tail}")

        # C3: every branch that carries work is reviewed — held ones too, so a partial
        # branch you later decide to take has a verdict on record.
        if result.get("branch"):
            diff_text = git(p.repo, "diff", f"{p.base}...{p.branch}", check=False)
            if reviewer is False:
                result["council"] = "review skipped (--no-council)"
            else:
                log("  council review ...")
                rev = reviewer(cfg, diff_text, item_id=iid)
                result["council"] = rev["summary"]
                if rev.get("markdown"):
                    with open(os.path.join(cfg.reviews_dir, f"{iid}.md"), "w") as fh:
                        fh.write(f"# council review — {iid} — {now_stamp()}\n\n{rev['markdown']}\n")
    except Exception as e:  # noqa: BLE001 — fail closed per item
        result.update(status="held", note=f"runner: internal error: {type(e).__name__}: {str(e)[:300]}")
        if git_ok(p.repo, "rev-list", "--count", f"{p.base}..{p.branch}") and \
                git(p.repo, "rev-list", "--count", f"{p.base}..{p.branch}", check=False).strip() not in ("", "0"):
            result["branch"] = p.branch
    finally:
        if not cfg.keep_worktree:
            _remove_worktree(p.repo, p.worktree)
        if not result["branch"]:
            if git_ok(p.repo, "show-ref", "--verify", "--quiet", f"refs/heads/{p.branch}") and \
                    not _delete_branch(cfg, p.repo, p.branch, "work-empty"):
                # not fatal: plan() reclaims an empty, worktree-less branch next run
                result["note"] += f" (empty branch {p.branch} could not be deleted; reclaimed next run)"
    _apply(cfg, result)
    return result


def _apply(cfg: Config, result: dict) -> None:
    """C4: write the item's new state (open stays open). Re-reads under the lock, and
    only transitions an item that is STILL `open` — if a human (or another tool) moved
    it during the session, their state wins and the run's result is recorded as a
    conflict note instead."""
    if result["status"] == "open":
        return

    def fn(item: dict):
        current = item.get("status")
        if current != "open":
            item["note"] = (f"runner: CONFLICT — the run finished with {result['status']} but the item is "
                            f"now {current} (changed during the run); left as is."
                            + (f" Work is on branch {result['branch']}." if result.get("branch") else "")
                            + f" Run said: {result['note'][:300]}")
            result["conflict"] = True
            return
        item["status"] = result["status"]
        if result.get("branch"):
            item["branch"] = result["branch"]
        else:
            item.pop("branch", None)
        if result.get("council"):
            item["council"] = result["council"]
        item["worked"] = today()
        item["note"] = result["note"]
        if result.get("session"):
            item["session"] = result["session"]
        if result.get("cost"):
            item["cost_usd"] = result["cost"]
    try:
        mutate_backlog(cfg, result["id"], fn)
        br = f" ({result['branch']})" if result.get("branch") else ""
        what = "conflict note" if result.get("conflict") else result["status"]
        result["git"] = backlog_commit(cfg, f"backlog: {result['id']} -> {what}{br}")
    except Exception as e:  # noqa: BLE001
        result["git"] = f"backlog update failed: {e}"
        print(f"backlog-run: could not update {result['id']}: {e}", file=sys.stderr)


def notify(cfg: Config, text: str) -> str:
    if not cfg.tg_enabled:
        return "telegram skipped (BACKLOG_RUN_TG=0)"
    if not os.path.isfile(cfg.tg_send):
        return f"telegram skipped ({cfg.tg_send} missing)"
    try:
        p = subprocess.run([cfg.tg_send, cfg.tg_chat, "-"], input=text, capture_output=True, text=True, timeout=90)
        return "telegram sent" if p.returncode == 0 else f"telegram failed: {p.stderr.strip()[:200]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"telegram failed: {e}"


def cmd_work(args, cfg: Config) -> int:
    items = load_yaml(cfg.backlog_path)["items"]
    planned = plan(cfg, items, only=args.only, repo_filter=args.repo, max_items=args.max_items)
    if args.dry_run:
        print(f"backlog-run dry-run — {now_stamp()} — max {cfg.max_items} item(s), {cfg.item_timeout}s each, deadline {cfg.deadline}s")
        if not planned:
            print("nothing open.")
        for p in planned:
            iid = p.item["id"]
            if p.action == "work":
                extra = f"  ({p.reason})" if p.reason else ""
                print(f"  WORK  {iid}{extra}\n        repo {os.path.basename(p.repo)}  branch {p.branch}  from {p.base}\n        worktree {p.worktree}")
            elif p.action == "hold":
                print(f"  HOLD  {iid}  — {p.reason}")
            else:
                print(f"  DEFER {iid}  — {p.reason}")
        return 0

    with RunLock(cfg):
        ensure_state(cfg)
        write_session_settings(cfg)
        start = time.monotonic()
        print(f"backlog-run work — {now_stamp()} — {sum(1 for p in planned if p.action == 'work')} to work, "
              f"{sum(1 for p in planned if p.action == 'hold')} to hold, {sum(1 for p in planned if p.action == 'defer')} deferred")
        results: list[dict] = []
        limit_hit = False
        for p in planned:
            iid = p.item["id"]
            if p.action == "hold":
                res = {"id": iid, "status": "held", "note": f"runner: {p.reason}", "branch": "", "council": "", "cost": 0.0, "session": ""}
                _apply(cfg, res)
                results.append(res)
                print(f"- HELD  {iid}: {p.reason}")
                continue
            if p.action == "defer":
                results.append({"id": iid, "status": "open", "note": p.reason, "deferred": True})
                continue
            if limit_hit:
                results.append({"id": iid, "status": "open", "note": "usage limit hit earlier tonight", "deferred": True})
                continue
            elapsed = time.monotonic() - start
            if elapsed + cfg.item_timeout > cfg.deadline:
                results.append({"id": iid, "status": "open", "note": "deadline: not enough time left tonight", "deferred": True})
                print(f"- DEFER {iid}: deadline")
                continue
            print(f"- WORK  {iid}")
            res = work_one(cfg, p, reviewer=(False if args.no_council else None))
            results.append(res)
            if res.get("limit"):
                limit_hit = True
            print(f"  -> {res['status']}: {res['note'][:200]}" + (f"\n     council: {res['council'][:200]}" if res.get("council") else ""))
        write_report(cfg)
        summary = summarize_run(results, limit_hit=limit_hit)
        print(summary)
        print(notify(cfg, summary))
    return 0


def summarize_run(results: list[dict], *, limit_hit: bool = False) -> str:
    counts = {"in_review": 0, "held": 0, "deferred": 0, "open": 0}
    lines = []
    for r in results:
        if r.get("deferred"):
            counts["deferred"] += 1
            continue
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        tag = {"in_review": "REVIEW", "held": "HELD", "open": "OPEN"}.get(r["status"], r["status"].upper())
        line = f"- {tag} {r['id']}"
        if r.get("cost"):
            line += f" (${r['cost']:.2f})"
        if r.get("council"):
            line += f"\n  council: {r['council'][:220]}"
        elif r.get("note"):
            line += f"\n  {r['note'][:220]}"
        lines.append(line)
    head = (f"backlog-run {today().isoformat()}: {counts['in_review']} in review, {counts['held']} held, "
            f"{counts['deferred']} deferred" + (" — USAGE LIMIT HIT" if limit_hit else ""))
    body = "\n".join(lines) if lines else "nothing worked tonight."
    return f"{head}\n{body}\nMorning: backlog-run report"


# ----------------------------------------------------------------------------- report / list / show


def _diff_stat(cfg: Config, item: dict) -> str:
    rp = repo_path(cfg, item.get("repo"))
    br = item.get("branch")
    if not rp or not br:
        return "(no branch)"
    if not git_ok(rp, "show-ref", "--verify", "--quiet", f"refs/heads/{br}"):
        return f"(branch {br} missing)"
    base = default_branch_ref(rp) or "HEAD"
    stat = git(rp, "diff", "--shortstat", f"{base}...{br}", check=False).strip()
    ahead = git(rp, "rev-list", "--count", f"{base}..{br}", check=False).strip()
    return f"{ahead} commit(s); {stat or 'no file changes'}"


def write_report(cfg: Config) -> str:
    ensure_state(cfg)
    items = load_yaml(cfg.backlog_path)["items"]
    review = [it for it in items if it.get("status") == "in_review"]
    held = [it for it in items if it.get("status") == "held"]
    opens = [it for it in items if it.get("status") == "open"]
    review.sort(key=lambda it: (str(it.get("worked") or ""), str(it.get("id"))))
    lines = [f"# backlog-run morning report — {now_stamp()}", "",
             f"{len(review)} awaiting your review · {len(held)} held · {len(opens)} open", ""]
    mapping = {}
    if review:
        lines.append("## Awaiting review (approve = merge + push + delete branch; drop = delete branch)")
        lines.append("")
    for n, it in enumerate(review, 1):
        mapping[str(n)] = it["id"]
        lines.append(f"### {n}. {it.get('title')}")
        lines.append(f"- id: `{it['id']}`  repo: `{it.get('repo')}`  branch: `{it.get('branch')}`  worked: {it.get('worked')}")
        lines.append(f"- diff: {_diff_stat(cfg, it)}")
        if it.get("note"):
            lines.append(f"- note: {it['note']}")
        if it.get("council"):
            lines.append(f"- council: {it['council']}")
        if it.get("session"):
            lines.append(f"- session: `{it['session']}`  cost: ${it.get('cost_usd', 0)}")
        lines.append(f"- `backlog-run show {n}` · `backlog-run diff {n}` · `backlog-run approve {n}` · `backlog-run drop {n}`")
        lines.append("")
    if held:
        lines.append("## Held (needs you)")
        for it in held:
            br = f"  branch `{it['branch']}`" if it.get("branch") else ""
            lines.append(f"- `{it['id']}` — {it.get('title')}{br}")
            if it.get("note"):
                lines.append(f"  - {it['note']}")
        lines.append("")
    lines.append(f"## Open ({len(opens)})")
    for it in sorted(opens, key=lambda x: str(x.get("created") or "")):
        lines.append(f"- `{it['id']}` ({it.get('repo')}) — {it.get('title')}")
    lines.append("")
    lines.append("Numbers refer to this report; ids always work. `backlog-run reopen <id>` returns a held item to the queue.")
    text = "\n".join(lines)
    with open(cfg.report_path, "w") as fh:
        fh.write(text + "\n")
    with open(cfg.report_json, "w") as fh:
        json.dump({"written": now_stamp(), "numbers": mapping}, fh, indent=1)
    return text


def resolve_ref(cfg: Config, token: str) -> str:
    """A report number ('1') or an item id."""
    if token.isdigit():
        if not os.path.exists(cfg.report_json):
            raise KeyError("no report yet — run `backlog-run report` first, or use the item id")
        with open(cfg.report_json) as fh:
            mapping = json.load(fh).get("numbers", {})
        if token not in mapping:
            raise KeyError(f"number {token} is not in the last report ({cfg.report_path})")
        return mapping[token]
    return token


def cmd_report(args, cfg: Config) -> int:
    print(write_report(cfg))
    return 0


def cmd_list(args, cfg: Config) -> int:
    items = load_yaml(cfg.backlog_path)["items"]
    for st in ACTIVE_STATES:
        for it in items:
            if it.get("status") == st:
                br = f"  {it['branch']}" if it.get("branch") else ""
                print(f"{st:10} {str(it.get('created')):10} {str(it.get('repo'))[:28]:28} {it['id']}{br}")
    return 0


def cmd_show(args, cfg: Config) -> int:
    iid = resolve_ref(cfg, args.item)
    it = find_item(load_yaml(cfg.backlog_path), iid) or find_item(load_yaml(cfg.archive_path), iid)
    if not it:
        print(f"backlog-run: no item {iid}", file=sys.stderr)
        return 1
    for k, v in it.items():
        if k == "prompt":
            continue
        print(f"{k}: {v}")
    print(f"diff: {_diff_stat(cfg, it)}")
    print("\n--- prompt ---\n" + str(it.get("prompt") or "").rstrip())
    rev = os.path.join(cfg.reviews_dir, f"{iid}.md")
    if os.path.exists(rev):
        print("\n--- council review ---")
        with open(rev) as fh:
            sys.stdout.write(fh.read())
    return 0


def cmd_diff(args, cfg: Config) -> int:
    iid = resolve_ref(cfg, args.item)
    it = find_item(load_yaml(cfg.backlog_path), iid)
    if not it:
        print(f"backlog-run: no active item {iid}", file=sys.stderr)
        return 1
    rp, br = repo_path(cfg, it.get("repo")), it.get("branch")
    if not rp or not br:
        print("backlog-run: item has no repo/branch", file=sys.stderr)
        return 1
    base = default_branch_ref(rp) or "HEAD"
    sys.stdout.write(git(rp, "diff", f"{base}...{br}", check=False))
    return 0


# ----------------------------------------------------------------------------- approve / drop / hold / reopen


def _worktree_for_branch(repo: str, branch: str) -> dict | None:
    for wt in parse_worktrees(repo):
        if wt.get("branch") == branch:
            return wt
    return None


def _release_branch(cfg: Config, repo: str, branch: str, *, force: bool, action: str) -> str:
    """Delete a worked branch, first removing its session worktree when that is safe.
    Returns a one-line outcome; never raises."""
    wt = _worktree_for_branch(repo, branch)
    if wt:
        path = wt["path"]
        if WORKTREE_DIRNAME not in path:
            return f"branch kept: checked out in a non-session worktree {path}"
        if git(path, "status", "--porcelain", check=False).strip():
            return f"branch kept: its worktree {path} has uncommitted changes"
        _remove_worktree(repo, path)
    sha = git(repo, "rev-parse", branch, check=False).strip()
    if not sha:
        return "branch already gone"
    journal(cfg, repo, branch, sha, action)
    flag = "-D" if force else "-d"
    if git_ok(repo, "branch", flag, branch):
        return f"branch deleted ({sha[:10]} journaled)"
    return f"branch kept: git branch {flag} refused"


def approve_one(cfg: Config, iid: str, *, log=print, allow_held: bool = False) -> bool:
    doc = load_yaml(cfg.backlog_path)
    it = find_item(doc, iid)
    if not it:
        log(f"approve {iid}: not an active item"); return False
    if not it.get("branch"):
        log(f"approve {iid}: has no branch to merge"); return False
    if it.get("status") == "held" and not allow_held:
        log(f"approve {iid}: is held ({str(it.get('note') or '')[:120]}); read its note and council line, then re-run with --held to merge it anyway"); return False
    if it.get("status") not in ("in_review", "held"):
        log(f"approve {iid}: status {it.get('status')} — only in_review items (or held with --held) can be approved"); return False
    rp, br = repo_path(cfg, it.get("repo")), it["branch"]
    if not rp:
        log(f"approve {iid}: repo {it.get('repo')!r} not found"); return False
    if not git_ok(rp, "show-ref", "--verify", "--quiet", f"refs/heads/{br}"):
        log(f"approve {iid}: branch {br} does not exist in {rp}"); return False
    base = default_branch_ref(rp)
    if not base or base.startswith("origin/"):
        log(f"approve {iid}: cannot resolve a local default branch in {rp}"); return False
    head = git(rp, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).strip()
    if head != base:
        log(f"approve {iid}: main checkout of {os.path.basename(rp)} is on {head or 'detached HEAD'}, not {base}; switch it first"); return False
    if git(rp, "status", "--porcelain", check=False).strip():
        log(f"approve {iid}: main checkout of {os.path.basename(rp)} has uncommitted changes; commit or stash first"); return False
    msg = (f"Merge {br}: {it.get('title')}\n\nBacklog item {iid} (worked {it.get('worked')}, approved {today().isoformat()}).\n"
           f"Council: {str(it.get('council') or '')[:500]}\n\nBacklog-Item: {iid}\nBacklog-Branch: {br}\n")
    # Idempotent: a re-run after a failed push/archive must not merge twice.
    if git_ok(rp, "merge-base", "--is-ancestor", br, base):
        merged = "already merged"
    else:
        try:
            git(rp, "merge", "--no-ff", "--no-edit", "-m", msg, br)
        except GitError as e:
            git(rp, "merge", "--abort", check=False)
            log(f"approve {iid}: merge failed and was aborted — {e}"); return False
        merged = "merged"
    merge_sha = git(rp, "rev-parse", "HEAD").strip()
    pushed = "no remote — local only"
    if git_ok(rp, "remote", "get-url", "origin"):
        if git_ok(rp, "push", "origin", base):
            pushed = f"pushed origin/{base}"
        else:
            log(f"approve {iid}: {merged} locally as {merge_sha[:10]} but `git push origin {base}` FAILED; "
                f"fix the push, then re-run approve (safe to repeat)")
            return False

    # Record the outcome BEFORE deleting the branch: if this fails the item stays
    # in_review with its branch intact and approve can simply be re-run.
    def fn(item: dict):
        item["merged"] = today()
        item["merge_commit"] = merge_sha
    try:
        mutate_backlog(cfg, iid, fn, archive_as="done")
    except Exception as e:  # noqa: BLE001
        log(f"approve {iid}: {merged} + {pushed}, but recording it in the backlog failed ({e}); branch kept — re-run approve")
        return False
    g = backlog_commit(cfg, f"backlog: {iid} -> done ({br} merged {merge_sha[:10]})", push=True)
    released = _release_branch(cfg, rp, br, force=False, action="approve")
    log(f"approve {iid}: {merged} {br} into {base} as {merge_sha[:10]}; {pushed}; {released}; backlog {g}")
    return True


def drop_one(cfg: Config, iid: str, *, log=print) -> bool:
    doc = load_yaml(cfg.backlog_path)
    it = find_item(doc, iid)
    if not it:
        log(f"drop {iid}: not an active item"); return False
    if it.get("status") not in ("in_review", "held"):
        log(f"drop {iid}: status {it.get('status')} — drop applies to in_review/held items"); return False
    released = "no branch"
    rp, br = repo_path(cfg, it.get("repo")), it.get("branch")
    if rp and br:
        wt = _worktree_for_branch(rp, br)
        if wt and git(wt["path"], "status", "--porcelain", check=False).strip():
            log(f"drop {iid}: its worktree {wt['path']} has uncommitted changes; item left as is"); return False

    def fn(item: dict):
        item["dropped"] = today()
    mutate_backlog(cfg, iid, fn, archive_as="dropped")   # record first, then delete (journaled)
    if rp and br:
        released = _release_branch(cfg, rp, br, force=True, action="drop")
    g = backlog_commit(cfg, f"backlog: {iid} -> dropped", push=True)
    log(f"drop {iid}: {released}; backlog {g}")
    return True


def cmd_approve(args, cfg: Config) -> int:
    ok = True
    with RunLock(cfg):
        for tok in args.items:
            try:
                iid = resolve_ref(cfg, tok)
            except KeyError as e:
                print(f"approve {tok}: {e}"); ok = False; continue
            ok = approve_one(cfg, iid, allow_held=args.held) and ok
        write_report(cfg)
    return 0 if ok else 1


def cmd_drop(args, cfg: Config) -> int:
    ok = True
    with RunLock(cfg):
        for tok in args.items:
            try:
                iid = resolve_ref(cfg, tok)
            except KeyError as e:
                print(f"drop {tok}: {e}"); ok = False; continue
            ok = drop_one(cfg, iid) and ok
        write_report(cfg)
    return 0 if ok else 1


def cmd_hold(args, cfg: Config) -> int:
    iid = resolve_ref(cfg, args.item)

    def fn(item: dict):
        if item.get("status") not in ("open", "in_review"):
            raise ValueError(f"{iid} is {item.get('status')}, not open/in_review")
        item["status"] = "held"
        item["note"] = args.note
    with RunLock(cfg):
        try:
            mutate_backlog(cfg, iid, fn)
        except (KeyError, ValueError) as e:
            print(f"hold: {e}", file=sys.stderr); return 1
        print(f"hold {iid}: held — {backlog_commit(cfg, f'backlog: {iid} -> held', push=True)}")
    return 0


def cmd_reopen(args, cfg: Config) -> int:
    iid = resolve_ref(cfg, args.item)

    def fn(item: dict):
        if item.get("status") != "held":
            raise ValueError(f"{iid} is {item.get('status')}, not held")
        item["status"] = "open"
        item.pop("worked", None)
        if str(item.get("note", "")).startswith("runner:"):
            item.pop("note", None)
    with RunLock(cfg):
        try:
            mutate_backlog(cfg, iid, fn)
        except (KeyError, ValueError) as e:
            print(f"reopen: {e}", file=sys.stderr); return 1
        print(f"reopen {iid}: open — {backlog_commit(cfg, f'backlog: {iid} -> open (reopened)', push=True)}")
    return 0


# ----------------------------------------------------------------------------- entry


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backlog-run", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("work", help="work open items unattended (nightly)")
    w.add_argument("--dry-run", action="store_true", help="show the plan; change nothing")
    w.add_argument("--max-items", type=int, default=None, help="items to work tonight (default 2)")
    w.add_argument("--only", action="append", help="work only this item id (repeatable)")
    w.add_argument("--repo", help="limit to items targeting this repo (dir name)")
    w.add_argument("--item-timeout", type=int, default=None, help="seconds per item (default 3600)")
    w.add_argument("--deadline", type=int, default=None, help="seconds for the whole run (default 10800)")
    w.add_argument("--budget-usd", type=float, default=None, help="--max-budget-usd per session (default 20; 0 = none)")
    w.add_argument("--model", help="model for the sessions (default: the CLI default)")
    w.add_argument("--no-council", action="store_true", help="skip the council review (tests/debugging)")
    w.add_argument("--no-notify", action="store_true", help="no Telegram summary")
    w.add_argument("--keep-worktree", action="store_true", help="leave the session worktree in place")
    w.set_defaults(func=cmd_work)

    r = sub.add_parser("report", help="write + print the morning report"); r.set_defaults(func=cmd_report)
    ls = sub.add_parser("list", help="one line per active item"); ls.set_defaults(func=cmd_list)
    sh = sub.add_parser("show", help="item details + council review"); sh.add_argument("item"); sh.set_defaults(func=cmd_show)
    df = sub.add_parser("diff", help="full diff of a worked branch"); df.add_argument("item"); df.set_defaults(func=cmd_diff)
    ap = sub.add_parser("approve", help="merge + push + delete branch; archive as done (human command)")
    ap.add_argument("items", nargs="+", help="report numbers or item ids")
    ap.add_argument("--held", action="store_true", help="also allow merging a held item's branch (read its note first)")
    ap.set_defaults(func=cmd_approve)
    dr = sub.add_parser("drop", help="delete the branch (journaled); archive as dropped")
    dr.add_argument("items", nargs="+", help="report numbers or item ids"); dr.set_defaults(func=cmd_drop)
    ho = sub.add_parser("hold", help="open/in_review -> held with a note")
    ho.add_argument("item"); ho.add_argument("note"); ho.set_defaults(func=cmd_hold)
    ro = sub.add_parser("reopen", help="held -> open"); ro.add_argument("item"); ro.set_defaults(func=cmd_reopen)
    return p


def main(argv=None) -> int:
    # cron/log friendliness: progress lines land in cron.log as they happen, not at exit;
    # and `backlog-run report | head` must not end in a BrokenPipeError traceback.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError, OSError):
        pass
    args = build_parser().parse_args(argv)
    cfg = Config()
    if args.cmd == "work":
        if args.max_items is not None:
            cfg.max_items = args.max_items
        if args.item_timeout is not None:
            cfg.item_timeout = args.item_timeout
        if args.deadline is not None:
            cfg.deadline = args.deadline
        if args.budget_usd is not None:
            cfg.budget_usd = args.budget_usd
        if args.model:
            cfg.model = args.model
        if args.no_notify:
            cfg.tg_enabled = False
        cfg.keep_worktree = args.keep_worktree
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
