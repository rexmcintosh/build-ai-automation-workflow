# loom/pending.py
"""What is waiting on Rex, in a shape a human can answer.

Two jobs:
  * cluster_blocked() — collapse quarantined learnings into DECISIONS. The same
    fact is routinely re-captured across sessions (one VPS onboarding rule showed
    up 6 times across 4 target articles), and showing six near-identical rows is
    exactly the noise that trains someone to ignore the surface. One fact = one
    decision, with every destination listed.
  * pending_summary() — the whole picture (articles landing + decisions needed)
    for the nightly briefing line and the review page.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

# Words too common to carry meaning when comparing two learnings.
_STOP = set("the a an of to in is are and or for on with that this it be as by from "
            "must all other only when new during its into via".split())

# Two learnings whose meaningful words overlap this much are the same fact.
# Calibrated on live data: the 6 VPS-onboarding captures sit at 0.42-1.00 to each
# other, while the unrelated macOS learning never exceeds 0.20 to any of them.
SAME_FACT = 0.40


def _learning_body(text: str) -> str:
    m = re.search(r"learning:\s*>?\s*(.+?)(?:\n\s*(?:route|type|subject):|\Z)", text, re.S)
    return re.sub(r"\s*\n\s*", " ", (m.group(1) if m else text)).strip().strip('"')


def _subject(text: str) -> str:
    m = re.search(r"subject:\s*(.+)", text)
    return m.group(1).strip() if m else "learning"


def _signature(text: str) -> set:
    return {w for w in re.findall(r"[a-z_]{3,}", _learning_body(text).lower())
            if w not in _STOP}


def cluster_blocked(items: List[dict]) -> List[dict]:
    """Group quarantined learnings into distinct decisions, most-repeated first."""
    if not items:
        return []
    sigs = [_signature(i.get("text", "")) for i in items]
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(items)):                       # single-linkage union-find
        for j in range(i + 1, len(items)):
            union = sigs[i] | sigs[j]
            if union and len(sigs[i] & sigs[j]) / len(union) >= SAME_FACT:
                parent[find(i)] = find(j)

    groups: Dict[int, list] = {}
    for idx, item in enumerate(items):
        groups.setdefault(find(idx), []).append(item)

    out = []
    for members in groups.values():
        # Quote the fullest phrasing — the terse re-captures lose context.
        best = max(members, key=lambda m: len(_learning_body(m.get("text", ""))))
        out.append({
            "subject": _subject(best.get("text", "")),
            "body": _learning_body(best.get("text", "")),
            "targets": sorted({m.get("target", "") for m in members if m.get("target")}),
            "ids": sorted(m.get("id", "") for m in members),
            "n": len(members),
        })
    out.sort(key=lambda g: (-g["n"], g["subject"]))
    return out


def _learning_block(learnings_dir: Path, lid: str) -> str:
    """The verbatim text of one learning — what a human needs to judge it."""
    try:
        sid, n = lid.split("#")
        blocks = re.split(r"(?m)^- type:", (Path(learnings_dir) / f"{sid}.md")
                          .read_text(encoding="utf-8"))
        return ("- type:" + blocks[int(n) + 1]).strip()
    except (ValueError, OSError, IndexError):
        return ""


def pending_summary(*, wiki_root, ledger_path, learnings_dir, loom_dir, today) -> dict:
    """Everything waiting on a human, in one payload. Shared by the briefing line
    and the review page so the two can never disagree about what's pending."""
    from .autopromote import auto_promote_check, is_held      # local: avoid import cycle
    from .ledger import WeaveLedger
    from .promote import _git

    wiki_root = Path(wiki_root)
    check = auto_promote_check(wiki_root=wiki_root, loom_dir=loom_dir, today=today)

    added = set()
    try:
        for line in _git(wiki_root, "diff", "--name-status",
                         "master..loom-shadow").stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2 and parts[0] == "A":
                added.add(parts[1])
    except Exception:                                          # noqa: BLE001
        pass

    articles = [{"file": f, "slug": Path(f).stem,
                 "dir": (f.split("/")[0] if "/" in f else "root"),
                 "new": f in added}
                for f in check["articles"]]

    try:
        led = WeaveLedger(ledger_path)
        blocked = [{"id": lid, "target": led.entry(lid).get("target", ""),
                    "reason": reason, "text": _learning_block(learnings_dir, lid)}
                   for lid, reason in led.quarantined()]
    except Exception:                                          # noqa: BLE001
        blocked = []

    return {
        "commits": check["commits"],
        "articles": articles,
        "new": sum(1 for a in articles if a["new"]),
        "updated": sum(1 for a in articles if not a["new"]),
        "decisions": cluster_blocked(blocked),
        "held": is_held(loom_dir, today),
        "staged_claude": check["staged"],
        "would_promote": check["go"],
    }


def briefing_line(payload: dict, url: str = "") -> str:
    """The single loom line for the 07:00 briefing — or "" to stay silent.

    Composed in code, never by the briefing model: these are counts a person acts
    on, and a paraphrase ("a bunch of articles") would be worse than useless.
    Returns at most two short lines to respect the briefing's phone-glanceable
    six-line budget.
    """
    promo = payload.get("promoted") or {}
    landed = promo.get("articles") or []
    decisions = payload.get("decisions") or []
    staged = payload.get("staged_claude") or []
    held = payload.get("held")

    n = len(landed)
    noun = "article" if n == 1 else "articles"

    if held:
        head = f"held — {n} {noun} waiting · reply GO to promote tonight"
    elif staged:
        head = f"{n} {noun} waiting — a memory/skill change needs you first"
    elif promo.get("promoted") and n:
        head = f"{n} {noun} landed in your wiki"
    elif decisions:
        head = "nothing landed"
    else:
        return ""                      # nothing happened and nothing is asked

    parts = [f"🧵 {head}"]
    if decisions:
        names = " · ".join(d.get("subject", "?") for d in decisions[:3])
        more = f" +{len(decisions) - 3}" if len(decisions) > 3 else ""
        parts.append(f"   {len(decisions)} need your call: {names}{more}")
    if url:
        parts.append(f"   {url}")
    return "\n".join(parts)
