"""volunteer.search - eligible volunteers by role, campus, training, availability and constraints."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from agent.clock import WEEKDAYS, fmt, parse
from agent.policies import P
from models.entities import InternalTask, Volunteer
from tools.base import ToolContext, ToolOutput, tool


class VolunteerSearchInput(BaseModel):
    role: str
    campus: Optional[str]
    start: str
    end: str
    exclude_ids: list[str] = Field(default_factory=list)


class VolunteerEvidence(BaseModel):
    role_match: bool
    campus_match: bool
    training_ok: bool
    available: bool
    constraints_ok: bool


class VolunteerCandidate(BaseModel):
    volunteer_id: str
    name: str
    campuses: list[str]
    current_load: int
    evidence: VolunteerEvidence
    reason: str


class VolunteerExcluded(BaseModel):
    volunteer_id: str
    reasons: list[str]


class VolunteerSearchOutput(ToolOutput):
    candidates: list[VolunteerCandidate]
    excluded: list[VolunteerExcluded]
    considered: int


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def is_available(v: Volunteer, start: datetime, end: datetime) -> bool:
    day = WEEKDAYS[start.weekday()]
    for blk in v.availability or []:
        if blk["day"] != day:
            continue
        h0, m0 = _hm(blk["start"])
        h1, m1 = _hm(blk["end"])
        if start >= start.replace(hour=h0, minute=m0) and end <= start.replace(hour=h1, minute=m1):
            return True
    return False


def in_blackout(v: Volunteer, start: datetime, end: datetime) -> bool:
    for b in v.blackout or []:
        if start < parse(b["end"]) and parse(b["start"]) < end:
            return True
    return False


def open_assignments_this_week(session, volunteer_id: str, start: datetime) -> int:
    week0 = (start - timedelta(days=start.weekday())).replace(hour=0, minute=0)
    week1 = week0 + timedelta(days=7)
    return (session.query(InternalTask)
            .filter(InternalTask.assignee_id == volunteer_id, InternalTask.status == "open",
                    InternalTask.kind == "volunteer_assignment", InternalTask.due >= week0, InternalTask.due < week1)
            .count())


def eligibility(session, v: Volunteer, role: str, campus: Optional[str], start: datetime, end: datetime) -> list[str]:
    """Return list of exclusion reasons (empty = eligible). Shared with the verifier."""
    reasons = []
    req = P()["volunteer_policy"]["role_training_requirements"].get(role, ["background_check"])
    if not v.active:
        reasons.append("inactive")
    if role not in v.approved_roles:
        reasons.append(f"not approved for {role}")
    if campus and campus not in v.campuses:
        reasons.append(f"campus mismatch ({'/'.join(v.campuses)})")
    missing = [t for t in req if not (v.training_flags or {}).get(t)]
    if missing:
        reasons.append("training incomplete: " + ", ".join(missing))
    if (v.constraints or {}).get("weekends_only") and start.weekday() < 5:
        reasons.append("constraint: weekends only")
    if not is_available(v, start, end):
        reasons.append("not available in window")
    if in_blackout(v, start, end):
        reasons.append("cancelled / blackout for this window")
    mx = (v.constraints or {}).get("max_trips_per_week")
    if mx is not None and open_assignments_this_week(session, v.volunteer_id, start) >= mx:
        reasons.append(f"constraint: max {mx} trips/week reached")
    return reasons


@tool("volunteer.search", access="read", input_model=VolunteerSearchInput, output_model=VolunteerSearchOutput,
      description="Find eligible volunteers (role, campus, training, availability, constraints). Minimal fields.")
def volunteer_search(ctx: ToolContext, inp: VolunteerSearchInput) -> VolunteerSearchOutput:
    start, end = parse(inp.start), parse(inp.end)
    pool = (ctx.session.query(Volunteer).order_by(Volunteer.volunteer_id).all())
    pool = [v for v in pool if inp.role in v.approved_roles]
    cands, excl = [], []
    for v in pool:
        reasons = eligibility(ctx.session, v, inp.role, inp.campus, start, end)
        if v.volunteer_id in inp.exclude_ids:
            reasons.append("excluded (cancelled or rejected)")
        if reasons:
            excl.append(VolunteerExcluded(volunteer_id=v.volunteer_id, reasons=reasons))
            continue
        cands.append(VolunteerCandidate(
            volunteer_id=v.volunteer_id, name=v.name, campuses=v.campuses, current_load=v.current_load,
            evidence=VolunteerEvidence(role_match=True, campus_match=True, training_ok=True, available=True,
                                       constraints_ok=True),
            reason=f"{inp.role} volunteer at {inp.campus}; trained; available {fmt(start)}",
        ))
    cands.sort(key=lambda c: (c.current_load, c.volunteer_id))
    return VolunteerSearchOutput(
        candidates=cands, excluded=excl, considered=len(pool),
        summary=f"{len(cands)} eligible {inp.role} volunteer(s) for {fmt(start)} ({len(pool)} considered)",
    )
