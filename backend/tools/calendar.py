"""calendar.read / calendar.hold / calendar.release - synthetic free/busy adapter.

calendar.read exposes free/busy only (never event contents). calendar.hold is a
reversible provisional hold and requires an approval token.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from agent.clock import fmt, iso, parse
from db.ids import next_id
from models.entities import CalendarBlock, StaffMember
from tools.base import ToolConflict, ToolContext, ToolOutput, tool

WORK_START, WORK_END = 9, 17


class Window(BaseModel):
    start: str
    end: str


class CalendarReadInput(BaseModel):
    staff_ids: list[str]
    window_start: str
    window_end: str
    slot_minutes: int = 60
    avoid: list[Window] = Field(default_factory=list, description="Requester constraints (e.g. ride windows).")
    max_slots: int = 12


class StaffAvailability(BaseModel):
    staff_id: str
    busy: list[Window]
    free_slots: list[Window]


class CalendarReadOutput(ToolOutput):
    availability: list[StaffAvailability]
    checked_at: str


def _blocks(session, staff_id: str) -> list[CalendarBlock]:
    return (session.query(CalendarBlock)
            .filter(CalendarBlock.staff_id == staff_id, CalendarBlock.status == "active").all())


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def find_conflicts(session, staff_id: str, start: datetime, end: datetime, ignore_action: Optional[str] = None) -> list[CalendarBlock]:
    return [b for b in _blocks(session, staff_id)
            if _overlaps(start, end, b.start, b.end) and (ignore_action is None or b.action_id != ignore_action)]


def _round_up(dt: datetime) -> datetime:
    extra = (30 - dt.minute % 30) % 30
    return (dt + timedelta(minutes=extra)).replace(second=0, microsecond=0)


def free_slots(session, staff_id: str, w0: datetime, w1: datetime, minutes: int,
               avoid: list[tuple[datetime, datetime]], cap: int) -> list[tuple[datetime, datetime]]:
    blocks = [(b.start, b.end) for b in _blocks(session, staff_id)]
    buffer = timedelta(minutes=30)
    out: list[tuple[datetime, datetime]] = []
    cur = _round_up(w0)
    while cur < w1 and len(out) < cap:
        day_start = cur.replace(hour=WORK_START, minute=0)
        day_end = cur.replace(hour=WORK_END, minute=0)
        if cur.weekday() >= 5 or cur >= day_end:
            cur = (cur + timedelta(days=1)).replace(hour=WORK_START, minute=0)
            continue
        if cur < day_start:
            cur = day_start
        end = cur + timedelta(minutes=minutes)
        ok = end <= day_end and end <= w1
        ok = ok and not any(_overlaps(cur, end, b0, b1) for b0, b1 in blocks)
        ok = ok and not any(_overlaps(cur, end, a0 - buffer, a1 + buffer) for a0, a1 in avoid)
        if ok:
            out.append((cur, end))
            cur = end
        else:
            cur += timedelta(minutes=30)
    return out


@tool("calendar.read", access="read", input_model=CalendarReadInput, output_model=CalendarReadOutput,
      description="Free/busy only for the requested staff within a window. No event details.")
def calendar_read(ctx: ToolContext, inp: CalendarReadInput) -> CalendarReadOutput:
    w0, w1 = parse(inp.window_start), parse(inp.window_end)
    avoid = [(parse(a.start), parse(a.end)) for a in inp.avoid]
    result = []
    total_free = 0
    for sid in inp.staff_ids:
        if ctx.session.get(StaffMember, sid) is None:
            continue
        busy = [Window(start=iso(b.start), end=iso(b.end)) for b in _blocks(ctx.session, sid)
                if _overlaps(b.start, b.end, w0, w1)]
        slots = free_slots(ctx.session, sid, w0, w1, inp.slot_minutes, avoid, inp.max_slots)
        total_free += len(slots)
        result.append(StaffAvailability(staff_id=sid, busy=busy,
                                        free_slots=[Window(start=iso(a), end=iso(b)) for a, b in slots]))
    return CalendarReadOutput(
        availability=result, checked_at=datetime.now().isoformat(timespec="seconds"),
        summary=f"checked {len(result)} staff calendar(s) {fmt(w0)} → {fmt(w1)}; {total_free} free slot(s)",
    )


class CalendarHoldInput(BaseModel):
    case_id: str
    staff_id: str
    start: str
    end: str
    label: str = "Pastoral conversation (provisional hold)"


class CalendarHoldOutput(ToolOutput):
    hold_id: str
    block_id: int
    staff_id: str
    start: str
    end: str


@tool("calendar.hold", access="write_reversible", input_model=CalendarHoldInput, output_model=CalendarHoldOutput,
      requires_approval=True, retryable=True,
      description="Create a reversible provisional calendar hold (approval token required).")
def calendar_hold(ctx: ToolContext, inp: CalendarHoldInput) -> CalendarHoldOutput:
    start, end = parse(inp.start), parse(inp.end)
    conflicts = find_conflicts(ctx.session, inp.staff_id, start, end)
    if conflicts:
        raise ToolConflict(f"{inp.staff_id} is no longer free {fmt(start)} (fresh calendar conflict) - no double booking")
    hold_id = next_id(ctx.session, "HLD")
    block = CalendarBlock(staff_id=inp.staff_id, start=start, end=end, kind="hold", case_id=inp.case_id,
                          action_id=ctx.action_id, status="active", source=hold_id)
    ctx.session.add(block)
    ctx.session.flush()
    return CalendarHoldOutput(hold_id=hold_id, block_id=block.block_id, staff_id=inp.staff_id,
                              start=inp.start, end=inp.end,
                              summary=f"hold {hold_id} created for {inp.staff_id} {fmt(start)}")


class CalendarReleaseInput(BaseModel):
    action_id: str


class CalendarReleaseOutput(ToolOutput):
    released: int


@tool("calendar.release", access="undo", input_model=CalendarReleaseInput, output_model=CalendarReleaseOutput,
      description="Reverse a provisional hold (undo reduces commitment; no approval needed).")
def calendar_release(ctx: ToolContext, inp: CalendarReleaseInput) -> CalendarReleaseOutput:
    blocks = ctx.session.query(CalendarBlock).filter(CalendarBlock.action_id == inp.action_id,
                                                     CalendarBlock.status == "active").all()
    for b in blocks:
        b.status = "released"
    ctx.session.flush()
    return CalendarReleaseOutput(released=len(blocks), summary=f"released {len(blocks)} hold(s)")
