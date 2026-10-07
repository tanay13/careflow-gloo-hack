"""REST API (FastAPI). OpenAPI docs at /docs."""
from __future__ import annotations

import json
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agent import orchestrator as orch
from agent.clock import demo_now, iso
from agent.events import EventError, inject_event
from agent.policies import P, poc_ids
from api.serializers import audit_row, case_detail, case_summary
from config import REPO_ROOT, settings
from db.database import get_session
from llm.provider import provider_info
from models.entities import AuditEvent, CareCase, StaffMember
from schemas.api import CaseCreate, EventIn, ReviewIn
from tools import ToolContext, ToolPermissionError, call_tool
from tools.base import describe_tools

router = APIRouter()


def _case_or_404(s: Session, case_id: str) -> CareCase:
    c = s.get(CareCase, case_id)
    if c is None:
        raise HTTPException(404, f"Case {case_id} not found")
    return c


# ----------------------------------------------------------------- cases

@router.post("/cases", tags=["cases"], summary="Create a case from an intake request")
def create_case(body: CaseCreate, s: Session = Depends(get_session)):
    c = orch.create_case(s, request_text=body.request_text, source=body.source, requester_ref=body.requester_ref,
                         intake_form=body.intake_form.model_dump(), consent_flags=body.consent_flags)
    if body.auto_run:
        orch.run_case(c.case_id)
    return case_summary(c, s)


@router.get("/cases", tags=["cases"])
def list_cases(status: Optional[str] = None, s: Session = Depends(get_session)):
    q = s.query(CareCase)
    if status:
        q = q.filter(CareCase.status == status)
    return [case_summary(c, s) for c in q.order_by(CareCase.created_at.desc(), CareCase.case_id.desc()).all()]


@router.post("/cases/{case_id}/run", tags=["cases"], summary="Start/continue orchestration (Run CareFlow)")
def run_case(case_id: str, s: Session = Depends(get_session)):
    _case_or_404(s, case_id)
    try:
        orch.run_case(case_id)
    except orch.CaseBusy as e:
        raise HTTPException(409, str(e))
    except orch.ReviewError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "case_id": case_id}


@router.get("/cases/{case_id}", tags=["cases"])
def get_case(case_id: str, s: Session = Depends(get_session)):
    return case_detail(s, _case_or_404(s, case_id))


@router.post("/cases/{case_id}/approve", tags=["cases"], summary="Approve / reject / reassign proposed actions")
def approve(case_id: str, body: ReviewIn, s: Session = Depends(get_session)):
    _case_or_404(s, case_id)
    try:
        return orch.submit_review(s, case_id, body.reviewer, [d.model_dump() for d in body.decisions], body.feedback,
                                  body.request_replan)
    except orch.CaseBusy as e:
        raise HTTPException(409, str(e))
    except orch.ReviewError as e:
        raise HTTPException(400, str(e))


@router.post("/cases/{case_id}/events", tags=["cases"], summary="Inject a demo event (mutates real state)")
def events(case_id: str, body: EventIn, s: Session = Depends(get_session)):
    _case_or_404(s, case_id)
    try:
        return inject_event(s, case_id, body.type, target=body.target, mode=body.mode, tool=body.tool)
    except orch.CaseBusy as e:
        raise HTTPException(409, str(e))
    except EventError as e:
        raise HTTPException(400, str(e))


@router.get("/cases/{case_id}/audit", tags=["audit"])
def case_audit(case_id: str, s: Session = Depends(get_session)):
    _case_or_404(s, case_id)
    return [audit_row(e) for e in s.query(AuditEvent).filter(AuditEvent.case_id == case_id).order_by(AuditEvent.event_id).all()]


@router.get("/audit", tags=["audit"])
def all_audit(limit: int = 500, case_id: Optional[str] = None, actor: Optional[str] = None, s: Session = Depends(get_session)):
    q = s.query(AuditEvent)
    if case_id:
        q = q.filter(AuditEvent.case_id == case_id)
    if actor:
        q = q.filter(AuditEvent.actor == actor)
    return [audit_row(e) for e in q.order_by(AuditEvent.event_id.desc()).limit(limit).all()]


@router.post("/actions/{action_id}/execute", tags=["actions"],
             summary="Execute one action after server-side permission check")
def execute_action(action_id: str, s: Session = Depends(get_session)):
    try:
        res = orch.execute_single(s, action_id)
    except KeyError:
        raise HTTPException(404, "Unknown action")
    except orch.ReviewError as e:
        raise HTTPException(400, str(e))
    if res["status"] == "blocked":
        raise HTTPException(403, res["result"].get("error", "Blocked by policy"))
    return res


