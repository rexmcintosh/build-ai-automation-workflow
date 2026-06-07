"""Deterministic secret gate. Wraps `detect-secrets scan <file>` and returns
True only when the scan finds zero secrets. This is the real control; the LLM
sanitize pass is a second layer, never the gate. Fail-closed: any error → not clean."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def scan_clean(path: Path) -> bool:
    # Discover detect-secrets-hook from venv if not on PATH
    venv_dir = Path(sys.executable).parent
    detect_secrets_hook = venv_dir / "detect-secrets-hook"

    if not detect_secrets_hook.exists():
        return False  # fail-closed

    try:
        proc = subprocess.run(
            [str(detect_secrets_hook), "--json", str(path)],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False  # fail-closed

    # detect-secrets-hook returns 0 if no secrets, non-zero if secrets found
    if proc.returncode == 0:
        return True  # No secrets found

    # Return code != 0 means secrets were found
    if not proc.stdout:
        return False  # Error or other issue

    try:
        results = json.loads(proc.stdout).get("results", {})
    except json.JSONDecodeError:
        return False
    return not any(results.values())
