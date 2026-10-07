"""task.create / task.cancel / task.complete - internal operational tasks (reversible)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agent.clock import parse
from db.ids import next_id
from models.entities import InternalTask, Volunteer
from tools.base import ToolConflict, ToolContext, ToolOutput, tool
from tools.volunteers import eligibility


class TaskCreateInput(BaseModel):
    case_id: str
    kind: str = Field(..., pattern="^(internal|volunteer_assignment)$")
    title: str
    assignee_type: str = Field(..., pattern="^(staff|volunteer|coordinator)$")
    assignee_id: Optional[str] = None
    due: Optional[str] = None
    end: Optional[str] = None
    role: Optional[str] = None
    campus: Optional[str] = None
    details: dict = Field(default_factory=dict)


class TaskCreateOutput(ToolOutput):
    task_id: str
    status: str


@tool("task.create", access="write_reversible", input_model=TaskCreateInput, output_model=TaskCreateOutput,
      requires_approval=True, description="Create an internal task or volunteer assignment (reversible).")
def task_create(ctx: ToolContext, inp: TaskCreateInput) -> TaskCreateOutput:
    if inp.kind == "volunteer_assignment":
        v = ctx.session.get(Volunteer, inp.assignee_id or "")
        if v is None:
            raise ToolConflict(f"Volunteer {inp.assignee_id} does not exist.")
        reasons = eligibility(ctx.session, v, inp.role or "transportation", inp.campus, parse(inp.due), parse(inp.end))
        if reasons:
            raise ToolConflict(f"{v.volunteer_id} no longer eligible: {'; '.join(reasons)}")
    tid = next_id(ctx.session, "TSK")
    ctx.session.add(InternalTask(
        task_id=tid, case_id=inp.case_id, action_id=ctx.action_id, kind=inp.kind, title=inp.title,
        assignee_type=inp.assignee_type, assignee_id=inp.assignee_id,
        due=parse(inp.due) if inp.due else None, details={**inp.details, "end": inp.end}, status="open",
    ))
    ctx.session.flush()
    return TaskCreateOutput(task_id=tid, status="open", summary=f"{tid} created: {inp.title}")


class TaskRefInput(BaseModel):
    action_id: Optional[str] = None
    task_id: Optional[str] = None
    reason: str = ""


class TaskRefOutput(ToolOutput):
    updated: int


def _find(ctx, inp: TaskRefInput):
    q = ctx.session.query(InternalTask)
    if inp.task_id:
        return q.filter(InternalTask.task_id == inp.task_id).all()
    return q.filter(InternalTask.action_id == inp.action_id).all()


@tool("task.cancel", access="undo", input_model=TaskRefInput, output_model=TaskRefOutput,
      description="Cancel a CareFlow-created task (reverses task.create).")
def task_cancel(ctx: ToolContext, inp: TaskRefInput) -> TaskRefOutput:
    rows = [t for t in _find(ctx, inp) if t.status == "open"]
    for t in rows:
        t.status = "cancelled"
        t.details = {**(t.details or {}), "cancel_reason": inp.reason}
    ctx.session.flush()
    return TaskRefOutput(updated=len(rows), summary=f"cancelled {len(rows)} task(s): {inp.reason}")


@tool("task.complete", access="undo", input_model=TaskRefInput, output_model=TaskRefOutput,
      allowed_actors={"SYSTEM", "EVENT", "HUMAN"}, description="Mark operational tasks complete.")
def task_complete(ctx: ToolContext, inp: TaskRefInput) -> TaskRefOutput:
    rows = [t for t in _find(ctx, inp) if t.status == "open"]
    for t in rows:
        t.status = "done"
    ctx.session.flush()
    return TaskRefOutput(updated=len(rows), summary=f"completed {len(rows)} task(s)")
