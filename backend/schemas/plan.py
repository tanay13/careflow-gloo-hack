"""Planner / verifier JSON contracts (typed)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OwnerEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    campus_match: bool = False
    role_match: bool = False
    experience_match: list[str] = Field(default_factory=list)
    availability_checked: bool = False
    poc_match: bool = False


class OwnerProposal(BaseModel):
    model_config = ConfigDict(extra="allow")
    staff_id: str
    name: Optional[str] = None
    role: Optional[str] = None
    reason: str = ""
    evidence: OwnerEvidence = Field(default_factory=OwnerEvidence)


class AppointmentOption(BaseModel):
    model_config = ConfigDict(extra="allow")
    option_id: str
    staff_id: str
    start: str
    end: str
    mode: str = "phone call"
    reason: str = ""
    availability_checked: bool = True


class ResourceAction(BaseModel):
    model_config = ConfigDict(extra="allow")
    resource_id: str
    action: Literal["reserve", "share_info"]
    quantity: int = 0
    reason: str = ""
    name: Optional[str] = None


class VolunteerTask(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_key: str
    volunteer_id: Optional[str] = None
    start: str
    end: str
    reason: str = ""


class InternalTaskSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    assignee_type: Literal["staff", "coordinator"] = "coordinator"
    assignee_id: Optional[str] = None


class UnresolvedItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    need: str
    detail: str
    severity: Literal["blocking", "needs_info", "info"] = "info"
    escalate: bool = False


class ForbiddenItem(BaseModel):
    topic: str
    handling: str


class PlanContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    objective: str
    known_facts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    sensitivity_flags: list[str] = Field(default_factory=list)
    proposed_owner: Optional[OwnerProposal] = None
    backup_owner: Optional[OwnerProposal] = None
    appointment_options: list[AppointmentOption] = Field(default_factory=list)
    resource_actions: list[ResourceAction] = Field(default_factory=list)
    volunteer_tasks: list[VolunteerTask] = Field(default_factory=list)
    internal_tasks: list[InternalTaskSpec] = Field(default_factory=list)
    message_draft: str = ""
    approvals_required: list[str] = Field(default_factory=list)
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)
    forbidden_items: list[ForbiddenItem] = Field(default_factory=list)
    rationale: str = ""
    stop_reason: Optional[str] = None


class VerifierResult(BaseModel):
    status: Literal["PASS", "REPLAN", "ESCALATE"]
    reasons: list[str] = Field(default_factory=list)
    invalid_fields: list[str] = Field(default_factory=list)
    feedback: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
