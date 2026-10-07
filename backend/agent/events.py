"""Demo event injection ("Simulate Event").

Every event mutates real backend state (volunteer blackout, resource stock,
calendar block, tool fault switchboard) and then lets the orchestrator detect
the invalidated plan and re-plan. Nothing here fakes the UI.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from agent import orchestrator as orch
from agent.clock import fmt, iso, parse
from agent.state_machine import CaseState as S
from agent.state_machine import transition
from audit.log import append_event
from models.entities import Action, CalendarBlock, CarePlan, CareCase, ResourceItem, Volunteer
from tools import ToolContext, call_tool
from tools.base import clear_faults, set_fault

EVENT_TYPES = ["volunteer_cancelled", "resource_unavailable", "staff_calendar_conflict", "tool_outage",
               "tool_restored", "tasks_completed"]
LIVE = ("executed", "carried_over", "pending")


class EventError(Exception):
    pass


def _ctx(session, case_id, version=None) -> ToolContext:
    return ToolContext(session, case_id, actor="EVENT", plan_version=version)


def _origin(a: Action) -> str:
    return a.carried_from or a.action_id


def inject_event(session: Session, case_id: str, etype: str, target: Optional[str] = None,
                 mode: Optional[str] = None, tool: Optional[str] = None) -> dict[str, Any]:
    case = session.get(CareCase, case_id)
    if case is None:
        raise KeyError(case_id)
    if etype not in EVENT_TYPES:
        raise EventError(f"Unknown event type {etype}")
    if case.is_running:
        raise orch.CaseBusy("Agent is running; wait for it to finish")
    plan = session.get(CarePlan, case.current_plan_id) if case.current_plan_id else None
    actions = session.query(Action).filter(Action.plan_id == plan.plan_id).order_by(Action.sort_order).all() if plan else []
    version = plan.version if plan else None

    if etype == "tool_outage":
        if not tool:
            # Default to a tool the monitoring check will actually exercise for this case.
            live = [a for a in actions if a.execution_status in ("executed", "carried_over")]
            tool = ("volunteer.search" if any(a.subtype == "volunteer_assignment" for a in live) or case.status == "NEW"
                    else "calendar.read" if any(a.type == "calendar.hold" for a in live) else "resource.search")
        mode = mode or "persistent"
        set_fault(session, tool, mode)
        append_event(session, case_id, actor="EVENT", event_type="tool.outage_injected", status="warn", tool_name=tool,
                     output_summary=f"{tool} outage injected ({mode}: {'fails once, retry succeeds' if mode == 'transient' else 'fails until restored'})")
        session.commit()
        if case.status == S.MONITORING.value:
            orch.launch(orch._flow_monitor, case_id, "monitoring_check")
            return {"ok": True, "next": "monitoring_check"}
        return {"ok": True, "next": "outage will affect the next tool call"}

    if etype == "tool_restored":
        clear_faults(session)
        append_event(session, case_id, actor="EVENT", event_type="tool.restored", output_summary="All simulated outages cleared")
        session.commit()
        return {"ok": True}

    if etype == "tasks_completed":
        if case.status != S.MONITORING.value:
            raise EventError("Case must be MONITORING to close")
        from models.entities import InternalTask

        n = 0
        for t in session.query(InternalTask).filter(InternalTask.case_id == case_id, InternalTask.status == "open").all():
            call_tool("task.complete", _ctx(session, case_id, version), {"task_id": t.task_id})
            n += 1
        append_event(session, case_id, actor="EVENT", event_type="tasks.completed", output_summary=f"{n} open task(s) marked complete")
        summary = orch.operational_summary(session, case)
        call_tool("case.update", ToolContext(session, case_id, actor="SYSTEM", plan_version=version),
                  {"case_id": case_id, "field": "summary", "value": summary})
        transition(session, case, S.RESOLVED, "All required tasks complete; operational summary generated", actor="SYSTEM")
        session.commit()
        return {"ok": True, "summary": summary}

    if case.status not in (S.MONITORING.value, S.AWAITING_APPROVAL.value):
        raise EventError(f"Plan-invalidating events apply to MONITORING or AWAITING_APPROVAL cases (case is {case.status})")

    invalidated: list[str] = []
    fb: dict[str, list] = {}
    refresh: set[str] = set()

    if etype == "volunteer_cancelled":
        vts = [a for a in actions if a.subtype == "volunteer_assignment" and a.execution_status in LIVE
               and a.approval_status not in ("not_selected", "rejected")]
        if target:
            vts = [a for a in vts if a.parameters.get("assignee_id") == target]
        if not vts:
            raise EventError("No active volunteer assignment to cancel in the current plan")
        a = vts[0]
        p = a.parameters
        vid = p["assignee_id"]
        v = session.get(Volunteer, vid)
        v.blackout = list(v.blackout or []) + [{"start": p["due"], "end": p["end"], "reason": "volunteer cancelled (demo event)"}]
        append_event(session, case_id, actor="EVENT", event_type="volunteer.cancelled", status="warn", plan_version=version,
                     output_summary=f"Volunteer {vid} cancelled {p['details']['task_key']} (pickup {fmt(parse(p['due']))})",
                     metadata={"volunteer_id": vid})
        if a.execution_status in ("executed", "carried_over"):
            call_tool("task.cancel", _ctx(session, case_id, version), {"action_id": _origin(a), "reason": f"{vid} cancelled"})
        a.execution_status = "invalidated"
        invalidated.append(f"volunteer_task:{p['details']['task_key']}")
        fb["exclude_volunteers"] = [vid]
        refresh = {"volunteers"}

    elif etype == "resource_unavailable":
        rs = [a for a in actions if a.type == "resource.reserve" and a.execution_status in LIVE
              and a.approval_status not in ("not_selected", "rejected")]
        if target:
            rs = [a for a in rs if a.parameters.get("resource_id") == target]
        if not rs:
            raise EventError("No reserved/planned resource to make unavailable")
        a = rs[0]
        rid = a.parameters["resource_id"]
        item = session.get(ResourceItem, rid)
        item.status, item.quantity = "out_of_stock", 0
        append_event(session, case_id, actor="EVENT", event_type="resource.unavailable", status="warn", plan_version=version,
                     output_summary=f"{item.name} ({rid}) became unavailable (stock 0)")
        if a.execution_status in ("executed", "carried_over"):
            call_tool("resource.release", _ctx(session, case_id, version), {"action_id": _origin(a)})
        a.execution_status = "invalidated"
        invalidated.append(f"resource:{rid}")
        refresh = {"resources"}

    elif etype == "staff_calendar_conflict":
        hs = [a for a in actions if a.type == "calendar.hold" and a.execution_status in LIVE
              and a.approval_status not in ("not_selected", "rejected")]
        if not hs:
            raise EventError("No appointment hold/option to conflict with")
        a = hs[0]
        p = a.parameters
        start, end = parse(p["start"]), parse(p["end"])
        session.add(CalendarBlock(staff_id=p["staff_id"], start=start - timedelta(minutes=15), end=end + timedelta(minutes=15),
                                  kind="busy", status="active", source="external_calendar_sync (demo event)"))
        append_event(session, case_id, actor="EVENT", event_type="calendar.conflict", status="warn", plan_version=version,
                     output_summary=f"External meeting added to {p['staff_id']} at {fmt(start)} - overlaps proposed/held slot")
        if a.execution_status in ("executed", "carried_over"):
            call_tool("calendar.release", _ctx(session, case_id, version), {"action_id": _origin(a)})
        a.execution_status = "invalidated"
        invalidated.append(f"appointment:{p.get('option_id')}")
        fb["exclude_slots"] = [{"staff_id": p["staff_id"], "start": p["start"]}]
        refresh = {"calendar"}

    session.commit()
    orch.launch(orch._flow_event_replan, case_id, f"replan_{etype}", invalidated, fb, sorted(refresh), f"event:{etype}")
    return {"ok": True, "next": "replanning", "invalidated": invalidated}


__all__ = ["inject_event", "EVENT_TYPES", "EventError", "iso"]
