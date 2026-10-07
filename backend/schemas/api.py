"""Request bodies for the REST API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AppointmentIn(BaseModel):
    label: str = "Appointment"
    day_offset: int = Field(..., ge=0, le=13, description="Days from Monday of the demo week")
    time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    location: str = ""


class IntakeFormIn(BaseModel):
    preferred_contact: Optional[str] = None
    appointments: list[AppointmentIn] = Field(default_factory=list)
    referrals: list[str] = Field(default_factory=list)


class CaseCreate(BaseModel):
    request_text: str = Field(..., min_length=3, max_length=4000)
    source: str = "web_form"
    requester_ref: Optional[str] = None
    intake_form: IntakeFormIn = Field(default_factory=IntakeFormIn)
    consent_flags: dict = Field(default_factory=lambda: {"contact_ok": True})
    auto_run: bool = False


class Decision(BaseModel):
    action_id: str
    decision: Literal["approve", "reject", "reassign"]
    staff_id: Optional[str] = None
    comments: Optional[str] = None


class ReviewIn(BaseModel):
    reviewer: str = "Care Coordinator"
    decisions: list[Decision] = Field(default_factory=list)
    feedback: Optional[str] = None
    request_replan: bool = False


class EventIn(BaseModel):
    type: Literal["volunteer_cancelled", "resource_unavailable", "staff_calendar_conflict", "tool_outage",
                  "tool_restored", "tasks_completed"]
    target: Optional[str] = None
    mode: Optional[Literal["transient", "persistent"]] = None
    tool: Optional[str] = None
