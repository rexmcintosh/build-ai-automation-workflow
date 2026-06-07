"""Thin wrapper around headless `claude -p`. Authenticates via the Max session
(no API key). Default has NO tools; pass allowed_tools for steps that need MCP/file writes."""
from __future__ import annotations

import shutil
import subprocess
from typing import List, Optional, Sequence


class LLMError(RuntimeError):
    pass


def _claude_bin() -> str:
    return shutil.which("claude") or "/usr/bin/claude"


def build_argv(prompt: str, model: str, allowed_tools: Optional[Sequence[str]] = None,
               skip_permissions: bool = False) -> List[str]:
    argv = [_claude_bin(), "-p", prompt, "--model", model, "--output-format", "text"]
    if allowed_tools:
        argv += ["--allowedTools", *allowed_tools]
    if skip_permissions:
        argv += ["--dangerously-skip-permissions"]
    return argv


def run(prompt: str, model: str, allowed_tools: Optional[Sequence[str]] = None,
        skip_permissions: bool = False, timeout: int = 600) -> str:
    proc = subprocess.run(
        build_argv(prompt, model, allowed_tools, skip_permissions),
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise LLMError(f"claude exited {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout.strip()
