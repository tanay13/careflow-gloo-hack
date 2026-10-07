"""Context gathering: the agent calls read-only tools to collect exactly the
operational data a plan needs (and nothing else)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from agent.clock import at_offset, demo_now, end_of_today, end_of_week, iso, parse
from agent.policies import P, categories_for_needs


def planning_window(needs: dict) -> tuple[str, str, int]:
    r = P()["routing"]
    now = demo_now()
    if needs.get("urgent_same_day"):
        return iso(now + timedelta(minutes=30)), iso(end_of_today()), r["urgent_callback_minutes"]
    if needs.get("timeframe") == "next_week":
        return iso(at_offset(7, "09:00")), iso(at_offset(11, "17:00")), r["appointment_minutes"]
    end = end_of_week()
    if (end - now) < timedelta(days=1):
        end = now + timedelta(days=4)
    return iso(now), iso(end), r["appointment_minutes"]


def gather_context(case, call: Callable[[str, dict], Any], feedback: dict, pause: Callable[[], None],
                   only: set[str] | None = None, prior_context: dict | None = None) -> dict[str, Any]:
    """`call(tool_name, payload)` executes a tool through the permissioned registry.

    `only` lets re-planning refresh just the affected sources (e.g. volunteers
    after a cancellation) while reusing the rest of `prior_context`.
    """
    needs = case.structured_needs or {}
    ctx: dict[str, Any] = dict(prior_context or {})
    ctx["case_id"] = case.case_id
    ctx["max_options"] = P()["routing"]["max_appointment_options"]
    want = lambda k: only is None or k in only  # noqa: E731

    primary = needs.get("primary_request_type")
    if want("staff") and primary in ("pastoral_conversation", "urgent_callback"):
        out = call("staff.search", {
            "campus": case.campus, "request_type": primary,
            "experience_tags": needs.get("experience_tags", []),
            "urgent": bool(needs.get("urgent_same_day")),
            "exclude_ids": feedback.get("exclude_staff", []),
        })
        ctx["staff_candidates"] = [c.model_dump() for c in out.candidates]
        ctx["staff_excluded"] = [e.model_dump() for e in out.excluded]
        ctx["routing_rule"] = out.routing_rule
        pause()
    elif want("staff"):
        ctx.setdefault("staff_candidates", [])

    if want("calendar") and ctx.get("staff_candidates"):
        w0, w1, minutes = planning_window(needs)
        avoid = [{"start": a["ride_start"], "end": a["ride_end"]} for a in needs.get("appointments", [])]
        out = call("calendar.read", {"staff_ids": [c["staff_id"] for c in ctx["staff_candidates"]],
                                     "window_start": w0, "window_end": w1, "slot_minutes": minutes, "avoid": avoid})
        ctx["availability"] = {a.staff_id: {"free_slots": [s.model_dump() for s in a.free_slots],
                                            "busy": [b.model_dump() for b in a.busy]} for a in out.availability}
        ctx["window"] = {"start": w0, "end": w1}
        pause()

    if want("resources"):
        cats = categories_for_needs(needs.get("needs", []))
        if "financial_assistance" in (case.safety_result or {}).get("routing_flags", []) and "financial_assistance" not in cats:
            cats.append("financial_assistance")
        if cats:
            out = call("resource.search", {"campus": case.campus, "categories": cats,
                                           "consent_flags": case.consent_flags or {},
                                           "referrals": needs.get("referrals", [])})
            ctx["resources"] = [i.model_dump() for i in out.items]
            pause()
        else:
            ctx.setdefault("resources", [])

    if want("volunteers") and "transportation" in needs.get("needs", []):
        rides = []
        excl = feedback.get("exclude_volunteers", [])
        for i, a in enumerate(needs.get("appointments", []), start=1):
            out = call("volunteer.search", {"role": "transportation", "campus": case.campus,
                                            "start": a["ride_start"], "end": a["ride_end"], "exclude_ids": excl})
            rides.append({"task_key": f"ride-{i}", "label": a["label"], "location": a.get("location", ""),
                          "appointment_time": a["appointment_time"], "start": a["ride_start"], "end": a["ride_end"],
                          "candidates": [c.model_dump() for c in out.candidates],
                          "excluded": [e.model_dump() for e in out.excluded]})
            pause()
        ctx["ride_tasks"] = rides
    elif want("volunteers"):
        ctx.setdefault("ride_tasks", [])
    return ctx


def summarize_context(ctx: dict) -> dict:
    return {
        "staff_candidates": len(ctx.get("staff_candidates", [])),
        "resources": len(ctx.get("resources", [])),
        "rides": [{"task_key": r["task_key"], "eligible": len(r["candidates"])} for r in ctx.get("ride_tasks", [])],
    }


__all__ = ["gather_context", "planning_window", "summarize_context", "parse"]
