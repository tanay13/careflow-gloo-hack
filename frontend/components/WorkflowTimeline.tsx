"use client";

import clsx from "clsx";
import { Wrench } from "lucide-react";
import type { AuditEvent, CaseDetail } from "@/types";
import { fmtTime, ms } from "@/lib/format";
import { StepIcon } from "./ui";

type Kind = "done" | "current" | "warn" | "error" | "blocked" | "paused";
interface Step {
  id: string;
  kind: Kind;
  label: string;
  detail?: string | null;
  time?: string;
  tool?: boolean;
  latency?: number | null;
  actor?: string;
}

/** Turn the append-only audit stream into concise, user-facing workflow steps (no chain-of-thought). */
function toSteps(events: AuditEvent[]): Step[] {
  const out: Step[] = [];
  for (const e of events) {
    const base = { id: String(e.event_id), time: e.timestamp, actor: e.actor };
    const s = e.output_summary || "";
    switch (e.event_type) {
      case "case.created":
        out.push({ ...base, kind: "done", label: "Intake received", detail: "Original text preserved" });
        break;
      case "duplicate.suspected":
        out.push({ ...base, kind: "warn", label: "Possible duplicate detected", detail: s });
        break;
      case "request.normalized":
        out.push({ ...base, kind: "done", label: "Request normalized", detail: s });
        break;
      case "safety_check":
        out.push({ ...base, kind: e.status === "warn" ? "blocked" : "done",
          label: e.status === "warn" ? "Safety gate: ESCALATE" : "Safety check passed", detail: s });
        break;
      case "prompt_injection.neutralized":
        out.push({ ...base, kind: "warn", label: "Embedded instructions ignored", detail: s });
        break;
      case "tool.call":
        out.push({ ...base, kind: "done", label: e.tool_name || "tool", detail: s, tool: true, latency: e.latency_ms });
        break;
      case "tool.retry":
        out.push({ ...base, kind: "warn", label: `Retrying ${e.tool_name}`, detail: s });
        break;
      case "tool.error":
        out.push({ ...base, kind: "error", label: `${e.tool_name} failed`, detail: s, tool: true });
        break;
      case "tool.blocked":
        out.push({ ...base, kind: "blocked", label: `${e.tool_name || "tool"} blocked by server`, detail: s, tool: true });
        break;
      case "tool.conflict":
        out.push({ ...base, kind: "warn", label: `${e.tool_name}: conflict`, detail: s, tool: true });
        break;
      case "plan.generated":
        out.push({ ...base, kind: "done", label: `Plan v${e.plan_version} generated`, detail: s.replace(/^Plan v\d+ \(\w+\): /, "") });
        break;
      case "verifier.result":
        out.push({ ...base, kind: s.startsWith("PASS") ? "done" : "warn", label: `Verifier: ${s.split(" ")[0]}`, detail: s.replace(/^\w+ - /, "") });
        break;
      case "verifier.pre_execution":
        out.push({ ...base, kind: s.startsWith("PASS") ? "done" : "warn", label: `Pre-execution re-check: ${s.split(" ")[0]}`, detail: s.replace(/^\w+ - /, "") });
        break;
      case "replan.started":
        out.push({ ...base, kind: "done", label: "Re-plan started", detail: s });
        break;
      case "approval.requested":
        out.push({ ...base, kind: "paused", label: s.startsWith("New") ? "New approval required" : "Awaiting human approval", detail: s });
        break;
      case "plan.reviewed":
        out.push({ ...base, kind: "done", label: "Human review submitted", detail: s });
        break;
      case "reviewer.feedback":
        out.push({ ...base, kind: "done", label: "Reviewer feedback", detail: s });
        break;
      case "execution.completed":
        out.push({ ...base, kind: "done", label: "Approved actions executed", detail: s });
        break;
      case "volunteer.cancelled":
      case "resource.unavailable":
      case "calendar.conflict":
      case "tool.outage_injected":
        out.push({ ...base, kind: "warn", label: s.split(" (")[0].split(" - ")[0], detail: s });
        break;
      case "tool.restored":
        out.push({ ...base, kind: "done", label: "Tools restored", detail: s });
        break;
      case "plan.invalidated":
        out.push({ ...base, kind: "warn", label: `Existing plan v${e.plan_version} invalidated`, detail: s.split(": ")[1] });
        break;
      case "replacement.found":
        out.push({ ...base, kind: "done", label: s.split(" found")[0] + " found", detail: s });
        break;
      case "replacement.none":
        out.push({ ...base, kind: "warn", label: "No eligible replacement", detail: s });
        break;
      case "escalation.created":
        out.push({ ...base, kind: "blocked", label: "Escalated to a human", detail: s });
        break;
      case "case.error":
        out.push({ ...base, kind: "error", label: "Recoverable error", detail: s });
        break;
      case "run.resumed":
        out.push({ ...base, kind: "done", label: "Run resumed", detail: s });
        break;
      case "monitor.ok":
        out.push({ ...base, kind: "done", label: "Monitoring check: all valid", detail: s });
        break;
      case "tasks.completed":
        out.push({ ...base, kind: "done", label: "Tasks completed", detail: s });
        break;
      case "state.changed": {
        const to = (e.metadata?.to as string) || "";
        if (to === "MONITORING") out.push({ ...base, kind: "done", label: "Monitoring for changes", detail: null });
        if (to === "RESOLVED") out.push({ ...base, kind: "done", label: "Case resolved", detail: s });
        break;
      }
      default:
        break;
    }
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
              <div className={clsx("flex items-center gap-1.5 text-[13px] font-medium",
                s.kind === "paused" ? "text-amber-800" : s.kind === "blocked" ? "text-rose-800" : "text-slate-800")}>
                {s.tool && <Wrench className="h-3 w-3 text-slate-400" />}
                <span className={clsx(s.tool && "font-mono text-[12px]")}>{s.label}</span>
              </div>
              <span className="shrink-0 font-mono text-[10px] text-slate-400">
                {s.latency != null ? `${ms(s.latency)} · ` : ""}
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
