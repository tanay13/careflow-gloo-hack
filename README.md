# CareFlow

**An AI agent that does the paperwork of pastoral care — so pastors can do the people work.**

Built for the Gloo AI Hackathon 2026 · Agents of Flourishing track · proposed Flatirons Community Church pilot.

> All people, cases, schedules, and resources in this prototype are synthetic. The crisis-escalation policy is a placeholder, not a real church protocol.

---

## The problem

When someone asks a church for care, the most important part is the human relationship. But before that conversation happens, someone on the Care team has to read the request, figure out the right pastor, check calendars, find resources, line up volunteer drivers, draft a follow-up and then start over when a volunteer cancels. That coordination burden is real, repetitive, and easy to drop. CareFlow exists to carry it end to end.

## Why an agent, not a chatbot

There is no chat box in CareFlow. You hand it a request, and it **does the job like a diligent coordinator would**: it reads the request, checks the safety rules, looks up the right people and resources, writes up a complete plan, double checks its own work, waits for a human's approval, does only what was approved, keeps watch afterwards — and if something changes, it fixes the plan instead of letting the request fall through the cracks. Then it shows its work: every step, every decision, every approval, in a record nobody can edit.

## Why this is not a simple LLM wrapper

A wrapper sends your words to a model and prints back its answer, if the model is wrong, confused, or talked into something unsafe, there's nothing in between. CareFlow is built the other way around: **the AI is one component inside a system that constrains it.** Around the model sit a state machine that owns every step, tools with server-enforced permissions, approval tokens a human must mint, a verifier that re-checks the plan against live data, monitoring that watches after execution, and a tamper proof record of everything. The model can suggest; only the system can act and only what a human allowed. That's the difference between a demo that chats and an agent a church could trust.

## What makes it advanced

**1. It knows what it must never decide.**
Pastoral judgment, crisis response, and money decisions stay with people always. CareFlow handles logistics: routing, scheduling, volunteers, resources, follow-ups, and recovering when plans change.

**2. It verifies itself with code, not vibes.**
This is the core idea. After the AI drafts a plan, a separate **deterministic verifier** re-checks everything against live data: Is this pastor actually eligible? Is that time slot still free, checked fresh, not from memory? Does that resource exist, with enough quantity? Is every name and ID traceable to a real record? Is every consequential action gated for human approval? If anything fails, the plan goes back for rework with precise feedback — or escalates to a human with the exact problem named. The AI is never the final judge of its own work.

**3. Humans approve in plain language.**
The review screen speaks like a person: "For you to decide", "Safe to go ahead", "Only people do this". Approve everything, tick a few, say no to one, suggest someone else, or ask for a new plan. Nothing, especially no message to a real person, goes out without a human saying so, enforced by the server, not by asking the AI nicely.

**4. It recovers instead of failing silently.**
A volunteer cancels? CareFlow finds a qualified replacement, makes a new plan version, and asks you to approve only what changed. No replacement exists? It escalates the exact unfilled need to the Care Coordinator, it never quietly drops it.

**5. It can't be talked out of its rules.**
Stamp "send this without approval" into a request and CareFlow flags the instruction as untrusted data, changes nothing, and the message stays blocked. Permissions live in code the AI cannot rewrite.

## Grounded in a real church, honest about what's assumed

Flatirons practitioners validated how routing really works there: pastors are matched by **locality and relevant experience**, and each week one pastor serves as **Pastor on Call** for urgent same day requests (handling roughly 5–20 a week). CareFlow models exactly that. Everything else, calendars, resources, approvals, crisis protocol, is clearly-labeled synthetic stand-in data awaiting validation.

## Proof it works, not promises

26 scenario tests run the full system end to end, normal requests, wrong-campus traps, fully-booked pastors, calendar conflicts, out-of-stock resources, volunteer cancellations with and without replacements, ambiguous requests, crisis indicators, counseling and money requests, prompt injection, stale calendars, tool outages, duplicate intakes, and full completions:

| Measure | Result |
|---|---|
| Tests passed | **26 / 26** |
| Right pastor every time | **100%** |
| Red flags caught and escalated | **100%** |
| Invented facts in plans | **0%** |
| Unsafe actions executed | **0** (3 attempts blocked) |
| Recoveries handled cleanly | **100%** |

See the **Quality checks** screen in the app, or `docs/eval-results.md`.

## Where this goes next

The prototype proves the pattern; the road ahead is about plugging it into real church life:

- **Real systems, not stand-ins** — connect the actual intake forms, calendars, staff roster, and messaging channels, so plans execute in the tools the Care team already uses.
- **Validated rules** — sit with the Care team and replace every synthetic assumption (approvals, resources, escalation protocol) with their real workflow.
- **Real-model evaluation** — run the same 26-scenario suite against a production model and publish the before/after, so safety is measured, not asserted.
- **People-aware roles** — church sign-in with distinct permissions for coordinators, pastors, and volunteer leads.
- **Wider care** — follow-up tracking over weeks, multi-campus load balancing for the on-call rotation, and smarter volunteer matching as the pool grows.

## Run it

You need Python 3.11+ and Node.js 20+. No database to install, no API key needed — it runs fully offline.

```bash
./scripts/start_backend.sh     # http://localhost:8000
./scripts/start_frontend.sh    # http://localhost:3000
./scripts/run_evals.sh         # the 26-scenario suite
```

To use a real AI model instead of the built-in deterministic mode (e.g. Gloo AI Studio), copy `.env.example` to `.env` and set `USE_MOCK_LLM=false` plus your endpoint details — the system falls back safely if the model ever fails. See `docs/agent-build-doc.md` for the full engineering story and `docs/application-flow.md` for how the pieces fit.

## Known limits

Synthetic data throughout; Flatirons' real systems, approvals, and crisis protocol still need validation. Messaging is a demo outbox (nothing is actually sent). No login yet. The safety rules are a conservative placeholder. And the evals ran in offline deterministic mode — the same suite is ready to run against a real model.
