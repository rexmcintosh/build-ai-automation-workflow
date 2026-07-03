"""Config + key loading. Cron has no shell env, so the Venice key is read
straight from ~/.env (accepts VENICE_API_KEY or VENICE_KEY)."""
from __future__ import annotations
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "diem" / "config.toml"


@dataclass(frozen=True)
class Checkpoint:
    time: str   # "HH:MM" local
    floor: float  # fraction of daily_diem


_DEFAULT_CHECKPOINTS = [Checkpoint("21:00", 0.40), Checkpoint("23:00", 0.15),
                        Checkpoint("00:15", 0.0)]
_DEFAULT_SEEDS = {
    "ask": {"cost": 0.5, "duration_s": 120},
    "review": {"cost": 1.0, "duration_s": 180},
    "images": {"cost": 2.0, "duration_s": 180},
    "backfill": {"cost": 1.0, "duration_s": 300},
    "cmd": {"cost": 1.0, "duration_s": 300},
}


@dataclass
class DiemConfig:
    daily_diem: float
    repos: list[Path]
    checkpoints: list[Checkpoint] = field(default_factory=lambda: list(_DEFAULT_CHECKPOINTS))
    deadline: str = "00:50"
    reset: str = "01:00"
    state_dir: Path = Path.home() / ".local/state/diem"
    outputs_dir: Path = Path.home() / ".local/state/diem/outputs"
    loom_repo: Path = Path.home() / "projects/build-ai-automation-workflow"
    loom_cmd: list[str] = field(default_factory=lambda: [
        str(Path.home() / "projects/build-ai-automation-workflow/.venv/bin/python"),
        "-m", "loom.cli", "backfill"])
    seeds: dict = field(default_factory=lambda: dict(_DEFAULT_SEEDS))
    telegram: dict | None = None
    cmd_whitelist: dict = field(default_factory=dict)
    backfill_max_per_night: int = 4
    backfill_chunk: int = 2

    @classmethod
    def load(cls, path: Path | None = None) -> "DiemConfig":
        path = path or DEFAULT_CONFIG
        try:
            raw = tomllib.loads(Path(path).read_text())
        except FileNotFoundError:
            print(f"error: no config at {path}", file=sys.stderr)
            raise SystemExit(2)
        if "daily_diem" not in raw:
            print("error: config needs daily_diem (your daily DIEM allowance)",
                  file=sys.stderr)
            raise SystemExit(2)
        kw = {"daily_diem": float(raw["daily_diem"]),
              "repos": [Path(r) for r in raw.get("repos", [])]}
        if "checkpoints" in raw:
            kw["checkpoints"] = [Checkpoint(c["time"], float(c["floor"]))
                                 for c in raw["checkpoints"]]
        for key in ("deadline", "reset", "backfill_max_per_night", "backfill_chunk"):
            if key in raw:
                kw[key] = raw[key]
        for key in ("state_dir", "outputs_dir", "loom_repo"):
            if key in raw:
                kw[key] = Path(raw[key])
        if "loom_cmd" in raw:
            kw["loom_cmd"] = list(raw["loom_cmd"])
        seeds = dict(_DEFAULT_SEEDS)
        seeds.update(raw.get("seeds", {}))
        kw["seeds"] = seeds
        kw["telegram"] = raw.get("telegram")
        kw["cmd_whitelist"] = raw.get("cmd_whitelist", {})
        return cls(**kw)


def load_venice_key(env_path: Path = Path.home() / ".env") -> str:
    try:
        lines = Path(env_path).read_text().splitlines()
    except OSError:
        lines = []
    found = {}
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line or line.startswith("#"):
            continue
        name, _, val = line.partition("=")
        found[name.strip()] = val.strip().strip("'\"")
    for name in ("VENICE_API_KEY", "VENICE_KEY"):
        if found.get(name):
            return found[name]
    print(f"error: neither VENICE_API_KEY nor VENICE_KEY found in {env_path}",
          file=sys.stderr)
    raise SystemExit(2)
