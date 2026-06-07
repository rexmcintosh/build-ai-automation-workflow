"""Copy a transcript into an immutable local spool before processing, so a
persistently-failing transcript is not lost to the 90-day retention window.
Idempotent: never overwrites an existing spooled copy."""
from __future__ import annotations

import shutil
from pathlib import Path


def spool_copy(transcript: Path, spool_dir: Path) -> Path:
    spool_dir = Path(spool_dir)
    spool_dir.mkdir(parents=True, exist_ok=True)
    dest = spool_dir / Path(transcript).name
    if not dest.exists():
        shutil.copy2(transcript, dest)
    return dest
