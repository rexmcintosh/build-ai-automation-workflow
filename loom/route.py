# loom/route.py
"""Route-confirm: a model picks the target file for one learning. Deterministic
fallback to the distill-suggested `route` when the model output is unparseable;
None when there is no usable suggestion either (caller defers the learning)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_PROMPTS = Path(__file__).parent / "prompts"
_JSON_RE = re.compile(r"\{.*\}", re.S)


def _suggested_target(learning: dict) -> Optional[dict]:
    route = (learning.get("route") or "").strip()
    if not route:
        return None
    slug = route.split("/", 1)[1] if route.startswith("wiki/") else route
    slug = slug if slug.endswith(".md") else f"{slug}.md"
    return {"target": slug, "action": "update", "cross_links": []}


def confirm_route(backend, learning: dict, index_listing: str) -> Optional[dict]:
    prompt = (_PROMPTS / "route.md").read_text()
    user = prompt.replace("{{LEARNING}}", json.dumps(learning, ensure_ascii=False)) \
                 .replace("{{INDEX}}", index_listing or "(empty)")
    try:
        raw = backend.complete("route", "Route one learning. Output only JSON.", user, json_mode=True)
        m = _JSON_RE.search(raw)
        data = json.loads(m.group(0)) if m else {}
        if data.get("target"):
            return {"target": data["target"],
                    "action": data.get("action", "update"),
                    "cross_links": data.get("cross_links", [])}
    except Exception:
        pass
    return _suggested_target(learning)
