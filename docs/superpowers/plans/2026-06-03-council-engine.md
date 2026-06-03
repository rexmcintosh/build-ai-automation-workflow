# Council Engine + On-Demand CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable `council` Python package — a reusable multi-model Venice "council" engine plus an on-demand CLI (`ask` / `review` / `panels`) — and refactor the PR reviewer to reuse it.

**Architecture:** Pure Python (`requests` + `concurrent.futures`), no agent framework. A `VeniceClient` (dependency-injected for testing) makes chat calls. `engine.run_panel` fans a prompt out to a panel of personas in parallel; a "chair" `synthesize` step produces a consensus with typed disagreements; `render` prints synthesis-on-top with a confidence noise-gate. Panels are defined as data in `panels.toml`.

**Tech Stack:** Python 3.12, `requests`, `tomllib` (stdlib), `pytest`. Packaged with `pyproject.toml`, exposes a `council` console script.

**Design source of truth:** `docs/superpowers/specs/2026-06-03-council-engine-design.md`. Read it first.

---

## File Structure

```
pyproject.toml                 # package metadata + console_scripts: council
.env.example                   # documents VENICE_API_KEY
council/
  __init__.py
  models.py                    # dataclasses: Member, Panel, Finding, MemberResult, Disagreement, Synthesis
  venice.py                    # VeniceClient (real HTTP) + VeniceError
  config.py                    # load_panels(), get_api_key(), Settings, byte-cap truncation
  panels.toml                  # the 4 preset panels + settings (data)
  prompts.py                   # OUTPUT_INSTRUCTIONS for members / synth / router (shared strings)
  engine.py                    # run_panel(), _ask_member()
  router.py                    # pick_panel()
  synthesize.py                # synthesize()  (the chair)
  render.py                    # render_markdown(), render_terminal(), rigor gate
  cli.py                       # main(): ask / review / panels subcommands
tests/
  conftest.py                  # FakeClient + fixtures
  test_models.py
  test_config.py
  test_engine.py
  test_router.py
  test_synthesize.py
  test_render.py
  test_cli.py
  test_venice_review_refactor.py
setup/templates/venice_review.py   # MODIFY: refactor to call engine
setup/templates/venice-review.yml  # MODIFY: install the council package in CI
```

**Key interface (the DI seam):** every component that calls the API takes a `client` argument with one method, `complete(model, system, user, *, json_mode=True) -> str`. The real `VeniceClient` implements it with HTTP; tests inject a `FakeClient`. No network in tests.

---

## Task 0: Package scaffold

**Files:**
- Create: `pyproject.toml`, `council/__init__.py`, `.env.example`, `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "council"
version = "0.1.0"
description = "Multi-model Venice AI council: ask / review / panels"
requires-python = ">=3.11"
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
council = "council.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
packages = ["council"]

[tool.setuptools.package-data]
council = ["panels.toml"]
```

- [ ] **Step 2: Create `council/__init__.py`**

```python
"""council — a multi-model Venice AI council (engine + CLI)."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Create `.env.example`**

```bash
# Venice AI API key — get one at https://venice.ai (Account → API Keys).
# Load via your shell or a .env; the council reads it from the environment.
VENICE_API_KEY=your-venice-key-here
```

- [ ] **Step 4: Create `tests/conftest.py` with the FakeClient seam**

```python
import json
import pytest


class FakeClient:
    """Stand-in for VeniceClient. Scripted responses keyed by model name,
    or a single default. Records calls for assertions."""

    def __init__(self, by_model=None, default=None, raises_for=None):
        self.by_model = by_model or {}
        self.default = default
        self.raises_for = raises_for or set()
        self.calls = []

    def complete(self, model, system, user, *, json_mode=True):
        self.calls.append({"model": model, "system": system, "user": user})
        if model in self.raises_for:
            raise RuntimeError(f"boom:{model}")
        payload = self.by_model.get(model, self.default)
        if payload is None:
            raise AssertionError(f"FakeClient has no scripted reply for {model}")
        return payload if isinstance(payload, str) else json.dumps(payload)


@pytest.fixture
def member_json():
    def make(stance="concerns", headline="ok", findings=(), suggestions=()):
        return {
            "stance": stance,
            "headline": headline,
            "findings": [
                {"point": p, "severity": s, "confidence": c} for (p, s, c) in findings
            ],
            "suggestions": list(suggestions),
        }
    return make
```

- [ ] **Step 5: Run pytest to confirm collection works (no tests yet)**

Run: `python -m pytest -q`
Expected: `no tests ran` (exit 5) — confirms pytest + imports are wired.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml council/__init__.py .env.example tests/conftest.py
git commit -m "chore(council): package scaffold + test FakeClient seam"
```

---

## Task 1: Data models

**Files:**
- Create: `council/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from council.models import Member, Panel, Finding, MemberResult, Synthesis, Disagreement


def test_panel_holds_members():
    p = Panel(
        name="decision",
        description="weigh a choice",
        members=[Member(name="Founder", model="m1", system="be a founder")],
        default_rigor="daily",
    )
    assert p.members[0].name == "Founder"
    assert p.default_rigor == "daily"


def test_member_result_defaults_are_independent():
    a = MemberResult(member="A", model="m", stance="approve", headline="hi")
    b = MemberResult(member="B", model="m", stance="approve", headline="hi")
    a.findings.append(Finding(point="x", severity="low", confidence=5))
    assert b.findings == []  # no shared mutable default


def test_synthesis_shape():
    s = Synthesis(recommendation="do X", confidence=8, consensus=["c1"],
                  disagreements=[Disagreement(topic="t", type="taste", positions="p")],
                  cross_panel_themes=[])
    assert s.disagreements[0].type == "taste"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'council.models'`.

