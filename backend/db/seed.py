"""Load synthetic data and prepare deterministic demo state.

`reset_and_seed()` rebuilds the database from data/*.json and drives a few
background cases through the *real* workflow (so the dashboard shows genuine
states), then leaves the urgent-POC and crisis demo cases as NEW for live runs.
The primary surgery-recovery case is intentionally NOT pre-created: the
presenter submits it live (it becomes CF-1042).
"""
from __future__ import annotations

import json
import logging

from agent.clock import at_offset
from config import DATA_DIR, RUNTIME
from db.database import SessionLocal, drop_all, engine, init_db
from models.entities import CalendarBlock, ResourceItem, StaffMember, Volunteer

log = logging.getLogger("careflow.seed")


def _load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def seed_reference_data(session) -> None:
    for s in _load("synthetic_staff.json")["staff"]:
        session.add(StaffMember(**{k: v for k, v in s.items() if not k.startswith("_")}))
    for v in _load("synthetic_volunteers.json")["volunteers"]:
        session.add(Volunteer(**{k: v2 for k, v2 in v.items() if not k.startswith("_")}, blackout=[]))
    for r in _load("synthetic_resources.json")["resources"]:
        d = {k: v for k, v in r.items() if not k.startswith("_")}
        d.setdefault("substitute_for", [])
        session.add(ResourceItem(**d))
    session.flush()
    for b in _load("synthetic_calendar.json")["busy"]:
        session.add(CalendarBlock(staff_id=b["staff_id"], start=at_offset(b["day_offset"], b["start"]),
                                  end=at_offset(b["day_offset"], b["end"]), kind="busy", source="seed"))
    session.commit()


def demo_cases() -> dict:
    return _load("synthetic_cases.json")


def reset_and_seed(with_background: bool = True, eng=None) -> None:
    from llm.provider import force_mock

    eng = eng or engine
    drop_all(eng)
    init_db(eng)
    s = SessionLocal()
    try:
        seed_reference_data(s)
    finally:
        s.close()
    if not with_background:
        return

    # Drive background cases through the real orchestrator, synchronously.
    from agent import orchestrator as orch
    from agent.events import inject_event
    from models.entities import Action, CareCase

    prev_sync, prev_delay = RUNTIME.get("sync"), RUNTIME.get("step_delay_ms")
    RUNTIME["sync"], RUNTIME["step_delay_ms"] = True, 0
    force_mock(True)
    try:
        data = demo_cases()
        for bg in data["background_cases"]:
            s = SessionLocal()
            try:
                c = orch.create_case(s, request_text=bg["request_text"], source=bg["source"],
                                     requester_ref=bg["requester_ref"], intake_form=bg.get("intake_form"),
                                     consent_flags=bg.get("consent_flags"))
                cid = c.case_id
            finally:
                s.close()
            orch.run_case(cid)
            if bg["seed_flow"] in ("resolve", "monitor"):
                s = SessionLocal()
                try:
                    case = s.get(CareCase, cid)
                    acts = s.query(Action).filter(Action.plan_id == case.current_plan_id, Action.approval_status == "pending",
                                                  Action.risk_level != "forbidden").all()
                    orch.submit_review(s, cid, "Dana Ellison (seed)", [{"action_id": a.action_id, "decision": "approve"} for a in acts],
                                       None, False)
                finally:
                    s.close()
            if bg["seed_flow"] == "resolve":
                s = SessionLocal()
                try:
                    inject_event(s, cid, "tasks_completed")
                finally:
                    s.close()
        for key in ("urgent_poc", "crisis_escalation"):
            d = next(x for x in data["demo_cases"] if x["key"] == key)
            s = SessionLocal()
            try:
                orch.create_case(s, request_text=d["request_text"], source=d["source"], requester_ref=d["requester_ref"],
                                 intake_form=d.get("intake_form"), consent_flags=d.get("consent_flags"))
            finally:
                s.close()
    finally:
        RUNTIME["sync"], RUNTIME["step_delay_ms"] = prev_sync, prev_delay
        force_mock(False)


def ensure_seeded() -> None:
    init_db()
    s = SessionLocal()
    try:
        empty = s.query(StaffMember).count() == 0
    finally:
        s.close()
    if empty:
        log.info("Empty database - seeding synthetic demo data")
        reset_and_seed()
