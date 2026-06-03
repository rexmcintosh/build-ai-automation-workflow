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
