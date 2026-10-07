# CareFlow — How the Application Actually Works

A detailed, code-accurate walkthrough of the CareFlow prototype: what happens to a care
request from intake to resolution, **where the LLM is used**, and **where deterministic
code makes the decisions**. Intended as a briefing document for explaining the system to judges.

Rule of thumb for the whole project:

> **The LLM proposes. Deterministic code disposes.**
> The model reads text, ranks pre-filtered options, drafts plans and explains rationale.
> Policy code decides safety, eligibility, risk, permissions, state transitions and validity.
> Nothing the model says can move money, send a message, book a calendar, or change a state
> on its own.

---

## 1. Big picture

```
Request text + intake form
        │
        ▼
┌──────────────────────────── ORCHESTRATOR (backend/agent/orchestrator.py) ────────────────────────────┐
│  Single agent loop. Owns the case objective. NEVER lets the model choose what happens next.         │
│                                                                                                      │
│  1. NORMALIZE ──► LLM call #1 (or deterministic extractor in mock mode)                              │
│  2. SAFETY GATE ──► deterministic policy; can HALT everything here                                   │
│  3. GATHER CONTEXT ──► read-only tools: staff, calendar, resources, volunteers                       │
│  4. PLAN ──► LLM call #2 (or deterministic reasoner) ──► structured plan JSON                        │
│  5. VERIFY ──► deterministic checks on FRESH database state (+ optional LLM review, call #3)         │
│       ├── PASS ──► stop and wait for a HUMAN                                                         │
│       ├── REPLAN ──► machine-readable feedback ──► back to step 4 (max 2 re-plans)                    │
│       └── ESCALATE ──► stop automation, hand the exact problem to a human                            │
│  6. HUMAN REVIEW ──► approve all / approve selected / reject / reassign / re-plan                    │
│  7. PRE-EXECUTION RE-VERIFY ──► deterministic; catches anything that changed since approval           │
│  8. EXECUTE ──► only approved actions, each with a server-checked approval token                    │
│  9. MONITOR ──► re-check commitments with tools; events trigger minimal-change re-plans              │
│ 10. RESOLVE or ESCALATE                                                                              │
│                                                                                                      │
│  Every step writes to an append-only audit log. Every state change goes through the state machine.   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The three LLM call sites are the only places model output enters the system, and each one
is fenced: fixed-vocabulary validation after normalization, JSON-schema validation after
planning, and a strictly-strengthening review after verification.

---

## 2. Stage-by-stage flow

### Stage 0 — Intake: `POST /cases` → `create_case()`

File: `backend/agent/orchestrator.py` (`create_case`, ~line 246).

- A case row (`CF-XXXX`) is created. The **original request text is stored verbatim** and never rewritten.
- Structured intake-form fields (preferred contact, appointment dates/times, consent flags) are stored separately from the free text.
- **Duplicate detection (deterministic):** token-set similarity ≥ 0.8 against existing cases sets `duplicate_of`. A duplicate is later escalated for human merge instead of being worked twice.
- Status: `NEW`. Nothing else happens until someone clicks **Run CareFlow** (`POST /cases/{id}/run`).

### Stage 1 — Normalize: `NEW → NORMALIZED`

Files: `backend/agent/normalizer.py`, `backend/llm/provider.py`.

**LLM call #1 — `provider.normalize(request_text, intake_form)`.**

- The rendered prompt (`agent/prompts.py`, `NORMALIZER_PROMPT`, version `careflow-prompts-v3`)
  wraps the request in `<care_request>` tags marked as **untrusted data** and demands JSON only:
  campus, needs (from a fixed list of 10), timeframe, `urgent_same_day`, trip count, contact
  method, preferred staff name, constraints, missing facts, escalation categories.
- In **mock mode** (`USE_MOCK_LLM=true`, the demo default), no network call happens:
  `MockLLMProvider.normalize` runs `deterministic_extract()` (regex/keyword extraction over the
  same fixed vocabulary) but still renders the real prompts to estimate token cost.
- With a real provider (`OpenAICompatibleProvider`), the call is `POST {LLM_BASE_URL}/chat/completions`
  with `temperature=0` and JSON-object response format. Any error, timeout, or invalid JSON
  falls back to the deterministic extractor, and the reason is recorded in the run metrics
  (`FallbackProvider`).

**Deterministic merge — `validate_normalized()` + `finalize()`.** Model output is *not* trusted:

- Campus must be one of the configured campuses; an explicit text match in the request wins.
- Needs the model invents are dropped unless they are in the 10 known need types.
- Model escalation flags can only be **added**; they can never clear a deterministic safety match.
- `finalize()` derives routing fields in code: `primary_request_type` (`urgent_callback` vs
  `pastoral_conversation` vs `financial_referral` vs `resource_only`), experience tags, ride
  windows computed from intake-form appointment times (pickup 45 min before, 2 h after, per
  `data/policies.json`), and known vs missing facts. Missing information (no campus, no ride
  times) is **flagged, never invented**.

Output: `structured_needs` on the case. Audit event: `request.normalized`.

### Stage 2 — Safety gate: `NORMALIZED → SAFETY_CHECKED` (or `ESCALATED`)

Files: `backend/agent/policies.py` (`safety_gate`), `data/policies.json`.

**Fully deterministic. The LLM is not consulted** (its flags are only additive input).

- Keyword/phrase matching against escalation categories: self-harm/crisis, abuse, medical
  emergency, imminent danger, minors. A match → decision `ESCALATE`.
- Sensitive-routing flags (financial assistance, counseling advice, prompt injection) steer
  routing but do not stop the workflow; prompt-injection text additionally writes a
  `prompt_injection.neutralized` audit event and changes nothing about permissions.
- On `ESCALATE`, normal orchestration **stops before any scheduling, resource, volunteer, or
  messaging tool runs**. No plan is generated, no message is drafted. The case shows the
  configured human escalation protocol (labeled synthetic — it is a placeholder, not
  Flatirons' real crisis protocol).

Audit event: `safety_check` with actor `POLICY`. This is the moment judges should understand:
**the most consequential decision in the system is made by plain code, not by the model.**

### Stage 3 — Gather context: `SAFETY_CHECKED → CONTEXT_GATHERED`

File: `backend/agent/context.py` (`gather_context`).

**No LLM involved.** The orchestrator calls read-only tools through the permissioned registry,
collecting exactly what a plan needs and nothing else:

| Tool call | What it returns | Policy applied inside the tool |
|---|---|---|
| `staff.search` | Eligible staff + per-person evidence + excluded list | Active, campus match, approved request type; urgent → current weekly POC then backup POC |
| `calendar.read` | Free/busy only (no event contents) for those staff, in a computed planning window, avoiding ride windows | Working hours, 30-min buffers around rides |
| `resource.search` | Approved catalog items for the needed categories, each annotated available / restrictions-satisfied / reserve-permitted | Campus-or-All, status, quantity, restriction codes |
| `volunteer.search` (per ride) | Eligible drivers + excluded list | Role, campus, training flags, availability, blackouts, weekend-only and max-trips constraints |

Key detail: the planner never sees the full roster, full calendars, or excluded staff internals
beyond reasons — the model receives a **minimized view** (`planner.py::_model_view`) of candidates
that already passed the policy filters. It can rank them; it cannot widen the pool.

### Stage 4 — Plan: `CONTEXT_GATHERED → PLAN_PROPOSED`

Files: `backend/agent/planner.py`, `backend/agent/mock_reasoner.py`, `backend/llm/provider.py`.

**LLM call #2 — `provider.generate_plan(case, context, feedback, prior)`.**

- The planner prompt restates the hard rules: IDs only from tool results, appointments only from
  free slots, honor reviewer/verifier feedback and locked items, no pastoral/financial/clinical
  judgment, unresolved items instead of invented facts.
- Output must validate against the `PlanContract` schema (`backend/schemas/plan.py`): objective,
  facts, owner/backup with evidence, appointment options, resource actions, volunteer tasks,
  internal tasks, message draft, unresolved items, forbidden items, rationale.
- **Malformed model JSON does not fail the case:** the planner falls back to the deterministic
  reasoner and records why.
- **Display names are re-attached from tool data** (`_enrich`); model-provided names are discarded,
  so the model cannot smuggle in a plausible-sounding person.
- In mock mode, `deterministic_plan()` does the ranking/selection job with plain code over the
  same contract, including minimal-change logic: items in `prior.locked` that are still valid are
  kept, only invalidated items are re-solved.

The contract is stored on a `CarePlan` row (versioned: v1, v2, …), plus a `_evidence_ids`
provenance snapshot of exactly which IDs the tools returned when this plan was made.

### Stage 5 — Verify: `PLAN_PROPOSED → VERIFIED`

File: `backend/agent/verifier.py` (`verify_plan`).

**Deterministic first, model second (and the model can only make the result stricter).**

The verifier re-reads the **live database**, not the planner's snapshot, and checks:

0. Crisis flags must never have reached planning (defense in depth).
1. **Provenance:** every staff/volunteer/resource ID came from a tool result (or locked prior plan) — fabricated IDs fail.
2. **Fresh eligibility:** owner still active, right campus/request type (or POC rule for urgent); volunteers re-checked against training, availability, blackouts.
3. **Fresh calendar conflicts + no double booking:** catches availability that went stale.
4. **Resource availability + restrictions + forbidden categories** (financial/student-family can never be reserved).
5. **Content scan:** no counseling/diagnosis/financial-decision/spiritual-judgment language in the message draft or rationale; no ungrounded IDs in text; no volunteer names in the requester message.
6. **Approval gates:** every consequential action in the plan is classified `approval_required`; `message.send` is irreversible.
7. Unresolved items marked `escalate` flip the whole result to `ESCALATE`.

Result: `PASS` → wait for human. `REPLAN` → machine-readable feedback (`exclude_staff`,
`exclude_slots`, `exclude_volunteers`, `exclude_resources`) goes back to the planner, refreshing
only the affected context sources; bounded by `max_replans=2`. `ESCALATE` → stop with the exact
unresolved need.

**LLM call #3 (conditional):** only when deterministic checks already passed *and* a real
provider is configured, the model reviews the plan — and can only downgrade to `REPLAN`/`ESCALATE`.
In mock mode this call is a no-op that still accounts estimated tokens. **Pre-execution
re-verification always runs with `use_model=False`** — pure code, no model.

The UI shows every individual check (pass/fail) under each plan version.

### Stage 6 — Human review: `VERIFIED → AWAITING_APPROVAL → APPROVED` (or back to `PLAN_PROPOSED`)

Files: `backend/agent/orchestrator.py` (`submit_review`), `backend/agent/actions.py`.

**Deterministic risk classification** (`plan_action_specs`) turns the plan into concrete `Action`
rows *before* the human sees them:

- `approval_required` (default unchecked): owner assignment, calendar holds, volunteer
  assignments, approval-flagged resources, external messages.
- `safe` (pre-selected, still only run on submit): internal tasks, delegated no-approval reservations.
- `forbidden` (never executable): financial decisions, counseling, and the standing human-only list.

The reviewer can approve all, approve a subset (**partial approval**), reject items, reassign the
owner (**server-validated to be inside the eligible pool** — anything else is refused with an
error), leave feedback, or request a re-plan. Rejecting/reassigning the owner triggers a re-plan
with that feedback. Each approval mints an **HMAC token** (`approval_id:action_id:plan_id` under
`APPROVAL_SECRET`); only the token *hash* is stored.

### Stage 7 — Pre-execution check + execute: `APPROVED → EXECUTING → MONITORING`

File: `backend/agent/orchestrator.py` (`_flow_execute`, `_execute_action`).

1. **Pre-execution re-verification (deterministic, no model):** because approval and execution
   are separated in time, the verifier re-reads calendars, volunteers and resources. On drift,
   approvals are voided and a new plan version is proposed — this is how stale availability is
   caught even if the world changed *after* the human approved.
2. **Execution runs approved actions only, external message last.** Each write tool call carries
   the server-minted token and passes `verify_approval()` (`backend/tools/base.py`): correct
   token hash, matching action and non-superseded plan, human decision for consequential actions,
   single-use tokens for irreversible sends. Failures are classified: `conflict` (stale state →
   re-plan, no retry), `blocked` (policy → audited, no state change), `outage` (retry once, then
   recoverable `ERROR` with a resume point).
3. Side effects land in real tables the UI reads: `calendar_blocks` (holds), `tasks`,
   `reservations`, `messages` (demo outbox — nothing is actually sent).

### Stage 8 — Monitor, events, re-plan: `MONITORING → PLAN_PROPOSED → …`

Files: `backend/agent/events.py`, `backend/agent/orchestrator.py`
(`_replan_after_invalidation`, `_flow_monitor`).

**Every demo event mutates real backend state** — nothing is faked in the UI:

| Event | State mutation | Agent response |
|---|---|---|
| Volunteer cancelled | Blackout block on that volunteer for the ride window; live task cancelled; action marked `invalidated` | Refresh volunteers only, find replacement, Plan v2, verify, request approval **for the new driver only** (unchanged items carry over) |
| Resource unavailable | Item → `out_of_stock`, qty 0; live reservation released | Refresh resources, approved substitute or flagged gap |
| Staff calendar conflict | External busy block overlapping the slot; live hold released | Refresh calendar, new option, updated message needs approval |
| Tool outage (transient/persistent) | Fault switchboard (`tool_faults`) makes the tool fail | Retry once; transient succeeds, persistent → visible `ERROR` → restore → resume |
| Tasks completed | Open tasks → done; operational summary written | `MONITORING → RESOLVED` |

If no valid replacement exists (e.g. cancel the replacement driver too), the verifier returns
`ESCALATE` and the case names the exact unfilled ride, routed to the Care Coordinator —
**escalation, never silent failure.**

### Stage 9 — Close: `MONITORING → RESOLVED`

`operational_summary()` generates a closure summary from executed records only: owner, completed
vs cancelled tasks, held reservations, sent (demo-outbox) messages, plan versions. Pastoral notes
are explicitly *not* recorded — they remain with the Care team.

---

## 3. Where the LLM is used (complete list)

There are **exactly three** model call sites, all behind the `LLMProvider` interface
(`backend/llm/provider.py`):

| # | Call | Where invoked | What it does | Fencing around it |
|---|---|---|---|---|
| 1 | `normalize(request_text, intake_form)` | `_flow_initial` (orchestrator.py:304) | Extract operational fields into JSON | Fixed-vocabulary merge (`validate_normalized`); deterministic baseline always wins; model flags are additive-only |
| 2 | `generate_plan(case, context, feedback, prior)` | `_plan_cycle` via `planner.generate_plan` (orchestrator.py:401) | Rank eligible options, assemble plan JSON, write rationale | `PlanContract` schema validation with deterministic fallback; names re-attached from tool data; verifier decides validity afterward |
| 3 | `verify_plan(plan, context)` | `verifier.verify_plan` (verifier.py:239) | Second-opinion review of a plan that already passed deterministic checks | Runs only on deterministic PASS with a real provider; can only downgrade to REPLAN/ESCALATE; pre-execution check always skips it |

Provider modes:

- **Mock (default, `USE_MOCK_LLM=true`):** `MockLLMProvider` runs the deterministic extractor
  and reasoner. No network, fully reproducible. It still renders the real v3 prompts to produce
  the *estimated* token counts shown in the UI.
- **Real (`USE_MOCK_LLM=false` + `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`):** any
  OpenAI-compatible `/chat/completions` endpoint (e.g. Gloo AI Studio), `temperature=0`,
  JSON-object mode. Wrapped in `FallbackProvider`: any failure falls back to the deterministic
  path and records the reason in the run metrics.
- **Evals:** forced mock (`force_mock(True)`), isolated temp database, zero pacing delay.

Cost/latency accounting: every provider result carries `usage` (tokens, latency, prompt version,
estimated-or-real). The orchestrator accumulates it per run; the UI's Latency & cost card shows
agent compute time (wall time minus the visible demo pacing delay), tool/model call counts, and
estimated USD.

---

## 4. Where deterministic code decides (complete list)

| Decision | File | Why it matters for the judging criteria |
|---|---|---|
| Safety escalation | `agent/policies.py::safety_gate`, `data/policies.json` | Guardrail recall: model can add flags, never remove them |
| Duplicate detection | `orchestrator.py::create_case` | No duplicate external actions (T17) |
| Staff eligibility + POC routing | `tools/staff.py`, `agent/policies.py::poc_ids` | Routing validity: model ranks, never qualifies |
| Calendar free/busy + conflict refusal | `tools/calendar.py::find_conflicts`, `calendar.hold` | No double booking, stale availability caught |
| Resource restrictions + reserve permissions | `agent/policies.py`, `tools/resources.py` | Resource grounding: waiver/restriction items never allocated |
| Volunteer eligibility | `tools/volunteers.py::eligibility` | Training, campus, availability, constraints enforced |
| Risk classification (safe / approval / forbidden) | `agent/actions.py::plan_action_specs` | Human-approval model; model never sets risk |
| Approval tokens + actor permissions + retry + audit-per-call | `tools/base.py::call_tool`, `verify_approval` | Unsafe-action rate 0: `message.send` blocked without human token (T13/T15) |
| State transitions | `agent/state_machine.py::transition` + `ALLOWED` | Illegal transitions raise + audit `state.transition_blocked` |
| Plan validity (7 check groups on fresh state) | `agent/verifier.py::verify_plan` | Unsupported-claim rate 0: fabricated IDs rejected |
| Minimal-change re-planning + carry-over | `orchestrator.py::_replan_after_invalidation`, `actions.py::persist_actions` | Recovery rate: only invalidated items re-solved and re-approved |
| Pre-execution re-verification | `orchestrator.py::_flow_execute` | Approvals voided on drift instead of executing stale plans |
| Event state mutations | `agent/events.py::inject_event` | Demo edge cases are real state changes, not UI theater |
| Append-only audit | `audit/log.py` + SQLite triggers in `db/database.py` | UPDATE/DELETE on `audit_events` is rejected by the database |
| Demo clock | `agent/clock.py` (`DEMO_NOW`) | Reproducible schedules, IDs (live case is CF-1042), eval results |
| Prompt-injection handling | System prompt + `safety_gate` routing flags + code-enforced permissions | Injected instructions treated as data; permissions unchanged |

---

## 5. Worked example: the primary demo (CF-1042)

A typical deterministic run of the surgery-recovery request:

1. **Intake** → `CF-1042` created, text preserved.
2. **Normalize** → campus Lafayette, needs `pastoral_conversation + transportation + recovery_resources`, timeframe this week, 2 intake-form appointments.
3. **Safety gate** → `PASS`, no routing flags.
4. **Context** → `staff.search`: 3 eligible of 16 considered (Denver's wide-open STF-004 excluded
   by campus rule); `calendar.read`: 29 free slots across 3 calendars; `resource.search`: 6 catalog
   items; `volunteer.search` ×2: 2 eligible drivers for ride 1, 1 for ride 2.
5. **Plan v1** → owner Jordan Lee (STF-001, Care Pastor, Lafayette; experience
   `medical_recovery, hospital_care`; availability verified), backup Maya Okonkwo, 2 appointment
   options, drivers VOL-014 + VOL-009, recovery packet RES-001 (safe) + meal train RES-002
   (approval), draft message. **Verifier: PASS (11 checks).**
6. **Review** → 7 consequential + 2 safe actions awaiting approval. Human approves → holds,
   tasks, reservations, and the demo-outbox message are created.
7. **Event: VOL-014 cancels** → blackout written, task cancelled, v1 invalidated → volunteers
   refreshed → replacement VOL-021 → **Plan v2, verifier PASS, 1 new approval required**.
8. **Event: VOL-021 cancels** → no eligible driver → **ESCALATED** with the exact unfilled ride
   (Thu Oct 8, 9:45 AM pickup) routed to the Care Coordinator.

Second and third demo cases: CF-1040 (urgent same-day → weekly POC Marcus Bell by policy rule,
not model judgment) and CF-1041 (safety gate matches → automation stops before any tool runs).

---

## 6. One-slide version (for the pitch)

- **User:** Care Ministry coordinator drowning in coordination logistics.
- **Agent, not chatbot:** owns a case objective through tools, plans, verification, approvals,
  execution, monitoring and re-planning. No chat box anywhere.
- **Bounded autonomy:** the model handles information gathering, ranking, drafting and
  explaining; code handles safety, eligibility, permissions, money-adjacent decisions and state.
- **Proof it works:** 26/26 scenario evals, 100% routing validity, 100% guardrail recall,
  0% unsupported claims, 0 unsafe actions executed, 100% recovery — plus a live volunteer
  cancellation handled on stage and an append-only audit log of everything.
- **Honest limits:** all data synthetic; only the locality/experience/POC routing concepts are
  practitioner-validated; the crisis policy is a placeholder, messaging is a demo outbox, and
  there is no auth yet.
