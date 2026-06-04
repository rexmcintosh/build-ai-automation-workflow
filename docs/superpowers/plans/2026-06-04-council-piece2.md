# Council Piece 2 — Review Beyond Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the council to review design docs / specs / plans — a `spec-review` panel, path-based routing, in-package PR-review orchestration with a thin CI shim, and a combined PR comment where doc findings are advisory.

**Architecture:** Reuse the Piece 1 engine (`run_panel` → `synthesize` → `render`) unchanged. Add `council/routing.py` (classify a path / split a diff), the `spec-review` panel (data), `council/render.render_combined`, and `council/review.run_pr_review` (split the diff → run `code-review` on code (gated) + `spec-review` on docs (advisory) → one comment). The per-repo `scripts/venice_review.py` becomes a thin shim so future upgrades reach all repos via a tag re-pin.

**Tech Stack:** Python 3.12, `requests`, `tomllib` (stdlib), `pytest`. Dev venv at `.venv/` — run tests as `.venv/bin/python -m pytest` (no system pip on this host).

**Design source of truth:** `docs/superpowers/specs/2026-06-04-council-piece2-review-beyond-code-design.md`. Read it first.

---

## File Structure

```
council/
  routing.py        # NEW — classify_path(), split_diff_by_type()
  review.py         # NEW — run_pr_review(): split → code-review (gate) + spec-review (advisory) → combined body
  render.py         # MODIFY — add render_combined()
  panels.toml       # MODIFY — add [panels.spec-review] (4 seats)
  cli.py            # MODIFY — `review` auto-picks panel by path when --panel omitted
  __init__.py       # MODIFY (Task 7) — __version__ = "0.2.0"
pyproject.toml      # MODIFY (Task 7) — version = "0.2.0"
setup/templates/
  venice_review.py  # MODIFY — reduce to a thin shim over council.review.run_pr_review
  venice-review.yml # MODIFY (Task 7) — re-pin install to @council-v0.2.0
tests/
  test_routing.py            # NEW
  test_review.py             # NEW
  test_render.py             # MODIFY — render_combined
  test_config.py             # MODIFY — spec-review panel loads
  test_cli.py                # MODIFY — review auto-pick
  test_venice_review_refactor.py  # MODIFY — shim delegates to run_pr_review
```

---

## Task 1: Routing — `classify_path` + `split_diff_by_type`

**Files:**
- Create: `council/routing.py`
- Test: `tests/test_routing.py`

- [ ] **Step 1: Write the failing test — `tests/test_routing.py`**

```python
from council.routing import classify_path, split_diff_by_type


def test_classify_by_extension():
    assert classify_path("README.md") == "doc"
    assert classify_path("notes/today.rst") == "doc"
    assert classify_path("a/b/thing.txt") == "doc"
    assert classify_path("design.adoc") == "doc"
    assert classify_path("src/app.py") == "code"
    assert classify_path("lib/util.js") == "code"


def test_classify_by_directory_segment():
    assert classify_path("docs/architecture.png") == "doc"   # under docs/
    assert classify_path("specs/api/example.py") == "doc"     # under specs/
    assert classify_path("plans/q3.json") == "doc"
    assert classify_path("plan/rollout.yaml") == "doc"
    assert classify_path("src/docs_helper.py") == "code"      # 'docs' only as a substring, not a segment


def test_classify_empty_is_code():
    assert classify_path("") == "code"
    assert classify_path("   ") == "code"


CODE_FILE = (
    "diff --git a/src/app.py b/src/app.py\n"
    "index 111..222 100644\n--- a/src/app.py\n+++ b/src/app.py\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)
DOC_FILE = (
    "diff --git a/docs/design.md b/docs/design.md\n"
    "index 333..444 100644\n--- a/docs/design.md\n+++ b/docs/design.md\n"
    "@@ -1 +1 @@\n-old doc\n+new doc\n"
)


def test_split_mixed_diff():
    code_diff, doc_diff = split_diff_by_type(CODE_FILE + DOC_FILE)
    assert "src/app.py" in code_diff and "docs/design.md" not in code_diff
    assert "docs/design.md" in doc_diff and "src/app.py" not in doc_diff


def test_split_code_only():
    code_diff, doc_diff = split_diff_by_type(CODE_FILE)
    assert "src/app.py" in code_diff
    assert doc_diff == ""


def test_split_doc_only():
    code_diff, doc_diff = split_diff_by_type(DOC_FILE)
    assert code_diff == ""
    assert "docs/design.md" in doc_diff


def test_split_empty_or_garbage():
    assert split_diff_by_type("") == ("", "")
    assert split_diff_by_type("not a diff at all") == ("", "")
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_routing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'council.routing'`.

