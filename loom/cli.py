"""`python -m loom.cli absorb [--live]` — entry point. Defaults to shadow mode."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .run import Config, absorb

_HOME = Path.home()
_LOOM = _HOME / "projects" / "build-ai-automation-workflow" / "loom"


def default_config() -> Config:
    return Config(
        projects_dir=_HOME / ".claude" / "projects",
        loom_dir=_LOOM,
        state_path=_LOOM / "state.json",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loom")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("absorb")
    a.add_argument("--live", action="store_true", help="v1 only; v0 ignores and runs shadow")
    args = parser.parse_args(argv)
    if args.cmd == "absorb":
        summary = absorb(default_config(), shadow=not args.live)
        print(json.dumps(summary))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
