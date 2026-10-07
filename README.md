# CareFlow

**A human-in-the-loop pastoral care coordination agent.**
Gloo AI Hackathon 2026 · Agents of Flourishing track · proposed Flatirons Community Church pilot.

CareFlow takes on the *administrative logistics* around a care request: routing, scheduling, volunteer and resource coordination, follow-up and exception handling. It deliberately does **not** replace pastoral judgment. It never counsels, diagnoses, interprets anyone's spiritual state, decides financial assistance, or contacts a person in crisis on its own.

> **All demo data is synthetic.** People, cases, schedules, volunteers and resources are invented. The safety/escalation policy is a placeholder, **not** Flatirons' real crisis protocol. Flatirons-specific production workflow still requires further validation with the Care team.

---

## Who it is for

The target user is a **Care Ministry coordinator or campus pastoral-care administrator**. This is the person who moves an incoming request to the right human owner and a workable support plan: reading requests, checking schedules, finding approved resources and volunteers, drafting follow-ups, and recovering when plans change.

### What is validated vs. assumed

Practitioner feedback from Flatirons (Associate Campus Pastor, Denver campus) validated these points, and they are modeled in the routing policy:

- Incoming pastoral/counseling requests are routed to the staff or services that best address the need.
- Pastors are assigned based on **locality** (being more local) or **relevant experience** for the circumstances.
- One pastor is assigned each week as **Pastor on Call (POC)**. If someone needs a call right away, that week's POC reaches out.
- A POC may receive roughly **5–20 requests in a week**.

Everything else, including resource inventory, volunteer systems, approval rules, escalation categories and messaging permissions, is a synthetic assumption that needs validation.

## Why it is an agent, not a chatbot

There is no chat box. Given a case objective, CareFlow:

1. normalizes the request into structured operational fields;
2. runs a **deterministic safety gate** that can halt everything;
3. calls tools: `staff.search`, `calendar.read`, `resource.search`, `volunteer.search`;
4. builds a structured care logistics plan;
5. runs a **separate verifier** against fresh state, and re-plans or escalates on failure;
6. stops for **human approval**, which can be full or partial, with reject, reassign, feedback or re-plan;
7. executes **only approved actions**, using server-checked approval tokens;
8. **monitors** commitments; when a volunteer cancels, a resource disappears or a calendar changes, it **re-plans the minimal set of affected items** and asks for new approval only for what changed;
9. **escalates the exact unresolved need** when no valid option exists;
10. writes every step to an **append-only audit log**, with latency and cost.

## Architecture (one orchestrator + verifier)

```
Next.js review console ──REST──► FastAPI
                                  ├─ Orchestrator (explicit state machine, retries, background runs)
                                  │    ├─ Normalizer      (LLM or deterministic; fixed vocabulary)
                                  │    ├─ Safety gate     (deterministic policy - can halt)
                                  │    ├─ Planner         (LLM or deterministic reasoner → plan JSON)
                                  │    └─ Verifier        (deterministic checks on FRESH state + optional model review)
                                  ├─ Tool registry (typed I/O, permissions, approval tokens, fault injection, audit)
                                  │    staff · calendar · resources · volunteers · tasks · messaging · cases · audit
                                  ├─ Policy store (data/policies.json)
                                  └─ SQLite (cases, plans, actions, approvals, tasks, holds, reservations,
                                             messages, append-only audit_events with DB triggers)
```

See [docs/architecture.md](docs/architecture.md) and [docs/agent-build-doc.md](docs/agent-build-doc.md).

## Setup

Requirements: Python 3.11+ (tested on 3.14) and Node 20+ (tested on 22).

```bash
cp .env.example .env            # optional; defaults run fully offline
./scripts/start_backend.sh      # terminal 1 → http://localhost:8000  (OpenAPI docs at /docs)
./scripts/start_frontend.sh     # terminal 2 → http://localhost:3000
```

On first start the backend creates `backend/careflow.db` and seeds it. To reset to the deterministic starting state at any time, use any of these:

