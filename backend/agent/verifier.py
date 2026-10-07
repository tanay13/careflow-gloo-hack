"""Verifier: an independent pass over the proposed plan.

Deterministic checks run against FRESH database state (not the planner's
snapshot), so stale availability, fabricated IDs, restriction violations and
permission problems are caught even if the planner (or a model) got them wrong.
An optional model review can only make the result stricter.
"""
from __future__ import annotations

import re
from typing import Any

from agent.actions import plan_action_specs
from agent.clock import fmt, parse
from agent.policies import P, check_resource_restrictions, poc_ids, resource_reserve_permission, scan_forbidden_content
from llm.provider import MockLLMProvider, get_provider
from models.entities import CalendarBlock, CareCase, ResourceItem, StaffMember, Volunteer
from schemas.plan import VerifierResult
from tools.calendar import find_conflicts
from tools.resources import resource_dict
from tools.volunteers import eligibility, in_blackout

CRISIS = {"self_harm_or_crisis", "abuse", "medical_emergency", "imminent_danger", "minor_involved"}


class _Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.reasons: list[str] = []
        self.invalid: list[str] = []
        self.escalate = False
        self.feedback: dict[str, list] = {"exclude_staff": [], "exclude_slots": [], "exclude_volunteers": [],
                                          "exclude_resources": []}

    def ok(self, name: str, detail: str = "") -> None:
        self.items.append({"check": name, "status": "pass", "detail": detail})

    def fail(self, name: str, field: str, reason: str, **fb) -> None:
        self.items.append({"check": name, "status": "fail", "detail": reason, "field": field})
        self.reasons.append(reason)
        self.invalid.append(field)
        for k, v in fb.items():
            self.feedback.setdefault(k, []).append(v)

    def esc(self, name: str, reason: str) -> None:
        self.items.append({"check": name, "status": "escalate", "detail": reason})
        self.reasons.append(reason)
        self.escalate = True


def _own_hold(b: CalendarBlock, case_id: str) -> bool:
    return b.kind == "hold" and b.case_id == case_id and b.status == "active"


