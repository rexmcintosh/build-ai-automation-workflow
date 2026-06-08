from __future__ import annotations
import re

_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
_DOC_SEGMENTS = {"docs", "spec", "specs", "plan", "plans"}
_FILE_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+?)\s*$", re.MULTILINE)


def classify_path(path: str) -> str:
    """Classify a repo-relative path as 'doc' or 'code'.

    doc  = a documentation/spec/plan file: extension in _DOC_EXTS, OR any
           directory segment in _DOC_SEGMENTS (docs/ specs/ plans/ ...).
    code = everything else (the default).
    """
    p = (path or "").strip().strip("/")
    if not p:
        return "code"
    segments = [s.lower() for s in p.split("/") if s]
    if not segments:
        return "code"
    name = segments[-1]
    dot = name.rfind(".")
    ext = name[dot:] if dot > 0 else ""
    if ext in _DOC_EXTS:
        return "doc"
    if any(seg in _DOC_SEGMENTS for seg in segments[:-1]):
        return "doc"
    return "code"


def split_diff_by_type(diff: str) -> tuple[str, str]:
    """Split a unified diff into (code_diff, doc_diff) by classifying each file
    on its `diff --git a/... b/...` header. Either bucket may be empty."""
    if not diff:
        return "", ""
    matches = list(_FILE_HEADER.finditer(diff))
    if not matches:
        return "", ""
    code_parts: list[str] = []
    doc_parts: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(diff)
        section = diff[start:end]
        path = m.group("b")  # the new-side path
        (doc_parts if classify_path(path) == "doc" else code_parts).append(section)
    return "".join(code_parts), "".join(doc_parts)