- [ ] **Step 3: Write `council/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Member:
    name: str
    model: str
    system: str


@dataclass
class Panel:
    name: str
    description: str
    members: list[Member]
    default_rigor: str = "daily"  # "daily" | "deep"


@dataclass
class Finding:
    point: str
    severity: str  # info | low | med | high | critical
    confidence: int  # 1..10


@dataclass
class MemberResult:
    member: str
    model: str
    stance: str  # approve | concerns | oppose | na
    headline: str
    findings: list[Finding] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class Disagreement:
    topic: str
    type: str  # mechanical | taste | user-challenge
    positions: str
    resolution: str = ""
    what_we_might_miss: str = ""
    if_wrong_cost: str = ""


@dataclass
class Synthesis:
    recommendation: str
    confidence: int
    consensus: list[str] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)
    cross_panel_themes: list[str] = field(default_factory=list)
    error: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add council/models.py tests/test_models.py
git commit -m "feat(council): core dataclasses"
```

---

## Task 2: Shared prompts

**Files:**
- Create: `council/prompts.py`

- [ ] **Step 1: Create `council/prompts.py`** (no test — pure constants, exercised by later tasks)

```python
import textwrap

MEMBER_OUTPUT = textwrap.dedent("""\
    Respond with ONLY a JSON object (no markdown, no prose around it):
    {
      "stance": "approve | concerns | oppose | na",
      "headline": "one sentence",
      "findings": [
        {"point": "short; include file:line for code", "severity": "info|low|med|high|critical", "confidence": 1-10}
      ],
      "suggestions": ["short optional improvements"]
    }
    confidence is YOUR certainty the finding is real (10 = certain). Keep lists <= 6 items.
    You are NOT here to rubber-stamp. Take a position.
""")

SYNTH_OUTPUT = textwrap.dedent("""\
    You are the CHAIR of a council. You have read every panelist's answer (they
    answered independently, blind to each other). Respond with ONLY a JSON object:
    {
      "recommendation": "the council's consensus answer / verdict",
      "confidence": 1-10,
      "consensus": ["points two or more panelists raised independently"],
      "disagreements": [
        {"topic":"...", "type":"mechanical|taste|user-challenge",
         "positions":"who held what", "resolution":"your call (mechanical/taste)",
         "what_we_might_miss":"(user-challenge only)", "if_wrong_cost":"(user-challenge only)"}
      ],
      "cross_panel_themes": ["concerns appearing across multiple lenses"]
    }
    Classify each disagreement: mechanical = one right answer (resolve it silently in
    recommendation); taste = valid differences (recommend, but list it); user-challenge =
    the panel agrees the user's stated direction is wrong (never silent; fill
    what_we_might_miss + if_wrong_cost; the user's direction is the default).
""")

ROUTER_PROMPT = textwrap.dedent("""\
    Pick the single best panel for the user's input. Respond with ONLY:
    {"panel": "<one of the names below>"}
    Panels:
""")
```

- [ ] **Step 2: Commit**

```bash
git add council/prompts.py
git commit -m "feat(council): shared output-instruction prompts"
```

---

## Task 3: Venice client (HTTP, with injectable seam)

**Files:**
- Create: `council/venice.py`
- Test: `tests/test_venice.py`

- [ ] **Step 1: Write the failing test** (uses a fake `post` so no real network)

```python
# tests/test_venice.py
import pytest
from council.venice import VeniceClient, VeniceError


def _resp(content, status=200):
    class R:
        status_code = status
        def json(self): return {"choices": [{"message": {"content": content}}]}
        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
    return R()


def test_complete_returns_content():
    calls = []
    def fake_post(url, **kw):
        calls.append((url, kw))
        return _resp('{"ok": true}')
    c = VeniceClient(api_key="k", post=fake_post)
    out = c.complete("model-x", "sys", "usr")
    assert out == '{"ok": true}'
    assert calls[0][1]["json"]["model"] == "model-x"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer k"


def test_complete_retries_then_raises():
    attempts = {"n": 0}
    def flaky_post(url, **kw):
        attempts["n"] += 1
        raise ConnectionError("nope")
    c = VeniceClient(api_key="k", post=flaky_post, retries=2, backoff=0)
    with pytest.raises(VeniceError):
        c.complete("m", "s", "u")
    assert attempts["n"] == 3  # 1 try + 2 retries
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_venice.py -q`
Expected: FAIL — `No module named 'council.venice'`.

- [ ] **Step 3: Write `council/venice.py`**

```python
from __future__ import annotations
import time
import requests

VENICE_API = "https://api.venice.ai/api/v1/chat/completions"


class VeniceError(RuntimeError):
    pass


class VeniceClient:
    """Thin Venice chat client. `post` is injectable for tests."""

    def __init__(self, api_key, *, base_url=VENICE_API, timeout=180,
                 retries=2, backoff=1.5, post=None, temperature=0.2):
        if not api_key:
            raise VeniceError("VENICE_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.temperature = temperature
        self._post = post or requests.post

    def complete(self, model, system, user, *, json_mode=True):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = self._post(self.base_url, headers=headers, json=payload,
                               timeout=self.timeout)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001 — bounded retry on any failure
                last = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
        raise VeniceError(f"Venice call failed after {self.retries + 1} tries: {last}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_venice.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add council/venice.py tests/test_venice.py
git commit -m "feat(council): Venice HTTP client with bounded retry + injectable post"
```

---

## Task 4: Resolve Venice models & write `panels.toml`

> This task **resolves the spec's open question** about real model IDs. It needs network + the API key, so run it on the VPS (`ssh dev@vps`, repo on `feat/council`, `VENICE_API_KEY` set).

**Files:**
- Create: `council/panels.toml`

- [ ] **Step 1: List the models Venice actually serves**