```bash
backend/.venv/bin/python scripts/seed_demo.py     # or the "Reset demo data" button, or POST /demo/reset
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `USE_MOCK_LLM` | `true` | Deterministic reasoner, no network. Set `false` to use a real model. |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | – | Any OpenAI-compatible `/chat/completions` endpoint (e.g. Gloo AI Studio). Falls back to the deterministic reasoner on any error. |
| `LLM_COST_INPUT_PER_1K`, `LLM_COST_OUTPUT_PER_1K` | 0.00015 / 0.0006 | Used for the cost estimate. |
| `DEMO_STEP_DELAY_MS` | `450` | Visible pacing between agent steps, so the audience can watch. Real state changes at every step. |
| `DEMO_NOW` | `2026-10-06T09:00:00` | Fixed demo clock (a Tuesday) so schedules are reproducible. |
| `APPROVAL_SECRET` | demo value | HMAC secret for approval tokens. |
| `DATABASE_URL` | `backend/careflow.db` | SQLite URL. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → API. |

## Evaluations

```bash
./scripts/run_evals.sh          # or the "Run evaluation suite" button on the Evaluations screen
```

The suite runs 26 scenarios (T01–T26) end-to-end in an isolated temporary database and writes `evals/results.json` and [docs/eval-results.md](docs/eval-results.md). Current result: **26/26 pass**. Routing validity is 100%, guardrail recall 100%, the unsupported-claim rate is 0%, 0 unsafe actions were executed, and the recovery rate is 100%. Planning compute is in milliseconds in deterministic mode.

## Demo script (3–5 minutes)

Start from a fresh reset (**Reset demo data**). Duplicate detection will flag the surgery request if it was already submitted in a rehearsal.

1. **Dashboard.** Show the queue, the status counts, and the Pastor-on-Call card (policy).
2. **New care request → "Lafayette surgery recovery (primary demo)" → Create case** (it becomes **CF-1042**).
3. Click **Run CareFlow** and watch the timeline: normalized → safety check passed → `staff.search` (3 eligible) → `calendar.read` → `resource.search` → `volunteer.search` ×2 → Plan v1 → Verifier PASS → awaiting approval.
4. **Review.** Show the owner card with campus, request type, availability and experience evidence, the two appointment options, the two driver assignments, the recovery packet (safe), the meal train (needs approval), the draft message (irreversible, gated), and the **Forbidden** column.
5. **Partial approval.** Check a few items and **Approve selected**, or click **Approve all permitted**. Actions execute; open **Executed changes** to see holds, tasks, reservations and the demo-outbox message.
6. **Simulate event → Volunteer cancelled: VOL-014.** CareFlow invalidates v1, calls `volunteer.search`, finds replacement **VOL-021**, generates **Plan v2**, verifies it, and requests approval **only for the new driver**.
7. Approve, then **Simulate event → Volunteer cancelled: VOL-021**. No eligible driver remains, so the case is **ESCALATED** with the exact unfilled ride, routed to the Care Coordinator. It does not fail silently.
8. Open the **Audit log** tab (or the global Audit log) and the **Latency & cost** card.
9. Open **Evaluations**.

Additional live edge cases: **CF-1040** (urgent same-day request routed to the weekly POC by policy); **CF-1041** (the safety gate stops automation); the *Prompt-injection* preset, whose injected instruction is flagged and changes nothing because `message.send` stays blocked; and **Simulate event → Tool outage (persistent)** on a monitoring case, which retries once, enters ERROR visibly, and recovers after **Restore tools → Retry**.

## Safety and guardrails

- **Deterministic safety gate** (self-harm/crisis, abuse, medical emergency, imminent danger, minors). It runs before planning, and the model can only *add* flags. When it matches, automation stops and the case shows the configured human escalation protocol (labeled synthetic).
- **Eligibility is code, not model judgment.** `staff.search` returns only active, campus-matched, request-type-approved staff, or the POC/backup POC for urgent requests. The planner can only rank those candidates.
- **No fabricated entities.** Every staff, volunteer and resource ID must come from a tool result. The verifier rejects anything else, and the evals measure a 0% unsupported-claim rate.
- **Server-side approval tokens.** Write tools need an HMAC token tied to an approval record. `message.send` is irreversible, needs a single-use **human** approval, and is blocked for crisis cases.
- **Forbidden actions** (financial decisions, counseling, diagnosis, moving money, autonomous crisis contact) are not executable. Financial categories can never be reserved.
- **Prompt-injection resistance.** Request text is wrapped as untrusted data. Instruction-like text is flagged, and permissions are enforced in code regardless.
- **Append-only audit.** SQLite triggers abort any UPDATE/DELETE on `audit_events`.
- **Data minimization.** Requester messages never include volunteer names, and calendars expose free/busy only.

## Known limitations

- Flatirons' real intake system, calendars, rosters, resource systems, approval rules and crisis protocol are **not validated**. Everything except the practitioner-validated routing concepts above is synthetic.
- Messaging is a demo outbox; nothing is actually sent. Calendar and roster adapters are mocks.
- There is no authentication or role-based access (reviewers type their name). Production needs church SSO and per-role permissions.
- The safety gate is keyword-based and intentionally conservative. A production system needs a validated protocol and clinical review.
- The deterministic reasoner is used in the demo and the evals. Real-model behavior depends on the configured provider and should be re-evaluated with the same suite.
- Single-process background threads and SQLite are fine for a demo, not for production scale.

## Repository layout

```
backend/   FastAPI app: agent/ (orchestrator, planner, verifier, policies, state machine, events),
           tools/ (typed, permissioned adapters), llm/ (provider interface), models/, schemas/, db/, audit/, api/
frontend/  Next.js + Tailwind review console
data/      synthetic staff, volunteers, resources, calendar, cases, policies.json
evals/     cases.json, run_evals.py, results.json
scripts/   start_backend.sh, start_frontend.sh, seed_demo.py, run_evals.sh
docs/      architecture.md, agent-build-doc.md, eval-results.md
```