def verify_plan(session, case: CareCase, contract: dict, context: dict, locked: dict | None = None,
                use_model: bool = True) -> tuple[VerifierResult, dict | None]:
    locked = locked or {}
    c = _Checks()
    needs = case.structured_needs or {}
    urgent = needs.get("urgent_same_day", False)
    primary = needs.get("primary_request_type")

    # 0. Defense in depth: crisis flags must never reach planning.
    if CRISIS.intersection(case.sensitivity_flags or []):
        c.esc("safety_flags", "Case carries a safety escalation flag - automation must stop.")

    # 1. Owner / backup provenance + fresh eligibility
    tool_staff = {s["staff_id"] for s in context.get("staff_candidates", [])}
    locked_owner = (locked.get("owner") or {}).get("staff_id")
    for key in ("proposed_owner", "backup_owner"):
        o = contract.get(key)
        if not o:
            continue
        sid = o["staff_id"]
        if sid not in tool_staff and sid != locked_owner:
            c.fail("entity_provenance", f"{key}.staff_id", f"{sid} was not returned by staff.search (possible fabrication).",
                   exclude_staff=sid)
            continue
        s = session.get(StaffMember, sid)
        if s is None:
            c.fail("entity_exists", f"{key}.staff_id", f"{sid} does not exist in the roster.", exclude_staff=sid)
            continue
        problems = []
        if not s.active:
            problems.append("inactive")
        if urgent:
            if sid not in (poc_ids()["current"], poc_ids()["backup"]):
                problems.append("not the weekly POC or designated backup (urgent policy)")
        else:
            if case.campus not in s.campuses:
                problems.append(f"wrong campus ({'/'.join(s.campuses)} vs {case.campus})")
            if primary and primary not in s.approved_request_types:
                problems.append(f"not approved for {primary}")
        if problems:
            c.fail("staff_eligibility", f"{key}.staff_id", f"{s.name} ({sid}) ineligible: {', '.join(problems)}.",
                   exclude_staff=sid)
        else:
            c.ok("staff_eligibility", f"{key}: {s.name} eligible (active, {'POC policy' if urgent else 'campus + request type'})")

    owner = contract.get("proposed_owner")
    if primary in ("pastoral_conversation", "urgent_callback") and not owner:
        if not any(u.get("need") in ("staff_owner", "clarification") for u in contract.get("unresolved_items", [])):
            c.fail("completeness", "proposed_owner", "No owner proposed and no unresolved item explains why.")

    # 2. Appointments: availability evidence + fresh conflict check + no double booking
    free = {sid: {s["start"] for s in v.get("free_slots", [])} for sid, v in context.get("availability", {}).items()}
    locked_opt_ids = {o["option_id"] for o in locked.get("appointments", [])}
    seen: list[tuple] = []
    for o in contract.get("appointment_options", []):
        field = f"appointment_options[{o['option_id']}]"
        if owner and o["staff_id"] != owner["staff_id"]:
            c.fail("appointment_owner", field, "Appointment is not on the proposed owner's calendar.")
            continue
        if o["option_id"] not in locked_opt_ids and o["start"] not in free.get(o["staff_id"], set()):
            c.fail("availability_checked", field, f"{fmt(parse(o['start']))} was not among calendar.read free slots (missing availability check).",
                   exclude_slots={"staff_id": o["staff_id"], "start": o["start"]})
            continue
        start, end = parse(o["start"]), parse(o["end"])
        conflicts = [b for b in find_conflicts(session, o["staff_id"], start, end) if not _own_hold(b, case.case_id)]
        if conflicts:
            c.fail("calendar_conflict", field, f"Fresh calendar check: {o['staff_id']} is now busy at {fmt(start)} (stale availability).",
                   exclude_slots={"staff_id": o["staff_id"], "start": o["start"]})
            continue
        for s0, s1, sid in seen:
            if sid == o["staff_id"] and start < s1 and s0 < end:
                c.fail("double_booking", field, "Two options overlap on the same calendar.")
        seen.append((start, end, o["staff_id"]))
    if contract.get("appointment_options") and not any(i["status"] == "fail" and i["check"].startswith(("calendar", "availability", "double"))
                                                       for i in c.items):
        c.ok("calendar_conflict", f"{len(contract['appointment_options'])} option(s) conflict-free on fresh read")

    # 3. Volunteers
    ride_cands = {rt["task_key"]: {v["volunteer_id"] for v in rt.get("candidates", [])} for rt in context.get("ride_tasks", [])}
    locked_v = {k: t.get("volunteer_id") for k, t in (locked.get("volunteer_tasks") or {}).items()}
    unresolved_keys = {u.get("task_key") for u in contract.get("unresolved_items", [])}
    for t in contract.get("volunteer_tasks", []):
        vid, key = t.get("volunteer_id"), t["task_key"]
        field = f"volunteer_tasks[{key}]"
        if not vid:
            if key not in unresolved_keys:
                c.fail("completeness", field, "Unfilled ride without an unresolved item.")
            continue
        is_locked = locked_v.get(key) == vid
        if not is_locked and vid not in ride_cands.get(key, set()):
            c.fail("entity_provenance", field, f"{vid} was not returned by volunteer.search for {key}.", exclude_volunteers=vid)
            continue
        v = session.get(Volunteer, vid)
        if v is None:
            c.fail("entity_exists", field, f"{vid} does not exist.", exclude_volunteers=vid)
            continue
        start, end = parse(t["start"]), parse(t["end"])
        if is_locked:
            bad = (not v.active) or in_blackout(v, start, end)
            reasons = ["cancelled/unavailable"] if bad else []
        else:
            reasons = eligibility(session, v, "transportation", case.campus, start, end)
        if reasons:
            c.fail("volunteer_eligibility", field, f"{vid} ineligible: {'; '.join(reasons)}.", exclude_volunteers=vid)
        else:
            c.ok("volunteer_eligibility", f"{vid} eligible for {key}")

    # 4. Resources
    tool_res = {r["resource_id"] for r in context.get("resources", [])}
    locked_res = {r["resource_id"] for r in locked.get("resources", [])}
    never = set(P()["resource_policy"]["never_reserve_categories"])
    for r in contract.get("resource_actions", []):
        rid = r["resource_id"]
        field = f"resource_actions[{rid}]"
        item = session.get(ResourceItem, rid)
        if item is None or (rid not in tool_res and rid not in locked_res):
            c.fail("entity_provenance", field, f"{rid} is not an approved catalog item returned by resource.search.",
                   exclude_resources=rid)
            continue
        d = resource_dict(item)
        if r["action"] == "reserve":
            if item.category in never:
                c.fail("forbidden_action", field, f"{item.name} is {item.category}: CareFlow may never reserve/decide it.",
                       exclude_resources=rid)
                continue
            perm, note = resource_reserve_permission(d)
            ok, unmet = check_resource_restrictions(d, {"consent_flags": case.consent_flags,
                                                        "referrals": needs.get("referrals", [])})
            if not perm:
                c.fail("tool_permission", field, note, exclude_resources=rid)
            elif not ok:
                c.fail("resource_restriction", field, f"{item.name}: {'; '.join(unmet)}", exclude_resources=rid)
            elif rid not in locked_res and (item.status != "available" or (item.quantity is not None and item.quantity < 1)):
                c.fail("resource_availability", field, f"{item.name} ({rid}) is {item.status} (qty {item.quantity}).",
                       exclude_resources=rid)
            else:
                c.ok("resource_check", f"{rid} exists, available, restrictions satisfied")
        else:
            if item.status == "inactive":
                c.fail("resource_availability", field, f"{rid} inactive.", exclude_resources=rid)
            else:
                c.ok("resource_check", f"{rid} information item exists")

    # 5. Forbidden content + unsupported claims in human-facing text
    texts = {"message_draft": contract.get("message_draft", ""), "rationale": contract.get("rationale", "")}
    for field, text in texts.items():
        for hit in scan_forbidden_content(text):
            c.fail("forbidden_judgment", field, f"Forbidden {hit['category']} language: '{hit['match']}'.")
    known_ids = tool_staff | tool_res | locked_res | {v for vs in ride_cands.values() for v in vs} | set(locked_v.values())
    for field, text in texts.items():
        for ident in set(re.findall(r"\b(?:STF|VOL|RES)-\d{3}\b", text)):
            if ident not in known_ids:
                c.fail("unsupported_claim", field, f"Text references {ident}, which no tool returned.")
    vol_names = {t.get("name") for t in contract.get("volunteer_tasks", []) if t.get("name")}
    for n in vol_names:
        if n and n in texts["message_draft"]:
            c.fail("data_minimization", "message_draft", "Requester message must not expose volunteer names.")
    if not any(i["check"] in ("forbidden_judgment", "unsupported_claim") for i in c.items):
        c.ok("content_scan", "No counseling/diagnosis/financial-decision language; all IDs grounded in tool output")

    # 6. Approval requirements / permission model on the derived actions
    specs = plan_action_specs(contract, case, message_id="(pending)")
    for s in specs:
        if s["type"] in ("message.send", "calendar.hold") or s["subtype"] in ("assign_owner", "volunteer_assignment"):
            if s["risk_level"] != "approval_required":
                c.fail("approval_gate", s["key"], f"{s['type']} must require human approval.")
        if s["type"] == "message.send" and s["reversible"]:
            c.fail("approval_gate", s["key"], "message.send must be marked irreversible.")
    c.ok("approval_gate", f"{sum(1 for s in specs if s['risk_level'] == 'approval_required')} consequential action(s) gated for human approval")

    # 7. Unresolved needs that must go to a human now
    for u in contract.get("unresolved_items", []):
        if u.get("escalate"):
            c.esc("unresolved_need", f"Escalate: {u['detail']}")

    status = "ESCALATE" if c.escalate else ("REPLAN" if c.invalid else "PASS")
    result = VerifierResult(status=status, reasons=c.reasons, invalid_fields=c.invalid,
                            feedback={k: v for k, v in c.feedback.items() if v}, checks=c.items)

    usage = None
    provider = get_provider()
    if use_model and status == "PASS" and not isinstance(provider, MockLLMProvider):
        # Model review may only add stricter findings.
        try:
            res = provider.verify_plan(contract, {"case": needs, "checks": c.items})
            usage = res.usage
            if res.get("status") in ("REPLAN", "ESCALATE") and not usage.get("fallback_reason"):
                result.status = res["status"]
                result.reasons += [f"[model review] {r}" for r in res.get("reasons", [])][:5]
                result.invalid_fields += [str(f) for f in res.get("invalid_fields", [])][:5]
        except Exception:  # noqa: BLE001
            pass
    elif use_model:
        usage = provider.verify_plan(contract, {"checks": len(c.items)}).usage if isinstance(provider, MockLLMProvider) else None
    return result, usage
