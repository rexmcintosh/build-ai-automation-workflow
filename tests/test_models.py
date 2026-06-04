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
