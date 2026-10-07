# CareFlow architecture

## Pattern: single orchestrator + separate verifier

A single orchestrator owns the case objective and state. Narrow tool adapters do the I/O. A verifier independently checks every plan against **fresh** database state. We chose this over a multi-agent swarm because it is easier to reason about, audit, demo and guard. There is exactly one place where state changes, and every consequential action passes one approval gate.

```
                  ┌───────────────────────── Next.js review console ─────────────────────────┐
                  │ Dashboard · New request · Case detail (plan, approval, changes, audit,   │
                  │ live workflow timeline, latency/cost) · Audit log · Evaluations · Policy │
                  └───────────────────────────────┬──────────────────────────────────────────┘
                                                  │ REST (polling while the agent runs)
┌─────────────────────────────────────────────────▼──────────────────────────────────────────────┐
│ FastAPI (backend/main.py, api/routes.py)                                                         │
│                                                                                                  │
│  agent/orchestrator.py ── explicit state machine (agent/state_machine.py)                        │
│     │  _flow_initial: normalize → safety gate → gather context → plan/verify loop → await approval│
│     │  submit_review: approvals + tokens → re-plan (feedback) OR pre-execution verify → execute   │
│     │  events.py: volunteer_cancelled / resource_unavailable / staff_calendar_conflict /          │
│     │             tool_outage → invalidate → minimal-change re-plan → verify → approval/escalate  │
│     │  _flow_monitor: re-check executed commitments with tools                                     │
│     ├─ agent/normalizer.py   (LLM or deterministic; fixed vocabulary validation)                  │
│     ├─ agent/policies.py     (deterministic: safety gate, restrictions, risk rules)               │
│     ├─ agent/context.py      (calls read-only tools)                                               │
│     ├─ agent/planner.py → llm/provider.py (Mock | OpenAI-compatible + fallback) → plan JSON       │
│     ├─ agent/actions.py      (plan → Actions, deterministic risk classification, carry-over)      │
│     └─ agent/verifier.py     (PASS / REPLAN / ESCALATE with machine-readable feedback)             │
│                                                                                                  │
│  tools/base.py  registry: typed pydantic I/O · allowed actors · approval-token check ·            │
│                 fault injection · 1 retry · latency · audit event per call                         │
│  tools/{staff,calendar,resources,volunteers,tasks,messaging,cases}.py                              │
│                                                                                                  │
│  SQLite: care_cases · staff · volunteers · resources · calendar_blocks · care_plans · actions ·   │
│          approvals · tasks · reservations · messages · audit_events (append-only triggers) ·     │
│          tool_faults · counters                                                                    │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## State machine

```
NEW → NORMALIZED → SAFETY_CHECKED → CONTEXT_GATHERED → PLAN_PROPOSED → VERIFIED → AWAITING_APPROVAL
      → APPROVED → EXECUTING → MONITORING → RESOLVED

SAFETY_CHECKED → ESCALATED            (safety gate / duplicate)
VERIFIED → PLAN_PROPOSED              (verifier REPLAN, bounded by max_replans=2)
VERIFIED → ESCALATED                  (verifier ESCALATE: unresolved need after an event, no POC, ...)
AWAITING_APPROVAL → PLAN_PROPOSED     (reviewer rejects owner / reassigns / requests re-plan, or event)
APPROVED → PLAN_PROPOSED              (pre-execution verification finds drift → approvals voided)
MONITORING → PLAN_PROPOSED            (invalidating event)
* → ERROR (recoverable) → resume at SAFETY_CHECKED | APPROVED | MONITORING
```

Transitions are enforced in `state_machine.transition()`. An illegal transition raises an error and writes a `state.transition_blocked` audit event.

## Key data flows

**Approval tokens.** `submit_review` creates an `Approval` row and stores `sha256(HMAC(secret, approval_id:action_id:plan_id))`. The executor re-mints the token server-side and passes it to the tool. `verify_approval` checks that the hash matches, the action and plan match, the plan is not superseded, the decision is human for `approval_required` actions, and irreversible tokens are single-use.

**Minimal-change re-planning.** On an invalidating event, the previous plan contract becomes `locked`, and the invalidated keys (e.g. `volunteer_task:ride-1`) are passed to the planner. Only those items are re-solved. Actions whose key is unchanged are *carried over* with their execution status, so the reviewer approves only what is new.

**Pre-execution verification.** Approval and execution are separated in time. Right before executing, the verifier re-reads calendars, volunteers and resources. If anything changed (eval T14), approvals are voided and a new plan version is proposed.

**Tool failures.** Each tool call gets at most one retry (`policies.json → tools.max_retries`), and every attempt is audited. A persistent failure puts the case into `ERROR` with a resume point, and the UI shows a retry button. Nothing continues silently.
