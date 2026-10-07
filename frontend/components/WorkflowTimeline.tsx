"use client";

import clsx from "clsx";
import type { AuditEvent, CaseDetail } from "@/types";
import { fmtTime } from "@/lib/format";
import { friendlyDetail, friendlyTitle } from "@/lib/friendly";
import { StepIcon } from "./ui";

type Kind = "done" | "current" | "warn" | "error" | "blocked" | "paused";
interface Step {
  id: string;
  kind: Kind;
  label: string;
  detail?: string | null;
  time?: string;
  actor?: string;
}

function kindFor(e: AuditEvent): Kind | null {
  // Returns null for low-level events pastors don't need to see.
  switch (e.event_type) {
    case "run.started":
    case "context.gathered":
    case "replan.started":
    case "run.resumed":
    case "monitor.started":
    case "tool.retry":
    case "tool.restored":
    case "reviewer.feedback":
    case "state.changed": {
      const to = String(e.metadata?.to || "");
      if (to === "MONITORING" || to === "RESOLVED" || to === "ESCALATED") return "done";
      return null;
    }
    case "duplicate.suspected":
    case "prompt_injection.neutralized":
    case "tool.conflict":
    case "tool.outage_injected":
    case "volunteer.cancelled":
    case "resource.unavailable":
    case "calendar.conflict":
    case "plan.invalidated":
    case "replacement.none":
    case "case.error":
      return "warn";
    case "tool.error":
      return "error";
    case "tool.blocked":
    case "escalation.created":
      return "blocked";
    case "safety_check":
      return e.status === "warn" ? "blocked" : "done";
    case "approval.requested":
      return "paused";
    default:
      return "done";
  }
}

/** Turn the audit stream into a plain-language story of the work (no jargon, no tool names). */
function toSteps(events: AuditEvent[]): Step[] {
  const out: Step[] = [];
  for (const e of events) {
    if (e.event_type === "verifier.result") {
      const s = e.output_summary || "";
      const kind = s.startsWith("PASS") ? "done" : "warn";
      out.push({ id: String(e.event_id), kind, label: friendlyTitle(e), detail: friendlyDetail(e), time: e.timestamp });
      continue;
    }
    const kind = kindFor(e);
    if (!kind) continue;
    out.push({ id: String(e.event_id), kind, label: friendlyTitle(e), detail: friendlyDetail(e), time: e.timestamp });
  }
  return out;
}

export default function WorkflowTimeline({ c }: { c: CaseDetail }) {
  const steps = toSteps(c.audit);
  // Only the latest "awaiting approval" step is live; earlier ones are history.
  const lastPause = steps.map((s) => s.kind).lastIndexOf("paused");
  steps.forEach((s, i) => {
    if (s.kind === "paused" && (i !== lastPause || c.status !== "AWAITING_APPROVAL")) s.kind = "done";
  });
  return (
    <ol className="relative space-y-0.5">
      {steps.map((s, i) => (
        <li key={s.id} className={clsx("slide-in relative flex gap-3 pb-2", i === steps.length - 1 && !c.is_running && "pb-0")}>
          {(i < steps.length - 1 || c.is_running) && <span className="absolute left-[7.5px] top-5 h-full w-px bg-slate-200" />}
          <div className="relative z-10 mt-0.5 bg-white">
            <StepIcon kind={s.kind} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <div className={clsx("text-[13px] font-medium",
                s.kind === "paused" ? "text-amber-800" : s.kind === "blocked" ? "text-rose-800" : "text-slate-800")}>
                {s.label}
              </div>
              <span className="shrink-0 font-mono text-[10px] text-slate-400">
                {fmtTime(s.time)}
              </span>
            </div>
            {s.detail && <div className="line-clamp-2 text-[11.5px] leading-snug text-slate-500">{s.detail}</div>}
          </div>
        </li>
      ))}
      {c.is_running && (
        <li className="relative flex gap-3">
          <div className="relative z-10 mt-0.5 bg-white">
            <StepIcon kind="current" />
          </div>
          <div className="text-[13px] font-medium text-brand-700">{c.current_step || "Working…"}</div>
        </li>
      )}
    </ol>
  );
}
