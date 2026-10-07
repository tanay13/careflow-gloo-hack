"""SQLAlchemy ORM entities (the persisted system of record for the prototype)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


def _now() -> datetime:
    return datetime.now()


class CareCase(Base):
    __tablename__ = "care_cases"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    source: Mapped[str] = mapped_column(String, default="web_form")
    requester_ref: Mapped[str] = mapped_column(String, default="anonymous (synthetic)")
    campus: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="NEW")
    request_text: Mapped[str] = mapped_column(Text)
    intake_form: Mapped[dict] = mapped_column(JSON, default=dict)
    structured_needs: Mapped[dict] = mapped_column(JSON, default=dict)
    sensitivity_flags: Mapped[list] = mapped_column(JSON, default=list)
    consent_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    safety_result: Mapped[dict] = mapped_column(JSON, default=dict)
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # latest tool results snapshot
    owner_staff_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_plan_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    escalation: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict] = mapped_column(JSON, default=dict)
    resume_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duplicate_of: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    current_step: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class StaffMember(Base):
    __tablename__ = "staff"

    staff_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    campuses: Mapped[list] = mapped_column(JSON, default=list)
    approved_request_types: Mapped[list] = mapped_column(JSON, default=list)
    experience_tags: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_current_poc: Mapped[bool] = mapped_column(Boolean, default=False)


class CalendarBlock(Base):
    """Free/busy block. kind = busy (external) | hold (CareFlow provisional hold)."""

    __tablename__ = "calendar_blocks"

    block_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_id: Mapped[str] = mapped_column(String, ForeignKey("staff.staff_id"))
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String, default="busy")
    case_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    action_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | released
    source: Mapped[str] = mapped_column(String, default="seed")


class Volunteer(Base):
    __tablename__ = "volunteers"

    volunteer_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    approved_roles: Mapped[list] = mapped_column(JSON, default=list)
    campuses: Mapped[list] = mapped_column(JSON, default=list)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    availability: Mapped[list] = mapped_column(JSON, default=list)
    training_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    current_load: Mapped[int] = mapped_column(Integer, default=0)
    blackout: Mapped[list] = mapped_column(JSON, default=list)  # list of {start,end,reason}


class ResourceItem(Base):
    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    campus: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    reservable: Mapped[bool] = mapped_column(Boolean, default=False)
    restrictions: Mapped[list] = mapped_column(JSON, default=list)
    substitute_for: Mapped[list] = mapped_column(JSON, default=list)


class CarePlan(Base):
    __tablename__ = "care_plans"

    plan_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, ForeignKey("care_cases.case_id"))
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    status: Mapped[str] = mapped_column(String, default="proposed")  # proposed|active|superseded|rejected
    trigger: Mapped[str] = mapped_column(String, default="initial")
    owner: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    backup_owner: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    appointment_options: Mapped[list] = mapped_column(JSON, default=list)
    resource_actions: Mapped[list] = mapped_column(JSON, default=list)
    volunteer_tasks: Mapped[list] = mapped_column(JSON, default=list)
    unresolved_items: Mapped[list] = mapped_column(JSON, default=list)
    forbidden_items: Mapped[list] = mapped_column(JSON, default=list)
    rationale: Mapped[str] = mapped_column(Text, default="")
    required_approvals: Mapped[list] = mapped_column(JSON, default=list)
    verifier_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    verifier_result: Mapped[dict] = mapped_column(JSON, default=dict)
    contract: Mapped[dict] = mapped_column(JSON, default=dict)  # full planner JSON
    planner_source: Mapped[str] = mapped_column(String, default="mock")


class Action(Base):
    __tablename__ = "actions"

    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, ForeignKey("care_cases.case_id"))
    plan_id: Mapped[str] = mapped_column(String, ForeignKey("care_plans.plan_id"))
    type: Mapped[str] = mapped_column(String)  # tool name e.g. calendar.hold
    subtype: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String)  # safe | approval_required | forbidden
    reversible: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_status: Mapped[str] = mapped_column(String, default="pending")
    execution_status: Mapped[str] = mapped_column(String, default="pending")
    tool_result: Mapped[dict] = mapped_column(JSON, default=dict)
    carried_from: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Approval(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(String)
    action_id: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    reviewer: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)  # approved | rejected | auto_permitted | not_selected
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class InternalTask(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    action_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)  # internal | volunteer_assignment
    title: Mapped[str] = mapped_column(String)
    assignee_type: Mapped[str] = mapped_column(String)  # staff | volunteer | coordinator
    assignee_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="open")  # open | done | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    action_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource_id: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="held")  # held | released
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String, default="phone_script")
    recipient_ref: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | sent_demo_outbox
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
    actor: Mapped[str] = mapped_column(String)  # SYSTEM | AGENT | POLICY | TOOL | VERIFIER | HUMAN | EVENT
    event_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ok")  # ok | warn | error | blocked | info
    tool_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    input_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class ToolFault(Base):
    """Demo fault-injection switchboard (tool outage simulation)."""

    __tablename__ = "tool_faults"

    tool_name: Mapped[str] = mapped_column(String, primary_key=True)
    remaining_failures: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String, default="transient")


class Counter(Base):
    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