- [ ] **Step 3: Write `council/routing.py`**

```python
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
```

- [ ] **Step 4: Run the test, verify it PASSES**

Run: `.venv/bin/python -m pytest tests/test_routing.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add council/routing.py tests/test_routing.py
git commit -m "feat(council): path/diff routing (classify_path, split_diff_by_type)"
```
End every commit message with a blank line then:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Task 2: The `spec-review` panel (data)

**Files:**
- Modify: `council/panels.toml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Add the failing test to `tests/test_config.py`** (append at end of file)

```python
def test_real_panels_include_spec_review():
    # loads the SHIPPED council/panels.toml (no path arg)
    settings, panels = load_panels()
    assert "spec-review" in panels
    p = panels["spec-review"]
    assert [m.name for m in p.members] == [
        "Editor", "Domain Skeptic", "Implementer", "Pre-mortem Adversary"]
    assert all(m.model and m.system for m in p.members)  # no empty models/personas
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_real_panels_include_spec_review -q`
Expected: FAIL — `KeyError: 'spec-review'`.

- [ ] **Step 3: Append the panel to `council/panels.toml`** (add at the end of the file)

```toml
# ---- spec-review -----------------------------------------------------------
[panels.spec-review]
description   = "Review a design doc / spec / plan for clarity, soundness, and buildability."
default_rigor = "daily"

[[panels.spec-review.members]]
name   = "Editor"
model  = "gemini-3-1-pro-preview"     # Google · clarity & completeness
system = """
You are a ruthless technical editor who has shipped 200 specs and knows that the
gap you skim past is the one that costs a week later. You are NOT here to praise the
writing. Laws: (1) Every requirement must be testable — if you can't tell whether
it's met, it's not a requirement. (2) Name what's missing, not just what's wrong.
(3) Ambiguity is a defect. Hunt: unstated assumptions, undefined terms, sections
that contradict each other, success criteria that aren't measurable, "TBD"s hiding
as prose. Never say "looks comprehensive" — point to the exact line and the exact
gap, or say the doc is complete and why.
"""

[[panels.spec-review.members]]
name   = "Domain Skeptic"
model  = "grok-4-3"                   # xAI · challenges premises
system = """
You are a skeptic who assumes the premise is wrong until shown otherwise. Your job is
not to improve the doc — it's to test whether it should exist as written. First ask:
is this solving the right problem? What is assumed true that nobody verified? What's
the cheaper thing that would make this unnecessary? Banned hedges: "it depends",
"seems reasonable". Name each load-bearing assumption and whether it would survive
five minutes of contact with reality.
"""

[[panels.spec-review.members]]
name   = "Implementer"
model  = "openai-gpt-53-codex"        # OpenAI · buildability
system = """
You are the engineer who has to BUILD this from the doc alone, with no author to ask.
You are NOT here to bless the plan. For every section ask: could I implement this as
written without guessing? What decision did the author leave to me that they should
have made? Where are the interfaces, data shapes, and error behaviors underspecified?
Flag each spot where you'd have to stop and ask a question — that question is the
defect. Never say "clear enough"; quote the line and say what you'd have to invent.
"""

[[panels.spec-review.members]]
name   = "Pre-mortem Adversary"
model  = "deepseek-v4-pro"            # DeepSeek · failure modes
system = """
You are running a pre-mortem: it is a year from now and the thing built from this doc
failed. Tell the story of how. What did the design believe that turned out false?
What edge case, scale point, or dependency did it ignore? What will the on-call
engineer curse at 2am? No reassurance, no compliments — just the concrete failure
paths and the early signal that would have warned us. If you genuinely can't find a
failure path, say so in one line.
"""
```

- [ ] **Step 4: Validate the TOML parses and the test passes**

Run: `.venv/bin/python -c "import tomllib; tomllib.load(open('council/panels.toml','rb')); print('ok')"`
Expected: `ok`.
Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS (all config tests green).

- [ ] **Step 5: Commit**

```bash
git add council/panels.toml tests/test_config.py
git commit -m "feat(council): spec-review panel (Editor/Skeptic/Implementer/Pre-mortem)"
```

---

## Task 3: `render_combined` (one body, multiple sections)

**Files:**
- Modify: `council/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Add the failing test to `tests/test_render.py`** (append; imports at top already include `render_markdown`, `gate_findings` — add `render_combined`)

