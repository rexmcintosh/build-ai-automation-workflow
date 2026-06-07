"""Turn a raw .jsonl transcript into distill input: user/assistant text, with
large tool_result blobs truncated to bound cost. Defensive against schema drift."""
from __future__ import annotations

import json
from pathlib import Path

MAX_TOOL_RESULT_CHARS = 500
_ROLES = ("user", "assistant")


def _block_text(block: dict, max_tool_chars: int) -> str:
    btype = block.get("type")
    if btype == "text":
        return str(block.get("text", ""))
    if btype == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):  # content can itself be blocks
            content = " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
        return str(content)[:max_tool_chars]
    return ""


def _content_text(message: dict, max_tool_chars: int) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [_block_text(b, max_tool_chars) for b in content if isinstance(b, dict)]
        return " ".join(p for p in parts if p)
    return ""


def extract_text(transcript: Path, max_tool_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    lines = []
    for raw in Path(transcript).read_text().splitlines():
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        role = rec.get("type") or rec.get("role")
        if role not in _ROLES:
            continue
        text = _content_text(rec.get("message", rec), max_tool_chars)
        if text:
            lines.append(f"[{role}] {text}")
    return "\n".join(lines)
