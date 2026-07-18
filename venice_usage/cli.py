"""`venice-usage` — the universal append primitive + offline rollup.
`log` is best-effort and always exits 0: logging must never break a caller."""
from __future__ import annotations
import argparse
import json
import sys
from .ledger import append, query_rollup

def _cmd_log(a) -> int:
    try:
        append(project=a.project, task_type=a.task_type, model=a.model,
               tokens_in=a.tokens_in, tokens_out=a.tokens_out,
               usd=a.usd, source=a.source, ts=a.ts)
    except Exception as e:  # noqa: BLE001 — append is best-effort
        print(f"venice-usage: log failed (ignored): {e}", file=sys.stderr)
    return 0

def _cmd_report(a) -> int:
    gb = tuple(c.strip() for c in a.group_by.split(",") if c.strip())
    try:
        rows = query_rollup(since=a.since, until=a.until, project=a.project, group_by=gb)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr); return 2
    if a.json:
        print(json.dumps(rows, indent=1)); return 0
    if not rows:
        print("(no usage rows)"); return 0
    headers = list(gb) + ["calls", "tokens_in", "tokens_out", "usd"]
    widths = {h: max(len(h), *(len(str(r[h])) for r in rows)) for h in headers}
    print("  ".join(h.ljust(widths[h]) for h in headers))
    for r in rows:
        cells = [str(r[h]) if h != "usd" else f"{r['usd']:.4f}" for h in headers]
        print("  ".join(c.ljust(widths[h]) for c, h in zip(cells, headers)))
    return 0

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="venice-usage")
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--project", required=True)
    lg.add_argument("--task-type", required=True, dest="task_type")
    lg.add_argument("--model", required=True)
    lg.add_argument("--tokens-in", type=int, default=0, dest="tokens_in")
    lg.add_argument("--tokens-out", type=int, default=0, dest="tokens_out")
    lg.add_argument("--usd", type=float, default=None)
    lg.add_argument("--source", default=None)
    lg.add_argument("--ts", default=None)
    rp = sub.add_parser("report")
    rp.add_argument("--since"); rp.add_argument("--until"); rp.add_argument("--project")
    rp.add_argument("--group-by", default="project,task_type", dest="group_by")
    rp.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    return _cmd_log(a) if a.cmd == "log" else _cmd_report(a)

if __name__ == "__main__":
    raise SystemExit(main())
