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
