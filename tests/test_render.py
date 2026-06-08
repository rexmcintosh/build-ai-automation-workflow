from council.render import render_markdown, gate_findings, render_combined
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
