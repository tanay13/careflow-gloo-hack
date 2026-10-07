"""case.update and audit.append."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from audit.log import append_event
from models.entities import CareCase, StaffMember
from tools.base import ToolContext, ToolOutput, ToolPermissionError, tool, verify_approval

# Fields CareFlow may touch. Record-of-record changes require human approval.
OPERATIONAL_FIELDS = {"summary", "operational_note"}
SENSITIVE_FIELDS = {"owner_staff_id"}


class CaseUpdateInput(BaseModel):
    case_id: str
    field: str = Field(..., description="owner_staff_id | summary | operational_note")
    value: Any


class CaseUpdateOutput(ToolOutput):
    case_id: str
    field: str


@tool("case.update", access="write_reversible", input_model=CaseUpdateInput, output_model=CaseUpdateOutput,
      allowed_actors={"SYSTEM", "HUMAN"},
      description="Update operational case fields; sensitive record changes require approval token.")
def case_update(ctx: ToolContext, inp: CaseUpdateInput) -> CaseUpdateOutput:
    case = ctx.session.get(CareCase, inp.case_id)
    if case is None:
        raise ToolPermissionError("Unknown case.")
    if inp.field in SENSITIVE_FIELDS:
        verify_approval(ctx.session, ctx.action_id, ctx.approval_token, irreversible=False)
        if ctx.session.get(StaffMember, inp.value) is None:
            raise ToolPermissionError(f"Staff {inp.value} does not exist.")
        case.owner_staff_id = inp.value
    elif inp.field == "summary":
        case.summary = str(inp.value)
    elif inp.field == "operational_note":
        notes = list((case.context or {}).get("notes", []))
        notes.append(str(inp.value))
        case.context = {**(case.context or {}), "notes": notes}
    else:
        raise ToolPermissionError(f"Field '{inp.field}' is not writable by CareFlow.")
    ctx.session.flush()
    return CaseUpdateOutput(case_id=case.case_id, field=inp.field, summary=f"case {inp.field} updated")


class AuditAppendInput(BaseModel):
    case_id: str
    event_type: str
    summary: str


class AuditAppendOutput(ToolOutput):
    event_id: int


@tool("audit.append", access="append", input_model=AuditAppendInput, output_model=AuditAppendOutput,
      description="Append-only audit event. Prior events cannot be modified or deleted.")
def audit_append(ctx: ToolContext, inp: AuditAppendInput) -> AuditAppendOutput:
    ev = append_event(ctx.session, inp.case_id, actor=ctx.actor_kind, event_type=inp.event_type,
                      output_summary=inp.summary, plan_version=ctx.plan_version)
    return AuditAppendOutput(event_id=ev.event_id, summary="appended")
