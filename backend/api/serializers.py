"""Shape ORM rows into JSON for the frontend."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from models.entities import (Action, Approval, AuditEvent, CalendarBlock, CarePlan, CareCase, InternalTask, Message,
                             Reservation, ResourceItem, StaffMember, Volunteer)


def _dt(v):
    return v.isoformat(timespec="seconds") if v else None


def audit_row(e: AuditEvent) -> dict[str, Any]:
    return {"event_id": e.event_id, "case_id": e.case_id, "timestamp": _dt(e.timestamp), "actor": e.actor,
            "event_type": e.event_type, "status": e.status, "tool_name": e.tool_name, "input_summary": e.input_summary,
            "output_summary": e.output_summary, "plan_version": e.plan_version, "approval_ref": e.approval_ref,
            "latency_ms": e.latency_ms, "metadata": e.event_metadata or {}}


def action_row(a: Action, approvals: list[Approval]) -> dict[str, Any]:
    appr = [x for x in approvals if x.action_id == a.action_id]
    last = appr[-1] if appr else None
    return {"action_id": a.action_id, "plan_id": a.plan_id, "type": a.type, "subtype": a.subtype, "title": a.title,
            "description": a.description, "parameters": {k: v for k, v in (a.parameters or {}).items() if not k.startswith("_")},
            "risk_level": a.risk_level, "reversible": a.reversible, "approval_status": a.approval_status,
            "execution_status": a.execution_status, "tool_result": a.tool_result, "carried_from": a.carried_from,
            "approval": {"approval_id": last.approval_id, "reviewer": last.reviewer, "decision": last.decision,
                         "timestamp": _dt(last.timestamp), "comments": last.comments} if last else None}


def plan_row(p: CarePlan, actions: list[Action], approvals: list[Approval]) -> dict[str, Any]:
    c = p.contract or {}
    return {"plan_id": p.plan_id, "version": p.version, "status": p.status, "trigger": p.trigger,
            "created_at": _dt(p.created_at), "planner_source": p.planner_source,
            "objective": c.get("objective"), "known_facts": c.get("known_facts", []), "missing_facts": c.get("missing_facts", []),
            "owner": p.owner, "backup_owner": p.backup_owner, "appointment_options": p.appointment_options,
            "resource_actions": p.resource_actions, "volunteer_tasks": p.volunteer_tasks,
            "internal_tasks": c.get("internal_tasks", []), "message_draft": c.get("message_draft"),
            "unresolved_items": p.unresolved_items, "forbidden_items": p.forbidden_items, "rationale": p.rationale,
            "required_approvals": p.required_approvals, "verifier_status": p.verifier_status,
            "verifier_result": p.verifier_result,
            "actions": [action_row(a, approvals) for a in sorted(actions, key=lambda a: a.sort_order)]}


def case_summary(c: CareCase, session: Session | None = None) -> dict[str, Any]:
    owner = None
    if session is not None and c.owner_staff_id:
        s = session.get(StaffMember, c.owner_staff_id)
        owner = s.name if s else None
    plan_v = None
    if session is not None and c.current_plan_id:
        p = session.get(CarePlan, c.current_plan_id)
        plan_v = p.version if p else None
    needs = c.structured_needs or {}
    return {"case_id": c.case_id, "created_at": _dt(c.created_at), "updated_at": _dt(c.updated_at), "source": c.source,
            "campus": c.campus, "status": c.status, "request_text": c.request_text, "needs": needs.get("needs", []),
            "urgent": needs.get("urgent_same_day", False), "sensitivity_flags": c.sensitivity_flags or [],
            "owner_name": owner, "plan_version": plan_v, "is_running": c.is_running, "current_step": c.current_step,
            "duplicate_of": c.duplicate_of}


def case_detail(session: Session, c: CareCase) -> dict[str, Any]:
    plans = session.query(CarePlan).filter(CarePlan.case_id == c.case_id).order_by(CarePlan.version).all()
    actions = session.query(Action).filter(Action.case_id == c.case_id).all()
    approvals = session.query(Approval).filter(Approval.case_id == c.case_id).order_by(Approval.timestamp).all()
    by_plan: dict[str, list[Action]] = {}
    for a in actions:
        by_plan.setdefault(a.plan_id, []).append(a)
    tasks = session.query(InternalTask).filter(InternalTask.case_id == c.case_id).order_by(InternalTask.created_at).all()
    holds = session.query(CalendarBlock).filter(CalendarBlock.case_id == c.case_id).all()
    res = session.query(Reservation).filter(Reservation.case_id == c.case_id).all()
    msgs = session.query(Message).filter(Message.case_id == c.case_id).order_by(Message.created_at).all()
    events = session.query(AuditEvent).filter(AuditEvent.case_id == c.case_id).order_by(AuditEvent.event_id).all()
    staff_names = {s.staff_id: s.name for s in session.query(StaffMember).all()}
    vol_names = {v.volunteer_id: v.name for v in session.query(Volunteer).all()}
    res_names = {r.resource_id: r.name for r in session.query(ResourceItem).all()}
    ctx = c.context or {}
    return {
        **case_summary(c, session),
        "requester_ref": c.requester_ref,
        "intake_form": c.intake_form,
        "consent_flags": c.consent_flags,
        "structured_needs": c.structured_needs,
        "safety_result": c.safety_result,
        "escalation": c.escalation,
        "error": c.error,
        "summary": c.summary,
        "metrics": c.metrics,
        "current_plan_id": c.current_plan_id,
        "context": {
            "staff_candidates": ctx.get("staff_candidates", []),
            "staff_excluded": ctx.get("staff_excluded", []),
            "routing_rule": ctx.get("routing_rule"),
            "availability": ctx.get("availability", {}),
            "window": ctx.get("window"),
            "resources": ctx.get("resources", []),
            "ride_tasks": ctx.get("ride_tasks", []),
            "feedback": ctx.get("feedback", {}),
        },
        "plans": [plan_row(p, by_plan.get(p.plan_id, []), approvals) for p in plans],
        "changes": {
            "tasks": [{"task_id": t.task_id, "kind": t.kind, "title": t.title, "assignee_type": t.assignee_type,
                       "assignee_id": t.assignee_id,
                       "assignee_name": vol_names.get(t.assignee_id) or staff_names.get(t.assignee_id),
                       "due": _dt(t.due), "status": t.status, "details": t.details} for t in tasks],
            "calendar_holds": [{"block_id": h.block_id, "hold_id": h.source, "staff_id": h.staff_id,
                                "staff_name": staff_names.get(h.staff_id), "start": _dt(h.start), "end": _dt(h.end),
                                "status": h.status} for h in holds],
            "reservations": [{"reservation_id": r.reservation_id, "resource_id": r.resource_id,
                              "resource_name": res_names.get(r.resource_id), "quantity": r.quantity, "status": r.status}
                             for r in res],
            "messages": [{"message_id": m.message_id, "channel": m.channel, "recipient_ref": m.recipient_ref,
                          "body": m.body, "status": m.status, "created_at": _dt(m.created_at), "sent_at": _dt(m.sent_at)}
                         for m in msgs],
        },
        "audit": [audit_row(e) for e in events],
        "names": {"staff": staff_names, "volunteers": vol_names, "resources": res_names},
    }
