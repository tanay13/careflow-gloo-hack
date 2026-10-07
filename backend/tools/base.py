"""Tool registry with server-side permission enforcement.

Every tool:
  * declares a typed pydantic input and output schema,
  * declares an access class (read / draft / write_reversible / write_irreversible / append),
  * is invoked only through `call_tool`, which enforces permissions, approval
    tokens, fault injection, a single retry, latency measurement and auditing.

Authorization never depends on the model: the planner can *propose* actions,
but write tools refuse to run without a valid server-issued approval token.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from agent.policies import P
from audit.log import append_event
from config import settings
from models.entities import Action, Approval, CarePlan, ToolFault


class ToolPermissionError(Exception):
    """Raised when a tool call is not authorized. Always audited as 'blocked'."""


class ToolFailure(Exception):
    """Raised when a tool fails after the allowed retries."""


class ToolConflict(Exception):
    """Raised when fresh state contradicts the request (e.g. calendar conflict).

    Not retried: the plan itself is stale and must be re-planned."""


class ToolOutput(BaseModel):
    summary: str = ""


@dataclass
class ToolContext:
    session: Session
    case_id: Optional[str]
    actor: str = "AGENT"  # AGENT | SYSTEM | HUMAN:<name> | EVENT | EVAL
    plan_version: Optional[int] = None
    action_id: Optional[str] = None
    approval_token: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def actor_kind(self) -> str:
        return self.actor.split(":", 1)[0]


@dataclass
class ToolSpec:
    name: str
    access: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    fn: Callable[[ToolContext, Any], Any]
    allowed_actors: set[str]
    requires_approval: bool
    retryable: bool
    description: str


REGISTRY: dict[str, ToolSpec] = {}

ACCESS_DEFAULT_ACTORS = {
    "read": {"AGENT", "SYSTEM", "HUMAN", "EVAL", "EVENT"},
    "draft": {"AGENT", "SYSTEM", "HUMAN"},
    # Writes are performed by the executor (SYSTEM) on behalf of an approval.
    "write_reversible": {"SYSTEM"},
    "write_irreversible": {"SYSTEM"},
    # Reversal of a CareFlow-created reversible action (reduces commitment).
    "undo": {"SYSTEM", "EVENT"},
    "append": {"AGENT", "SYSTEM", "HUMAN", "EVENT", "POLICY", "VERIFIER"},
}


def tool(
    name: str,
    *,
    access: str,
    input_model: Type[BaseModel],
    output_model: Type[BaseModel],
    requires_approval: bool = False,
    retryable: bool = True,
    description: str = "",
    allowed_actors: Optional[set[str]] = None,
):
    def deco(fn):
        REGISTRY[name] = ToolSpec(
            name=name,
            access=access,
            input_model=input_model,
            output_model=output_model,
            fn=fn,
            allowed_actors=allowed_actors or ACCESS_DEFAULT_ACTORS[access],
            requires_approval=requires_approval,
            retryable=retryable,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
        )
        return fn

    return deco


# ---------------------------------------------------------------------------
# Approval tokens
# ---------------------------------------------------------------------------

def mint_token(approval_id: str, action_id: str, plan_id: str) -> str:
    msg = f"{approval_id}:{action_id}:{plan_id}".encode()
    return hmac.new(settings.approval_secret.encode(), msg, hashlib.sha256).hexdigest()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_approval(session: Session, action_id: Optional[str], token: Optional[str], *, irreversible: bool) -> Approval:
    """Server-side gate. Raises ToolPermissionError unless a valid approval exists."""
    if not action_id or not token:
        raise ToolPermissionError("No approval token supplied - action requires explicit approval.")
    action = session.get(Action, action_id)
    if action is None:
        raise ToolPermissionError(f"Unknown action {action_id}.")
    if action.risk_level == "forbidden":
        raise ToolPermissionError("Action is forbidden by policy and can never execute.")
    appr = (
        session.query(Approval)
        .filter(Approval.action_id == action_id, Approval.decision.in_(["approved", "auto_permitted"]))
        .order_by(Approval.timestamp.desc())
        .first()
    )
    if appr is None:
        raise ToolPermissionError("No approval record for this action.")
    if not hmac.compare_digest(appr.token_hash or "", token_hash(token)):
        raise ToolPermissionError("Approval token does not match this action.")
    if action.risk_level == "approval_required" and appr.decision != "approved":
        raise ToolPermissionError("Action requires explicit HUMAN approval; policy auto-permit is insufficient.")
    if irreversible and (appr.decision != "approved" or not appr.reviewer.startswith("HUMAN")):
        raise ToolPermissionError("Irreversible action requires explicit human approval.")
    if irreversible and appr.consumed:
        raise ToolPermissionError("Approval token already used (irreversible actions are single-use).")
    plan = session.get(CarePlan, action.plan_id)
    if plan is None or plan.status not in ("active", "proposed"):
        raise ToolPermissionError("Approval belongs to a superseded plan version.")
    return appr


# ---------------------------------------------------------------------------
# Fault injection (demo "Tool outage")
# ---------------------------------------------------------------------------

def _maybe_fault(session: Session, name: str) -> None:
    fault = session.get(ToolFault, name)
    if fault and fault.remaining_failures > 0:
        fault.remaining_failures -= 1
        session.flush()
        raise ToolFailure(f"{name} unavailable (simulated {fault.mode} outage)")


def set_fault(session: Session, name: str, mode: str) -> None:
    fault = session.get(ToolFault, name) or ToolFault(tool_name=name)
    fault.mode = mode
    fault.remaining_failures = 1 if mode == "transient" else 1000
    session.merge(fault)
    session.flush()


def clear_faults(session: Session) -> None:
    for f in session.query(ToolFault).all():
        f.remaining_failures = 0
    session.flush()


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------

def call_tool(name: str, ctx: ToolContext, payload: dict | BaseModel | None = None):
    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolPermissionError(f"Unknown tool '{name}'.")
    session = ctx.session
    payload = payload or {}
    raw = payload.model_dump() if isinstance(payload, BaseModel) else payload
    try:
        inp = spec.input_model.model_validate(raw)
    except ValidationError as e:
        append_event(session, ctx.case_id, actor="POLICY", event_type="tool.input_rejected", status="blocked",
                     tool_name=name, output_summary=f"Input failed schema validation: {e.errors()[:2]}",
                     plan_version=ctx.plan_version)
        raise ToolPermissionError(f"Invalid input for {name}") from e

    # ---- permission checks (never delegated to the model) ----
    try:
        if ctx.actor_kind not in spec.allowed_actors:
            raise ToolPermissionError(f"Actor {ctx.actor_kind} is not permitted to call {name} ({spec.access}).")
        approval = None
        if spec.requires_approval:
            approval = verify_approval(session, ctx.action_id, ctx.approval_token,
                                       irreversible=spec.access == "write_irreversible")
    except ToolPermissionError as e:
        append_event(session, ctx.case_id, actor="POLICY", event_type="tool.blocked", status="blocked",
                     tool_name=name, input_summary=_short(raw), output_summary=str(e),
                     plan_version=ctx.plan_version, metadata={"action_id": ctx.action_id, "actor": ctx.actor})
        raise

    max_retries = P()["tools"]["max_retries"] if spec.retryable else 0
    attempt = 0
    while True:
        t0 = time.perf_counter()
        try:
            _maybe_fault(session, name)
            result = spec.fn(ctx, inp)
            out = result if isinstance(result, spec.output_model) else spec.output_model.model_validate(result)
            latency = (time.perf_counter() - t0) * 1000
            if approval is not None and spec.access == "write_irreversible":
                approval.consumed = True
            append_event(session, ctx.case_id, actor="TOOL", event_type="tool.call", tool_name=name,
                         input_summary=_short(raw), output_summary=getattr(out, "summary", ""),
                         plan_version=ctx.plan_version, latency_ms=latency,
                         approval_ref=approval.approval_id if approval else None,
                         metadata={"attempt": attempt + 1, "access": spec.access, "action_id": ctx.action_id})
            return out
        except ToolPermissionError as e:
            append_event(session, ctx.case_id, actor="POLICY", event_type="tool.blocked", status="blocked",
                         tool_name=name, input_summary=_short(raw), output_summary=str(e),
                         plan_version=ctx.plan_version)
            raise
        except ToolConflict as e:
            append_event(session, ctx.case_id, actor="TOOL", event_type="tool.conflict", status="warn",
                         tool_name=name, input_summary=_short(raw), output_summary=str(e),
                         plan_version=ctx.plan_version, latency_ms=(time.perf_counter() - t0) * 1000)
            raise
        except Exception as e:  # noqa: BLE001 - surface every failure in the audit log
            latency = (time.perf_counter() - t0) * 1000
            append_event(session, ctx.case_id, actor="TOOL", event_type="tool.error", status="error",
                         tool_name=name, input_summary=_short(raw), output_summary=str(e),
                         plan_version=ctx.plan_version, latency_ms=latency, metadata={"attempt": attempt + 1})
            if attempt < max_retries:
                attempt += 1
                append_event(session, ctx.case_id, actor="AGENT", event_type="tool.retry", status="warn",
                             tool_name=name, output_summary=f"Retrying {name} (attempt {attempt + 1} of {max_retries + 1})",
                             plan_version=ctx.plan_version)
                continue
            raise ToolFailure(f"{name} failed after {attempt + 1} attempt(s): {e}") from e


def _short(raw: Any, limit: int = 220) -> str:
    s = str(raw)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def describe_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "access": s.access,
            "requires_approval": s.requires_approval,
            "allowed_actors": sorted(s.allowed_actors),
            "description": s.description,
            "input_schema": s.input_model.model_json_schema(),
            "output_schema": s.output_model.model_json_schema(),
        }
        for s in REGISTRY.values()
    ]
