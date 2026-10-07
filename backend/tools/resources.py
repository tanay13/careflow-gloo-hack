"""resource.search / resource.reserve / resource.release over the approved catalog only."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agent.policies import check_resource_restrictions, resource_reserve_permission
from db.ids import next_id
from models.entities import CareCase, Reservation, ResourceItem
from tools.base import ToolConflict, ToolContext, ToolOutput, ToolPermissionError, tool


def resource_dict(r: ResourceItem) -> dict:
    return {
        "resource_id": r.resource_id, "name": r.name, "category": r.category, "description": r.description,
        "campus": r.campus, "kind": r.kind, "quantity": r.quantity, "status": r.status,
        "approval_required": r.approval_required, "reservable": r.reservable,
        "restrictions": r.restrictions or [], "substitute_for": r.substitute_for or [],
    }


class ResourceSearchInput(BaseModel):
    campus: Optional[str] = None
    categories: list[str]
    consent_flags: dict = Field(default_factory=dict)
    referrals: list[str] = Field(default_factory=list)


class ResourceHit(BaseModel):
    resource_id: str
    name: str
    category: str
    description: str
    campus: str
    kind: str
    quantity: Optional[int]
    status: str
    approval_required: bool
    reservable: bool
    restrictions: list[str]
    substitute_for: list[str]
    available: bool
    restrictions_satisfied: bool
    unmet_restrictions: list[str]
    reserve_permitted: bool
    reserve_policy_note: str


class ResourceSearchOutput(ToolOutput):
    items: list[ResourceHit]


@tool("resource.search", access="read", input_model=ResourceSearchInput, output_model=ResourceSearchOutput,
      description="Search the seeded approved catalog only (campus or All). Never fabricates resources.")
def resource_search(ctx: ToolContext, inp: ResourceSearchInput) -> ResourceSearchOutput:
    q = ctx.session.query(ResourceItem).filter(ResourceItem.category.in_(inp.categories),
                                               ResourceItem.status != "inactive")
    items = []
    for r in q.order_by(ResourceItem.resource_id).all():
        if not (r.campus == "All" or (inp.campus and r.campus == inp.campus)):
            continue
        d = resource_dict(r)
        ok, unmet = check_resource_restrictions(d, {"consent_flags": inp.consent_flags, "referrals": inp.referrals})
        perm, note = resource_reserve_permission(d)
        available = r.status == "available" and (r.quantity is None or r.quantity > 0)
        items.append(ResourceHit(**d, available=available, restrictions_satisfied=ok, unmet_restrictions=unmet,
                                 reserve_permitted=perm, reserve_policy_note=note))
    n_avail = sum(1 for i in items if i.available)
    return ResourceSearchOutput(items=items,
                                summary=f"{len(items)} catalog item(s) for {', '.join(inp.categories)}; {n_avail} available")


class ResourceReserveInput(BaseModel):
    case_id: str
    resource_id: str
    quantity: int = 1


class ResourceReserveOutput(ToolOutput):
    reservation_id: str
    resource_id: str
    remaining: Optional[int]


@tool("resource.reserve", access="write_reversible", input_model=ResourceReserveInput,
      output_model=ResourceReserveOutput, requires_approval=True,
      description="Temporary reversible reservation for delegated categories only.")
def resource_reserve(ctx: ToolContext, inp: ResourceReserveInput) -> ResourceReserveOutput:
    r = ctx.session.get(ResourceItem, inp.resource_id)
    if r is None:
        raise ToolPermissionError(f"{inp.resource_id} is not in the approved catalog.")
    d = resource_dict(r)
    perm, note = resource_reserve_permission(d)
    if not perm:
        raise ToolPermissionError(note)
    case = ctx.session.get(CareCase, inp.case_id)
    ok, unmet = check_resource_restrictions(d, {"consent_flags": case.consent_flags if case else {},
                                                "referrals": (case.structured_needs or {}).get("referrals", []) if case else []})
    if not ok:
        raise ToolPermissionError("Restriction not satisfied: " + "; ".join(unmet))
    if r.status != "available" or (r.quantity is not None and r.quantity < inp.quantity):
        raise ToolConflict(f"{r.resource_id} {r.name} is no longer available (status={r.status}, qty={r.quantity})")
    if r.quantity is not None:
        r.quantity -= inp.quantity
    rid = next_id(ctx.session, "RSV")
    ctx.session.add(Reservation(reservation_id=rid, case_id=inp.case_id, action_id=ctx.action_id,
                                resource_id=r.resource_id, quantity=inp.quantity, status="held"))
    ctx.session.flush()
    return ResourceReserveOutput(reservation_id=rid, resource_id=r.resource_id, remaining=r.quantity,
                                 summary=f"reserved {inp.quantity}× {r.name} ({r.resource_id}) as {rid}")


class ResourceReleaseInput(BaseModel):
    action_id: str


class ResourceReleaseOutput(ToolOutput):
    released: int


@tool("resource.release", access="undo", input_model=ResourceReleaseInput, output_model=ResourceReleaseOutput,
      description="Release a CareFlow reservation (reverses resource.reserve).")
def resource_release(ctx: ToolContext, inp: ResourceReleaseInput) -> ResourceReleaseOutput:
    rows = ctx.session.query(Reservation).filter(Reservation.action_id == inp.action_id,
                                                 Reservation.status == "held").all()
    for row in rows:
        row.status = "released"
        item = ctx.session.get(ResourceItem, row.resource_id)
        if item and item.quantity is not None and item.status == "available":
            item.quantity += row.quantity
    ctx.session.flush()
    return ResourceReleaseOutput(released=len(rows), summary=f"released {len(rows)} reservation(s)")
