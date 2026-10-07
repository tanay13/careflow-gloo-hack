"""message.draft (safe) and message.send (irreversible, hard approval gate).

No real messages are ever sent by this prototype: message.send writes to a demo
outbox table. Even so, it is blocked server-side without a human approval token.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from db.ids import next_id
from models.entities import CareCase, Message
from tools.base import ToolContext, ToolOutput, ToolPermissionError, tool

CRISIS_FLAGS = {"self_harm_or_crisis", "abuse", "medical_emergency", "imminent_danger", "minor_involved"}


def _assert_not_crisis(ctx: ToolContext, case_id: str) -> None:
    case = ctx.session.get(CareCase, case_id)
    if case and CRISIS_FLAGS.intersection(case.sensitivity_flags or []):
        raise ToolPermissionError("Case is under safety escalation - no automated contact with the requester.")


class DraftInput(BaseModel):
    case_id: str
    recipient_ref: str
    channel: str = "phone_script"
    subject: str = ""
    body: str


class DraftOutput(ToolOutput):
    message_id: str
    status: str


@tool("message.draft", access="draft", input_model=DraftInput, output_model=DraftOutput,
      description="Store a draft communication. A draft is never treated as sent.")
def message_draft(ctx: ToolContext, inp: DraftInput) -> DraftOutput:
    _assert_not_crisis(ctx, inp.case_id)
    mid = next_id(ctx.session, "MSG")
    ctx.session.add(Message(message_id=mid, case_id=inp.case_id, channel=inp.channel, recipient_ref=inp.recipient_ref,
                            subject=inp.subject, body=inp.body, status="draft"))
    ctx.session.flush()
    return DraftOutput(message_id=mid, status="draft", summary=f"draft {mid} saved (not sent)")


class SendInput(BaseModel):
    message_id: str


class SendOutput(ToolOutput):
    message_id: str
    status: str


@tool("message.send", access="write_irreversible", input_model=SendInput, output_model=SendOutput,
      requires_approval=True, retryable=False,
      description="Send an approved message (demo outbox). Blocked without explicit human approval token.")
def message_send(ctx: ToolContext, inp: SendInput) -> SendOutput:
    msg = ctx.session.get(Message, inp.message_id)
    if msg is None:
        raise ToolPermissionError("Unknown draft.")
    _assert_not_crisis(ctx, msg.case_id)
    if msg.status != "draft":
        raise ToolPermissionError(f"Message already {msg.status}; duplicate send prevented.")
    msg.status = "sent_demo_outbox"
    msg.sent_at = datetime.now()
    ctx.session.flush()
    return SendOutput(message_id=msg.message_id, status=msg.status,
                      summary=f"{msg.message_id} delivered to demo outbox (no real message sent)")
