"""Derive concrete Actions from a plan contract and classify their risk.

Risk classification is deterministic and comes from policy - the model never
decides whether something needs approval.

  safe              - reversible internal work (internal tasks, delegated
                      reservations with no approval flag). Pre-selected in the
                      review UI; still executed only after the review is submitted.
  approval_required - external communication, staff assignment, calendar holds,
                      volunteer assignments, approval-flagged resources.
  forbidden         - never executable (financial decisions, counseling, ...).
"""
from __future__ import annotations

import hashlib
from typing import Any

from agent.clock import fmt, parse
from models.entities import Action, CareCase


def _h(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def plan_action_specs(contract: dict, case: CareCase, message_id: str | None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    order = 0

    def add(**kw):
        nonlocal order
        order += 1
        kw.setdefault("description", "")
        kw.setdefault("reversible", True)
        specs.append({**kw, "sort_order": order})

    o = contract.get("proposed_owner")
    if o:
        add(key=f"owner:{o['staff_id']}", type="case.update", subtype="assign_owner",
            title=f"Assign {o.get('name') or o['staff_id']} as case owner",
            description=o.get("reason", ""), risk_level="approval_required",
            parameters={"case_id": case.case_id, "field": "owner_staff_id", "value": o["staff_id"]})

    for opt in contract.get("appointment_options", []):
        add(key=f"hold:{opt['staff_id']}:{opt['start']}", type="calendar.hold", subtype="appointment_hold",
            title=f"Provisional hold {fmt(parse(opt['start']))} ({opt.get('mode', '')})",
            description=opt.get("reason", ""), risk_level="approval_required",
            parameters={"case_id": case.case_id, "staff_id": opt["staff_id"], "start": opt["start"], "end": opt["end"],
                        "label": "Pastoral conversation (provisional)", "option_id": opt["option_id"]})

    for t in contract.get("volunteer_tasks", []):
        if not t.get("volunteer_id"):
            continue
        add(key=f"vtask:{t['task_key']}:{t['volunteer_id']}", type="task.create", subtype="volunteer_assignment",
            title=f"Assign driver {t.get('name') or t['volunteer_id']} - {t.get('label', t['task_key'])}",
            description=f"Pickup {fmt(parse(t['start']))}. {t.get('reason', '')}", risk_level="approval_required",
            parameters={"case_id": case.case_id, "kind": "volunteer_assignment",
                        "title": f"Ride: {t.get('label', t['task_key'])}", "assignee_type": "volunteer",
                        "assignee_id": t["volunteer_id"], "due": t["start"], "end": t["end"], "role": "transportation",
                        "campus": case.campus, "details": {"task_key": t["task_key"], "location": t.get("location", ""),
                                                           "appointment_time": t.get("appointment_time")}})

    for r in contract.get("resource_actions", []):
        if r["action"] != "reserve":
            continue
        appr = bool(r.get("approval_required"))
        add(key=f"reserve:{r['resource_id']}", type="resource.reserve", subtype="reservation",
            title=f"Reserve {r.get('name') or r['resource_id']} ({r['resource_id']})",
            description=r.get("reason", ""), risk_level="approval_required" if appr else "safe",
            parameters={"case_id": case.case_id, "resource_id": r["resource_id"], "quantity": max(1, r.get("quantity") or 1)})

    for it in contract.get("internal_tasks", []):
        add(key=f"internal:{_h(it['title'])}", type="task.create", subtype="internal", title=it["title"],
            description="Internal operational task (reversible)", risk_level="safe",
            parameters={"case_id": case.case_id, "kind": "internal", "title": it["title"],
                        "assignee_type": it.get("assignee_type", "coordinator"), "assignee_id": it.get("assignee_id")})

    msg = contract.get("message_draft")
    if msg and (case.consent_flags or {}).get("contact_ok", True):
        add(key=f"message:{_h(msg)}", type="message.send", subtype="external_message",
            title="Send confirmation message to requester", description=msg, risk_level="approval_required",
            reversible=False, parameters={"message_id": message_id})

    for f in contract.get("forbidden_items", []):
        add(key=f"forbidden:{_h(f['topic'])}", type="forbidden", subtype="human_only", title=f["topic"],
            description=f["handling"], risk_level="forbidden", reversible=False, parameters={})
    return specs


def persist_actions(session, case: CareCase, plan, specs: list[dict], prior_actions: list[Action], next_id) -> list[Action]:
    """Create Action rows; items identical to the prior version are carried over
    with their status (minimal-change re-planning)."""
    prior_by_key = {a.parameters.get("_key"): a for a in prior_actions
                    if a.execution_status not in ("invalidated", "failed")}
    rows = []
    for s in specs:
        prev = prior_by_key.get(s["key"])
        params = {**s["parameters"], "_key": s["key"]}
        a = Action(action_id=next_id(session, "ACT"), case_id=case.case_id, plan_id=plan.plan_id, type=s["type"],
                   subtype=s["subtype"], title=s["title"], description=s["description"], parameters=params,
                   risk_level=s["risk_level"], reversible=s["reversible"], sort_order=s["sort_order"])
        if s["risk_level"] == "forbidden":
            a.approval_status, a.execution_status = "n/a", "blocked_by_policy"
        elif prev is not None and prev.execution_status in ("executed", "carried_over"):
            a.approval_status, a.execution_status = "carried_over", "carried_over"
            a.carried_from, a.tool_result = prev.carried_from or prev.action_id, prev.tool_result
            if s["type"] == "message.send":
                a.parameters = {**params, "message_id": prev.parameters.get("message_id")}
        elif prev is not None and prev.approval_status in ("not_selected", "rejected") and plan.trigger.startswith("event:"):
            a.approval_status, a.execution_status = prev.approval_status, "skipped"
            a.carried_from = prev.action_id
        rows.append(a)
        session.add(a)
    session.flush()
    return rows
