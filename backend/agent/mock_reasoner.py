"""Deterministic reasoner used in mock mode (and as the LLM fallback).

It produces the same planner JSON contract a real model would. It only ever
selects from tool results that already passed deterministic policy filters,
so it cannot invent staff, volunteers, resources or eligibility rules.

Re-planning is "minimal change": items in `prior.locked` (already executed and
still valid) are kept; only invalidated items are re-solved.
"""
from __future__ import annotations

from typing import Any

from agent.clock import fmt, parse
from agent.policies import poc_ids

SECONDARY_TYPES = {
    "recovery_resources": "recovery_support",
    "transportation": "recovery_support",
    "hospital_visit": "hospital_followup",
    "grief_support": "grief_support",
    "family_support": "marriage_family",
}


def _first(name: str) -> str:
    return name.split(" ")[0]


def _owner_obj(c: dict, case: dict, slots: list, label: str | None = None) -> dict:
    return {
        "staff_id": c["staff_id"],
        "name": c["name"],
        "role": c["role"],
        "reason": label or c["reason"],
        "evidence": {
            "active": True,
            "campus_match": c["evidence"]["campus_match"],
            "role_match": True,
            "experience_match": c["evidence"]["experience_match"],
            "availability_checked": True,
            "free_slots_found": len(slots),
            "poc_match": c["evidence"]["poc_match"],
            "routing_rule": c["evidence"]["routing_rule"],
        },
    }


def _pick_options(slots: list[dict], n: int, one_per_day: bool = True) -> list[dict]:
    out, days = [], set()
    for s in slots:
        d = s["start"][:10]
        if one_per_day and d in days:
            continue
        out.append(s)
        days.add(d)
        if len(out) >= n:
            break
    if len(out) < n and one_per_day:  # fill from remaining slots
        for s in slots:
            if s not in out:
                out.append(s)
            if len(out) >= n:
                break
    return out


