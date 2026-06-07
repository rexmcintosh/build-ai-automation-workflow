"""Loom orchestrator. v0 shadow mode: gate → spool → distill → write learnings
artifact → mark 'distilled'. Live weave (Opus → wiki/.claude) is added in v1."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from . import llm
from .discovery import find_pending, session_id_for
from .gate import scan_clean
from .spool import spool_copy
from .state import LoomState
from .transcript import extract_text

_PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class Config:
    projects_dir: Path
    loom_dir: Path
    state_path: Path


def _distill_prompt(text: str) -> str:
    return (_PROMPTS / "distill.md").read_text().replace("{{TRANSCRIPT}}", text)


def absorb(cfg: Config, shadow: bool = True) -> Dict[str, int]:
    state = LoomState(cfg.state_path)
    learnings_dir = cfg.loom_dir / "learnings"
    spool_dir = cfg.loom_dir / "spool"
    quarantine_dir = cfg.loom_dir / "quarantine"
    summary = {"distilled": 0, "quarantined": 0, "failed": 0}

    for transcript in find_pending(cfg.projects_dir, state):
        sid = session_id_for(transcript)

        # Stage 0 gate — never feed a flagged transcript to an LLM
        if not scan_clean(transcript):
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(transcript, quarantine_dir / transcript.name)
            summary["quarantined"] += 1
            continue

        spool_copy(transcript, spool_dir)

        # Stage 1 distill (Sonnet)
        try:
            text = extract_text(transcript)
            learnings = llm.run(_distill_prompt(text), model="sonnet")
        except Exception:
            logging.exception("distill failed for %s", transcript)
            summary["failed"] += 1
            continue  # stays pending; spooled copy preserves it

        # Stage 2.0 gate — scan the learnings artifact before persisting
        learnings_dir.mkdir(parents=True, exist_ok=True)
        artifact = learnings_dir / f"{sid}.md"
        tmp_artifact = learnings_dir / f"{sid}.tmp"
        tmp_artifact.write_text(learnings + "\n")
        if not scan_clean(tmp_artifact):
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_artifact), str(quarantine_dir / f"{sid}.md"))
            summary["quarantined"] += 1
            continue  # stays pending; no unscanned artifact left in learnings/
        tmp_artifact.rename(artifact)  # atomic on POSIX, only after the gate passes

        state.advance(sid, "distilled")
        summary["distilled"] += 1
        # v1 will continue here: route + Opus weave → 'weaved' → commit → 'committed'

    return summary
