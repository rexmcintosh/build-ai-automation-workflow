# loom/backends.py
"""Pluggable text->text completion. Weaving never touches the filesystem, so the
backend is swappable: `claude` runs the Max session via `claude -p`; `venice` runs
the same-tier models through Venice on DIEM. Role -> model is per backend."""
from __future__ import annotations

from typing import Optional

from . import llm
from .venice import VeniceClient

CLAUDE_MODELS = {"distill": "sonnet", "route": "haiku", "weave": "opus"}
VENICE_MODELS = {"route": "gemini-3-5-flash", "weave": "claude-opus-4-8"}


class Backend:
    name = "base"
    def complete(self, role: str, system: str, user: str, json_mode: bool = False) -> str:
        raise NotImplementedError


class ClaudeBackend(Backend):
    name = "claude"
    def complete(self, role: str, system: str, user: str, json_mode: bool = False) -> str:
        model = CLAUDE_MODELS[role]
        prompt = f"{system}\n\n{user}"            # claude -p takes one stdin prompt
        return llm.run(prompt, model=model)


class VeniceBackend(Backend):
    name = "venice"
    def __init__(self, api_key: str) -> None:
        self._client = VeniceClient(api_key)
    def complete(self, role: str, system: str, user: str, json_mode: bool = False) -> str:
        return self._client.complete(VENICE_MODELS[role], system, user, json_mode=json_mode)


def get_backend(name: str, api_key: Optional[str] = None) -> Backend:
    if name == "claude":
        return ClaudeBackend()
    if name == "venice":
        import os
        return VeniceBackend(api_key or os.environ.get("VENICE_API_KEY", ""))
    raise ValueError(f"unknown backend: {name}")
