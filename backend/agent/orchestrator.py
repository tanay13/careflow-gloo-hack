"""CareFlow orchestrator - single agent loop + separate verifier.

Owns the case objective and drives it through the explicit state machine:

  NEW -> NORMALIZED -> SAFETY_CHECKED -> CONTEXT_GATHERED -> PLAN_PROPOSED
      -> VERIFIED -> AWAITING_APPROVAL -> APPROVED -> EXECUTING -> MONITORING
      -> RESOLVED | ESCALATED (| ERROR, recoverable)

Responsibilities split:
  * deterministic code: state transitions, safety gate, eligibility, risk
    classification, permissions, verification, retries;
  * planner (LLM or deterministic reasoner): rank already-eligible options,
    assemble the plan JSON, explain rationale, re-plan after failures.

Long-running flows run in a background thread with a small visible pause
between steps (DEMO_STEP_DELAY_MS) so a live audience can watch real state
changes via polling. Evals run synchronously with zero delay.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from agent.actions import persist_actions, plan_action_specs
from agent.clock import fmt, parse
from agent.context import gather_context, summarize_context
from agent.normalizer import deterministic_extract, finalize, validate_normalized
from agent.planner import generate_plan
from agent.policies import P, poc_ids, safety_gate
from agent.state_machine import CaseState as S
from agent.state_machine import transition
from agent.verifier import verify_plan
from audit.log import append_event
from config import RUNTIME, settings
from db.database import SessionLocal
from db.ids import next_id
from llm.provider import MockLLMProvider, get_provider
from models.entities import Action, Approval, CarePlan, CareCase, StaffMember
from tools import ToolConflict, ToolContext, ToolFailure, ToolPermissionError, call_tool
from tools.base import mint_token, token_hash

log = logging.getLogger("careflow.orchestrator")


class CaseBusy(Exception):
    pass


class ReviewError(Exception):
    pass


# ---------------------------------------------------------------------------
# Run bookkeeping (latency / tool calls / tokens / cost)
# ---------------------------------------------------------------------------

class RunStats:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.t0 = time.perf_counter()
        self.started = datetime.now().isoformat(timespec="seconds")
        self.paused_ms = 0.0
        self.tool_calls = 0
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.estimated = True
        self.provider = None
        self.fallbacks: list[str] = []

    def add_llm(self, usage: dict | None) -> None:
        if not usage:
            return
        self.llm_calls += 1
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))
        self.estimated = self.estimated and bool(usage.get("estimated", True))
        self.provider = usage.get("provider")
        if usage.get("fallback_reason"):
            self.fallbacks.append(usage["fallback_reason"])

    def finish(self) -> dict[str, Any]:
        wall = (time.perf_counter() - self.t0) * 1000
        cost = (self.input_tokens / 1000) * settings.llm_cost_input_per_1k + \
               (self.output_tokens / 1000) * settings.llm_cost_output_per_1k
        return {
            "kind": self.kind, "started": self.started, "wall_ms": round(wall, 1),
            "agent_ms": round(max(0.0, wall - self.paused_ms), 1), "demo_pause_ms": round(self.paused_ms, 1),
            "tool_calls": self.tool_calls, "llm_calls": self.llm_calls, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "est_cost_usd": round(cost, 6), "tokens_estimated": self.estimated,
            "provider": self.provider, "fallbacks": self.fallbacks,
        }


class Runner:
    """Per-flow context: session, case, stats and helpers."""

    def __init__(self, session: Session, case_id: str, kind: str) -> None:
        self.s = session
        self.case: CareCase = session.get(CareCase, case_id)
        if self.case is None:
            raise KeyError(case_id)
        self.stats = RunStats(kind)
        self.plan_version: Optional[int] = None

    # -- helpers --------------------------------------------------------
    def commit(self) -> None:
        self.s.commit()

    def pause(self) -> None:
        delay = RUNTIME.get("step_delay_ms", 0)
        self.commit()
        if delay:
            time.sleep(delay / 1000)
            self.stats.paused_ms += delay

    def step(self, label: str) -> None:
        self.case.current_step = label
        self.commit()

    def to(self, state: S, reason: str, actor: str = "AGENT") -> None:
        transition(self.s, self.case, state, reason, actor, plan_version=self.plan_version)
        self.commit()

    def audit(self, actor: str, event_type: str, summary: str = "", status: str = "ok", **kw) -> None:
        append_event(self.s, self.case.case_id, actor=actor, event_type=event_type, status=status,
                     output_summary=summary, plan_version=kw.pop("plan_version", self.plan_version), **kw)

    def tool(self, name: str, payload: dict, actor: str = "AGENT", action_id: str | None = None,
             token: str | None = None):
        self.stats.tool_calls += 1
        self.case.current_step = f"Calling {name}"
        self.commit()
        ctx = ToolContext(self.s, self.case.case_id, actor=actor, plan_version=self.plan_version,
                          action_id=action_id, approval_token=token)
        return call_tool(name, ctx, payload)

    def record_metrics(self) -> None:
        m = dict(self.case.metrics or {})
        runs = list(m.get("runs", []))
        runs.append(self.stats.finish())
        totals = {
            "runs": len(runs),
            "agent_ms": round(sum(r["agent_ms"] for r in runs), 1),
            "tool_calls": sum(r["tool_calls"] for r in runs),
            "llm_calls": sum(r["llm_calls"] for r in runs),
            "input_tokens": sum(r["input_tokens"] for r in runs),
            "output_tokens": sum(r["output_tokens"] for r in runs),
            "est_cost_usd": round(sum(r["est_cost_usd"] for r in runs), 6),
            "tokens_estimated": all(r["tokens_estimated"] for r in runs),
        }
        self.case.metrics = {"runs": runs, "totals": totals}


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(case_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(case_id, threading.Lock())


def launch(flow: Callable[..., None], case_id: str, kind: str, *args) -> None:
    """Run `flow(runner, *args)` in the background (or inline when RUNTIME['sync'])."""
    lock = _lock_for(case_id)
    if not lock.acquire(blocking=False):
        raise CaseBusy(f"{case_id} is already running")
    s = SessionLocal()
    try:
        c = s.get(CareCase, case_id)
        c.is_running = True
        s.commit()
    finally:
        s.close()

    def _target():
        session = SessionLocal()
        try:
            r = Runner(session, case_id, kind)
            try:
                flow(r, *args)
            except Exception as e:  # noqa: BLE001 - never fail silently
                log.error("flow %s failed: %s", kind, traceback.format_exc())
                session.rollback()
                r = Runner(session, case_id, kind)
                _enter_error(r, f"Unexpected error: {type(e).__name__}: {e}", resume="SAFETY_CHECKED"
                             if r.case.status in ("NEW", "NORMALIZED", "SAFETY_CHECKED", "CONTEXT_GATHERED") else "MONITORING")
            r.record_metrics()
            r.case.is_running = False
            r.case.current_step = None
            session.commit()
        finally:
            session.close()
            lock.release()

    if RUNTIME.get("sync"):
        _target()
    else:
        threading.Thread(target=_target, daemon=True, name=f"careflow-{case_id}").start()


def _enter_error(r: Runner, message: str, resume: str, tool: str | None = None) -> None:
    r.case.error = {"message": message, "tool": tool, "resume_state": resume, "at": datetime.now().isoformat(timespec="seconds")}
    r.case.resume_state = resume
    r.audit("SYSTEM", "case.error", message, status="error", tool_name=tool)
    try:
        r.to(S.ERROR, f"Recoverable error - {message}", actor="SYSTEM")
    except Exception:  # noqa: BLE001
        r.commit()


def _escalate(r: Runner, reason: str, category: str, unresolved: str | None = None, protocol: str | None = None) -> None:
    coord = r.s.get(StaffMember, poc_ids()["coordinator"])
    r.case.escalation = {
        "reason": reason, "category": category, "unresolved_need": unresolved,
        "handler": {"staff_id": coord.staff_id, "name": coord.name, "role": coord.role} if coord else None,
        "protocol": protocol or "Synthetic demo policy: a designated human reviews and decides next steps.",
        "automation_stopped": True, "at": datetime.now().isoformat(timespec="seconds"),
    }
    r.audit("POLICY" if category.startswith("safety") or category == "duplicate" else "AGENT",
            "escalation.created", reason, status="warn", metadata={"category": category})
    r.to(S.ESCALATED, reason)


# ---------------------------------------------------------------------------
# Case creation (synchronous)
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z']+", text.lower()))


def create_case(session: Session, *, request_text: str, source: str = "web_form", requester_ref: str | None = None,
                intake_form: dict | None = None, consent_flags: dict | None = None) -> CareCase:
    case = CareCase(case_id=next_id(session, "CF"), source=source, request_text=request_text.strip(),
                    requester_ref=requester_ref or "anonymous (synthetic)", intake_form=intake_form or {},
                    consent_flags=consent_flags if consent_flags is not None else {"contact_ok": True},
                    status=S.NEW.value, metrics={})
    session.add(case)
    session.flush()
    append_event(session, case.case_id, actor="SYSTEM", event_type="case.created",
                 input_summary=f"source={source}", output_summary=f"Intake received ({len(request_text)} chars); original text preserved")
    # Duplicate detection (deterministic token similarity over recent cases)
    thr = P()["duplicate_detection"]["similarity_threshold"]
    mine = _tokens(request_text)
    for other in session.query(CareCase).filter(CareCase.case_id != case.case_id).all():
        theirs = _tokens(other.request_text)
        if not mine or not theirs:
            continue
        sim = len(mine & theirs) / len(mine | theirs)
        if sim >= thr:
            case.duplicate_of = other.case_id
            append_event(session, case.case_id, actor="POLICY", event_type="duplicate.suspected", status="warn",
                         output_summary=f"Probable duplicate of {other.case_id} (similarity {sim:.2f})")
            break
    session.commit()
    return case


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_case(case_id: str) -> None:
    s = SessionLocal()
    try:
        case = s.get(CareCase, case_id)
        if case is None:
            raise KeyError(case_id)
        status = case.status
    finally:
        s.close()
    if status == S.NEW.value:
        launch(_flow_initial, case_id, "initial_plan")
    elif status == S.ERROR.value:
        launch(_flow_resume, case_id, "resume_after_error")
    elif status == S.MONITORING.value:
        launch(_flow_monitor, case_id, "monitoring_check")
    else:
        raise ReviewError(f"Case is {status}; nothing to run.")


def _flow_initial(r: Runner) -> None:
    case = r.case
    r.audit("AGENT", "run.started", "CareFlow run started (objective: coordinate care logistics)")
    r.pause()

    # 1. Normalize
    r.step("Normalizing request")
    provider = get_provider()
    res = provider.normalize(case.request_text, case.intake_form or {})
    r.stats.add_llm(res.usage)
    baseline = deterministic_extract(case.request_text, case.intake_form or {})
    norm = baseline if isinstance(provider, MockLLMProvider) or res.usage.get("fallback_reason") else \
        validate_normalized(dict(res), case.request_text, case.intake_form or {}, baseline)
    norm = finalize(norm, case.request_text, case.intake_form or {})
    case.structured_needs = norm
    case.campus = norm["campus"]
    r.audit("AGENT", "request.normalized",
            f"campus={norm['campus'] or 'unknown'}; needs={', '.join(norm['needs']) or 'unclear'}; "
            f"timeframe={norm['timeframe']}; urgent={norm['urgent_same_day']}",
            metadata={"missing_facts": norm["missing_facts"], "provider": res.usage.get("provider")})
    r.to(S.NORMALIZED, "Structured operational fields extracted")
    r.pause()

    # 2. Deterministic safety / sensitivity gate
    r.step("Safety & sensitivity gate")
    gate = safety_gate(case.request_text, norm.get("escalation_categories"))
    case.safety_result = gate
    case.sensitivity_flags = gate["categories"] + gate["routing_flags"]
    if gate["decision"] == "ESCALATE":
        r.audit("POLICY", "safety_check", f"ESCALATE - categories: {', '.join(gate['categories'])}", status="warn",
                metadata=gate)
    else:
        extra = f"; routing flags: {', '.join(gate['routing_flags'])}" if gate["routing_flags"] else ""
        r.audit("POLICY", "safety_check", f"PASS - no escalation category matched{extra}", metadata=gate)
    if "prompt_injection" in gate["routing_flags"]:
        r.audit("POLICY", "prompt_injection.neutralized",
                "Instruction-like text found in request; treated as untrusted data. Permissions unchanged.", status="warn")
    r.to(S.SAFETY_CHECKED, f"Safety gate: {gate['decision']}", actor="POLICY")
    r.pause()

    if gate["decision"] == "ESCALATE":
        cats = gate["categories"]
        label = "minor-related request" if cats == ["minor_involved"] else "safety indicator"
        _escalate(r, f"Deterministic safety gate matched {label} ({', '.join(cats)}). Normal automation stopped; "
                     "no scheduling, resources or automated contact.", category="safety:" + ",".join(cats),
                  protocol=gate["protocol_label"])
        return
    if case.duplicate_of:
        _escalate(r, f"Probable duplicate of {case.duplicate_of}. No external actions created; a human should merge or confirm.",
                  category="duplicate")
        return

    _gather_and_plan(r, trigger="initial")


def _gather_and_plan(r: Runner, trigger: str) -> None:
    case = r.case
    fb = dict((case.context or {}).get("feedback", {}))
    r.step("Gathering context")
    try:
        ctx = gather_context(case, lambda n, p: r.tool(n, p), fb, r.pause)
    except ToolFailure as e:
        _enter_error(r, str(e), resume="SAFETY_CHECKED", tool=str(e).split(" ")[0])
        return
    ctx["feedback"] = fb
    case.context = ctx
    r.audit("AGENT", "context.gathered", "Context: " + str(summarize_context(ctx)))
    r.to(S.CONTEXT_GATHERED, "Staff, calendar, resource and volunteer context gathered")
    _plan_cycle(r, trigger=trigger, feedback=fb, prior=None)


def _case_view(case: CareCase) -> dict:
    n = case.structured_needs or {}
    return {**n, "case_id": case.case_id, "campus": case.campus,
            "routing_flags": (case.safety_result or {}).get("routing_flags", []),
            "sensitivity_flags": case.sensitivity_flags or [], "consent_flags": case.consent_flags or {}}


def _merge_fb(a: dict, b: dict) -> dict:
    out = {k: list(v) if isinstance(v, list) else v for k, v in (a or {}).items()}
    for k, v in (b or {}).items():
        if isinstance(v, list):
            cur = out.setdefault(k, [])
            for x in v:
                if x not in cur:
                    cur.append(x)
        else:
            out[k] = v
    return out


def _plan_cycle(r: Runner, trigger: str, feedback: dict, prior: dict | None) -> None:
    """Plan -> verify loop with bounded re-planning."""
    case = r.case
    max_replans = P()["verifier"]["max_replans"]
    fb = dict(feedback or {})
    prior_plan = r.s.get(CarePlan, case.current_plan_id) if case.current_plan_id else None
    prior_actions = r.s.query(Action).filter(Action.plan_id == prior_plan.plan_id).all() if prior_plan else []

    for attempt in range(max_replans + 1):
        if case.status != S.PLAN_PROPOSED.value:
            r.to(S.PLAN_PROPOSED, "Planning" if attempt == 0 else "Verifier requested re-plan")
        version = (r.s.query(CarePlan).filter(CarePlan.case_id == case.case_id).count()) + 1
        r.plan_version = version
        r.step(f"Generating plan v{version}")
        contract, usage, source = generate_plan(_case_view(case), case.context or {}, fb, prior)
        r.stats.add_llm(usage)
        contract["_prior"] = prior
        contract["_locked"] = (prior or {}).get("locked")
        # Provenance snapshot: IDs the tools actually returned when this plan was made.
        ctx_now = case.context or {}
        contract["_evidence_ids"] = {
            "staff": [x["staff_id"] for x in ctx_now.get("staff_candidates", [])],
            "resources": [x["resource_id"] for x in ctx_now.get("resources", [])],
            "volunteers": sorted({v["volunteer_id"] for rt in ctx_now.get("ride_tasks", []) for v in rt["candidates"]}),
        }

        plan = CarePlan(plan_id=next_id(r.s, "PLN"), case_id=case.case_id, version=version, status="draft",
                        trigger=trigger, owner=contract.get("proposed_owner"), backup_owner=contract.get("backup_owner"),
                        appointment_options=contract.get("appointment_options", []),
                        resource_actions=contract.get("resource_actions", []),
                        volunteer_tasks=contract.get("volunteer_tasks", []),
                        unresolved_items=contract.get("unresolved_items", []),
                        forbidden_items=contract.get("forbidden_items", []), rationale=contract.get("rationale", ""),
                        contract=contract, planner_source=source)
        r.s.add(plan)
        r.s.flush()

        specs = plan_action_specs(contract, case, message_id=None)
        prior_by_key = {a.parameters.get("_key"): a for a in prior_actions}
        for sp in specs:
            if sp["type"] != "message.send":
                continue
            prev = prior_by_key.get(sp["key"])
            if prev is not None and prev.parameters.get("message_id"):
                sp["parameters"]["message_id"] = prev.parameters["message_id"]
            else:
                try:
                    d = r.tool("message.draft", {"case_id": case.case_id, "recipient_ref": case.requester_ref,
                                                 "channel": (case.structured_needs or {}).get("contact_method") or "phone_script",
                                                 "subject": f"Care request {case.case_id}", "body": sp["description"]})
                    sp["parameters"]["message_id"] = d.message_id
                except ToolPermissionError:
                    specs.remove(sp)
        actions = persist_actions(r.s, case, plan, specs, prior_actions, next_id)
        plan.required_approvals = [a.title for a in actions if a.risk_level == "approval_required" and a.approval_status == "pending"]
        owner = contract.get("proposed_owner")
        r.audit("AGENT", "plan.generated",
                f"Plan v{version} ({source}): owner={owner['name'] if owner else 'none'}; "
                f"{len(plan.appointment_options)} appointment option(s); "
                f"{sum(1 for t in plan.volunteer_tasks if t.get('volunteer_id'))} volunteer task(s); "
                f"{len(plan.resource_actions)} resource(s); {len(plan.unresolved_items)} unresolved",
                metadata={"trigger": trigger, "planner": source, "fallback": usage.get("fallback_reason")})
        r.pause()

        r.step(f"Verifying plan v{version}")
        result, vusage = verify_plan(r.s, case, contract, case.context or {}, locked=(prior or {}).get("locked"))
        r.stats.add_llm(vusage)
        plan.verifier_status = result.status
        plan.verifier_result = result.model_dump()
        r.to(S.VERIFIED, f"Verifier: {result.status}", actor="VERIFIER")
        n_pass = sum(1 for c in result.checks if c["status"] == "pass")
        r.audit("VERIFIER", "verifier.result",
                f"{result.status}" + (f" - {'; '.join(result.reasons[:3])}" if result.reasons else f" - {n_pass} checks passed"),
                status={"PASS": "ok", "REPLAN": "warn", "ESCALATE": "warn"}[result.status],
                metadata={"invalid_fields": result.invalid_fields})
        r.pause()

        if result.status == "PASS":
            _supersede_others(r, plan)
            plan.status = "proposed"
            case.current_plan_id = plan.plan_id
            n_appr = sum(1 for a in actions if a.approval_status == "pending" and a.risk_level == "approval_required")
            n_safe = sum(1 for a in actions if a.approval_status == "pending" and a.risk_level == "safe")
            r.to(S.AWAITING_APPROVAL, f"Plan v{version} verified; {n_appr} action(s) need approval")
            r.audit("AGENT", "approval.requested",
                    f"{'New approval' if version > 1 else 'Approval'} required: {n_appr} consequential action(s), "
                    f"{n_safe} policy-permitted reversible action(s)", status="info")
            return
        if result.status == "ESCALATE":
            _supersede_others(r, plan)
            plan.status = "escalated"
            case.current_plan_id = plan.plan_id
            unresolved = [u["detail"] for u in contract.get("unresolved_items", []) if u.get("escalate")]
            reason = unresolved[0] if unresolved else "; ".join(result.reasons[:2])
            _escalate(r, f"Cannot safely complete automatically: {reason}", category="unresolved_need",
                      unresolved="; ".join(unresolved) or None)
            return

        # REPLAN: feed machine-readable feedback to the planner.
        plan.status = "rejected_by_verifier"
        fb = _merge_fb(fb, result.feedback)
        r.audit("AGENT", "replan.started", f"Re-planning with verifier feedback: {result.feedback}", status="warn")
        refresh = set()
        if any(f.startswith("appointment") for f in result.invalid_fields):
            refresh.add("calendar")
        if any(f.startswith("volunteer") for f in result.invalid_fields):
            refresh.add("volunteers")
        if any(f.startswith("resource") for f in result.invalid_fields):
            refresh.add("resources")
        if any(f.endswith("owner.staff_id") for f in result.invalid_fields):
            refresh |= {"staff", "calendar"}
        if refresh:
            try:
                case.context = {**gather_context(case, lambda n, p: r.tool(n, p), fb, r.pause, only=refresh,
                                                 prior_context=case.context), "feedback": fb}
            except ToolFailure as e:
                _enter_error(r, str(e), resume="SAFETY_CHECKED")
                return
        case.context = {**(case.context or {}), "feedback": fb}

    _escalate(r, f"Verifier could not approve a plan after {max_replans + 1} attempts.", category="verifier_exhausted")


def _supersede_others(r: Runner, keep: CarePlan) -> None:
    for p in r.s.query(CarePlan).filter(CarePlan.case_id == r.case.case_id, CarePlan.plan_id != keep.plan_id,
                                        CarePlan.status.in_(["proposed", "active"])).all():
        p.status = "superseded"


# ---------------------------------------------------------------------------
# Human review
# ---------------------------------------------------------------------------

def submit_review(session: Session, case_id: str, reviewer: str, decisions: list[dict], feedback: str | None,
                  request_replan: bool) -> dict:
    case = session.get(CareCase, case_id)
    if case is None:
        raise KeyError(case_id)
    if case.is_running:
        raise CaseBusy("Agent is still running")
    if case.status != S.AWAITING_APPROVAL.value:
        raise ReviewError(f"Case is {case.status}, not AWAITING_APPROVAL")
    plan = session.get(CarePlan, case.current_plan_id)
    pending = {a.action_id: a for a in session.query(Action).filter(Action.plan_id == plan.plan_id).all()
               if a.approval_status == "pending" and a.risk_level != "forbidden"}
    dmap = {d["action_id"]: d for d in decisions}
    unknown = [aid for aid in dmap if aid not in pending]
    if unknown:
        raise ReviewError(f"Actions not reviewable in current plan: {unknown}")

    reviewer_ref = f"HUMAN:{reviewer or 'reviewer'}"
    fb_add: dict[str, Any] = {}
    counts = {"approved": 0, "rejected": 0, "not_selected": 0, "reassigned": 0}
    owner_changed = False
    eligible = {c["staff_id"] for c in (case.context or {}).get("staff_candidates", [])}
    for aid, a in pending.items():
        d = dmap.get(aid)
        decision = "not_selected" if d is None else d["decision"]
        comments = (d or {}).get("comments")
        if decision == "reassign":
            if a.subtype != "assign_owner":
                raise ReviewError("Only owner assignments can be reassigned")
            sid = (d or {}).get("staff_id")
            if sid not in eligible:
                raise ReviewError(f"{sid} is not in the policy-eligible pool; reassignment refused")
            fb_add["preferred_owner"] = sid
            fb_add.setdefault("exclude_staff", []).append(a.parameters["value"])
            owner_changed = True
            counts["reassigned"] += 1
            decision_store = "rejected"
            comments = f"Reassign to {sid}. {comments or ''}".strip()
        elif decision == "reject":
            counts["rejected"] += 1
            decision_store = "rejected"
            if a.subtype == "assign_owner":
                fb_add.setdefault("exclude_staff", []).append(a.parameters["value"])
                owner_changed = True
            elif a.type == "calendar.hold":
                fb_add.setdefault("exclude_slots", []).append({"staff_id": a.parameters["staff_id"], "start": a.parameters["start"]})
            elif a.subtype == "volunteer_assignment":
                fb_add.setdefault("exclude_volunteers", []).append(a.parameters["assignee_id"])
            elif a.type == "resource.reserve":
                fb_add.setdefault("exclude_resources", []).append(a.parameters["resource_id"])
        elif decision == "approve":
            counts["approved"] += 1
            decision_store = "approved"
        else:
            counts["not_selected"] += 1
            decision_store = "not_selected"
        appr = Approval(approval_id=next_id(session, "APR"), plan_id=plan.plan_id, action_id=aid, case_id=case_id,
                        reviewer=reviewer_ref, decision=decision_store, comments=comments)
        if decision_store == "approved":
            appr.token_hash = token_hash(mint_token(appr.approval_id, aid, plan.plan_id))
        session.add(appr)
        a.approval_status = decision_store

    append_event(session, case_id, actor="HUMAN", event_type="plan.reviewed", plan_version=plan.version,
                 output_summary=f"{reviewer}: approved {counts['approved']}, rejected {counts['rejected']}, "
                                f"reassigned {counts['reassigned']}, not selected {counts['not_selected']}",
                 metadata=counts)
    if feedback:
        append_event(session, case_id, actor="HUMAN", event_type="reviewer.feedback", output_summary=feedback[:300],
                     plan_version=plan.version)

    if request_replan or owner_changed:
        fb = _merge_fb((case.context or {}).get("feedback", {}), fb_add)
        if feedback:
            fb.setdefault("notes", []).append(feedback[:300])
        case.context = {**(case.context or {}), "feedback": fb}
        plan.status = "rejected_by_reviewer"
        transition(session, case, S.PLAN_PROPOSED, "Reviewer requested changes", actor="HUMAN")
        session.commit()
        launch(_flow_replan_feedback, case_id, "replan_reviewer_feedback", fb)
        return {"next": "replanning", **counts}

    if counts["approved"] == 0:
        session.rollback()
        raise ReviewError("Select at least one action to approve, or request a re-plan.")
    plan.status = "active"
    transition(session, case, S.APPROVED, f"{counts['approved']} action(s) approved by {reviewer}", actor="HUMAN")
    session.commit()
    launch(_flow_execute, case_id, "execute_approved")
    return {"next": "executing", **counts}


def _flow_replan_feedback(r: Runner, fb: dict) -> None:
    r.audit("AGENT", "replan.started", "Re-planning with reviewer feedback", status="warn")
    # Refresh staff/calendar so the reviewer's exclusions are applied by the tools themselves.
    try:
        r.case.context = {**gather_context(r.case, lambda n, p: r.tool(n, p), fb, r.pause,
                                           only={"staff", "calendar"}, prior_context=r.case.context), "feedback": fb}
    except ToolFailure as e:
        _enter_error(r, str(e), resume="SAFETY_CHECKED")
        return
    _plan_cycle(r, trigger="reviewer_feedback", feedback=fb, prior=None)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute_action(r: Runner, a: Action) -> str:
    appr = (r.s.query(Approval).filter(Approval.action_id == a.action_id, Approval.decision == "approved")
            .order_by(Approval.timestamp.desc()).first())
    token = mint_token(appr.approval_id, a.action_id, a.plan_id) if appr else None
    params = {k: v for k, v in (a.parameters or {}).items() if not k.startswith("_") and k != "option_id"}
    try:
        out = r.tool(a.type, params, actor="SYSTEM", action_id=a.action_id, token=token)
        a.execution_status = "executed"
        a.tool_result = out.model_dump()
        return "executed"
    except ToolConflict as e:
        a.execution_status = "failed"
        a.tool_result = {"error": str(e), "kind": "conflict"}
        return "conflict"
    except ToolPermissionError as e:
        a.execution_status = "blocked"
        a.tool_result = {"error": str(e), "kind": "permission"}
        return "blocked"
    except ToolFailure as e:
        a.execution_status = "failed"
        a.tool_result = {"error": str(e), "kind": "outage"}
        return "outage"


def execute_single(session: Session, action_id: str, actor: str = "API") -> dict:
    """POST /actions/{id}/execute - one action, server-side permission check."""
    a = session.get(Action, action_id)
    if a is None:
        raise KeyError(action_id)
    if a.execution_status in ("executed", "carried_over"):
        raise ReviewError("Action already executed")
    r = Runner(session, a.case_id, "execute_single")
    r.plan_version = session.get(CarePlan, a.plan_id).version
    prev = a.execution_status
    status = _execute_action(r, a)
    if status == "blocked":
        # A refused attempt is audited (tool.blocked) but must not alter the
        # action's lifecycle: it can still run normally after human approval.
        a.execution_status = prev
    session.commit()
    return {"action_id": action_id, "status": status, "result": a.tool_result}


def _flow_execute(r: Runner) -> None:
    case = r.case
    plan = r.s.get(CarePlan, case.current_plan_id)
    r.plan_version = plan.version

    # Pre-execution re-verification against fresh state (catches stale availability).
    r.step("Pre-execution verification")
    contract = plan.contract
    result, _ = verify_plan(r.s, case, contract, case.context or {}, locked=contract.get("_locked"), use_model=False)
    r.audit("VERIFIER", "verifier.pre_execution",
            result.status + (f" - {'; '.join(result.reasons[:2])}" if result.reasons else " - state unchanged since approval"),
            status="ok" if result.status == "PASS" else "warn")
    r.pause()
    if result.status != "PASS":
        plan.status = "superseded"
        r.to(S.PLAN_PROPOSED, "State changed after approval; approvals voided and plan re-proposed")
        fb = _merge_fb((case.context or {}).get("feedback", {}), result.feedback)
        try:
            case.context = {**gather_context(case, lambda n, p: r.tool(n, p), fb, r.pause,
                                             only={"calendar", "volunteers", "resources"}, prior_context=case.context),
                            "feedback": fb}
        except ToolFailure as e:
            _enter_error(r, str(e), resume="SAFETY_CHECKED")
            return
        _plan_cycle(r, trigger="pre_execution_drift", feedback=fb, prior=contract.get("_prior"))
        return

    r.to(S.EXECUTING, "Executing approved actions only", actor="SYSTEM")
    actions = (r.s.query(Action).filter(Action.plan_id == plan.plan_id, Action.approval_status == "approved",
                                        Action.execution_status.in_(["pending", "failed", "blocked"]))
               .order_by(Action.sort_order).all())
    actions.sort(key=lambda a: a.type == "message.send")  # external message last
    outcomes: dict[str, list[Action]] = {}
    for a in actions:
        r.step(f"Executing: {a.title}")
        st = _execute_action(r, a)
        outcomes.setdefault(st, []).append(a)
        r.pause()
        if st == "outage":
            break
    if outcomes.get("outage"):
        a = outcomes["outage"][0]
        _enter_error(r, f"{a.type} failed after retry while executing '{a.title}'. Remaining approved actions paused.",
                     resume="APPROVED", tool=a.type)
        return
    n_exec = len(outcomes.get("executed", []))
    r.audit("SYSTEM", "execution.completed", f"{n_exec} approved action(s) executed; "
            f"{len(outcomes.get('conflict', []))} conflict(s); {len(outcomes.get('blocked', []))} blocked")
    r.to(S.MONITORING, "Monitoring tasks, holds and volunteers for changes", actor="SYSTEM")
    if outcomes.get("conflict"):
        inval = [_invalidation_key(a) for a in outcomes["conflict"]]
        _replan_after_invalidation(r, [k for k in inval if k], {}, {"calendar", "volunteers", "resources"},
                                   "event:execution_conflict")


def _invalidation_key(a: Action) -> str | None:
    if a.type == "calendar.hold":
        return f"appointment:{a.parameters.get('option_id')}"
    if a.subtype == "volunteer_assignment":
        return f"volunteer_task:{a.parameters.get('details', {}).get('task_key')}"
    if a.type == "resource.reserve":
        return f"resource:{a.parameters.get('resource_id')}"
    return None


# ---------------------------------------------------------------------------
# Monitoring, events and re-planning
# ---------------------------------------------------------------------------

def _locked_from(contract: dict) -> dict:
    return {
        "owner": contract.get("proposed_owner"),
        "backup": contract.get("backup_owner"),
        "appointments": contract.get("appointment_options", []),
        "volunteer_tasks": {t["task_key"]: t for t in contract.get("volunteer_tasks", [])},
        "resources": contract.get("resource_actions", []),
        "internal_tasks": contract.get("internal_tasks", []),
    }


def _replan_after_invalidation(r: Runner, invalidated: list[str], fb_add: dict, refresh: set[str], trigger: str) -> None:
    case = r.case
    plan = r.s.get(CarePlan, case.current_plan_id)
    r.plan_version = plan.version
    case.context = {**(case.context or {}), "pending_invalidation": {"invalidated": invalidated, "fb": fb_add,
                                                                     "refresh": sorted(refresh), "trigger": trigger}}
    r.audit("AGENT", "plan.invalidated", f"Existing plan v{plan.version} invalidated: {', '.join(invalidated)}", status="warn")
    r.to(S.PLAN_PROPOSED, f"Invalidating event ({trigger.split(':', 1)[-1]}) - re-planning affected items only")
    r.audit("AGENT", "replan.started", "Minimal-change re-plan: keep valid commitments, re-solve invalidated items")
    r.pause()
    fb = _merge_fb((case.context or {}).get("feedback", {}), fb_add)
    try:
        ctx = gather_context(case, lambda n, p: r.tool(n, p), fb, r.pause, only=refresh, prior_context=case.context)
    except ToolFailure as e:
        _enter_error(r, str(e), resume="MONITORING")
        return
    ctx["feedback"] = fb
    ctx.pop("pending_invalidation", None)
    case.context = ctx
    for rt in ctx.get("ride_tasks", []):
        if f"volunteer_task:{rt['task_key']}" in invalidated:
            if rt["candidates"]:
                r.audit("AGENT", "replacement.found",
                        f"Replacement {rt['candidates'][0]['volunteer_id']} found for {rt['task_key']}")
            else:
                r.audit("AGENT", "replacement.none", f"No eligible replacement for {rt['task_key']}", status="warn")
    prior = {"locked": _locked_from(plan.contract), "invalidated": invalidated, "trigger": trigger,
             "contract": {k: v for k, v in plan.contract.items() if not k.startswith("_")}}
    _plan_cycle(r, trigger=trigger, feedback=fb, prior=prior)


def _flow_event_replan(r: Runner, invalidated: list[str], fb_add: dict, refresh: list[str], trigger: str) -> None:
    _replan_after_invalidation(r, invalidated, fb_add, set(refresh), trigger)


def _flow_monitor(r: Runner) -> None:
    """Re-check executed commitments against fresh state (tool calls)."""
    case = r.case
    plan = r.s.get(CarePlan, case.current_plan_id)
    r.plan_version = plan.version if plan else None
    r.step("Monitoring check")
    r.audit("AGENT", "monitor.started", "Re-checking holds, volunteers and reservations")
    invalid: list[str] = []
    actions = r.s.query(Action).filter(Action.plan_id == plan.plan_id).all() if plan else []
    try:
        holds = [a for a in actions if a.type == "calendar.hold" and a.execution_status in ("executed", "carried_over")]
        if holds:
            out = r.tool("calendar.read", {"staff_ids": list({a.parameters["staff_id"] for a in holds}),
                                           "window_start": min(a.parameters["start"] for a in holds),
                                           "window_end": max(a.parameters["end"] for a in holds), "slot_minutes": 30})
            from tools.calendar import find_conflicts
            for a in holds:
                cs = [b for b in find_conflicts(r.s, a.parameters["staff_id"], parse(a.parameters["start"]), parse(a.parameters["end"]))
                      if not (b.kind == "hold" and b.case_id == case.case_id)]
                if cs:
                    invalid.append(f"appointment:{a.parameters.get('option_id')}")
            r.pause()
        for a in [a for a in actions if a.subtype == "volunteer_assignment" and a.execution_status in ("executed", "carried_over")]:
            p = a.parameters
            out = r.tool("volunteer.search", {"role": "transportation", "campus": p.get("campus"), "start": p["due"], "end": p["end"]})
            ex = {e.volunteer_id: e.reasons for e in out.excluded}
            reasons = [x for x in ex.get(p["assignee_id"], []) if not x.startswith("constraint: max")]
            if reasons:
                invalid.append(f"volunteer_task:{p['details']['task_key']}")
            r.pause()
        reserves = [a for a in actions if a.type == "resource.reserve" and a.execution_status in ("executed", "carried_over")]
        if reserves:
            from models.entities import ResourceItem
            cats = sorted({r.s.get(ResourceItem, a.parameters["resource_id"]).category for a in reserves})
            out = r.tool("resource.search", {"campus": case.campus, "categories": cats, "consent_flags": case.consent_flags or {}})
            present = {i.resource_id for i in out.items}
            for a in reserves:
                if a.parameters["resource_id"] not in present:
                    invalid.append(f"resource:{a.parameters['resource_id']}")
            r.pause()
    except ToolFailure as e:
        _enter_error(r, f"Monitoring check failed: {e}", resume="MONITORING", tool=str(e).split(" ")[0])
        return
    if invalid:
        _replan_after_invalidation(r, invalid, {}, {"calendar", "volunteers"}, "event:monitor_detected_change")
    else:
        r.audit("AGENT", "monitor.ok", "All commitments still valid")


def _flow_resume(r: Runner) -> None:
    case = r.case
    resume = case.resume_state or "SAFETY_CHECKED"
    r.audit("AGENT", "run.resumed", f"Resuming from recoverable error at {resume}")
    case.error = {}
    if resume == "SAFETY_CHECKED":
        r.to(S.SAFETY_CHECKED, "Retrying context gathering")
        _gather_and_plan(r, trigger="resume")
    elif resume == "APPROVED":
        r.to(S.APPROVED, "Retrying approved actions")
        _flow_execute(r)
    else:
        r.to(S.MONITORING, "Resuming monitoring")
        pend = (case.context or {}).get("pending_invalidation")
        if pend:
            _replan_after_invalidation(r, pend["invalidated"], pend["fb"], set(pend["refresh"]), pend["trigger"])
        else:
            _flow_monitor(r)


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------

def operational_summary(session: Session, case: CareCase) -> str:
    from models.entities import InternalTask, Message, Reservation

    owner = session.get(StaffMember, case.owner_staff_id) if case.owner_staff_id else None
    tasks = session.query(InternalTask).filter(InternalTask.case_id == case.case_id).all()
    res = session.query(Reservation).filter(Reservation.case_id == case.case_id, Reservation.status == "held").all()
    msgs = session.query(Message).filter(Message.case_id == case.case_id, Message.status == "sent_demo_outbox").count()
    plans = session.query(CarePlan).filter(CarePlan.case_id == case.case_id).count()
    done = sum(1 for t in tasks if t.status == "done")
    cancelled = sum(1 for t in tasks if t.status == "cancelled")
    parts = [f"Case {case.case_id} closed (operational summary generated by CareFlow).",
             f"Owner: {owner.name + ' (' + owner.role + ')' if owner else 'not assigned'}.",
             f"Tasks: {done} completed, {cancelled} cancelled/replaced.",
             f"Resources reserved: {', '.join(r.resource_id for r in res) or 'none'}.",
             f"Messages sent (demo outbox, human-approved): {msgs}.",
             f"Plan versions: {plans}.",
             "Pastoral notes and judgments are intentionally not recorded by CareFlow; they remain with the Care team."]
    return " ".join(parts)


def owner_name(session: Session, staff_id: str | None) -> str | None:
    s = session.get(StaffMember, staff_id) if staff_id else None
    return s.name if s else None


__all__ = ["create_case", "run_case", "submit_review", "execute_single", "launch", "CaseBusy", "ReviewError",
           "Runner", "_flow_event_replan", "_flow_monitor", "operational_summary", "fmt"]
