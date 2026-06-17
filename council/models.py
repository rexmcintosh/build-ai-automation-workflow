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
class SweepFinding:
    point: str
    severity: str
    confidence: int
    locations: list[str] = field(default_factory=list)  # chunk labels it appeared in
    sources: list[str] = field(default_factory=list)  # panel members that raised it


@dataclass
class SweepReport:
    findings: list["SweepFinding"] = field(default_factory=list)
    chunks_scanned: int = 0
    dropped: int = 0  # files beyond max_chunks (surfaced, never silent)
    summary: str = ""
    error: str | None = None


@dataclass
class CandidateVote:
    member: str
    model: str
    pick: str  # label of the preferred candidate
    ranking: list[str] = field(default_factory=list)  # labels best -> worst
    rationale: str = ""
    error: str | None = None


@dataclass
class ComparisonResult:
    winner: str
    rationale: str = ""
    ranking: list[str] = field(default_factory=list)  # chair's overall order
    grafts: list[str] = field(default_factory=list)  # best ideas from runners-up
    confidence: int = 5
    votes: list["CandidateVote"] = field(default_factory=list)
    error: str | None = None


@dataclass
class Synthesis:
    recommendation: str
    confidence: int
    consensus: list[str] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)
    cross_panel_themes: list[str] = field(default_factory=list)
    error: str | None = None