Run:
```bash
curl -s https://api.venice.ai/api/v1/models \
  -H "Authorization: Bearer $VENICE_API_KEY" | python3 -m json.tool | grep '"id"'
```
Record the available model IDs. Choose for **diversity** (different families disagree differently). Target roughly: a strong reasoner (architect/founder/chair), a code model (eng/bug), a separate-family model for the adversary (ideally non-Claude), a fast/cheap model for the router. If a model in the lists below isn't available, substitute the closest available ID and note it in a comment.

- [ ] **Step 2: Write `council/panels.toml`** (fill `model = ` with verified IDs; persona prompts follow the spec §4 recipe — identity-with-a-number, named laws, banned hedges, non-rubber-stamp opening)

```toml
[settings]
default_panel = "decision"
router_model  = "REPLACE-with-a-cheap-fast-model"
chair_model   = "REPLACE-with-a-strong-reasoner"
byte_cap      = 200000
timeout       = 180

# ---- code-review -----------------------------------------------------------
[panels.code-review]
description   = "Review a code change for correctness, security, and design."
default_rigor = "daily"

[[panels.code-review.members]]
name   = "Eng Manager"
model  = "REPLACE-code-model"
system = """
You are an engineering manager with 15 years shipping production systems and the
scar tissue to prove it. You are NOT here to rubber-stamp this change.
Laws: (1) Boring by default — every team gets ~three innovation tokens, spend them
wisely. (2) Design for the tired human at 3am. (3) Make the change easy, then make
the easy change. Internalize Conway's Law and blast-radius thinking; do not recite
them. Hunt: architecture fit, test coverage, what breaks under load or partial
failure. Never say "looks good to me" or "consider maybe" — name the issue and its
file:line, or say the change is sound and why.
"""

[[panels.code-review.members]]
name   = "Security Officer"
model  = "REPLACE-distinct-family-model"
system = """
You are a CSO who has run real incident response. Zero noise is more important than
zero misses — a report with 3 real findings beats 3 real + 12 theoretical. Hunt:
injection (SQL/shell/prompt), authz bypass, secrets in code or logs, unsafe
deserialization, SSRF, missing validation at trust boundaries. Only flag issues you
can defend; set confidence honestly (a single critical finding is worth surfacing
even at low confidence). Banned: "best practice suggests", "it is recommended".
State the attack and the impact, or say there is no real risk here.
"""

[[panels.code-review.members]]
name   = "Adversary"
model  = "REPLACE-non-Claude-model-if-possible"
system = """
You are a 200-IQ chaos engineer and attacker. Your job is to find how this fails in
production — not to be nice. Think: race conditions, partial writes, the input the
author never tested, the dependency that times out, the retry that double-charges.
No compliments. Just the problems, each with the concrete scenario that triggers it.
If you genuinely cannot break it, say so in one line.
"""

# ---- decision --------------------------------------------------------------
[panels.decision]
description   = "Weigh a choice or trade-off and recommend a direction."
default_rigor = "daily"

[[panels.decision.members]]
name   = "Founder"
model  = "REPLACE-strong-reasoner"
system = """
You are a founder/CEO who refuses to rubber-stamp. First ask: is this even the right
problem? What happens if we do nothing? What's the 10x version? Laws: "Strong
opinions, loosely held — state what evidence would change your mind." Internalize
Munger inversion (what would make this fail?), Bezos one-way vs two-way doors, Jobs
subtraction. Banned hedges: "it depends", "there are many ways to think about this".
Take a position and defend it.
"""

[[panels.decision.members]]
name   = "Eng Manager"
model  = "REPLACE-code-model"
system = """
You are a pragmatic engineering manager. Judge feasibility, effort, and the cheapest
path that actually works. Boring by default. Flag the option that will hurt at 3am.
Never say "both are viable" without saying which you'd ship and why.
"""

[[panels.decision.members]]
name   = "Inversion Adversary"
model  = "REPLACE-distinct-family-model"
system = """
You are the skeptic. Assume this decision goes badly — explain exactly how, and what
early signal would tell us we chose wrong. Name failure modes, hidden costs, and the
status-quo option people are ignoring. No reassurance. Just the risks.
"""

# ---- brainstorm ------------------------------------------------------------
[panels.brainstorm]
description   = "Generate and pressure-test ideas / explore a problem space."
default_rigor = "daily"

[[panels.brainstorm.members]]
name   = "YC Partner"
model  = "REPLACE-strong-reasoner"
system = """
You are a YC partner in builder mode. Delight is the currency — what would make
someone say "whoa"? But specificity is the only currency that counts: name the actual
human, not the category. Push for the narrowest wedge that's a complete experience.
Banned: "that's an interesting idea", "you might consider". React with a real take.
"""

[[panels.brainstorm.members]]
name   = "Scope-Expansion Founder"
model  = "REPLACE-distinct-family-model"
system = """
You are a cathedral-builder. Dream: what's the 10x version of this idea? What adjacent
thing becomes possible if this works? Generate boldly — this is divergence, not a
gate. Then name the one bet the whole thing rests on.
"""

[[panels.brainstorm.members]]
name   = "Designer"
model  = "REPLACE-code-or-reasoner-model"
system = """
You are a product designer obsessed with the emotional arc. Where is the magical
moment? Where would a real user feel friction, confusion, or boredom? Taste is
debuggable — when something feels wrong, name the principle it violates. Empty states
and first-run are features, not afterthoughts.
"""

# ---- red-team --------------------------------------------------------------
[panels.red-team]
description   = "Adversarially try to break a plan, claim, or design."
default_rigor = "deep"

[[panels.red-team.members]]
name   = "Adversary"
model  = "REPLACE-non-Claude-model-if-possible"
system = """
You are an attacker and chaos engineer. Break this. Think like someone with motive and
time. Enumerate concrete attack paths and failure scenarios; surface everything,
including low-confidence ones (mark them tentative). No compliments.
"""

[[panels.red-team.members]]
name   = "Security Officer"
model  = "REPLACE-distinct-family-model"
system = """
You are a CSO in comprehensive mode: surface anything that MIGHT be a real issue, flag
uncertain ones as TENTATIVE. Cover secrets, authz, injection, supply chain, trust
boundaries. Set confidence honestly so the chair can sort signal from noise.
"""

[[panels.red-team.members]]
name   = "Eng Manager"
model  = "REPLACE-code-model"
system = """
You are the engineer who has been paged at 2am on a Friday. What breaks under load,
partial failure, bad input, or a dependency outage? Where are the silent failures and
unnamed errors? Name each with the trigger.
"""

[[panels.red-team.members]]
name   = "Inversion Founder"
model  = "REPLACE-strong-reasoner"
system = """
You are a founder running a pre-mortem: it's a year from now and this failed. Tell the
story of how. What did we believe that turned out false? What did we ignore?
"""
```

