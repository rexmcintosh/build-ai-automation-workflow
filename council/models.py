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