# ------------------------------------------------------------- tool endpoints

def _read_tool(s: Session, name: str, payload: dict):
    try:
        return call_tool(name, ToolContext(s, None, actor="HUMAN:api"), payload)
    except ToolPermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        s.commit()


@router.get("/staff/search", tags=["tools"])
def staff_search(request_type: str = "pastoral_conversation", campus: Optional[str] = None,
                 experience_tags: list[str] = Query(default=[]), urgent: bool = False, s: Session = Depends(get_session)):
    return _read_tool(s, "staff.search", {"campus": campus, "request_type": request_type,
                                          "experience_tags": experience_tags, "urgent": urgent}).model_dump()


@router.get("/resources/search", tags=["tools"])
def resource_search(categories: list[str] = Query(default=["recovery_resources"]), campus: Optional[str] = None,
                    s: Session = Depends(get_session)):
    return _read_tool(s, "resource.search", {"campus": campus, "categories": categories}).model_dump()


@router.get("/availability", tags=["tools"])
def availability(staff_ids: list[str] = Query(...), start: Optional[str] = None, end: Optional[str] = None,
                 slot_minutes: int = 60, s: Session = Depends(get_session)):
    from agent.clock import end_of_week

    return _read_tool(s, "calendar.read", {"staff_ids": staff_ids, "window_start": start or iso(demo_now()),
                                           "window_end": end or iso(end_of_week()), "slot_minutes": slot_minutes}).model_dump()


@router.get("/volunteers/search", tags=["tools"])
def volunteer_search(role: str, start: str, end: str, campus: Optional[str] = None, s: Session = Depends(get_session)):
    return _read_tool(s, "volunteer.search", {"role": role, "campus": campus, "start": start, "end": end}).model_dump()


# ------------------------------------------------------------- meta / demo

@router.get("/dashboard", tags=["meta"])
def dashboard(s: Session = Depends(get_session)):
    cases = s.query(CareCase).all()
    counts = Counter(c.status for c in cases)
    poc = s.get(StaffMember, poc_ids()["current"])
    backup = s.get(StaffMember, poc_ids()["backup"])
    urgent_open = sum(1 for c in cases if (c.structured_needs or {}).get("urgent_same_day") and c.status not in ("RESOLVED", "CANCELLED"))
    recent = s.query(AuditEvent).order_by(AuditEvent.event_id.desc()).limit(12).all()
    agent_ms = [r["agent_ms"] for c in cases for r in (c.metrics or {}).get("runs", []) if r["kind"] == "initial_plan"]
    return {
        "counts": dict(counts), "total": len(cases),
        "poc": {"staff_id": poc.staff_id, "name": poc.name, "role": poc.role, "campuses": poc.campuses,
                "weekly_capacity": P()["routing"]["poc_weekly_capacity"], "urgent_open": urgent_open},
        "backup_poc": {"staff_id": backup.staff_id, "name": backup.name},
        "recent": [audit_row(e) for e in recent],
        "median_plan_ms": sorted(agent_ms)[len(agent_ms) // 2] if agent_ms else None,
        "demo_now": iso(demo_now()),
    }


@router.get("/policies", tags=["meta"])
def policies():
    return P()


@router.get("/tools", tags=["meta"])
def tools():
    return describe_tools()


@router.get("/config", tags=["meta"])
def config():
    return {**provider_info(), "demo_now": settings.demo_now, "step_delay_ms": settings.demo_step_delay_ms,
            "synthetic_data": True}


@router.get("/demo/scenarios", tags=["demo"])
def scenarios():
    from db.seed import demo_cases

    return demo_cases()["demo_cases"]


@router.post("/demo/reset", tags=["demo"], summary="Rebuild the database with deterministic synthetic demo data")
def reset():
    from db.seed import reset_and_seed

    reset_and_seed()
    return {"ok": True}


@router.get("/evals/results", tags=["evals"])
def eval_results():
    path = REPO_ROOT / "evals" / "results.json"
    if not path.exists():
        return {"available": False}
    with open(path) as f:
        return {"available": True, **json.load(f)}


@router.post("/evals/run", tags=["evals"], summary="Run the evaluation suite in an isolated temporary database")
def eval_run():
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, str(REPO_ROOT / "evals" / "run_evals.py"), "--quiet"],
                          capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT))
    if proc.returncode not in (0, 1):
        raise HTTPException(500, proc.stderr[-2000:])
    return eval_results()
