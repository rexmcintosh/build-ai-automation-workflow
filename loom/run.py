# loom/run.py
"""Loom orchestrator. v0 distill (gate -> spool -> distill -> learnings artifact)
plus v1 weave (route -> group/cap -> weave -> commit on loom-shadow). Shadow mode
keeps v0 behavior; live mode runs the weave."""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yaml

from .backends import get_backend
from .discovery import find_pending, session_id_for
from .fingerprint import learning_id
from .gate import scan_clean
from .gitio import ShadowRepo
from .indexer import rebuild_backlinks, upsert_index_entry
from .ledger import WeaveLedger
from .route import confirm_route
from .spool import spool_copy
from .state import LoomState
from .transcript import extract_text
from .weave import weave_target
from . import llm  # noqa: F401  (kept for monkeypatch compatibility in tests)

_PROMPTS = Path(__file__).parent / "prompts"
_STAGE_ORDER = {"pending": 0, "distilled": 1, "weaved": 2, "committed": 3, "quarantined": 9}


@dataclass
class Config:
    projects_dir: Path
    loom_dir: Path
    state_path: Path
    wiki_worktree: Optional[Path] = None  # loom-shadow worktree; weave commits land here
    wiki_master: Optional[Path] = None    # master worktree; promote merges/commits here
    claude_dir: Optional[Path] = None  # claude_dir: used by promote (CLI), not by absorb/weave
    ledger_path: Optional[Path] = None


def _distill_prompt(text: str) -> str:
    return (_PROMPTS / "distill.md").read_text(encoding="utf-8").replace("{{TRANSCRIPT}}", text)


def _parse_learnings(artifact_text: str) -> List[dict]:
    try:
        data = yaml.safe_load(artifact_text)
    except Exception:
        return []
    return [d for d in (data or []) if isinstance(d, dict) and d.get("learning")]


def _index_listing(wiki: Path) -> str:
    idx = wiki / "_index.md"
    return idx.read_text(encoding="utf-8") if idx.exists() else ""


def absorb(cfg: Config, shadow: bool = True, backend: str = "claude",
           max_targets: int = 10, today: str = "", deadline_seconds=None,
           max_per_target: int = 4, distill: bool = True) -> Dict[str, object]:
    state = LoomState(cfg.state_path)
    learnings_dir = cfg.loom_dir / "learnings"
    spool_dir = cfg.loom_dir / "spool"
    quarantine_dir = cfg.loom_dir / "quarantine"
    summary = {"distilled": 0, "quarantined": 0, "failed": 0,
               "committed": 0, "deferred": 0, "rejected": 0, "deadline_hit": False,
               "limit_hit": False}

    start = time.monotonic()
    def _expired() -> bool:
        return deadline_seconds is not None and (time.monotonic() - start) > deadline_seconds

    # ---------- Stage 1: distill (v0) ----------
    # `distill=False` (used by `backfill`) weaves the already-distilled backlog only — it never
    # tries to distill new pending sessions (the nightly `absorb` on the Claude backend does that).
    be = get_backend(backend)
    if distill:
        for transcript in find_pending(cfg.projects_dir, state):
            if _expired():
                summary["deadline_hit"] = True
                break
            sid = session_id_for(transcript)
            if _STAGE_ORDER[state.state_of(sid)] >= _STAGE_ORDER["distilled"]:
                continue
            if not scan_clean(transcript):
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(transcript, quarantine_dir / transcript.name)
                state.advance(sid, "quarantined")
                summary["quarantined"] += 1
                continue
            spool_copy(transcript, spool_dir)
            try:
                text = extract_text(transcript)
                learnings = be.complete("distill", "Extract durable learnings.", _distill_prompt(text))
            except llm.UsageLimitError:
                summary["limit_hit"] = True
                break
            except Exception:
                logging.exception("distill failed for %s", transcript)
                summary["failed"] += 1
                continue
            learnings_dir.mkdir(parents=True, exist_ok=True)
            artifact = learnings_dir / f"{sid}.md"
            tmp_artifact = learnings_dir / f"{sid}.tmp"
            tmp_artifact.write_text(learnings + "\n", encoding="utf-8")
            if not scan_clean(tmp_artifact):
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(tmp_artifact), str(quarantine_dir / f"{sid}.md"))
                state.advance(sid, "quarantined")
                summary["quarantined"] += 1
                continue
            tmp_artifact.rename(artifact)
            state.advance(sid, "distilled")
            summary["distilled"] += 1

    if summary["limit_hit"]:
        return summary
    if shadow:
        return summary

    # ---------- Stage 2: weave (v1) ----------
    try:
        _weave_all(cfg, state, backend, max_targets, max_per_target, today, summary, _expired)
    except llm.UsageLimitError:
        summary["limit_hit"] = True
    return summary


