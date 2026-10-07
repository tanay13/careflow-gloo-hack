"""Planner: asks the configured provider for a structured plan, validates the
JSON contract, and falls back to the deterministic reasoner if the model output
is malformed. The verifier (not the planner) decides whether a plan is valid."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent.mock_reasoner import deterministic_plan
from llm.provider import MockLLMProvider, get_provider
from schemas.plan import PlanContract


def generate_plan(case: dict, context: dict, feedback: dict, prior: dict | None) -> tuple[dict[str, Any], dict, str]:
    """Return (plan_json, usage, source)."""
    provider = get_provider()
    res = provider.generate_plan(case, _model_view(context), feedback, prior)
    usage = res.usage
    source = "mock" if isinstance(provider, MockLLMProvider) or usage.get("fallback_reason") else "llm"
    try:
        contract = PlanContract.model_validate(dict(res)).model_dump()
    except ValidationError as e:
        usage = {**usage, "fallback_reason": f"plan schema invalid: {e.errors()[:1]}"}
        contract = PlanContract.model_validate(deterministic_plan(case, context, feedback, prior)).model_dump()
        source = "mock"
    # Enrich display names from tool data (never trust model-provided names).
    _enrich(contract, context)
    return contract, usage, source


def _model_view(context: dict) -> dict:
    """Minimum necessary data for the model (data minimisation)."""
    return {k: v for k, v in context.items() if k not in ("staff_excluded",)}


def _enrich(contract: dict, context: dict) -> None:
    staff = {c["staff_id"]: c for c in context.get("staff_candidates", [])}
    for key in ("proposed_owner", "backup_owner"):
        o = contract.get(key)
        if o and o["staff_id"] in staff:
            o["name"] = staff[o["staff_id"]]["name"]
            o["role"] = staff[o["staff_id"]]["role"]
    res = {r["resource_id"]: r for r in context.get("resources", [])}
    for r in contract.get("resource_actions", []):
        if r["resource_id"] in res:
            src = res[r["resource_id"]]
            r.update({"name": src["name"], "category": src["category"], "kind": src["kind"],
                      "approval_required": bool(src["approval_required"]) and r["action"] == "reserve"})
    vols = {}
    for rt in context.get("ride_tasks", []):
        for c in rt.get("candidates", []):
            vols[c["volunteer_id"]] = c
        for t in contract.get("volunteer_tasks", []):
            if t["task_key"] == rt["task_key"]:
                t.setdefault("label", rt["label"])
                t.setdefault("appointment_time", rt["appointment_time"])
                t.setdefault("location", rt.get("location", ""))
    for t in contract.get("volunteer_tasks", []):
        if t.get("volunteer_id") in vols:
            t["name"] = vols[t["volunteer_id"]]["name"]
