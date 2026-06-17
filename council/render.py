from __future__ import annotations
from .models import Finding, MemberResult, Synthesis, ComparisonResult, SweepReport

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


def render_comparison(task: str, res: ComparisonResult) -> str:
    """Render a `council compare` result: winner + rationale on top, the chair's
    ranking and grafts, then each panelist's independent vote below."""
    out = ["## Council — compare", "", f"**Task:** {task}", ""]
    if res.error:
        out += [f"_comparison unavailable: {res.error}_", "", "── Raw votes ──", ""]
    else:
        out += [f"### Winner: {res.winner}  (confidence {res.confidence}/10)", "",
                res.rationale, ""]
        if res.ranking:
            out += [f"**Ranking:** {' > '.join(res.ranking)}", ""]
        if res.grafts:
            out += ["**Graft from the runners-up:**"] + [f"- {g}" for g in res.grafts] + [""]
        out += ["── Panel votes ──", ""]
    for v in res.votes:
        if v.error:
            out += [f"#### {v.member} · {v.model} — errored", f"_{v.error}_", ""]
            continue
        out += [f"#### {v.member} · {v.model} — pick: {v.pick}",
                f"ranking: {' > '.join(v.ranking)}" if v.ranking else "",
                f"_{v.rationale}_", ""]
    return "\n".join(out)


def render_sweep(path: str, rep: SweepReport) -> str:
    """Render a `council sweep` report: chair summary on top, findings worst-first,
    and an explicit coverage line (scanned / dropped — never a silent cap)."""
    out = ["## Council — security sweep", "", f"**Target:** {path}", ""]
    out += [f"### Summary", "", rep.summary, ""]
    if rep.error:
        out += [f"_summary error: {rep.error}_", ""]
    if rep.findings:
        out += [f"### Findings ({len(rep.findings)})", ""]
        for f in rep.findings:
            loc = ", ".join(f.locations)
            src = ", ".join(f.sources)
            out.append(f"- `{f.severity}` (c{f.confidence}) {f.point}  "
                       f"_— {loc} · raised by {src}_")
        out.append("")
    else:
        out += ["_No findings above the confidence gate._", ""]
    out += [f"---", f"Coverage: scanned {rep.chunks_scanned} file(s); "
            f"{rep.dropped} eligible file(s) dropped by the chunk cap."]
    return "\n".join(out)


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