At the top of `tests/test_render.py`, change the import line to also import `render_combined`:
```python
from council.render import render_markdown, gate_findings, render_combined
```

Append the test:
```python
def test_render_combined_orders_sections_and_marks_advisory():
    syn_a = Synthesis(recommendation="fix the bug", confidence=9, consensus=[],
                      disagreements=[], cross_panel_themes=[])
    syn_b = Synthesis(recommendation="clarify the spec", confidence=7, consensus=[],
                      disagreements=[], cross_panel_themes=[])
    res_a = [MemberResult("Eng", "m1", "oppose", "bug here")]
    res_b = [MemberResult("Editor", "m2", "concerns", "vague")]
    body = render_combined([
        ("Code review (gate)", "", "Code changes", syn_a, res_a),
        ("Docs review (advisory)", "Advisory only — does not affect the merge check.",
         "Doc changes", syn_b, res_b),
    ])
    assert "# Council Review" in body
    assert body.index("Code review (gate)") < body.index("Docs review (advisory)")
    assert "Advisory only" in body
    assert "fix the bug" in body and "clarify the spec" in body
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_combined'`.

- [ ] **Step 3: Add `render_combined` to `council/render.py`** (append at end of file)

```python
def render_combined(sections, *, rigor: str = "daily") -> str:
    """Render multiple review sections into one comment body.

    sections: list of (title, advisory_note, question, syn, results).
    Each section gets a header, an optional italic note, then the standard
    synthesis-on-top markdown.
    """
    out = ["# Council Review", ""]
    for title, note, question, syn, results in sections:
        out.append(f"## {title}")
        if note:
            out += ["", f"_{note}_"]
        out += ["", render_markdown(question, syn, results, rigor=rigor), ""]
    return "\n".join(out)
```

- [ ] **Step 4: Run the test, verify it PASSES**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: PASS (all render tests green).

- [ ] **Step 5: Commit**

```bash
git add council/render.py tests/test_render.py
git commit -m "feat(council): render_combined (multi-section review comment)"
```

---

## Task 4: `council/review.py` — `run_pr_review`

**Files:**
- Create: `council/review.py`
- Test: `tests/test_review.py`

- [ ] **Step 1: Write the failing test — `tests/test_review.py`**

```python
from council.review import run_pr_review
from council.models import Panel, Member
from tests.conftest import FakeClient

CODE = ("diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -1 +1 @@\n-old\n+new\n")
DOC = ("diff --git a/docs/design.md b/docs/design.md\n--- a/docs/design.md\n+++ b/docs/design.md\n"
       "@@ -1 +1 @@\n-old\n+new\n")


def _panels():
    return {
        "code-review": Panel("code-review", "review code", [Member("Eng", "code1", "be an eng")]),
        "spec-review": Panel("spec-review", "review docs", [Member("Editor", "doc1", "be an editor")]),
    }


def _chair(rec="ok"):
    return {"recommendation": rec, "confidence": 8, "consensus": [],
            "disagreements": [], "cross_panel_themes": []}


def test_mixed_pr_runs_both_blocking_counts_code_only(member_json):
    client = FakeClient(by_model={
        "code1": member_json(stance="oppose", headline="bug",
                             findings=[("nil deref at app.py:1", "high", 9)]),
        "doc1": member_json(stance="concerns", headline="vague",
                            findings=[("undefined term", "high", 9)]),
        "c": _chair("address both"),
    })
    body, blocking, unavailable = run_pr_review(CODE + DOC, _panels(), client, chair_model="c")
    assert "Code review (gate)" in body and "Docs review (advisory)" in body
    assert blocking == 1          # only the code finding counts
    assert unavailable is False


def test_docs_only_pr_never_blocks(member_json):
    client = FakeClient(by_model={
        "doc1": member_json(stance="oppose", headline="bad",
                            findings=[("fatal gap", "critical", 9)]),
        "c": _chair("clarify"),
    })
    body, blocking, unavailable = run_pr_review(DOC, _panels(), client, chair_model="c")
    assert "Docs review (advisory)" in body
    assert "Code review (gate)" not in body
    assert blocking == 0          # docs never block, even a critical
    assert unavailable is False


def test_code_panel_outage_fails_closed(member_json):
    client = FakeClient(by_model={"c": _chair()}, raises_for={"code1"})
    _, blocking, unavailable = run_pr_review(CODE, _panels(), client, chair_model="c")
    assert unavailable is True     # whole (1-member) code panel errored


def test_doc_panel_outage_does_not_block(member_json):
    client = FakeClient(by_model={
        "code1": member_json(stance="approve", headline="lgtm"),
        "c": _chair()},
        raises_for={"doc1"})
    _, blocking, unavailable = run_pr_review(CODE + DOC, _panels(), client, chair_model="c")
    assert unavailable is False    # doc-side failure must not fail the gate


def test_empty_diff_is_noop():
    body, blocking, unavailable = run_pr_review("", _panels(), FakeClient(), chair_model="c")
    assert blocking == 0 and unavailable is False
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_review.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'council.review'`.

