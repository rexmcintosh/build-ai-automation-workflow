# loom/backends.py
"""Pluggable text->text completion. Weaving never touches the filesystem, so the
backend is swappable: `claude` runs the Max session via `claude -p`; `venice` runs
the same-tier models through Venice on DIEM. Role -> model is per backend."""
from __future__ import annotations

from typing import Optional

from . import llm
from .venice import VeniceClient

CLAUDE_MODELS = {"distill": "sonnet", "route": "haiku", "weave": "opus"}
# Route/distill are validated-output, high-volume stages — priced for volume
# (deepseek-v4-flash: 1M ctx, ~11x cheaper than the gemini flash it replaced).
# Weave writes the wiki and stays on the strongest model pending the 2026-08
# bake-off (kimi-k2-6 / glm-5 / deepseek-v4-pro vs opus).
VENICE_MODELS = {"distill": "deepseek-v4-flash", "route": "deepseek-v4-flash",
                 "weave": "claude-opus-4-8"}


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
        return self._client.complete(VENICE_MODELS[role], system, user,
                                     json_mode=json_mode, task=role)


def get_backend(name: str, api_key: Optional[str] = None) -> Backend:
    if name == "claude":
        return ClaudeBackend()
    if name == "venice":
        import os
        # One Venice key per project; VENICE_API_KEY remains the fallback so
        # this is safe to deploy before the loom key is minted.
        key = (api_key
               or os.environ.get("VENICE_LOOM_KEY")
               or os.environ.get("VENICE_API_KEY", ""))
        return VeniceBackend(key)
    raise ValueError(f"unknown backend: {name}")
