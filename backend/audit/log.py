"""Append-only audit log writer.

There is intentionally no update/delete API here, and SQLite triggers abort any
UPDATE/DELETE on the table (see db/database.py).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from models.entities import AuditEvent

log = logging.getLogger("careflow.audit")


def append_event(
    session: Session,
    case_id: Optional[str],
    *,
    actor: str,
    event_type: str,
    status: str = "ok",
    tool_name: Optional[str] = None,
    input_summary: Optional[str] = None,
    output_summary: Optional[str] = None,
    plan_version: Optional[int] = None,
    approval_ref: Optional[str] = None,
    latency_ms: Optional[float] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    ev = AuditEvent(
        case_id=case_id,
        actor=actor,
        event_type=event_type,
        status=status,
        tool_name=tool_name,
        input_summary=input_summary,
        output_summary=output_summary,
        plan_version=plan_version,
        approval_ref=approval_ref,
        latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        event_metadata=json.loads(json.dumps(metadata or {}, default=str)),
    )
    session.add(ev)
    session.flush()
    log.info(
        json.dumps(
            {
                "case": case_id,
                "actor": actor,
                "event": event_type,
                "status": status,
                "tool": tool_name,
                "out": output_summary,
                "latency_ms": ev.latency_ms,
            }
        )
    )
    return ev