- [ ] **Step 3: Write `council/review.py`**

```python
from __future__ import annotations

from .routing import split_diff_by_type
from .engine import run_panel
from .synthesize import synthesize
from .render import render_combined


def _is_blocking(finding) -> bool:
    """Code-side gate: any `critical`, or a `high` with confidence >= 8."""
    return finding.severity == "critical" or (
        finding.severity == "high" and finding.confidence >= 8)


def run_pr_review(diff: str, panels: dict, client, *, chair_model: str):
    """Split a PR diff, review the code slice (gated) and the doc slice (advisory).

    Returns (body, blocking, unavailable):
      - body: one combined comment (a section per non-empty slice)
      - blocking: count of blocking findings in the CODE section only
      - unavailable: fail-closed flag keyed on the CODE review only (chair errored,
        or >= half the code panel errored). Doc-side failures never set it.
    """
    code_diff, doc_diff = split_diff_by_type(diff)
    sections = []
    blocking = 0
    unavailable = False

    if code_diff.strip():
        results = run_panel(
            panels["code-review"],
            f"Review this code diff:\n\n```diff\n{code_diff}\n```", client)
        syn = synthesize("Code review", results, client, chair_model=chair_model)
        sections.append(("Code review (gate)", "", "Code changes", syn, results))
        blocking = sum(1 for r in results for f in r.findings if _is_blocking(f))
        errored = sum(1 for r in results if r.error)
        unavailable = syn.error is not None or not results or errored * 2 >= len(results)

    if doc_diff.strip():
        results = run_panel(
            panels["spec-review"],
            f"Review this design doc / spec / plan diff:\n\n```diff\n{doc_diff}\n```", client)
        syn = synthesize("Doc review", results, client, chair_model=chair_model)
        sections.append(("Docs review (advisory)",
                         "Advisory only — does not affect the merge check.",
                         "Doc changes", syn, results))

    if not sections:
        return "Nothing to review.", 0, False
    return render_combined(sections), blocking, unavailable
```

- [ ] **Step 4: Run the test, verify it PASSES**

Run: `.venv/bin/python -m pytest tests/test_review.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add council/review.py tests/test_review.py
git commit -m "feat(council): run_pr_review (code gated + docs advisory, combined comment)"
```

---

## Task 5: Reduce `venice_review.py` to a thin shim

**Files:**
- Modify: `setup/templates/venice_review.py`
- Test: `tests/test_venice_review_refactor.py`

- [ ] **Step 1: Replace `tests/test_venice_review_refactor.py` entirely** (the behavioral tests now live in `tests/test_review.py`; this asserts the shim wires up correctly)

```python
import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "venice_review", pathlib.Path("setup/templates/venice_review.py"))
vr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(vr)


def test_shim_exposes_main_and_post_comment():
    assert hasattr(vr, "main") and callable(vr.main)
    assert hasattr(vr, "post_comment") and callable(vr.post_comment)


def test_shim_delegates_to_run_pr_review():
    # the orchestration logic must live in the package, not the script
    import inspect
    src = inspect.getsource(vr)
    assert "from council.review import run_pr_review" in src
    assert "run_pr_review(" in src
    assert "build_review" not in src  # old per-script logic is gone
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_venice_review_refactor.py -q`
Expected: FAIL — `test_shim_delegates_to_run_pr_review` fails (current script still defines `build_review`, no `run_pr_review` import).

- [ ] **Step 3: Replace the entire contents of `setup/templates/venice_review.py`**

