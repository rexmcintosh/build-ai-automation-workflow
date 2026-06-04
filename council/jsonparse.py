"""Lenient JSON extraction for model responses.

Even with Venice's `response_format: json_object`, some models (notably the
Claude family, e.g. claude-opus-4-8) intermittently wrap their JSON in a
markdown ```json ... ``` fence or surround it with prose. A strict
`json.loads` then fails and the whole panelist/chair result is discarded. This
helper recovers the JSON object from those shapes.
"""
from __future__ import annotations
import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def loads_lenient(raw):
    """Parse a JSON object from a model response, tolerating markdown code
    fences and surrounding prose. Raises ValueError if none can be found."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty or non-string response")
    text = raw.strip()
    # 1. The happy path: it's already clean JSON.
    try:
        return json.loads(text)
    except ValueError:
        pass
    # 2. A ```json ... ``` (or bare ``` ... ```) fenced block.
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except ValueError:
            pass
    # 3. Last resort: the outermost {...} span (handles prose on either side).
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        return json.loads(text[start:end + 1])
    raise ValueError("no JSON object found in response")
