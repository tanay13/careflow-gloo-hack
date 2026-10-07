"""Explicit case state machine.

The LLM never chooses state transitions. Every status change goes through
`transition()`, which rejects anything not in ALLOWED and writes an audit event.
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy.orm import Session


class CaseState(str, Enum):
    NEW = "NEW"
    NORMALIZED = "NORMALIZED"
    SAFETY_CHECKED = "SAFETY_CHECKED"
    CONTEXT_GATHERED = "CONTEXT_GATHERED"
    PLAN_PROPOSED = "PLAN_PROPOSED"
    VERIFIED = "VERIFIED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


S = CaseState

ALLOWED: dict[CaseState, set[CaseState]] = {
    S.NEW: {S.NORMALIZED, S.CANCELLED, S.ERROR},
    S.NORMALIZED: {S.SAFETY_CHECKED, S.ESCALATED, S.ERROR},
    S.SAFETY_CHECKED: {S.CONTEXT_GATHERED, S.ESCALATED, S.ERROR},
    S.CONTEXT_GATHERED: {S.PLAN_PROPOSED, S.ESCALATED, S.ERROR},
    S.PLAN_PROPOSED: {S.VERIFIED, S.ESCALATED, S.ERROR},
    # VERIFIED -> PLAN_PROPOSED when the verifier returns REPLAN.
    S.VERIFIED: {S.AWAITING_APPROVAL, S.PLAN_PROPOSED, S.ESCALATED, S.ERROR},
    # AWAITING_APPROVAL -> PLAN_PROPOSED when a reviewer rejects/edits or the
    # plan is invalidated by an event before approval.
    S.AWAITING_APPROVAL: {S.APPROVED, S.PLAN_PROPOSED, S.ESCALATED, S.CANCELLED},
    # APPROVED -> PLAN_PROPOSED when pre-execution re-verification finds drift.
    S.APPROVED: {S.EXECUTING, S.PLAN_PROPOSED, S.ERROR},
    S.EXECUTING: {S.MONITORING, S.ERROR, S.ESCALATED},
    S.MONITORING: {S.PLAN_PROPOSED, S.RESOLVED, S.ESCALATED, S.ERROR, S.CANCELLED},
    # Recoverable error: resume at the stage that failed.
    S.ERROR: {S.SAFETY_CHECKED, S.MONITORING, S.APPROVED, S.ESCALATED, S.CANCELLED},
    # Escalated cases can be returned to monitoring/planning only by a human.
    S.ESCALATED: {S.PLAN_PROPOSED, S.RESOLVED, S.CANCELLED},
    S.RESOLVED: set(),
    S.CANCELLED: set(),
}

TERMINAL = {S.RESOLVED, S.CANCELLED}


class InvalidTransition(Exception):
    pass


def can_transition(current: str, target: str) -> bool:
    return CaseState(target) in ALLOWED[CaseState(current)]


def transition(session: Session, case, target: CaseState | str, reason: str, actor: str = "SYSTEM",
               plan_version: int | None = None) -> None:
    from audit.log import append_event

    target = CaseState(target)
    current = CaseState(case.status)
    if target not in ALLOWED[current]:
        append_event(
            session,
            case.case_id,
            actor="POLICY",
            event_type="state.transition_blocked",
            status="blocked",
            input_summary=f"{current.value} -> {target.value}",
            output_summary=f"Transition not allowed by state machine ({reason})",
        )
        raise InvalidTransition(f"{current.value} -> {target.value} not allowed")
    case.status = target.value
    append_event(
        session,
        case.case_id,
        actor=actor,
        event_type="state.changed",
        input_summary=f"{current.value} -> {target.value}",
        output_summary=reason,
        plan_version=plan_version,
        metadata={"from": current.value, "to": target.value},
    )
    session.flush()
