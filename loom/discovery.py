"""Find session transcripts that still need work (delta via LoomState)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from .state import LoomState


def session_id_for(transcript: Path) -> str:
    return Path(transcript).stem


def find_pending(projects_dir: Path, state: LoomState) -> List[Path]:
    transcripts = sorted(Path(projects_dir).glob("*/*.jsonl"))
    return [t for t in transcripts if not state.is_complete(session_id_for(t))]
