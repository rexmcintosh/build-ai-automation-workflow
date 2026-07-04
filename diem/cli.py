"""`diem` console entry. Cron calls `diem drain --checkpoint`; humans and
Claude sessions use queue/status/pause. Config: ~/.config/diem/config.toml."""
from __future__ import annotations
import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .balance import BalanceClient
from .config import DiemConfig, load_venice_key
from .drain import floor_for, next_deadline, next_reset, run_checkpoint
from .queue import QueueDir, new_item
from .report import evening_ping, send_telegram, write_morning_report
from .runners import run_item
from .state import Estimates, Reviewed, clear_pause, set_pause
from .queue import Item  # noqa: F401 (re-export convenience for sessions)


def _now() -> datetime:
    return datetime.now()


def _bits(cfg):
    q = QueueDir(cfg.state_dir)
    est = Estimates(Path(cfg.state_dir) / "estimates.json", cfg.seeds)
    rev = Reviewed(Path(cfg.state_dir) / "reviewed.json")
    return q, est, rev


def _diem_day(cfg, now: datetime) -> str:
    return (next_reset(cfg, now) - timedelta(days=1)).date().isoformat()


def _cmd_drain(cfg, now: datetime) -> int:
    key = load_venice_key()
    env = {**os.environ, "VENICE_API_KEY": key, "VENICE_KEY": key}
    q, est, rev = _bits(cfg)
    balance = BalanceClient(key)

    def runner(item, *, deadline_epoch):
        return run_item(item, cfg, env,
                        deadline_epoch=time.monotonic() + deadline_epoch)

    summary = run_checkpoint(cfg, now=now, balance=balance, queue=q,
                             estimates=est, reviewed=rev, runner=runner)
    day = _diem_day(cfg, now)
    jl = Path(cfg.state_dir) / "summaries" / f"{day}.jsonl"
    jl.parent.mkdir(parents=True, exist_ok=True)
    first_of_night = not jl.exists()
    with open(jl, "a") as fh:
        fh.write(json.dumps(summary) + "\n")

    if first_of_night:
        send_telegram(cfg, evening_ping(summary, cfg))
    last_cp = max(cfg.checkpoints,
                  key=lambda c: (c.time < cfg.reset, c.time))  # 00:15 sorts last
    if now.strftime("%H:%M") >= last_cp.time and now.strftime("%H:%M") < cfg.reset:
        summaries = [json.loads(l) for l in jl.read_text().splitlines() if l.strip()]
        path = write_morning_report(cfg, day, summaries)
        ran = sum(len(s.get("ran", [])) for s in summaries)
        failed = sum(1 for s in summaries for r in s.get("ran", []) if not r["ok"])
        send_telegram(cfg, f"DIEM night done: {ran} job(s), {failed} failed.\n"
                           f"Report: {path}")
    print(json.dumps(summary, indent=1))
    return 0


def _cmd_status(cfg, now: datetime) -> int:
    q, est, _ = _bits(cfg)
    try:
        bal = BalanceClient(load_venice_key()).diem_balance()
        pct = f"{100 * bal / cfg.daily_diem:.0f}%"
    except SystemExit:
        bal, pct = None, "? (no key)"
    pend = q.pending(now.isoformat(timespec="seconds"))
    banked = sum(1 for i in pend if i.banked)
    print(f"balance:  {bal} ({pct} of {cfg.daily_diem})")
    print(f"floor:    {floor_for(cfg, now):.1f}  deadline: {next_deadline(cfg, now)}"
          f"  reset: {next_reset(cfg, now)}")
    print(f"queue:    {len(pend)} pending ({banked} banked)")
    for i in pend:
        print(f"  {i.id[:8]} {'B' if i.banked else ' '} {i.type:9} {i.created}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="diem")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("drain")
    d.add_argument("--checkpoint", action="store_true", required=True)
    d.add_argument("--config", default=None)

    st = sub.add_parser("status"); st.add_argument("--config", default=None)

    qp = sub.add_parser("queue"); qsub = qp.add_subparsers(dest="qcmd", required=True)
    qa = qsub.add_parser("add"); qa.add_argument("--config", default=None)
    qa.add_argument("type", choices=["ask", "review", "images", "backfill", "cmd"])
    qa.add_argument("args", nargs="*")
    qa.add_argument("--panel", default="decision"); qa.add_argument("--range")
    qa.add_argument("--expires"); qa.add_argument("--max-targets", type=int, default=2)
    ql = qsub.add_parser("list"); ql.add_argument("--config", default=None)
    qr = qsub.add_parser("rm"); qr.add_argument("id"); qr.add_argument("--config", default=None)

    pa = sub.add_parser("pause")
    pa.add_argument("hours", nargs="?", type=float); pa.add_argument("--config", default=None)
    re_ = sub.add_parser("resume"); re_.add_argument("--config", default=None)

    args = p.parse_args(argv)
    cfg = DiemConfig.load(Path(args.config) if args.config else None)
    now = _now()
    now_iso = now.isoformat(timespec="seconds")

    if args.cmd == "drain":
        return _cmd_drain(cfg, now)
    if args.cmd == "status":
        return _cmd_status(cfg, now)
    if args.cmd == "queue":
        q, _, _ = _bits(cfg)
        if args.qcmd == "add":
            payload = None
            if args.type == "ask":
                payload = {"question": " ".join(args.args), "panel": args.panel}
            elif args.type == "review":
                repo = args.args[0]
                payload = ({"repo": repo, "range": args.range,
                            "head": args.range.split("..")[-1]} if args.range
                           else {"repo": repo, "diff": True})
            elif args.type == "images":
                payload = {"repo": args.args[0], "count": int(args.args[1])}
            elif args.type == "backfill":
                payload = {"max_targets": args.max_targets}
            elif args.type == "cmd":
                payload = {"name": args.args[0]}
            it = new_item(args.type, payload, banked=True,
                          expires=args.expires, created=now_iso)
            added = q.add(it)
            print(it.id if added else "duplicate — not added")
            return 0 if added else 1
        if args.qcmd == "list":
            for i in q.pending(now_iso):
                print(f"{i.id[:8]} {'B' if i.banked else ' '} {i.type:9} "
                      f"{i.created}  {json.dumps(i.payload)[:60]}")
            return 0
        if args.qcmd == "rm":
            return 0 if q.remove(args.id) else 1
    if args.cmd == "pause":
        until = (now + timedelta(hours=args.hours)) if args.hours \
            else next_reset(cfg, now)
        set_pause(cfg.state_dir, until.isoformat(timespec="seconds"))
        print(f"paused until {until}")
        return 0
    if args.cmd == "resume":
        clear_pause(cfg.state_dir)
        print("resumed")
        return 0
    return 1