def _weave_all(cfg, state, backend_name, max_targets, max_per_target, today, summary,
               expired: Callable[[], bool]):
    repo = ShadowRepo(cfg.wiki_worktree, base="master")
    ledger = WeaveLedger(cfg.ledger_path)
    ledger.reconcile_from_git(repo.committed_ids())          # git is authoritative
    be = get_backend(backend_name)
    index_listing = _index_listing(cfg.wiki_worktree)
    learnings_dir = cfg.loom_dir / "learnings"

    sessions = [sid for sid in _sessions_at_least(state, "distilled")
                if _STAGE_ORDER[state.state_of(sid)] < _STAGE_ORDER["committed"]]
    sessions.sort(key=lambda s: (learnings_dir / f"{s}.md").stat().st_mtime
                  if (learnings_dir / f"{s}.md").exists() else 0)

    buckets: Dict[str, List[dict]] = {}
    dirs: Dict[str, str] = {}
    session_learnings: Dict[str, List[str]] = {}
    for sid in sessions:
        art = learnings_dir / f"{sid}.md"
        if not art.exists():
            state.advance(sid, "committed")                 # zero-learning session
            continue
        items = _parse_learnings(art.read_text(encoding="utf-8"))
        if not items:
            state.advance(sid, "committed")
            continue
        ids_here = []
        for idx, learning in enumerate(items):
            lid = learning_id(sid, idx)
            ids_here.append(lid)
            if ledger.status_of(lid) in ("committed", "rejected"):
                continue
            cached = ledger.entry(lid)
            if cached.get("target"):              # routed in a prior run — reuse, no model call
                route = {"target": cached["target"], "action": cached.get("action", "update")}
            else:
                route = confirm_route(be, learning, index_listing)
                if not route:
                    ledger.defer(lid, "unroutable")
                    continue
                ledger.plan(lid, route["target"], route["action"])
            entry = dict(learning)
            entry.update(id=lid, target=route["target"],
                         directory=route["target"].split("/", 1)[0])
            buckets.setdefault(route["target"], []).append(entry)
            dirs[route["target"]] = entry["directory"]
        session_learnings[sid] = ids_here

    targets = list(buckets.keys())
    for target in targets[:max_targets]:
        # Cap learnings woven into ONE target per run: keeps each weave a small, reviewable
        # diff and stops a popular pre-existing article from triggering a bisect/cost storm.
        # The overflow is deferred and drains over subsequent runs.
        weave_now = buckets[target][:max_per_target]
        for entry in buckets[target][max_per_target:]:
            ledger.defer(entry["id"], "per-target cap")
            summary["deferred"] += 1
        if expired():
            summary["deadline_hit"] = True
            for entry in weave_now:
                ledger.defer(entry["id"], "run deadline")
                summary["deferred"] += 1
            continue
        try:
            res = weave_target(be, repo, ledger, target, dirs[target], weave_now, today=today)
        except llm.UsageLimitError:
            raise
        except Exception:
            logging.exception("weave_target failed for %s", target)
            for entry in weave_now:
                ledger.defer(entry["id"], "weave exception")
                summary["deferred"] += 1
            continue
        summary["committed"] += len(res["committed"])
        summary["rejected"] += len(res["rejected"])
        if res["committed"]:
            slug = Path(target).stem
            committed_set = set(res["committed"])
            first = next((b for b in weave_now if b["id"] in committed_set), weave_now[0])
            upsert_index_entry(cfg.wiki_worktree, slug, dirs[target], first["learning"], today=today)
    for target in targets[max_targets:]:
        for entry in buckets[target]:
            ledger.defer(entry["id"], "per-run cap")
            summary["deferred"] += 1

    rebuild_backlinks(cfg.wiki_worktree)
    repo.commit_paths(["_index.md", "_backlinks.json"], "index: rebuild _index/_backlinks")

    for sid, ids in session_learnings.items():
        statuses = [ledger.status_of(i) for i in ids]
        if all(s in ("committed", "rejected") for s in statuses):
            state.advance(sid, "committed")
        # 'weaved' is reachable only if a future change separates write from commit; today commit_file is atomic so learnings go planned->committed directly.
        elif all(s in ("committed", "rejected", "woven") for s in statuses):
            state.advance(sid, "weaved")
        # else stays distilled

    summary["rejected_items"] = ledger.rejected()
    summary["shadow_commits"] = repo.commits_since()
    oldest = repo.oldest_unpromoted_epoch()
    summary["oldest_age_days"] = int((time.time() - oldest) / 86400) if oldest else 0


def _sessions_at_least(state: LoomState, floor: str) -> List[str]:
    return [sid for sid, e in state._data.items()
            if _STAGE_ORDER.get(e.get("state", "pending"), 0) >= _STAGE_ORDER[floor]]
