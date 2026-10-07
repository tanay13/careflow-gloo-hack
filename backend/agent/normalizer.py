"""Request normalization: free text + intake form -> structured operational fields.

`deterministic_extract` is the offline/mock extractor. When a real model is
configured its output is merged through `validate_normalized`, which only
accepts values from a fixed vocabulary (the model cannot add new need types,
campuses, or remove deterministic facts).
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from agent.clock import at_offset, fmt, iso
from agent.policies import P, experience_tags_for

KNOWN_NEEDS = ["pastoral_conversation", "transportation", "recovery_resources", "meals", "mobility_equipment",
               "grief_support", "financial_assistance", "hospital_visit", "family_support", "counseling_advice"]

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a couple of": 2, "a few": 3}

NEED_PATTERNS: dict[str, list[str]] = {
    "pastoral_conversation": [r"\bpastor", r"\bpastoral", r"\btalk (with|to)\b", r"\bspeak (with|to)\b",
                              r"\bconversation\b", r"\bmeet with\b", r"\bcall me\b", r"\bpray with\b"],
    "transportation": [r"\btransportation\b", r"\bride(s)?\b", r"\bcan(no|')?t drive\b", r"\bcannot drive\b",
                       r"\bunable to drive\b", r"\bneed a lift\b"],
    "recovery_resources": [r"\brecovery resources\b", r"\bresources for recovery\b", r"\bpractical resources\b",
                           r"\brecovery\b.*\bresources\b", r"\bresources\b.*\brecovery\b"],
    "meals": [r"\bmeal", r"\bfood\b", r"\bdinners?\b"],
    "mobility_equipment": [r"\bwheelchair\b", r"\bwalker\b", r"\bshower chair\b", r"\bcrutches\b"],
    "grief_support": [r"\bpassed away\b", r"\bdied\b", r"\bgrief\b", r"\bfuneral\b", r"\bloss of\b"],
    "financial_assistance": [r"\brent\b", r"\bbills?\b", r"\bpay (my|for|the)\b", r"\bmoney\b", r"\bfinancial",
                             r"\bafford\b", r"\bmortgage\b"],
    "hospital_visit": [r"\bin the hospital\b", r"\bhospital visit\b", r"\bvisit me\b"],
    "family_support": [r"\bmarriage\b", r"\bmy (husband|wife|spouse)\b", r"\bfamily (conflict|issues)\b"],
    "counseling_advice": [r"\badvice\b", r"\bwhat should i do\b", r"\btell me what to do\b", r"\bshould i leave\b"],
}


def _detect_campus(text: str) -> str | None:
    low = text.lower()
    for campus in P()["campuses"]:
        variants = [campus.lower()] + ([v.strip() for v in campus.lower().split("/")] if "/" in campus else [])
        for v in variants:
            if re.search(r"\b" + re.escape(v) + r"\b", low):
                return campus
    return None


def _trip_count(text: str) -> int | None:
    low = text.lower()
    m = re.search(r"(\d+|one|two|three|four|five|a couple of|a few)\s+(follow[- ]up\s+)?(appointments|rides|trips|visits)", low)
    if m:
        tok = m.group(1)
        return int(tok) if tok.isdigit() else NUMBER_WORDS.get(tok)
    return None


def deterministic_extract(text: str, intake_form: dict | None) -> dict[str, Any]:
    intake_form = intake_form or {}
    low = text.lower().replace("\u2019", "'")
    needs = [n for n, pats in NEED_PATTERNS.items() if any(re.search(p, low) for p in pats)]

    # Surgery/recovery + "resources" phrased loosely still means recovery resources.
    if "recovery_resources" not in needs and re.search(r"\b(surgery|recovering)\b", low) and "resource" in low:
        needs.append("recovery_resources")

    timeframe = "unspecified"
    urgent = False
    if re.search(r"\b(today|as soon as possible|asap|right away|immediately|urgent)\b", low):
        timeframe, urgent = "today", True
    elif "this week" in low:
        timeframe = "this_week"
    elif "next week" in low:
        timeframe = "next_week"

    contact = intake_form.get("preferred_contact")
    if not contact:
        if re.search(r"\b(call|phone)\b", low):
            contact = "phone"
        elif "email" in low:
            contact = "email"

    preferred = None
    m = re.search(r"\b[Pp]astor ([A-Z][a-z]+(?: [A-Z][a-z]+)?)", text)
    if m:
        preferred = m.group(1)

    constraints = []
    m = re.search(r"(can(?:no|')?t drive[^.,;]*)", low)
    if m:
        constraints.append(m.group(1).strip())

    return {
        "campus": _detect_campus(text),
        "needs": needs,
        "timeframe": timeframe,
        "urgent_same_day": urgent,
        "transport_trips": _trip_count(text) if "transportation" in needs else None,
        "contact_method": contact,
        "preferred_staff_name": preferred,
        "household_constraints": constraints,
        "missing_facts": [],
        "escalation_categories": [],
    }


def validate_normalized(raw: dict[str, Any], text: str, intake_form: dict, baseline: dict[str, Any]) -> dict[str, Any]:
    """Merge model output with deterministic baseline using a fixed vocabulary."""
    campus = raw.get("campus") if raw.get("campus") in P()["campuses"] else None
    campus = baseline.get("campus") or campus  # explicit text match wins
    needs = list(baseline.get("needs", []))
    for n in raw.get("needs", []) or []:
        if n in KNOWN_NEEDS and n not in needs:
            needs.append(n)
    tf = raw.get("timeframe") if raw.get("timeframe") in {"today", "this_week", "next_week", "unspecified"} else None
    urgent = bool(baseline.get("urgent_same_day") or raw.get("urgent_same_day"))
    return {
        **baseline,
        "campus": campus,
        "needs": needs,
        "timeframe": baseline["timeframe"] if baseline["timeframe"] != "unspecified" else (tf or "unspecified"),
        "urgent_same_day": urgent,
        "transport_trips": baseline.get("transport_trips") or (raw.get("transport_trips") if isinstance(raw.get("transport_trips"), int) else None),
        "household_constraints": baseline.get("household_constraints") or [str(x)[:120] for x in raw.get("household_constraints", [])[:3]],
        "escalation_categories": [c for c in raw.get("escalation_categories", []) or []
                                  if c in P()["safety_gate"]["escalation_categories"]],
    }


def finalize(norm: dict[str, Any], text: str, intake_form: dict) -> dict[str, Any]:
    """Derive routing fields, appointment windows, known/missing facts (deterministic)."""
    needs = norm["needs"]
    if norm["urgent_same_day"] and "pastoral_conversation" not in needs:
        needs.insert(0, "pastoral_conversation")

    if norm["urgent_same_day"]:
        primary = "urgent_callback"
    elif "pastoral_conversation" in needs or "counseling_advice" in needs or "grief_support" in needs or "hospital_visit" in needs:
        primary = "pastoral_conversation"
    elif "financial_assistance" in needs:
        primary = "financial_referral"
    elif needs:
        primary = "resource_only"
    else:
        primary = None

    appts = []
    for a in intake_form.get("appointments", []) or []:
        start = at_offset(int(a["day_offset"]), a["time"])
        pol = P()["volunteer_policy"]
        appts.append({
            "label": a.get("label", "Appointment"),
            "location": a.get("location", ""),
            "appointment_time": iso(start),
            "ride_start": iso(start - timedelta(minutes=pol["ride_pickup_minutes_before"])),
            "ride_end": iso(start + timedelta(minutes=pol["ride_return_minutes_after"])),
        })

    known, missing = [], list(norm.get("missing_facts", []))
    if norm["campus"]:
        known.append(f"Campus: {norm['campus']} (stated by requester)")
    elif norm["urgent_same_day"]:
        known.append("Campus not stated - not required: the weekly Pastor on Call covers all campuses")
    else:
        missing.append("Campus not stated - locality routing needs it")
    if needs:
        known.append("Needs: " + ", ".join(n.replace("_", " ") for n in needs))
    else:
        missing.append("Specific need is unclear")
    if norm["timeframe"] != "unspecified":
        known.append("Timeframe: " + norm["timeframe"].replace("_", " "))
    if norm.get("contact_method"):
        known.append(f"Preferred contact: {norm['contact_method']}")
    for c in norm.get("household_constraints", []):
        known.append(f"Constraint: {c}")
    trips = norm.get("transport_trips")
    if "transportation" in needs:
        if appts:
            known.append(f"{len(appts)} appointment time(s) supplied via intake form: "
                         + "; ".join(fmt(datetime_from(a['appointment_time'])) for a in appts))
        else:
            missing.append("Appointment dates/times for transportation not provided")
        if trips and appts and trips != len(appts):
            missing.append(f"Request mentions {trips} trips but intake form lists {len(appts)} appointment(s)")

    return {
        **norm,
        "needs": needs,
        "primary_request_type": primary,
        "experience_tags": experience_tags_for(text),
        "appointments": appts,
        "known_facts": known,
        "missing_facts": missing,
        "referrals": intake_form.get("referrals", []),
    }


def datetime_from(s: str):
    from agent.clock import parse

    return parse(s)
