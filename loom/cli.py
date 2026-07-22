# loom/cli.py
"""`python -m loom.cli <cmd>`:
  absorb [--live] [--max-targets N] [--deadline-seconds S]   nightly distill (+weave if --live), backend=claude
  backfill [--max-targets N] [--all]     backlog weave, backend=venice (DIEM)
  promote [--auto]                       apply staged .claude + merge loom-shadow -> master
                                         (--auto: only if the unattended gate allows)
  hold [--clear]                         veto tonight's auto-promote (self-expires next day)
  pending                                JSON: what's landing + what needs a decision
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

from .autopromote import auto_promote_check, clear_hold, set_hold
from .ledger import WeaveLedger
from .pending import cluster_blocked, pending_summary
from .promote import promote, rollback
from .run import Config, absorb
from .state import LoomState

_HOME = Path.home()
_REPO = _HOME / "projects" / "build-ai-automation-workflow"
_LOOM = _REPO / "loom"


def pending_payload(cfg: Config, today: str) -> dict:
    return pending_summary(wiki_root=cfg.wiki_master, ledger_path=cfg.ledger_path,
                           learnings_dir=cfg.loom_dir / "learnings",
                           loom_dir=cfg.loom_dir, today=today)


def default_config() -> Config:
    return Config(
        projects_dir=_HOME / ".claude" / "projects",
        loom_dir=_LOOM,
        state_path=_LOOM / "state.json",
        wiki_worktree=_HOME / "wiki-loom-shadow",
        wiki_master=_HOME / "wiki",
        claude_dir=_HOME / ".claude",
        ledger_path=_LOOM / "weave_ledger.json",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loom")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("absorb")
    a.add_argument("--live", action="store_true")
    a.add_argument("--max-targets", type=int, default=10)
    a.add_argument("--max-per-target", type=int, default=4)
    a.add_argument("--deadline-seconds", type=float, default=3600.0)

    b = sub.add_parser("backfill")
    b.add_argument("--max-targets", type=int, default=10)
    b.add_argument("--max-per-target", type=int, default=4)
    b.add_argument("--all", action="store_true")

    pr = sub.add_parser("promote")
    pr.add_argument("--auto", action="store_true")
    hd = sub.add_parser("hold"); hd.add_argument("--clear", action="store_true")
    sub.add_parser("pending")
    rq = sub.add_parser("requeue"); rq.add_argument("session_id")
    rb = sub.add_parser("rollback"); rb.add_argument("--ts", required=True)

    args = parser.parse_args(argv)
    cfg = default_config()
    today = time.strftime("%Y-%m-%d")

    if args.cmd == "absorb":
        summary = absorb(cfg, shadow=not args.live, backend="claude",
                         max_targets=args.max_targets, max_per_target=args.max_per_target,
                         today=today, deadline_seconds=args.deadline_seconds)
        print(json.dumps(summary, cls=_PathEncoder)); return 0
    if args.cmd == "backfill":
        cap = 10 ** 9 if args.all else args.max_targets
        # distill=False: backfill weaves the already-distilled backlog on Venice/DIEM only;
        # it never distills new pending sessions (that's the nightly Claude-backed absorb's job).
        summary = absorb(cfg, shadow=False, backend="venice", max_targets=cap,
                         max_per_target=args.max_per_target, today=today, distill=False)
        print(json.dumps(summary, cls=_PathEncoder)); return 0
    if args.cmd == "promote":
        landed = {}
        if getattr(args, "auto", False):
            # Unattended: the gate decides. A refusal is a normal outcome, not an
            # error — the nightly run must not fail just because it stood down.
            check = auto_promote_check(wiki_root=cfg.wiki_master,
                                       loom_dir=cfg.loom_dir, today=today)
            if not check["go"]:
                print(json.dumps({"promoted": False, **check}, cls=_PathEncoder)); return 0
            # Carry what's about to land: once promote() merges, the pending list is
            # gone, and the morning briefing line is built from this JSON.
            landed = {"articles": check["articles"], "commits": check["commits"]}
        res = promote(wiki_root=cfg.wiki_master, shadow_root=cfg.wiki_worktree,
                      claude_root=cfg.claude_dir,
                      backups_dir=cfg.loom_dir / "promote-backups", expect_unmodified=True)
        print(json.dumps({"promoted": True, **landed, **res}, cls=_PathEncoder)); return 0
    if args.cmd == "hold":
        if args.clear:
            clear_hold(cfg.loom_dir); print(json.dumps({"hold": None})); return 0
        set_hold(cfg.loom_dir, today); print(json.dumps({"hold": today})); return 0
    if args.cmd == "pending":
        print(json.dumps(pending_payload(cfg, today), cls=_PathEncoder)); return 0
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