def deterministic_plan(case: dict, ctx: dict, fb: dict | None, prior: dict | None) -> dict[str, Any]:
    fb = fb or {}
    prior = prior or {}
    locked = prior.get("locked", {}) or {}
    invalidated = set(prior.get("invalidated", []) or [])
    trigger = prior.get("trigger", "initial")
    event_driven = trigger.startswith("event:")

    needs: list[str] = case.get("needs", [])
    urgent = case.get("urgent_same_day", False)
    campus = case.get("campus")
    flags = set(case.get("routing_flags", []))

    unresolved: list[dict] = []
    forbidden: list[dict] = []
    internal: list[dict] = list(locked.get("internal_tasks", []))
    rationale: list[str] = []

    # ------------------------------------------------------------------ owner
    avail = ctx.get("availability", {})
    excl_slots = {(s["staff_id"], s["start"]) for s in fb.get("exclude_slots", [])}

    def slots(sid: str) -> list[dict]:
        return [s for s in avail.get(sid, {}).get("free_slots", []) if (sid, s["start"]) not in excl_slots]

    all_cands = ctx.get("staff_candidates", [])
    cands = [c for c in all_cands if c["staff_id"] not in set(fb.get("exclude_staff", []))]
    by_id = {c["staff_id"]: c for c in all_cands}

    owner = backup = None
    if invalidated:
        what = ", ".join(k.replace("_", " ").replace(":", " ") for k in sorted(invalidated))
        rationale.append(f"Re-planned after {trigger.split(':', 1)[-1].replace('_', ' ')}: only invalidated items ({what}) "
                         "were re-solved; all other commitments are unchanged.")
    if locked.get("owner") and locked["owner"]["staff_id"] in by_id:
        owner = locked["owner"]
        backup = locked.get("backup")
        rationale.append(f"Owner {owner['name']} unchanged.")
    elif case.get("primary_request_type") in ("pastoral_conversation", "urgent_callback") and cands:
        if urgent:
            ordered = list(cands)  # policy order: current POC, then backup POC
        else:
            wanted = {SECONDARY_TYPES[n] for n in needs if n in SECONDARY_TYPES}
            ordered = sorted(cands, key=lambda c: (
                -len(c["evidence"]["experience_match"]),
                -len(wanted.intersection(c.get("approved_request_types", []))),
                -min(len(slots(c["staff_id"])), 4),
                c["staff_id"]))
        pref = fb.get("preferred_owner")
        if pref and pref in {c["staff_id"] for c in ordered}:
            ordered.sort(key=lambda c: c["staff_id"] != pref)
            rationale.append(f"Reviewer reassigned owner to {by_id[pref]['name']}.")
        req_name = (case.get("preferred_staff_name") or "").lower()
        if req_name:
            match = [c for c in ordered if req_name in c["name"].lower()]
            if match and slots(match[0]["staff_id"]):
                ordered.sort(key=lambda c: c["staff_id"] != match[0]["staff_id"])
                rationale.append(f"Requester asked for {match[0]['name']}, who is eligible and available.")
            elif match:
                rationale.append(f"Requester asked for {match[0]['name']}, who has no availability in the window; "
                                 "an eligible alternative is proposed.")
            else:
                rationale.append(f"Requested staff '{case['preferred_staff_name']}' is not in the eligible pool for this request.")
        with_slots = [c for c in ordered if slots(c["staff_id"])]
        if with_slots:
            o = with_slots[0]
            if urgent:
                poc = poc_ids()
                label = ("Current weekly Pastor on Call - urgent same-day policy rule" if o["staff_id"] == poc["current"]
                         else "Current POC unavailable today - designated backup POC per policy")
                owner = _owner_obj(o, case, slots(o["staff_id"]), label)
                if o["staff_id"] != poc["current"]:
                    rationale.append("Weekly POC has no callback window today; fallback rule routes to the designated backup POC.")
                else:
                    rationale.append("Urgent same-day request routed to this week's Pastor on Call by policy (not model judgment).")
            else:
                owner = _owner_obj(o, case, slots(o["staff_id"]))
                exp = ", ".join(o["evidence"]["experience_match"]) or "general pastoral care"
                rationale.append(f"Locality + experience routing: {o['name']} ({o['role']}, {campus}) is approved for "
                                 f"pastoral conversations with relevant experience ({exp}); availability verified.")
            rest = [c for c in with_slots[1:]] or [c for c in ordered if c["staff_id"] != o["staff_id"]]
            if rest:
                b = rest[0]
                backup = _owner_obj(b, case, slots(b["staff_id"]),
                                    "Backup: next eligible candidate by policy ranking")
        else:
            need = "urgent callback today" if urgent else "pastoral conversation in requested window"
            unresolved.append({"need": "staff_owner", "severity": "blocking", "escalate": True,
                               "detail": f"No eligible staff has availability for {need} "
                                         f"({len(cands)} eligible candidate(s) checked). Care Coordinator must assign manually."})
    elif case.get("primary_request_type") in ("pastoral_conversation", "urgent_callback") and not cands:
        if campus or urgent:
            unresolved.append({"need": "staff_owner", "severity": "blocking", "escalate": True,
                               "detail": "No eligible staff returned by staff.search for this campus/request type."})

    # ------------------------------------------------------------ appointments
    options: list[dict] = []
    locked_opts = [o for o in locked.get("appointments", []) if f"appointment:{o['option_id']}" not in invalidated]
    if owner:
        prior_opts = locked.get("appointments", [])
        wanted = len(prior_opts) or ctx.get("max_options", 2)
        options = list(locked_opts)
        missing_n = wanted - len(options)
        if missing_n > 0:
            taken = {o["start"] for o in options}
            fresh = [s for s in slots(owner["staff_id"]) if s["start"] not in taken]
            chosen = _pick_options(fresh, missing_n, one_per_day=not urgent)
            used = {o["option_id"] for o in prior.get("contract", {}).get("appointment_options", [])} | \
                {o["option_id"] for o in options}
            n = 1
            for s in chosen:
                while f"opt-{n}" in used:
                    n += 1
                used.add(f"opt-{n}")
                mode = "phone call" if (urgent or case.get("contact_method") == "phone") else f"in person at {campus} campus"
                options.append({
                    "option_id": f"opt-{n}", "staff_id": owner["staff_id"], "start": s["start"], "end": s["end"],
                    "mode": mode, "availability_checked": True,
                    "reason": ("Callback window today from free/busy check" if urgent
                               else f"Free on {owner['name']}'s calendar; avoids requester's ride windows"),
                })
            if prior_opts and not chosen:
                unresolved.append({"need": "appointment", "severity": "blocking", "escalate": event_driven,
                                   "detail": f"{owner['name']} has no remaining free slot in the window after the calendar conflict."})
        if options:
            rationale.append(f"{len(options)} appointment option(s) proposed from verified free/busy data.")

    # --------------------------------------------------------- volunteer tasks
    vtasks: list[dict] = []
    excl_vol = set(fb.get("exclude_volunteers", []))
    locked_v = locked.get("volunteer_tasks", {})
    if "transportation" in needs:
        rides = ctx.get("ride_tasks", [])
        if not rides:
            trips = case.get("transport_trips") or "the"
            unresolved.append({"need": "transportation", "severity": "needs_info", "escalate": False,
                               "detail": f"Transportation requested for {trips} appointment(s) but dates/times were not provided; "
                                         "coordinator must collect them before drivers can be matched."})
        for rt in rides:
            key = rt["task_key"]
            if key in locked_v and f"volunteer_task:{key}" not in invalidated:
                vtasks.append(locked_v[key])
                continue
            pool = [c for c in rt.get("candidates", []) if c["volunteer_id"] not in excl_vol]
            base = {"task_key": key, "need": "transportation", "label": rt["label"],
                    "appointment_time": rt["appointment_time"], "location": rt.get("location", ""),
                    "start": rt["start"], "end": rt["end"]}
            if pool:
                v = pool[0]
                replaced = f"volunteer_task:{key}" in invalidated
                vtasks.append({**base, "volunteer_id": v["volunteer_id"], "name": v["name"],
                               "reason": ("Replacement: " if replaced else "") +
                                         f"eligible {campus}-area driver; trained; available {fmt(parse(rt['start']))}; "
                                         f"lowest current load ({v['current_load']})",
                               "replacement": replaced})
            else:
                excl_n = len(rt.get("excluded", []))
                vtasks.append({**base, "volunteer_id": None, "name": None, "reason": "No eligible driver"})
                unresolved.append({
                    "need": "transportation", "task_key": key, "severity": "blocking",
                    "escalate": event_driven,
                    "detail": f"No eligible driver for {rt['label']} - pickup {fmt(parse(rt['start']))} "
                              f"({rt.get('location', '')}). {excl_n} volunteer(s) checked and excluded.",
                })
        filled = sum(1 for t in vtasks if t.get("volunteer_id"))
        if rides:
            rationale.append(f"Transportation: {filled}/{len(rides)} ride(s) matched to trained {campus} drivers available at pickup time.")

    # --------------------------------------------------------------- resources
    res_actions: list[dict] = []
    resources = ctx.get("resources", [])
    excl_res = set(fb.get("exclude_resources", [])) | {k.split(":", 1)[1] for k in invalidated if k.startswith("resource:")}
    locked_r = [r for r in locked.get("resources", []) if f"resource:{r['resource_id']}" not in invalidated]
    res_actions.extend(locked_r)
    have = {r["resource_id"] for r in res_actions}

    def add(r: dict, action: str, reason: str) -> None:
        if r["resource_id"] in have:
            return
        have.add(r["resource_id"])
        res_actions.append({"resource_id": r["resource_id"], "name": r["name"], "category": r["category"],
                            "action": action, "quantity": 1 if action == "reserve" else 0,
                            "approval_required": bool(r["approval_required"]) and action == "reserve",
                            "kind": r["kind"], "reason": reason})

    cats_done = {r["category"] for r in locked_r}
    by_cat: dict[str, list[dict]] = {}
    for r in resources:
        if r["resource_id"] in excl_res:
            continue
        by_cat.setdefault(r["category"], []).append(r)

    def handle_physical(cat: str, label: str) -> None:
        items = by_cat.get(cat, [])
        phys = [r for r in items if r["kind"] in ("physical", "service")]
        good = [r for r in phys if r["available"] and r["reserve_permitted"] and r["restrictions_satisfied"]]
        if good:
            r = good[0]
            note = "approval required (coordinator sign-off)" if r["approval_required"] else "delegated, reversible reservation"
            add(r, "reserve", f"In approved catalog at {r['campus']}; {r['quantity']} available; {note}")
            return
        restricted = [r for r in phys if r["available"] and not r["restrictions_satisfied"]]
        for r in restricted:
            unresolved.append({"need": cat, "severity": "info", "escalate": False,
                               "detail": f"{r['name']} ({r['resource_id']}) not allocated: {'; '.join(r['unmet_restrictions'])}"})
        unavailable = [r for r in phys if not r["available"]] + \
            [r for r in resources if r["resource_id"] in excl_res and r["category"] == cat]
        subs = [s for s in resources if s["available"] and s["resource_id"] not in excl_res and
                any(u["resource_id"] in s.get("substitute_for", []) for u in unavailable)]
        if subs:
            s = subs[0]
            names = ", ".join(sorted({u["resource_id"] for u in unavailable}))
            add(s, "share_info" if s["kind"] == "information" else "reserve",
                f"Approved substitute for {names} (unavailable)")
        elif unavailable or (not phys and cat in ("meals",)):
            names = ", ".join(sorted({f"{u['name']} ({u['resource_id']})" for u in unavailable})) or label
            unresolved.append({"need": cat, "severity": "blocking" if event_driven else "info",
                               "escalate": False,
                               "detail": f"{names} unavailable and no approved substitute - gap flagged for coordinator."})

    if "recovery_resources" in needs and "recovery_resources" not in cats_done:
        handle_physical("recovery_resources", "Recovery packet")
    if ("meals" in needs or "recovery_resources" in needs) and "meals" not in cats_done:
        handle_physical("meals", "Meal support")
    if "mobility_equipment" in needs and "mobility_equipment" not in cats_done:
        handle_physical("mobility_equipment", "Mobility equipment")
    if "grief_support" in needs:
        for r in by_cat.get("grief_support", []):
            if r["kind"] == "information" and r["available"]:
                add(r, "share_info", "Approved information resource")
            elif not r["restrictions_satisfied"]:
                unresolved.append({"need": "grief_support", "severity": "info", "escalate": False,
                                   "detail": f"{r['name']} not allocated: {'; '.join(r['unmet_restrictions'])}"})
    info_cats = ["support_group", "transportation", "hospital_visitation", "family_support"]
    for cat in info_cats:
        for r in by_cat.get(cat, []):
            if r["kind"] == "information" and r["available"]:
                add(r, "share_info", "Approved information resource relevant to stated need")

    if "financial_assistance" in needs or "financial_assistance" in flags:
        for r in by_cat.get("financial_assistance", []):
            add(r, "share_info", "Referral information only - the benevolence team decides")
        internal.append({"title": "Benevolence referral: requester asked about financial help (decision by benevolence team)",
                         "assignee_type": "staff", "assignee_id": poc_ids()["benevolence"]})
        forbidden.append({"topic": "Financial assistance decision",
                          "handling": "CareFlow cannot approve, deny, or estimate assistance. Routed to the benevolence "
                                      "team's separate process (typically 7-10 business days)."})
    if "counseling_advice" in needs or "counseling_advice" in flags:
        forbidden.append({"topic": "Counseling / personal advice requested",
                          "handling": "CareFlow does not counsel or advise. The request is routed to a pastor for a human conversation."})
    if "prompt_injection" in flags:
        forbidden.append({"topic": "Instructions embedded in request text",
                          "handling": "Treated as untrusted content. Policies, permissions and approval gates are unchanged."})

    reserved = [r for r in res_actions if r["action"] == "reserve"]
    if reserved:
        rationale.append("Resources: " + ", ".join(f"{r['name']} ({r['resource_id']})" for r in reserved) + " from the approved catalog.")

    # ------------------------------------------------------------ internal tasks
    titles = {t["title"] for t in internal}
    coord = poc_ids()["coordinator"]
    for r in reserved:
        if r["kind"] == "physical":
            t = f"Prepare {r['name']} ({r['resource_id']}) for pickup/delivery"
            if t not in titles:
                internal.append({"title": t, "assignee_type": "coordinator", "assignee_id": coord})
    if not case.get("campus") and not urgent:
        t = "Contact requester to clarify campus and specific need"
        if t not in titles:
            internal.append({"title": t, "assignee_type": "coordinator", "assignee_id": coord})
    if any(u["severity"] == "needs_info" for u in unresolved):
        t = "Collect missing details from requester (see unresolved items)"
        if t not in titles:
            internal.append({"title": t, "assignee_type": "coordinator", "assignee_id": coord})

    for m in case.get("missing_facts", []):
        if "Campus not stated" in m or "need is unclear" in m:
            unresolved.append({"need": "clarification", "severity": "needs_info", "escalate": False, "detail": m})

    # ----------------------------------------------------------------- message
    message = _draft_message(case, owner, options, vtasks, res_actions, unresolved, urgent)

    if not rationale:
        rationale.append("Insufficient information to route; flagged missing facts for the coordinator instead of guessing.")

    return {
        "objective": _objective(case),
        "known_facts": case.get("known_facts", []),
        "missing_facts": case.get("missing_facts", []),
        "sensitivity_flags": sorted(set(case.get("sensitivity_flags", [])) | flags),
        "proposed_owner": owner,
        "backup_owner": backup,
        "appointment_options": options,
        "resource_actions": res_actions,
        "volunteer_tasks": vtasks,
        "internal_tasks": internal,
        "message_draft": message,
        "approvals_required": [],
        "unresolved_items": unresolved,
        "forbidden_items": forbidden,
        "rationale": " ".join(rationale),
        "stop_reason": None,
    }


