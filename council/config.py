from __future__ import annotations
import os
import sys
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .models import Member, Panel


@dataclass
class Settings:
    default_panel: str = "decision"
    router_model: str = ""
    chair_model: str = ""
    byte_cap: int = 200_000
    timeout: int = 180


def get_api_key() -> str:
    key = os.environ.get("VENICE_API_KEY")
    if not key:
        print("error: VENICE_API_KEY is not set. Add it to your environment or .env "
              "(see .env.example).", file=sys.stderr)
        raise SystemExit(2)
    return key


def _panels_path(path=None) -> Path:
    if path:
        return Path(path)
    override = Path.home() / ".config" / "council" / "panels.toml"
    if override.exists():
        return override
    return Path(str(files("council") / "panels.toml"))


def load_panels(path=None):
    data = tomllib.load(open(_panels_path(path), "rb"))
    s = data.get("settings", {})
    settings = Settings(
        default_panel=s.get("default_panel", "decision"),
        router_model=s.get("router_model", ""),
        chair_model=s.get("chair_model", ""),
        byte_cap=int(s.get("byte_cap", 200_000)),
        timeout=int(s.get("timeout", 180)),
    )
    panels = {}
    for name, p in data.get("panels", {}).items():
        members = [Member(name=m["name"], model=m["model"], system=m["system"])
                   for m in p.get("members", [])]
        panels[name] = Panel(name=name, description=p.get("description", ""),
                             members=members, default_rigor=p.get("default_rigor", "daily"))
    return settings, panels


def truncate(text: str, cap: int) -> str:
    b = text.encode("utf-8", errors="ignore")
    if len(b) <= cap:
        return text
    head = b[: cap // 2].decode("utf-8", errors="ignore")
    tail = b[-cap // 2:].decode("utf-8", errors="ignore")
    return f"{head}\n\n... [input truncated, {len(b)} bytes total] ...\n\n{tail}"
