"""Per-session state machine. Each transcript advances pending → distilled →
weaved → committed. Writes are atomic; reruns resume from the last clean state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

STATES = ("pending", "distilled", "weaved", "committed")


class LoomState:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: Dict[str, dict] = {}
        if self.path.exists():
            self._data = json.loads(self.path.read_text() or "{}")

    def state_of(self, session_id: str) -> str:
        return self._data.get(session_id, {}).get("state", "pending")

    def is_complete(self, session_id: str) -> bool:
        """True when no further work is needed in the current mode.

        v0 shadow mode ends at 'distilled'; v1 will end at 'committed'.
        Treat every state at or past 'distilled' as complete so that reruns
        skip already-processed sessions (idempotency requirement)."""
        return self.state_of(session_id) in ("distilled", "weaved", "committed")

    def advance(self, session_id: str, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state: {state}")
        self._data.setdefault(session_id, {})["state"] = state
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")
        tmp.replace(self.path)  # atomic on POSIX