def _objective(case: dict) -> str:
    parts = []
    needs = case.get("needs", [])
    if case.get("urgent_same_day"):
        parts.append("same-day pastoral callback")
    elif "pastoral_conversation" in needs:
        parts.append("pastoral conversation")
    if "transportation" in needs:
        parts.append("transportation")
    if "recovery_resources" in needs:
        parts.append("recovery resources")
    if "financial_assistance" in needs:
        parts.append("benevolence referral")
    if not parts:
        parts.append("clarify request")
    where = f" ({case['campus']})" if case.get("campus") else ""
    return "Coordinate " + ", ".join(parts) + where


def _draft_message(case, owner, options, vtasks, res_actions, unresolved, urgent) -> str:
    """Operational, non-counseling confirmation script. Never includes volunteer names."""
    campus = case.get("campus")
    lines = [f"Hello, this is the {campus + ' ' if campus else ''}Care team following up on your request "
             f"(ref {case['case_id']})."]
    if owner and urgent and options:
        lines.append(f"{_first(owner['name'])} from our pastoral team will call you today; the earliest window is "
                     f"{fmt(parse(options[0]['start']))}.")
    elif owner and options:
        times = " or ".join(fmt(parse(o["start"])) for o in options)
        lines.append(f"{_first(owner['name'])} from our Care team would be glad to have a pastoral conversation with you. "
                     f"Possible times: {times}. Please let us know which works best.")
    elif owner:
        lines.append(f"{_first(owner['name'])} from our Care team will reach out to schedule a conversation.")
    filled = [t for t in vtasks if t.get("volunteer_id")]
    if filled:
        # Deliberately count-free so a driver swap does not change (and re-gate) the message.
        lines.append("We are arranging volunteer drivers for your follow-up appointments; "
                     "we will confirm pickup details with you.")
    reserve = [r for r in res_actions if r["action"] == "reserve"]
    info = [r for r in res_actions if r["action"] == "share_info"]
    if reserve:
        lines.append("We are setting aside: " + ", ".join(r["name"] for r in reserve) + " (subject to confirmation).")
    if info:
        lines.append("We can also share information on: " + ", ".join(r["name"] for r in info) + ".")
    if "financial_assistance" in case.get("needs", []):
        lines.append("Financial assistance is reviewed by a separate team through its own process; "
                     "we have included how to apply.")
    if any(u["severity"] == "needs_info" for u in unresolved):
        lines.append("Could you share a few more details (for example your campus, what you need help with, "
                     "or appointment times) so we can route this to the right person?")
    lines.append("If anything changes, reply to this message or call the Care office.")
    return " ".join(lines)