- [ ] **Step 3: Validate the TOML parses**

Run: `python3 -c "import tomllib; tomllib.load(open('council/panels.toml','rb')); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add council/panels.toml
git commit -m "feat(council): preset panels (verified Venice models + gstack-style personas)"
```

---

## Task 5: Config loader

**Files:**
- Create: `council/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import textwrap
import pytest
from council.config import load_panels, get_api_key, Settings, truncate

TOML = textwrap.dedent("""
[settings]
default_panel = "decision"
router_model = "rmodel"
chair_model = "cmodel"
byte_cap = 50

[panels.decision]
description = "weigh a choice"
default_rigor = "daily"
[[panels.decision.members]]
name = "Founder"
model = "m1"
system = "be a founder"
""")


def test_load_panels(tmp_path):
    f = tmp_path / "panels.toml"
    f.write_text(TOML)
    settings, panels = load_panels(f)
    assert isinstance(settings, Settings)
    assert settings.default_panel == "decision"
    assert panels["decision"].members[0].name == "Founder"
    assert panels["decision"].default_rigor == "daily"


def test_get_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "abc")
    assert get_api_key() == "abc"


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("VENICE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        get_api_key()


def test_truncate_keeps_head_and_tail():
    out = truncate("x" * 100, cap=20)
    assert "truncated" in out
    assert len(out.encode()) < 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL — `No module named 'council.config'`.

- [ ] **Step 3: Write `council/config.py`**

```python
from __future__ import annotations
import os
import sys
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .models import Member, Panel


@dataclass
class Settings:
    default_panel: str = "decision"
    router_model: str = ""
    chair_model: str = ""
    byte_cap: int = 200_000
    timeout: int = 180


def get_api_key() -> str:
    key = os.environ.get("VENICE_API_KEY")
    if not key:
        print("error: VENICE_API_KEY is not set. Add it to your environment or .env "
              "(see .env.example).", file=sys.stderr)
        raise SystemExit(2)
    return key


def _panels_path(path=None) -> Path:
    if path:
        return Path(path)
    override = Path.home() / ".config" / "council" / "panels.toml"
    if override.exists():
        return override
    return Path(str(files("council") / "panels.toml"))


def load_panels(path=None):
    data = tomllib.load(open(_panels_path(path), "rb"))
    s = data.get("settings", {})
    settings = Settings(
        default_panel=s.get("default_panel", "decision"),
        router_model=s.get("router_model", ""),
        chair_model=s.get("chair_model", ""),
        byte_cap=int(s.get("byte_cap", 200_000)),
        timeout=int(s.get("timeout", 180)),
    )
    panels = {}
    for name, p in data.get("panels", {}).items():
        members = [Member(name=m["name"], model=m["model"], system=m["system"])
                   for m in p.get("members", [])]
        panels[name] = Panel(name=name, description=p.get("description", ""),
                             members=members, default_rigor=p.get("default_rigor", "daily"))
    return settings, panels


