# diem/drain.py
"""The drain loop. All decisions are clock/budget arithmetic — no judgment.
Interactive evening use is honored implicitly: balance re-read between jobs
means a human burning DIEM pushes the balance to the floor and we stop."""
from __future__ import annotations
import subprocess
from datetime import datetime, timedelta

from .balance import BalanceUnavailable
from .discover import discover
from .queue import new_item
from .state import Lock, pause_until


def _at(now: datetime, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def next_deadline(cfg, now: datetime) -> datetime:
    """Deadline of the CURRENT DIEM day — may already be in the past (e.g. in
    the (deadline, reset) gap). Anchored via next_reset so a late-firing
    checkpoint can never see a ~24h-out deadline. Config contract: deadline
    falls between the last checkpoint and reset on the clock (00:50 < 01:00)."""
    return _at(next_reset(cfg, now), cfg.deadline)


def next_reset(cfg, now: datetime) -> datetime:
    r = _at(now, cfg.reset)
    return r if now <= r else r + timedelta(days=1)


def _last_fired(cfg, now: datetime):
    """(fired_at, Checkpoint) of the latest checkpoint at-or-before now within
    the current DIEM day, or None if none has fired yet."""
    day_start = next_reset(cfg, now) - timedelta(days=1)
    best = None
    for cp in cfg.checkpoints:
        t = _at(day_start, cp.time)
        if t < day_start:
            t += timedelta(days=1)
        if t <= now and (best is None or t > best[0]):
            best = (t, cp)
    return best


def floor_for(cfg, now: datetime) -> float:
    """Latest checkpoint at-or-before now on the DIEM day (reset..reset).
    Checkpoint times are anchored to the DAY START, not now's date — at
    00:05 the operative checkpoint is *yesterday's* 23:00, and a 00:15
    checkpoint belongs to the day that started the previous 01:00.
    Before the first checkpoint fires, use the first (most conservative)."""
    best = _last_fired(cfg, now)
    frac = best[1].floor if best else cfg.checkpoints[0].floor
    return frac * cfg.daily_diem


def run_checkpoint(cfg, *, now: datetime, balance, queue, estimates, reviewed,
                   runner, run=subprocess.run) -> dict:
    now_iso = now.isoformat(timespec="seconds")
    floor = floor_for(cfg, now)
    deadline = next_deadline(cfg, now)
    summary = {"aborted": None, "floor": floor, "started_balance": None,
               "ended_balance": None, "ran": [], "skipped": [],
               "deadline": deadline.isoformat(timespec="seconds")}

    pu = pause_until(cfg.state_dir)
    if pu and pu > now_iso:
        summary["aborted"] = "paused"
        return summary

    if now > deadline:
        summary["aborted"] = "past_deadline"
        return summary
    if _last_fired(cfg, now) is None:
        summary["aborted"] = "no_checkpoint_fired"  # off-schedule run (post-reset or mid-day)
        return summary

    lock = Lock(cfg.state_dir / "drain.lock")
    if not lock.acquire():
        summary["aborted"] = "locked"
        return summary
    try:
        day_start_iso = (next_reset(cfg, now) - timedelta(days=1)) \
            .isoformat(timespec="seconds")
        discover(cfg, queue, reviewed, now_iso, day_start_iso=day_start_iso,
                 run=run)
        elapsed = 0.0    # simulated wall-clock from job durations (tests inject now)
        attempted = set()  # ids run this checkpoint — failures retry NEXT checkpoint
        skipped_ids = set()  # dedupe: an unfittable item is re-seen every pass
        while True:
            try:
                bal = balance.diem_balance()
            except BalanceUnavailable:
                summary["aborted"] = "balance_unavailable"
                return summary
            if summary["started_balance"] is None:
                summary["started_balance"] = bal
            summary["ended_balance"] = bal
            if bal <= floor:
                return summary

            eff_now = now + timedelta(seconds=elapsed)
            pend = queue.pending(now_iso)
            picked, skipped_this_pass = None, []
            for it in pend:
                if it.id in attempted:
                    continue
                cost, dur = estimates.estimate(it.type)
                if bal - cost < floor:
                    reason = "budget"
                elif eff_now + timedelta(seconds=dur) > deadline:
                    reason = "deadline"
                else:
                    picked = it
                    break
                if it.id not in skipped_ids:
                    skipped_ids.add(it.id)
                    skipped_this_pass.append({"id": it.id, "type": it.type,
                                              "reason": reason})
            summary["skipped"].extend(skipped_this_pass)

            if picked is None:
                # Filler ONLY on a truly empty queue — items that merely don't
                # fit (budget/deadline) must not spawn backfill noise.
                if (not pend and queue.night_count("backfill", day_start_iso)
                        < cfg.backfill_max_per_night):
                    queue.add(new_item("backfill",
                                       {"max_targets": cfg.backfill_chunk},
                                       created=now_iso))
                    continue  # picked up through the normal budget/deadline gate
                return summary

            attempted.add(picked.id)
            deadline_epoch = (deadline - eff_now).total_seconds()
            res = runner(picked, deadline_epoch=deadline_epoch)
            elapsed += res.duration_s
            try:
                after = balance.diem_balance()
            except BalanceUnavailable:
                after = bal
            cost = max(0.0, bal - after)
            estimates.record(picked.type, cost=cost, duration_s=res.duration_s)
            entry = {"id": picked.id, "type": picked.type, "ok": res.ok,
                     "cost": cost, "duration_s": res.duration_s,
                     "output_path": res.output_path, "error": res.error}
            summary["ran"].append(entry)
            if res.ok:
                queue.archive(picked, {"ok": True, "cost": cost,
                                       "output_path": res.output_path})
                if picked.type == "review" and picked.payload.get("head"):
                    reviewed.set(picked.payload["repo"], picked.payload["head"])
            else:
                picked.attempts += 1
                if picked.attempts < picked.max_attempts:
                    queue.requeue(picked)
                else:
                    queue.archive(picked, {"ok": False, "error": res.error})
    finally:
        lock.release()
