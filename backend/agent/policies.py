"""Deterministic policy engine.

Everything in this module is plain code driven by data/policies.json. The LLM
is never consulted for: safety escalation, eligibility, approval requirements,
resource restrictions or permissions.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from config import DATA_DIR


@lru_cache(maxsize=1)
def load_policies() -> dict[str, Any]:
    with open(DATA_DIR / "policies.json") as f:
        return json.load(f)


def P() -> dict[str, Any]:
    return load_policies()


def _match_terms(text: str, terms: list[str]) -> list[str]:
    """Word-boundary-at-start phrase matching (case-insensitive)."""
    low = text.lower().replace("\u2019", "'")
    hits = []
    for term in terms:
        if re.search(r"(?<![a-z])" + re.escape(term.lower()), low):
            hits.append(term)
    return hits


# ---------------------------------------------------------------------------
# Safety / sensitivity gate
# ---------------------------------------------------------------------------

def safety_gate(text: str, model_flags: list[str] | None = None) -> dict[str, Any]:
    """Return {"decision": PASS|ESCALATE, "categories": [...], "matches": {...}, "routing_flags": [...]}.

    `model_flags` (optional, from the LLM normalizer) may only ADD escalation
    categories - they can never clear a deterministic match.
    """
    gate = P()["safety_gate"]
    matches: dict[str, list[str]] = {}
    for cat, terms in gate["escalation_categories"].items():
        hits = _match_terms(text, terms)
        if hits:
            matches[cat] = hits
    for flag in model_flags or []:
        if flag in gate["escalation_categories"] and flag not in matches:
            matches[flag] = ["(model-assisted classification)"]

    routing: dict[str, list[str]] = {}
    for cat, terms in gate["sensitive_routing"].items():
        hits = _match_terms(text, terms)
        if hits:
            routing[cat] = hits

    decision = "ESCALATE" if matches else "PASS"
    return {
        "decision": decision,
        "categories": sorted(matches.keys()),
        "matches": matches,
        "routing_flags": sorted(routing.keys()),
        "routing_matches": routing,
        "policy_version": P()["version"],
        "protocol_label": gate["protocol_label"] if matches else None,
    }


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def experience_tags_for(text: str) -> list[str]:
    tags: list[str] = []
    mapping = P()["routing"]["need_to_experience_tags"]
    low = text.lower()
    for keyword, t in mapping.items():
        if keyword in low:
            for tag in t:
                if tag not in tags:
                    tags.append(tag)
    return tags


def categories_for_needs(needs: list[str]) -> list[str]:
    mapping = P()["resource_policy"]["need_to_categories"]
    cats: list[str] = []
    for n in needs:
        for c in mapping.get(n, []):
            if c not in cats:
                cats.append(c)
    return cats


def poc_ids() -> dict[str, str]:
    r = P()["routing"]
    return {
        "current": r["current_poc_staff_id"],
        "backup": r["backup_poc_staff_id"],
        "coordinator": r["care_coordinator_staff_id"],
        "benevolence": r["benevolence_staff_id"],
    }


# ---------------------------------------------------------------------------
# Resource restriction checks (deterministic)
# ---------------------------------------------------------------------------

def check_resource_restrictions(resource: dict[str, Any], case_flags: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (satisfied, unmet_reasons) for a resource's restriction codes."""
    unmet: list[str] = []
    consent = case_flags.get("consent_flags", {}) or {}
    referrals = case_flags.get("referrals", []) or []
    for code in resource.get("restrictions", []):
        if code == "human_decision_only":
            unmet.append("Decision reserved for humans (financial/sensitive) - CareFlow may only refer.")
        elif code == "coordinator_signoff":
            # Satisfied by requiring human approval on the action (enforced in risk policy).
            continue
        elif code.startswith("requires_consent:"):
            key = code.split(":", 1)[1]
            if not consent.get(key):
                unmet.append(f"Requires consent flag '{key}' which is not on file.")
        elif code.startswith("requires_referral:"):
            key = code.split(":", 1)[1]
            if key not in referrals:
                unmet.append(f"Requires a '{key}' referral which is not on file.")
        else:
            unmet.append(f"Unknown restriction '{code}' - treated as unmet.")
    return (not unmet, unmet)


def resource_reserve_permission(resource: dict[str, Any]) -> tuple[bool, str]:
    rp = P()["resource_policy"]
    if resource["category"] in rp["never_reserve_categories"]:
        return False, f"Category '{resource['category']}' can never be reserved by CareFlow."
    if resource["category"] not in rp["delegated_reserve_categories"]:
        return False, f"Category '{resource['category']}' is not delegated to the agent."
    if not resource.get("reservable"):
        return False, "Item is not delegated for agent reservation."
    return True, "Delegated category"


# ---------------------------------------------------------------------------
# Forbidden content scanning (used by the verifier on any human-facing text)
# ---------------------------------------------------------------------------

FORBIDDEN_CONTENT_PATTERNS = {
    "counseling": [r"\byou should (leave|forgive|stay|pray more|confront)", r"\bmy advice\b", r"\bi (would )?(advise|recommend) (that )?you\b", r"\bthe right thing to do\b"],
    "spiritual_judgment": [r"\byour faith (is|seems)\b", r"\bgod (is punishing|wants you to)\b", r"\bspiritual(ly)? (weak|immature|strong)\b", r"\bsin(ful)?\b"],
    "diagnosis": [r"\byou (have|may have|probably have|are suffering from) (depression|anxiety|ptsd|an infection|a disorder)", r"\bdiagnos"],
    "financial_decision": [r"\b(approved|denied|eligible|ineligible) for (financial|benevolence|assistance)", r"\bwe will pay\b", r"\bwe('| wi)ll cover\b"],
}


def scan_forbidden_content(text: str) -> list[dict[str, str]]:
    low = text.lower()
    hits = []
    for cat, patterns in FORBIDDEN_CONTENT_PATTERNS.items():
        for p in patterns:
            m = re.search(p, low)
            if m:
                hits.append({"category": cat, "match": m.group(0)})
    return hits
