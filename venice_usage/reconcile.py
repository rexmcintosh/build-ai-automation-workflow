"""Check a ledger rollup against what Venice actually billed.

    python -m venice_usage.reconcile --since 2026-09-04 --project council

This is the feedback loop whose absence let a 2.5x pricing error reach an audit.
The ledger's `usd` is an estimate; `GET /billing/usage-history` is the invoice.
Nothing else on this box compares the two per model, so nothing else could have
noticed that `claude-opus-4-8` was being valued at 15.00/75.00 against a 6.00 /
30.00 bill while grok, codex and gemini were being counted as free.

How the two sides are joined. The bills carry no project tag, so an account-wide
window cannot be compared to one project's rollup directly. Every billed line
item does carry `inferenceDetails.requestId`, `promptTokens` and
`completionTokens`, and the ledger records the same two token counts and a
second-precision timestamp for each call. So the billed rows are folded into
requests, and each ledger row is matched to the unclaimed request with the same
(model, prompt tokens, completion tokens) nearest it in time. A request is
claimed once. Rows that match nothing are reported, not quietly dropped —
usually the last call of the window, whose bill has not landed yet.

Billed model ids sometimes carry a serving suffix the ledger does not
(`deepseek-v4-pro-api`), which `refresh_prices.resolve_id` already handles.

Reads only. The ledger is opened read-only and Venice is only ever asked for
usage history — no chat completion is made.
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys
from datetime import datetime, timedelta

from .refresh_prices import fetch_billing, open_ledger, parse_sku

#: How far apart a ledger row's timestamp and its bill may be and still be the
#: same call. Observed maximum on real data is under a second; a minute is slack
#: for clock skew, not a licence to match different calls.
MATCH_WINDOW_SECONDS = 600


def _strip_route(model):
    """`deepseek-v4-pro-api` -> `deepseek-v4-pro`. The ledger logs the id it
    asked for; the bill logs the route it was served on."""
    return model[:-4] if model.endswith("-api") else model


def fold_requests(rows):
    """Billed line items -> one record per request: model, tokens, DIEM, when.

    Every SKU charged to a request is summed, flat-fee ones (`search-augmentation`,
    which is billed per web search alongside the tokens) included — the invoice
    for a call is everything it was charged, not just its tokens."""
    by_id: dict[str, dict] = {}
    for r in rows or []:
        details = r.get("inferenceDetails") or {}
        rid = details.get("requestId")
        if not rid:
            continue
        rec = by_id.setdefault(rid, {"request_id": rid, "model": None, "amount": 0.0,
                                     "prompt_tokens": None, "completion_tokens": None,
                                     "ts": None})
        rec["amount"] += abs(float(r.get("amount") or 0.0))
        rec["prompt_tokens"] = details.get("promptTokens")
        rec["completion_tokens"] = details.get("completionTokens")
        parsed = parse_sku(r.get("sku"))
        if parsed and rec["model"] is None:
            rec["model"] = _strip_route(parsed[0])
        ts = r.get("timestamp")
        if ts and (rec["ts"] is None or ts < rec["ts"]):
            rec["ts"] = ts
    return list(by_id.values())


def _parse_ts(text):
    return datetime.fromisoformat((text or "").replace("Z", "+00:00")).replace(tzinfo=None)


def match(ledger_rows, requests, window=MATCH_WINDOW_SECONDS):
    """Pair ledger rows with billed requests. Returns (matched, unmatched).

    `matched` is a list of `(ledger_row, request)`; a request is used at most
    once, so two identical calls in the same second cost two bills, not one
    counted twice."""
    buckets = collections.defaultdict(list)
    for req in requests:
        if req["model"] is None or req["ts"] is None:
            continue
        buckets[(req["model"], req["prompt_tokens"], req["completion_tokens"])].append(
            (_parse_ts(req["ts"]), req))
    for pool in buckets.values():
        pool.sort(key=lambda pair: pair[0])

    claimed, matched, unmatched = set(), [], []
    for row in ledger_rows:
        when = _parse_ts(row["ts"])
        best = None
        for req_ts, req in buckets.get((row["model"], row["tokens_in"], row["tokens_out"]), []):
            if id(req) in claimed:
                continue
            gap = abs((req_ts - when).total_seconds())
            if best is None or gap < best[0]:
                best = (gap, req)
        if best and best[0] <= window:
            claimed.add(id(best[1]))
            matched.append((row, best[1]))
        else:
            unmatched.append(row)
    return matched, unmatched


def read_ledger(db_path, *, since=None, until=None, project=None):
    sql = "SELECT ts, project, model, tokens_in, tokens_out, usd FROM usage"
    where, params = [], []
    if since:
        where.append("ts >= ?"); params.append(since)
    if until:
        where.append("ts <= ?"); params.append(until)
    if project:
        where.append("project = ?"); params.append(project)
    if where:
        sql += " WHERE " + " AND ".join(where)
    with open_ledger(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql + " ORDER BY ts", params)]


def summarise(matched, unmatched, *, price_basis="current"):
    """Per-model ledger-vs-billed totals for the matched calls."""
    from .pricing import PRICES
    per = collections.defaultdict(lambda: {"calls": 0, "ledger": 0.0, "billed": 0.0})
    for row, req in matched:
        cell = per[row["model"]]
        cell["calls"] += 1
        cell["billed"] += req["amount"]
        rate = PRICES.get(row["model"])
        if price_basis == "current" and rate is not None:
            cell["ledger"] += (row["tokens_in"] / 1e6 * rate["input"]
                               + row["tokens_out"] / 1e6 * rate["output"])
        else:
            cell["ledger"] += row["usd"] or 0.0
    return {"per_model": dict(per),
            "ledger": sum(c["ledger"] for c in per.values()),
            "billed": sum(c["billed"] for c in per.values()),
            "matched": len(matched), "unmatched": len(unmatched)}


def render(summary, *, since, until, project, price_basis):
    from .pricing import basis_line
    out = [f"reconciliation: project={project or '(all)'} since={since} until={until or 'now'}",
           basis_line(price_basis),
           f"matched {summary['matched']} ledger row(s) to a billed request; "
           f"{summary['unmatched']} unmatched",
           "",
           f"{'model':30} {'calls':>6} {'ledger':>10} {'billed':>10} {'delta':>9}"]
    for model in sorted(summary["per_model"],
                        key=lambda m: -summary["per_model"][m]["billed"]):
        cell = summary["per_model"][model]
        delta = (cell["ledger"] / cell["billed"] - 1) * 100 if cell["billed"] else float("nan")
        out.append(f"{model:30} {cell['calls']:6} {cell['ledger']:10.4f} "
                   f"{cell['billed']:10.4f} {delta:+8.2f}%")
    total = (summary["ledger"] / summary["billed"] - 1) * 100 if summary["billed"] else float("nan")
    out.append(f"{'TOTAL':30} {summary['matched']:6} {summary['ledger']:10.4f} "
               f"{summary['billed']:10.4f} {total:+8.2f}%")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m venice_usage.reconcile",
                                description="Compare a ledger rollup with Venice's bills.")
    p.add_argument("--since", required=True)
    p.add_argument("--until", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--price-basis", default="current", choices=("current", "stored"),
                   dest="price_basis")
    p.add_argument("--db", default=None, help="ledger to read (read-only)")
    p.add_argument("--tolerance", type=float, default=5.0,
                   help="percent the two sides may differ before this exits 2")
    a = p.parse_args(sys.argv[1:] if argv is None else list(argv))

    key = os.environ.get("VENICE_ADMIN_KEY")
    if not key:
        print("VENICE_ADMIN_KEY is not set (run: set -a; . ~/.env; set +a)", file=sys.stderr)
        return 1
    from .ledger import default_db
    db_path = a.db or str(default_db())
    rows = read_ledger(db_path, since=a.since, until=a.until, project=a.project)
    if not rows:
        print("no ledger rows in that window", file=sys.stderr)
        return 1

    # Widen the billing window by a day on each side: a bill can land a moment
    # after the call, and the join is on request identity, not on the window.
    start = (_parse_ts(rows[0]["ts"]) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (_parse_ts(rows[-1]["ts"]) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    billing = fetch_billing(key, start=start, end=end)
    matched, unmatched = match(rows, fold_requests(billing))
    summary = summarise(matched, unmatched, price_basis=a.price_basis)
    print(render(summary, since=a.since, until=a.until, project=a.project,
                 price_basis=a.price_basis))
    for row in unmatched:
        print(f"unmatched: {row['ts']} {row['model']} "
              f"{row['tokens_in']}/{row['tokens_out']} (no bill found)", file=sys.stderr)
    if not summary["billed"]:
        return 1
    drift = abs(summary["ledger"] / summary["billed"] - 1) * 100
    if drift > a.tolerance:
        print(f"\nledger is {drift:.2f}% away from the bills, over the {a.tolerance:g}% "
              f"tolerance — refresh the price table and look again.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