```python
"""Venice review council — GitHub Action shim over the `council` engine.

Splits the PR diff, reviews code changes (gated) and doc changes (advisory) via
council.review.run_pr_review, posts one consolidated comment, and exits 1 when
there are blocking code findings or the code review was unavailable (fail closed).

Required env: VENICE_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO, DIFF_PATH
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import requests
from council.config import load_panels, get_api_key, truncate
from council.venice import VeniceClient
from council.review import run_pr_review

GITHUB_API = "https://api.github.com"


def post_comment(repo, pr, body, token):
    requests.post(f"{GITHUB_API}/repos/{repo}/issues/{pr}/comments",
                  headers={"Authorization": f"Bearer {token}",
                           "Accept": "application/vnd.github+json"},
                  json={"body": body}, timeout=30).raise_for_status()


def main() -> int:
    settings, panels = load_panels()
    diff = truncate(Path(os.environ["DIFF_PATH"]).read_text(), settings.byte_cap)
    if not diff.strip():
        print("Empty diff, nothing to review.")
        return 0
    client = VeniceClient(get_api_key(), timeout=settings.timeout)
    body, blocking, unavailable = run_pr_review(
        diff, panels, client, chair_model=settings.chair_model)
    post_comment(os.environ["REPO"], os.environ["PR_NUMBER"], body, os.environ["GITHUB_TOKEN"])
    if unavailable:
        print("::error::review council unavailable (code panel/chair failed) — failing closed",
              file=sys.stderr)
        return 1
    if blocking:
        print(f"::error::{blocking} blocking finding(s) from the review council", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test + full suite**

Run: `.venv/bin/python -m pytest tests/test_venice_review_refactor.py -q`
Expected: PASS (2 passed).
Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add setup/templates/venice_review.py tests/test_venice_review_refactor.py
git commit -m "refactor(venice-review): thin shim over council.review.run_pr_review"
```

---

## Task 6: CLI `review` auto-picks the panel by path

**Files:**
- Modify: `council/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add the failing test to `tests/test_cli.py`** (append). It needs a `spec-review` panel in the injected env, so define a local panels dict.

```python
def _env_with_spec(member_json):
    from council.config import Settings
    settings = Settings(default_panel="decision", router_model="r", chair_model="c")
    panels = {
        "code-review": Panel("code-review", "review code", [Member("Eng", "code1", "eng")]),
        "spec-review": Panel("spec-review", "review docs", [Member("Editor", "doc1", "editor")]),
    }
    client = FakeClient(by_model={
        "code1": member_json(stance="approve", headline="ok"),
        "doc1": member_json(stance="approve", headline="ok"),
        "c": {"recommendation": "x", "confidence": 8, "consensus": [],
              "disagreements": [], "cross_panel_themes": []}})
    return settings, panels, client


def test_review_doc_file_autopicks_spec_review(tmp_path, member_json):
    settings, panels, client = _env_with_spec(member_json)
    f = tmp_path / "design.md"
    f.write_text("# Design\nsome spec prose\n")
    cli.main(["review", str(f)], _settings=settings, _panels=panels, _client=client)
    models = {c["model"] for c in client.calls}
    assert "doc1" in models       # spec-review seat was consulted
    assert "code1" not in models  # code-review seat was not


def test_review_code_file_autopicks_code_review(tmp_path, member_json):
    settings, panels, client = _env_with_spec(member_json)
    f = tmp_path / "app.py"
    f.write_text("print('hi')\n")
    cli.main(["review", str(f)], _settings=settings, _panels=panels, _client=client)
    models = {c["model"] for c in client.calls}
    assert "code1" in models and "doc1" not in models


def test_review_explicit_panel_overrides_autopick(tmp_path, member_json):
    settings, panels, client = _env_with_spec(member_json)
    f = tmp_path / "design.md"
    f.write_text("# Design\n")
    cli.main(["review", str(f), "--panel", "code-review"],
             _settings=settings, _panels=panels, _client=client)
    models = {c["model"] for c in client.calls}
    assert "code1" in models and "doc1" not in models
```

- [ ] **Step 2: Run the test, verify it FAILS**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: FAIL — doc file currently routes to `code-review` (the hardcoded default), so `doc1` is never called.

- [ ] **Step 3: Modify `council/cli.py`**

3a. Change the `review` subparser's `--panel` default from `"code-review"` to `None`:

```python
    r.add_argument("--panel", default=None)
```

3b. In the `review` command handler, after `ctx` is built and before `_run`, replace the existing final line:

```python
        ctx = truncate(f"Review this:\n\n{text}", settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)