def truncate(text: str, cap: int) -> str:
    b = text.encode("utf-8", errors="ignore")
    if len(b) <= cap:
        return text
    head = b[: cap // 2].decode("utf-8", errors="ignore")
    tail = b[-cap // 2:].decode("utf-8", errors="ignore")
    return f"{head}\n\n... [input truncated, {len(b)} bytes total] ...\n\n{tail}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add council/config.py tests/test_config.py
git commit -m "feat(council): config loader (panels.toml, api key, truncation)"
```

---

## Task 6: Engine (`run_panel`)

**Files:**
- Create: `council/engine.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py
from council.engine import run_panel
from council.models import Panel, Member
from tests.conftest import FakeClient


def _panel():
    return Panel(name="decision", description="d", members=[
        Member("Founder", "m1", "be a founder"),
        Member("Eng", "m2", "be an eng"),
    ])


def test_run_panel_parallel_collects_results(member_json):
    client = FakeClient(by_model={
        "m1": member_json(stance="approve", headline="go",
                          findings=[("ship it", "info", 9)]),
        "m2": member_json(stance="concerns", headline="careful"),
    })
    results = run_panel(_panel(), "ship X?", client)
    by = {r.member: r for r in results}
    assert by["Founder"].stance == "approve"
    assert by["Founder"].findings[0].confidence == 9
    assert by["Eng"].stance == "concerns"


def test_run_panel_isolates_member_errors(member_json):
    client = FakeClient(by_model={"m2": member_json()}, raises_for={"m1"})
    results = run_panel(_panel(), "x", client)
    by = {r.member: r for r in results}
    assert by["Founder"].error is not None
    assert by["Founder"].stance == "na"
    assert by["Eng"].error is None  # one failure doesn't kill the panel


def test_run_panel_coerces_bad_json():
    client = FakeClient(default="not json at all")
    results = run_panel(_panel(), "x", client)
    assert all(r.error is not None for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine.py -q`
Expected: FAIL — `No module named 'council.engine'`.

- [ ] **Step 3: Write `council/engine.py`**

```python
from __future__ import annotations
import concurrent.futures
import json

from .models import Member, Panel, Finding, MemberResult
from .prompts import MEMBER_OUTPUT


def _ask_member(member: Member, context: str, client) -> MemberResult:
    try:
        raw = client.complete(
            member.model,
            member.system + "\n\n" + MEMBER_OUTPUT,
            f"Here is the input to weigh in on:\n\n{context}",
        )
        data = json.loads(raw)
        findings = [
            Finding(point=str(f.get("point", "")),
                    severity=str(f.get("severity", "info")),
                    confidence=int(f.get("confidence", 5)))
            for f in data.get("findings", []) if isinstance(f, dict)
        ]
        return MemberResult(
            member=member.name, model=member.model,
            stance=str(data.get("stance", "na")),
            headline=str(data.get("headline", "")),
            findings=findings,
            suggestions=[str(s) for s in data.get("suggestions", [])],
        )
    except Exception as e:  # noqa: BLE001
        return MemberResult(member=member.name, model=member.model, stance="na",
                            headline="(member errored)", error=f"{type(e).__name__}: {e}")


def run_panel(panel: Panel, context: str, client, *, max_workers=None) -> list[MemberResult]:
    workers = max_workers or max(1, len(panel.members))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_ask_member, m, context, client): m for m in panel.members}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    order = [m.name for m in panel.members]
    results.sort(key=lambda r: order.index(r.member))
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add council/engine.py tests/test_engine.py
git commit -m "feat(council): engine.run_panel (parallel fan-out, error isolation, coercion)"
```

---

## Task 7: Router (`pick_panel`)

**Files:**
- Create: `council/router.py`
- Test: `tests/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_router.py
from council.router import pick_panel
from council.models import Panel
from tests.conftest import FakeClient


def _panels():
    return {
        "decision": Panel("decision", "weigh a choice", []),
        "code-review": Panel("code-review", "review code", []),
    }


def test_router_returns_named_panel():
    client = FakeClient(default={"panel": "code-review"})
    assert pick_panel("review this diff", _panels(), client,
                      router_model="r", default="decision") == "code-review"


def test_router_falls_back_on_unknown():
    client = FakeClient(default={"panel": "nonsense"})
    assert pick_panel("x", _panels(), client, router_model="r",
                      default="decision") == "decision"


def test_router_falls_back_on_error():
    client = FakeClient(raises_for={"r"})
    assert pick_panel("x", _panels(), client, router_model="r",
                      default="decision") == "decision"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_router.py -q`
Expected: FAIL — `No module named 'council.router'`.

- [ ] **Step 3: Write `council/router.py`**

```python
from __future__ import annotations
import json

from .prompts import ROUTER_PROMPT


def pick_panel(context: str, panels: dict, client, *, router_model: str,
               default: str, snippet_chars: int = 1500) -> str:
    listing = "\n".join(f"- {name}: {p.description}" for name, p in panels.items())
    system = ROUTER_PROMPT + listing
    try:
        raw = client.complete(router_model, system, context[:snippet_chars])
        name = json.loads(raw).get("panel", "")
        return name if name in panels else default
    except Exception:  # noqa: BLE001
        return default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_router.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add council/router.py tests/test_router.py
git commit -m "feat(council): router.pick_panel with default fallback"
```

---

## Task 8: Synthesize (the chair)

**Files:**
- Create: `council/synthesize.py`
- Test: `tests/test_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_synthesize.py
from council.synthesize import synthesize
from council.models import MemberResult
from tests.conftest import FakeClient


def _results():
    return [
        MemberResult("Founder", "m1", "approve", "go"),
        MemberResult("Eng", "m2", "concerns", "risky"),
    ]


def test_synthesize_parses_chair_json():
    client = FakeClient(default={
        "recommendation": "do X with guardrails",
        "confidence": 8,
        "consensus": ["X is the right direction"],
        "disagreements": [{"topic": "rollout", "type": "taste",
                           "positions": "founder fast, eng slow", "resolution": "stage it"}],
        "cross_panel_themes": ["timeline risk"],
    })
    s = synthesize("ship X?", _results(), client, chair_model="c")
    assert s.recommendation.startswith("do X")
    assert s.disagreements[0].type == "taste"
    assert s.cross_panel_themes == ["timeline risk"]
    assert s.error is None


def test_synthesize_falls_back_on_error():
    client = FakeClient(raises_for={"c"})
    s = synthesize("x", _results(), client, chair_model="c")
    assert s.error is not None
    assert "unavailable" in s.recommendation.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthesize.py -q`
Expected: FAIL — `No module named 'council.synthesize'`.

- [ ] **Step 3: Write `council/synthesize.py`**

```python
from __future__ import annotations
import json

from .models import MemberResult, Disagreement, Synthesis
from .prompts import SYNTH_OUTPUT


def _panel_digest(results: list[MemberResult]) -> str:
    lines = []
    for r in results:
        if r.error:
            lines.append(f"### {r.member} ({r.model}) — errored, no input")
            continue
        lines.append(f"### {r.member} ({r.model}) — stance: {r.stance}")
        lines.append(f"headline: {r.headline}")
        for f in r.findings:
            lines.append(f"- [{f.severity} c{f.confidence}] {f.point}")
        for s in r.suggestions:
            lines.append(f"- (suggestion) {s}")
    return "\n".join(lines)


def synthesize(context: str, results: list[MemberResult], client, *, chair_model: str) -> Synthesis:
    user = (f"ORIGINAL INPUT:\n{context}\n\n"
            f"PANELIST ANSWERS (they answered independently, blind to each other):\n"
            f"{_panel_digest(results)}")
    try:
        raw = client.complete(chair_model, SYNTH_OUTPUT, user)
        d = json.loads(raw)
        dis = [Disagreement(
            topic=str(x.get("topic", "")), type=str(x.get("type", "taste")),
            positions=str(x.get("positions", "")), resolution=str(x.get("resolution", "")),
            what_we_might_miss=str(x.get("what_we_might_miss", "")),
            if_wrong_cost=str(x.get("if_wrong_cost", "")),
        ) for x in d.get("disagreements", []) if isinstance(x, dict)]
        return Synthesis(
            recommendation=str(d.get("recommendation", "")),
            confidence=int(d.get("confidence", 5)),
            consensus=[str(c) for c in d.get("consensus", [])],
            disagreements=dis,
            cross_panel_themes=[str(t) for t in d.get("cross_panel_themes", [])],
        )
    except Exception as e:  # noqa: BLE001
        return Synthesis(recommendation="(synthesis unavailable — see raw panel below)",
                         confidence=0, error=f"{type(e).__name__}: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthesize.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add council/synthesize.py tests/test_synthesize.py
git commit -m "feat(council): chair synthesizer (typed disagreements + consensus)"
```

---

## Task 9: Render (synthesis-on-top + rigor gate)

**Files:**
- Create: `council/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render.py
from council.render import render_markdown, gate_findings
from council.models import MemberResult, Finding, Synthesis


def test_gate_daily_keeps_high_and_critical():
    fs = [Finding("low-conf nit", "low", 3),
          Finding("solid", "med", 9),
          Finding("scary but unsure", "critical", 2)]
    shown, demoted = gate_findings(fs, rigor="daily")
    points = {f.point for f in shown}
    assert "solid" in points
    assert "scary but unsure" in points  # critical always shown
    assert "low-conf nit" not in points  # dropped (<5, not critical)


def test_gate_deep_keeps_almost_everything():
    fs = [Finding("c2", "low", 2), Finding("c9", "high", 9)]
    shown, demoted = gate_findings(fs, rigor="deep")
    assert {f.point for f in shown} == {"c2", "c9"}


def test_render_markdown_has_synthesis_on_top():
    syn = Synthesis(recommendation="do X", confidence=8, consensus=["agree on X"],
                    disagreements=[], cross_panel_themes=[])
    results = [MemberResult("Founder", "m1", "approve", "go",
                            findings=[Finding("ship", "med", 9)])]
    md = render_markdown("ship X?", syn, results, rigor="daily")
    assert md.index("do X") < md.index("Founder")  # synthesis precedes raw panel
    assert "## Council" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_render.py -q`
Expected: FAIL — `No module named 'council.render'`.

- [ ] **Step 3: Write `council/render.py`**

```python
from __future__ import annotations
from .models import Finding, MemberResult, Synthesis

_MIN_CONF = {"daily": 8, "deep": 2}


def gate_findings(findings: list[Finding], *, rigor: str):
    """Return (shown, demoted). Critical always shown. daily: >=8 shown, 5-7 demoted,
    <5 dropped. deep: >=2 shown (treat 2-7 as tentative), <2 dropped."""
    shown, demoted = [], []
    floor = _MIN_CONF.get(rigor, 8)
    for f in findings:
        if f.severity == "critical" or f.confidence >= floor:
            shown.append(f)
        elif rigor == "daily" and f.confidence >= 5:
            demoted.append(f)
        # else dropped
    return shown, demoted


def _finding_line(f: Finding, tentative=False) -> str:
    tag = " _(tentative)_" if (tentative or f.confidence < 8) else ""
    return f"- `{f.severity}` (c{f.confidence}) {f.point}{tag}"


def render_markdown(question: str, syn: Synthesis, results: list[MemberResult],
                    *, rigor: str = "daily") -> str:
    out = ["## Council", "", f"**Question:** {question}", ""]
    out += [f"### Recommendation (confidence {syn.confidence}/10)", "", syn.recommendation, ""]
    if syn.consensus:
        out += ["**Consensus:**"] + [f"- {c}" for c in syn.consensus] + [""]
    if syn.cross_panel_themes:
        out += ["**Cross-panel themes:**"] + [f"- {t}" for t in syn.cross_panel_themes] + [""]
    for d in syn.disagreements:
        out += [f"**Disagreement — {d.topic}** _({d.type})_", f"- positions: {d.positions}"]
        if d.type == "user-challenge":
            out += [f"- what we might be missing: {d.what_we_might_miss}",
                    f"- if we're wrong, the cost is: {d.if_wrong_cost}"]
        elif d.resolution:
            out += [f"- chair's call: {d.resolution}"]
        out += [""]
    out += ["---", "", "<details><summary>Raw panel</summary>", ""]
    for r in results:
        out += [f"#### {r.member} · {r.model} — {r.stance}", "", f"_{r.headline}_", ""]
        if r.error:
            out += [f"_errored: {r.error}_", ""]
            continue
        shown, demoted = gate_findings(r.findings, rigor=rigor)
        out += [_finding_line(f) for f in shown]
        if demoted:
            out += ["", "<sub>lower-confidence:</sub>"] + [_finding_line(f, True) for f in demoted]
        if r.suggestions:
            out += [""] + [f"- _(suggestion)_ {s}" for s in r.suggestions]
        out += [""]
    out += ["</details>"]
    return "\n".join(out)


def render_terminal(question: str, syn: Synthesis, results: list[MemberResult],
                    *, rigor: str = "daily") -> str:
    # Reuse markdown; terminals render it fine. Strip the <details> wrappers.
    md = render_markdown(question, syn, results, rigor=rigor)
    return md.replace("<details><summary>Raw panel</summary>", "── Raw panel ──").replace("</details>", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_render.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add council/render.py tests/test_render.py
git commit -m "feat(council): render synthesis-on-top + confidence noise-gate"
```

---

## Task 10: CLI (`ask` / `review` / `panels`)

**Files:**
- Create: `council/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test** (inject a client + panels so no network/config files needed)

```python
# tests/test_cli.py
from council import cli
from council.models import Panel, Member
from council.config import Settings
from tests.conftest import FakeClient


def _env(member_json):
    settings = Settings(default_panel="decision", router_model="r", chair_model="c")
    panels = {"decision": Panel("decision", "weigh", [Member("Founder", "m1", "founder")]),
              "code-review": Panel("code-review", "review", [Member("Eng", "m1", "eng")])}
    client = FakeClient(
        by_model={"m1": member_json(stance="approve", headline="go"),
                  "r": {"panel": "decision"},
                  "c": {"recommendation": "do X", "confidence": 8, "consensus": [],
                        "disagreements": [], "cross_panel_themes": []}})
    return settings, panels, client


def test_ask_runs_and_prints_recommendation(capsys, member_json):
    settings, panels, client = _env(member_json)
    rc = cli.main(["ask", "ship X?"], _settings=settings, _panels=panels, _client=client)
    assert rc == 0
    assert "do X" in capsys.readouterr().out


def test_panels_lists_names(capsys, member_json):
    settings, panels, client = _env(member_json)
    rc = cli.main(["panels"], _settings=settings, _panels=panels, _client=client)
    assert rc == 0
    out = capsys.readouterr().out
    assert "decision" in out and "code-review" in out


def test_ask_explicit_panel_overrides_router(capsys, member_json):
    settings, panels, client = _env(member_json)
    cli.main(["ask", "x", "--panel", "code-review"], _settings=settings,
             _panels=panels, _client=client)
    # the router model "r" should never have been called
    assert all(c["model"] != "r" for c in client.calls)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL — `No module named 'council.cli'`.

- [ ] **Step 3: Write `council/cli.py`** (the `_settings/_panels/_client` kwargs are test seams; production builds them from config + env)

```python
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .config import load_panels, get_api_key, Settings, truncate
from .venice import VeniceClient
from .engine import run_panel
from .router import pick_panel
from .synthesize import synthesize
from .render import render_markdown, render_terminal


def _build(panels_path=None):
    settings, panels = load_panels(panels_path)
    client = VeniceClient(get_api_key(), timeout=settings.timeout)
    return settings, panels, client


def _gather_context(question: str, files: list[str], cap: int) -> str:
    parts = [question] if question else []
    for fp in files or []:
        if fp == "-":
            parts.append("--- stdin ---\n" + sys.stdin.read())
        else:
            parts.append(f"--- {fp} ---\n" + Path(fp).read_text(errors="ignore"))
    return truncate("\n\n".join(parts), cap)


def _run(context, panel_name, settings, panels, client, rigor, fmt):
    if panel_name is None:
        panel_name = pick_panel(context, panels, client,
                                router_model=settings.router_model,
                                default=settings.default_panel)
    panel = panels[panel_name]
    rigor = rigor or panel.default_rigor
    results = run_panel(panel, context, client)
    syn = synthesize(context, results, client, chair_model=settings.chair_model)
    render = render_markdown if fmt == "md" else render_terminal
    print(f"[panel: {panel_name} · rigor: {rigor}]\n")
    print(render(context[:120], syn, results, rigor=rigor))
    return 0


def main(argv=None, *, _settings: Settings = None, _panels=None, _client=None) -> int:
    p = argparse.ArgumentParser(prog="council")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="ask the council a question")
    a.add_argument("question")
    a.add_argument("--panel"); a.add_argument("--file", action="append")
    a.add_argument("--rigor", choices=["daily", "deep"]); a.add_argument("--format", default="term")
    a.add_argument("--panels")

    r = sub.add_parser("review", help="review a file / dir / diff")
    r.add_argument("path", nargs="?")
    r.add_argument("--diff", action="store_true")
    r.add_argument("--panel", default="code-review")
    r.add_argument("--rigor", choices=["daily", "deep"]); r.add_argument("--format", default="term")
    r.add_argument("--panels")

    sub.add_parser("panels", help="list councils").add_argument("--panels", nargs="?")

    args = p.parse_args(argv)

    if _settings is not None:
        settings, panels, client = _settings, _panels, _client
    else:
        settings, panels, client = _build(getattr(args, "panels", None))

    if args.cmd == "panels":
        for name, panel in panels.items():
            seats = ", ".join(m.name for m in panel.members)
            print(f"{name:14} {panel.description}\n{'':14} seats: {seats}")
        return 0

    if args.cmd == "ask":
        ctx = _gather_context(args.question, args.file, settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    if args.cmd == "review":
        import subprocess
        if args.diff:
            text = subprocess.run(["git", "diff"], capture_output=True, text=True).stdout
        elif args.path == "-" or args.path is None:
            text = sys.stdin.read()
        else:
            pth = Path(args.path)
            text = "\n\n".join(f"--- {f} ---\n{f.read_text(errors='ignore')}"
                               for f in (pth.rglob("*") if pth.is_dir() else [pth]) if f.is_file())
        ctx = truncate(f"Review this:\n\n{text}", settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add council/cli.py tests/test_cli.py
git commit -m "feat(council): CLI (ask / review / panels) with injectable seams"
```

---

## Task 11: Refactor `venice_review.py` to reuse the engine

**Files:**
- Modify: `setup/templates/venice_review.py`
- Modify: `setup/templates/venice-review.yml`
- Test: `tests/test_venice_review_refactor.py`

- [ ] **Step 1: Write the regression test** (the PR path still produces a comment body + the right exit code, via the engine, with a mocked client)

```python
# tests/test_venice_review_refactor.py
import importlib.util, pathlib
from council.models import Panel, Member
from tests.conftest import FakeClient

# load the template module by path
_spec = importlib.util.spec_from_file_location(
    "venice_review", pathlib.Path("setup/templates/venice_review.py"))
vr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(vr)


def test_build_review_blocks_on_high_severity(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="oppose", headline="bug",
                          findings=[("nil deref at api.py:10", "high", 9)]),
        "c": {"recommendation": "fix the nil deref", "confidence": 9,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    body, blocking = vr.build_review("diff text", panel, client, chair_model="c")
    assert "## Council" in body
    assert blocking >= 1  # severity>=high counts as blocking → exit 1


def test_build_review_clean_diff_no_block(member_json):
    panel = Panel("code-review", "review", [Member("Eng", "m1", "eng")])
    client = FakeClient(by_model={
        "m1": member_json(stance="approve", headline="lgtm"),
        "c": {"recommendation": "ship it", "confidence": 8,
              "consensus": [], "disagreements": [], "cross_panel_themes": []}})
    body, blocking = vr.build_review("diff", panel, client, chair_model="c")
    assert blocking == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_venice_review_refactor.py -q`
Expected: FAIL — `build_review` does not exist yet.

- [ ] **Step 3: Rewrite `setup/templates/venice_review.py`** to use the engine

```python
"""Venice review council — GitHub Action front-end on the `council` engine.

Runs the `code-review` panel over a PR diff, posts one consolidated comment,
and exits 1 when there are blocking findings (severity >= high).

Required env: VENICE_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO, DIFF_PATH
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import requests
from council.config import load_panels, get_api_key, truncate
from council.venice import VeniceClient
from council.engine import run_panel
from council.synthesize import synthesize
from council.render import render_markdown

GITHUB_API = "https://api.github.com"
_BLOCKING = {"high", "critical"}


def build_review(diff: str, panel, client, *, chair_model: str):
    results = run_panel(panel, f"Review this pull request diff:\n\n```diff\n{diff}\n```", client)
    syn = synthesize("PR diff review", results, client, chair_model=chair_model)
    body = render_markdown("Pull request review", syn, results, rigor=panel.default_rigor)
    blocking = sum(1 for r in results for f in r.findings if f.severity in _BLOCKING)
    return body, blocking


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
    body, blocking = build_review(diff, panels["code-review"], client,
                                  chair_model=settings.chair_model)
    post_comment(os.environ["REPO"], os.environ["PR_NUMBER"], body, os.environ["GITHUB_TOKEN"])
    if blocking:
        print(f"::error::{blocking} blocking finding(s) from the review council", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Update `setup/templates/venice-review.yml`** install step so CI has the package

Change the "Install deps" step to install the council package from the repo that hosts it:

```yaml
      - name: Install council
        run: pip install --quiet "council @ git+https://github.com/rexmcintosh/build-ai-automation-workflow@main"
```
(When/if `council` is published to PyPI, simplify to `pip install council`.)

- [ ] **Step 5: Run the regression test**

Run: `python -m pytest tests/test_venice_review_refactor.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add setup/templates/venice_review.py setup/templates/venice-review.yml tests/test_venice_review_refactor.py
git commit -m "refactor(venice-review): reuse council engine; install package in CI"
```

---

## Task 12: Install on the VPS + manual smoke test + usage doc

**Files:**
- Create: `council/README.md`

- [ ] **Step 1: Install the package on the VPS**

Run (on the VPS, repo on `feat/council`):
```bash
cd ~/projects/build-ai-automation-workflow
pipx install . 2>/dev/null || pip install --user -e .
council panels
```
Expected: the 4 panels print with their seats.

- [ ] **Step 2: Live smoke test (real Venice call — needs `VENICE_API_KEY`)**

Run:
```bash
export VENICE_API_KEY=...    # or load from .env
council ask "Is SQLite a reasonable choice for a single-user finance tracker?"
```
Expected: a `[panel: decision]` header, a recommendation, consensus/dissents, and a raw-panel section. If a model ID is wrong you'll see members "errored" — fix the IDs in `panels.toml` (Task 4).

- [ ] **Step 3: Write `council/README.md`** (usage, panels, config, secrets)

```markdown
# council

A multi-model Venice AI council. Fan a question/artifact out to a panel of
personas, get a synthesized recommendation with typed disagreements.

## Install
    pipx install .            # from this repo
    cp .env.example .env      # add your VENICE_API_KEY

## Use
    council ask "Postgres or SQLite for a single-user app?"
    council ask --panel red-team "Critique this plan" --file plan.md
    council review path/to/file.py
    council review --diff
    council panels

## Panels
code-review · decision · brainstorm · red-team. Edit `council/panels.toml`
(or `~/.config/council/panels.toml`) to change personas/models or add seats.

## Secret
`VENICE_API_KEY` from the environment / `.env`. Never commit it.
```

- [ ] **Step 4: Commit**

```bash
git add council/README.md
git commit -m "docs(council): usage README + VPS install/smoke notes"
```

- [ ] **Step 5: Push the branch**

```bash
git push -u origin feat/council
```

---

## Definition of done

- `python -m pytest -q` all green (no network in tests).
- `council panels`, `council ask`, `council review` work on the VPS against real Venice.
- `venice_review.py` produces a PR comment + exit-1-on-blocking via the engine (regression test green).
- `panels.toml` has verified, diverse Venice model IDs (no `REPLACE-` placeholders left).
- Branch pushed; open a draft PR for the Venice council to review itself. 🪞
