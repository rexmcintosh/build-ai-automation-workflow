"""One runner per item type. diem never implements a workload — it shells
out to council / loom / repo-declared commands, with the 00:50 deadline as
a subprocess hard timeout. Failures return RunResult(ok=False), never raise."""
from __future__ import annotations
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    ok: bool
    duration_s: float
    output_path: str | None = None
    error: str | None = None


def _save(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "")
    return str(path)


def run_item(item, cfg, env: dict, *, deadline_epoch: float,
             run=subprocess.run, clock=time.monotonic) -> RunResult:
    start = clock()
    timeout = max(30.0, deadline_epoch - start)
    p = item.payload

    def _exec(argv, *, cwd=None, input=None):
        return run(argv, capture_output=True, text=True, timeout=timeout,
                   env=env, cwd=cwd, input=input)

    def _done(proc, out_path: Path | None, log_stdout: bool):
        dur = clock() - start
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[-500:]
            return RunResult(False, dur, error=f"exit {proc.returncode}: {err}")
        saved = _save(out_path, proc.stdout) if (out_path and log_stdout) else None
        return RunResult(True, dur, output_path=saved)

    try:
        if item.type == "ask":
            proc = _exec(["council", "ask", p["question"],
                          "--panel", p.get("panel", "decision"), "--format", "md"])
            return _done(proc, Path(cfg.outputs_dir) / "asks" / f"{item.id}.md", True)

        if item.type == "review":
            repo = p["repo"]
            name = Path(repo).name
            out = Path(cfg.outputs_dir) / "reviews" / f"{name}-{item.id}.md"
            if p.get("diff"):
                proc = _exec(["council", "review", "--diff", "--format", "md"],
                             cwd=repo)
                return _done(proc, out, True)
            gd = _exec(["git", "-C", repo, "diff", p["range"]])
            if gd.returncode != 0:
                return RunResult(False, clock() - start,
                                 error=f"git diff failed: {gd.stderr.strip()[-300:]}")
            if not gd.stdout.strip():
                return RunResult(True, clock() - start)  # nothing to review
            proc = _exec(["council", "review", "-", "--format", "md"],
                         input=gd.stdout)
            return _done(proc, out, True)

        if item.type == "images":
            command = p.get("command")
            if not command:
                # Fall back to standing-order.json
                standing_order_path = Path(p["repo"]) / ".diem" / "standing-order.json"
                try:
                    so_data = json.loads(standing_order_path.read_text())
                    command = so_data.get("command")
                except (FileNotFoundError, json.JSONDecodeError, KeyError,
                        AttributeError, TypeError):
                    return RunResult(False, clock() - start,
                                     error="images item has no command and no standing order")
            if not isinstance(command, list) or not command:
                return RunResult(False, clock() - start,
                                 error="images item has no command and no standing order")
            argv = list(command) + ["--count", str(p["count"])]
            proc = _exec(argv, cwd=p["repo"])
            return _done(proc, Path(cfg.outputs_dir) / "logs" / f"{item.id}.log", True)

        if item.type == "backfill":
            argv = list(cfg.loom_cmd) + ["--max-targets", str(p.get("max_targets", 2))]
            proc = _exec(argv, cwd=str(cfg.loom_repo))
            return _done(proc, Path(cfg.outputs_dir) / "logs" / f"{item.id}.log", True)

        if item.type == "cmd":
            entry = cfg.cmd_whitelist.get(p.get("name", ""))
            if not entry:
                return RunResult(False, clock() - start,
                                 error=f"'{p.get('name')}' not in cmd whitelist")
            proc = _exec(list(entry["argv"]), cwd=entry["repo"])
            return _done(proc, Path(cfg.outputs_dir) / "logs" / f"{item.id}.log", True)

        return RunResult(False, clock() - start, error=f"unknown type {item.type}")
    except subprocess.TimeoutExpired:
        return RunResult(False, clock() - start,
                         error=f"timeout after {timeout:.0f}s (deadline backstop)")
    except Exception as e:  # noqa: BLE001 — one bad job must not kill the drain
        return RunResult(False, clock() - start, error=f"{type(e).__name__}: {e}")
