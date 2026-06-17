# loom/indexer.py
"""Maintain the wiki's _backlinks.json (fully regenerated, deterministic) and
_index.md (incremental: a new article gets one summary line under its section).
Summaries for NEW articles are passed in by the caller; existing lines are left
for hand-review on loom-shadow."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
SUMMARY_LIMIT = 110


def clean_summary(text: str, limit: int = SUMMARY_LIMIT) -> str:
    """One-line index summary: collapse whitespace, truncate at a word boundary with an
    ellipsis (never mid-word). Strips trailing markdown/backtick noise from the cut."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-`\"'")
    return f"{cut}…"


SECTION_FOR = {
    "people": "People", "companies": "Companies", "projects": "Projects",
    "places": "Places", "eras": "Eras", "transitions": "Transitions",
    "decisions": "Decisions", "philosophies": "Philosophies", "patterns": "Patterns",
    "skills": "Skills", "tools": "Tools", "relationships": "Relationships",
    "health": "Health",
}


def _articles(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*.md")
                  if not p.name.startswith("_") and ".git" not in p.parts)


def rebuild_backlinks(root: Path) -> None:
    root = Path(root)
    back: Dict[str, set] = {}
    for art in _articles(root):
        slug = art.stem
        for m in _WIKILINK.finditer(art.read_text(encoding="utf-8")):
            target = m.group(1).strip()
            if target and target != slug:
                back.setdefault(target, set()).add(slug)
    out = {k: sorted(v) for k, v in sorted(back.items())}
    (root / "_backlinks.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def upsert_index_entry(root: Path, slug: str, directory: str, summary: str, today: str) -> None:
    root = Path(root)
    idx = root / "_index.md"
    text = idx.read_text(encoding="utf-8") if idx.exists() else "# RexBrain — Master Index\n"
    if f"[[{slug}]]" in text:                      # already indexed — idempotent
        return
    section = SECTION_FOR.get(directory, "Unsorted")
    line = f"- [[{slug}]] — {clean_summary(summary)}"
    heading = f"## {section}"
    lines = text.splitlines()
    if heading in lines:
        at = lines.index(heading) + 1              # insert right under the heading
        lines.insert(at, line)
    else:
        lines += ["", heading, line]
    text = "\n".join(lines) + ("\n" if not text.endswith("\n") else "")
    text = re.sub(r"(?m)^(last_updated:).*$", rf"\1 {today}", text)
    text = re.sub(r"(?im)(last updated:)\s*[0-9-]+", rf"\1 {today}", text)  # intro line, if present
    text = _bump_total_pages(text)
    idx.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _bump_total_pages(text: str) -> str:
    """Increment the curated article count by one (frontmatter + intro line), preserving the
    wiki's editorial counting convention rather than recomputing from a file glob."""
    def _inc(m):
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    text = re.sub(r"(?m)^(total_pages:\s*)(\d+)", _inc, text)
    text = re.sub(r"(?i)(Total pages:\s*)(\d+)", _inc, text)
    return text
