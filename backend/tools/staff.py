"""staff.search - deterministic eligibility filtering over the synthetic roster.

Implements the practitioner-validated routing concepts:
  * locality (campus match) and relevant experience,
  * the weekly Pastor on Call (POC) for same-day/urgent callbacks.
The model may later *rank* these candidates but can never add to them.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agent.policies import poc_ids
from models.entities import StaffMember
from tools.base import ToolContext, ToolOutput, tool


class StaffSearchInput(BaseModel):
    campus: Optional[str] = Field(None, description="Requester's campus (locality).")
    request_type: str = Field(..., description="Operational request type, e.g. pastoral_conversation.")
    experience_tags: list[str] = Field(default_factory=list)
    urgent: bool = False
    exclude_ids: list[str] = Field(default_factory=list, description="Staff rejected by a reviewer.")


class StaffEvidence(BaseModel):
    active: bool
    campus_match: bool
    role_match: bool
    experience_match: list[str]
    poc_match: bool
    routing_rule: str


class StaffCandidate(BaseModel):
    staff_id: str
    name: str
    role: str
    campuses: list[str]
    experience_tags: list[str]
    approved_request_types: list[str]
    is_current_poc: bool
    evidence: StaffEvidence
    reason: str


class StaffExcluded(BaseModel):
    staff_id: str
    name: str
    reasons: list[str]


class StaffSearchOutput(ToolOutput):
    candidates: list[StaffCandidate]
    excluded: list[StaffExcluded]
    routing_rule: str
    considered: int


def _candidate(s: StaffMember, campus_match: bool, exp: list[str], rule: str, reason: str) -> StaffCandidate:
    return StaffCandidate(
        staff_id=s.staff_id, name=s.name, role=s.role, campuses=s.campuses,
        experience_tags=s.experience_tags, approved_request_types=s.approved_request_types,
        is_current_poc=s.is_current_poc,
        evidence=StaffEvidence(active=s.active, campus_match=campus_match, role_match=True,
                               experience_match=exp, poc_match=s.is_current_poc, routing_rule=rule),
        reason=reason,
    )


@tool("staff.search", access="read", input_model=StaffSearchInput, output_model=StaffSearchOutput,
      description="Return only staff eligible by policy (active, campus, approved request type, experience, POC).")
def staff_search(ctx: ToolContext, inp: StaffSearchInput) -> StaffSearchOutput:
    roster = ctx.session.query(StaffMember).order_by(StaffMember.staff_id).all()
    candidates: list[StaffCandidate] = []
    excluded: list[StaffExcluded] = []

    if inp.urgent:
        # Policy: urgent same-day requests go to the current weekly POC, then the
        # designated backup POC. Campus does not restrict POC coverage.
        ids = poc_ids()
        rule = "urgent_same_day -> current weekly Pastor on Call, then designated backup POC"
        order = [ids["current"], ids["backup"]]
        by_id = {s.staff_id: s for s in roster}
        for sid in order:
            s = by_id.get(sid)
            if s is None:
                continue
            reasons = []
            if not s.active:
                reasons.append("inactive")
            if "urgent_callback" not in s.approved_request_types:
                reasons.append("not approved for urgent_callback")
            if sid in inp.exclude_ids:
                reasons.append("rejected by reviewer")
            if reasons:
                excluded.append(StaffExcluded(staff_id=s.staff_id, name=s.name, reasons=reasons))
                continue
            label = "Current weekly Pastor on Call" if sid == ids["current"] else "Designated backup POC"
            exp = [t for t in inp.experience_tags if t in s.experience_tags]
            candidates.append(_candidate(s, bool(inp.campus and inp.campus in s.campuses), exp, rule,
                                         f"{label} (policy rule, not model judgment)."))
        summary = f"POC routing: {len(candidates)} policy candidate(s) ({', '.join(c.staff_id for c in candidates) or 'none'})"
        return StaffSearchOutput(candidates=candidates, excluded=excluded, routing_rule=rule,
                                 considered=len(order), summary=summary)

    rule = "active AND campus match (locality) AND approved request type; ranked by experience"
    if not inp.campus:
        return StaffSearchOutput(candidates=[], excluded=[], routing_rule=rule, considered=0,
                                 summary="No campus provided - locality routing cannot run (flag missing info).")
    for s in roster:
        reasons = []
        if not s.active:
            reasons.append("inactive")
        if inp.campus not in s.campuses:
            reasons.append(f"campus mismatch ({'/'.join(s.campuses)})")
        if inp.request_type not in s.approved_request_types:
            reasons.append(f"not approved for {inp.request_type}")
        if s.staff_id in inp.exclude_ids:
            reasons.append("rejected by reviewer")
        if reasons:
            # Only report exclusions that are informative (same campus or wide-open alternatives)
            excluded.append(StaffExcluded(staff_id=s.staff_id, name=s.name, reasons=reasons))
            continue
        exp = [t for t in inp.experience_tags if t in s.experience_tags]
        reason = f"{s.role} at {inp.campus}; approved for {inp.request_type}"
        if exp:
            reason += f"; experience: {', '.join(exp)}"
        candidates.append(_candidate(s, True, exp, rule, reason))

    candidates.sort(key=lambda c: (-len(c.evidence.experience_match), c.staff_id))
    summary = f"returned {len(candidates)} eligible candidate(s) for {inp.campus} ({len(roster)} considered)"
    return StaffSearchOutput(candidates=candidates, excluded=excluded, routing_rule=rule,
                             considered=len(roster), summary=summary)
