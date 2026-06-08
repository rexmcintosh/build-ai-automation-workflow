# loom/cli.py
"""`python -m loom.cli <cmd>`:
  absorb [--live] [--max-targets N] [--deadline-seconds S]   nightly distill (+weave if --live), backend=claude
  backfill [--max-targets N] [--all]     backlog weave, backend=venice (DIEM)
  promote                                apply staged .claude + merge loom-shadow -> master
  requeue <session_id>                   return a quarantined/stuck session to pending
  rollback --ts <stamp>                  restore ~/.claude from a promote backup
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


class _PathEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Path):
            return str(o)
        return super().default(o)

from .promote import promote, rollback
from .run import Config, absorb
from .state import LoomState

_HOME = Path.home()
_REPO = _HOME / "projects" / "build-ai-automation-workflow"
_LOOM = _REPO / "loom"


def default_config() -> Config:
    return Config(
        projects_dir=_HOME / ".claude" / "projects",
        loom_dir=_LOOM,
        state_path=_LOOM / "state.json",
        wiki_worktree=_HOME / "wiki-loom-shadow",
        claude_dir=_HOME / ".claude",
        ledger_path=_LOOM / "weave_ledger.json",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loom")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("absorb")
    a.add_argument("--live", action="store_true")
    a.add_argument("--max-targets", type=int, default=10)
    a.add_argument("--deadline-seconds", type=float, default=3600.0)

    b = sub.add_parser("backfill")
    b.add_argument("--max-targets", type=int, default=10)
    b.add_argument("--all", action="store_true")

    sub.add_parser("promote")
    rq = sub.add_parser("requeue"); rq.add_argument("session_id")
    rb = sub.add_parser("rollback"); rb.add_argument("--ts", required=True)

    args = parser.parse_args(argv)
    cfg = default_config()
    today = time.strftime("%Y-%m-%d")

    if args.cmd == "absorb":
        summary = absorb(cfg, shadow=not args.live, backend="claude",
                         max_targets=args.max_targets, today=today,
                         deadline_seconds=args.deadline_seconds)
        print(json.dumps(summary, cls=_PathEncoder)); return 0
    if args.cmd == "backfill":
        cap = 10 ** 9 if args.all else args.max_targets
        summary = absorb(cfg, shadow=False, backend="venice", max_targets=cap, today=today)
        print(json.dumps(summary, cls=_PathEncoder)); return 0
    if args.cmd == "promote":
        res = promote(wiki_root=cfg.wiki_worktree, claude_root=cfg.claude_dir,
                      backups_dir=cfg.loom_dir / "promote-backups", expect_unmodified=True)
        print(json.dumps(res, cls=_PathEncoder)); return 0
    if args.cmd == "requeue":
        # Re-queue a quarantined/stuck session -> next `absorb` re-runs Stage-0 from scratch.
        # (A committed session won't re-weave: git trailers reconcile it back to committed.)
        LoomState(cfg.state_path).advance(args.session_id, "pending")
        print(json.dumps({"requeued": args.session_id})); return 0
    if args.cmd == "rollback":
        res = rollback(backups_dir=cfg.loom_dir / "promote-backups", ts=args.ts)
        print(json.dumps(res, cls=_PathEncoder)); return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