```

with panel auto-pick:

```python
        ctx = truncate(f"Review this:\n\n{text}", settings.byte_cap)
        panel_name = args.panel
        if panel_name is None:
            # auto-pick by target: a single doc file -> spec-review; otherwise code-review.
            # (dirs / --diff / stdin span many files; the CI front-end splits those.)
            from .routing import classify_path
            if not args.diff and args.path not in (None, "-") and Path(args.path).is_file() \
                    and classify_path(args.path) == "doc":
                panel_name = "spec-review"
            else:
                panel_name = "code-review"
        return _run(ctx, panel_name, settings, panels, client, args.rigor, args.format)
```

- [ ] **Step 4: Run the test + full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add council/cli.py tests/test_cli.py
git commit -m "feat(council): review auto-picks spec-review for doc files"
```

---

## Task 7: Version bump, tag, rollout, live smoke

> Network + multi-repo + merge steps. Steps 1-3 are in-branch (run anywhere). Steps 5-7 need `VENICE_API_KEY`, the merge to `main`, and run on the VPS. Re-pinning to `@council-v0.2.0` mirrors the Piece-1 rollout (`scripts/migrate`-style loop).

**Files:**
- Modify: `pyproject.toml`, `council/__init__.py`, `setup/templates/venice-review.yml`

- [ ] **Step 1: Bump the version**

In `pyproject.toml` change `version = "0.1.0"` → `version = "0.2.0"`.
In `council/__init__.py` change `__version__ = "0.1.0"` → `__version__ = "0.2.0"`.

- [ ] **Step 2: Re-pin the Action template to the (about-to-exist) v0.2.0 tag**

In `setup/templates/venice-review.yml`, change the install ref `@council-v0.1.0` → `@council-v0.2.0`.

- [ ] **Step 3: Full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: all green.
```bash
git add pyproject.toml council/__init__.py setup/templates/venice-review.yml
git commit -m "chore(council): v0.2.0 — Piece 2 (review beyond code); re-pin Action to v0.2.0"
```

- [ ] **Step 4: Merge to `main` via the merge protocol**

Post a Merge recommendation for `feat/council-piece2 → main` and wait for the human's "do it" (per `~/.claude/CLAUDE.md`). Merge with a merge commit, delete the branch.

- [ ] **Step 5: Tag and push `council-v0.2.0`** (on the VPS, on `main` after merge)

```bash
git checkout main && git pull
git tag -a council-v0.2.0 -m "council v0.2.0 — Piece 2: review beyond code (spec-review panel + routing)"
git push origin council-v0.2.0
```

- [ ] **Step 6: Verify the tag installs, then re-pin + re-shim the 17 repos**

Verify install from the new tag:
```bash
python3 -m venv /tmp/v2 && /tmp/v2/bin/pip install --quiet \
  "council @ git+https://github.com/rexmcintosh/build-ai-automation-workflow@council-v0.2.0"
/tmp/v2/bin/council panels | grep spec-review && rm -rf /tmp/v2
```
Expected: `spec-review` appears in the panel list.

Then for each of the 17 repos: copy the thinned `scripts/venice_review.py`, bump the workflow install ref `@council-v0.1.0` → `@council-v0.2.0`, commit + push to `main`. (Use a loop like the Piece-1 rollout; verify each landed against the remote tip.)

- [ ] **Step 7: Live smoke (real Venice)**

```bash
export VENICE_API_KEY=...   # or source ~/.env
council review docs/superpowers/specs/2026-06-04-council-piece2-review-beyond-code-design.md
```
Expected: a `[panel: spec-review]` header and a real synthesis with Editor/Skeptic/Implementer/Pre-mortem findings.
Then open a throwaway PR touching both a `.py` and a `.md` file in this repo and confirm the posted comment has both a **Code review (gate)** and a **Docs review (advisory)** section, and that only code findings affect the check.

- [ ] **Step 8: Update the roadmap note**

Append to `docs/superpowers/RESUME-council.md`: Piece 2 shipped (v0.2.0); the 17 repos re-pinned. Commit:
```bash
git add docs/superpowers/RESUME-council.md
git commit -m "docs(council): mark Piece 2 shipped (v0.2.0)"
```

---

## Definition of done

- `.venv/bin/python -m pytest -q` all green (no network in tests).
- `council review <a-spec>.md` runs the `spec-review` panel; `council review <code>` runs `code-review`; `--panel` overrides.
- A mixed PR posts one comment with a gated **Code** section and an advisory **Docs** section; only code findings affect the check; a doc-side outage never fails it.
- `scripts/venice_review.py` is a thin shim over `council.review.run_pr_review`.
- `council` v0.2.0 tagged; the 17 repos re-pinned to `@council-v0.2.0` with the thinned shim.
```
