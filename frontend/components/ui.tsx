import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleDot, Loader2, OctagonX, PauseCircle, XCircle } from "lucide-react";
import type { CaseStatus } from "@/types";

const STATUS_STYLE: Record<string, string> = {
  NEW: "border-sky-200 bg-sky-50 text-sky-800",
  NORMALIZED: "border-slate-200 bg-slate-50 text-slate-700",
  SAFETY_CHECKED: "border-slate-200 bg-slate-50 text-slate-700",
  CONTEXT_GATHERED: "border-slate-200 bg-slate-50 text-slate-700",
  PLAN_PROPOSED: "border-indigo-200 bg-indigo-50 text-indigo-800",
  VERIFIED: "border-indigo-200 bg-indigo-50 text-indigo-800",
  AWAITING_APPROVAL: "border-amber-300 bg-amber-50 text-amber-900",
  APPROVED: "border-teal-200 bg-teal-50 text-teal-800",
  EXECUTING: "border-teal-200 bg-teal-50 text-teal-800",
  MONITORING: "border-emerald-200 bg-emerald-50 text-emerald-800",
  RESOLVED: "border-slate-300 bg-slate-100 text-slate-700",
  ESCALATED: "border-rose-300 bg-rose-50 text-rose-800",
  CANCELLED: "border-slate-200 bg-slate-50 text-slate-500",
  ERROR: "border-orange-300 bg-orange-50 text-orange-800",
};

export function StatusBadge({ status, className }: { status: CaseStatus | string; className?: string }) {
  return (
    <span className={clsx("chip whitespace-nowrap font-semibold", STATUS_STYLE[status] || STATUS_STYLE.NEW, className)}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  if (risk === "approval_required")
    return <span className="chip border-amber-300 bg-amber-50 text-amber-900">Requires approval</span>;
  if (risk === "forbidden") return <span className="chip border-rose-300 bg-rose-50 text-rose-800">Forbidden · human only</span>;
  return <span className="chip border-teal-200 bg-teal-50 text-teal-800">Safe · reversible</span>;
}

export function VerifierBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const s = {
    PASS: "border-emerald-300 bg-emerald-50 text-emerald-800",
    REPLAN: "border-amber-300 bg-amber-50 text-amber-900",
    ESCALATE: "border-rose-300 bg-rose-50 text-rose-800",
  }[status];
  return <span className={clsx("chip font-semibold", s)}>Verifier: {status}</span>;
}

export function ExecBadge({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    executed: ["Executed", "border-emerald-300 bg-emerald-50 text-emerald-800"],
    carried_over: ["Done earlier · still valid", "border-slate-200 bg-slate-50 text-slate-600"],
    pending: ["Pending", "border-slate-200 bg-white text-slate-600"],
    failed: ["Failed", "border-orange-300 bg-orange-50 text-orange-800"],
    blocked: ["Blocked by server", "border-rose-300 bg-rose-50 text-rose-800"],
    blocked_by_policy: ["Not executable", "border-rose-200 bg-rose-50 text-rose-700"],
    invalidated: ["Invalidated", "border-orange-300 bg-orange-50 text-orange-800"],
    skipped: ["Skipped", "border-slate-200 bg-slate-50 text-slate-500"],
  };
  const [label, cls] = map[status] || [status, "border-slate-200 bg-slate-50 text-slate-600"];
  return <span className={clsx("chip", cls)}>{label}</span>;
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">{children}</div>;
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function StepIcon({ kind }: { kind: "done" | "current" | "warn" | "error" | "blocked" | "paused" }) {
  if (kind === "done") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (kind === "current") return <Loader2 className="h-4 w-4 animate-spin text-brand-600" />;
  if (kind === "warn") return <AlertTriangle className="h-4 w-4 text-amber-600" />;
  if (kind === "error") return <OctagonX className="h-4 w-4 text-orange-600" />;
  if (kind === "blocked") return <XCircle className="h-4 w-4 text-rose-600" />;
  if (kind === "paused") return <PauseCircle className="h-4 w-4 text-amber-600" />;
  return <CircleDot className="h-4 w-4" />;
}

export function Tag({ children, tone = "slate" }: { children: React.ReactNode; tone?: "slate" | "teal" | "amber" | "rose" | "sky" | "indigo" }) {
  const t = {
    slate: "border-slate-200 bg-slate-50 text-slate-700",
    teal: "border-teal-200 bg-teal-50 text-teal-800",
    amber: "border-amber-200 bg-amber-50 text-amber-900",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    sky: "border-sky-200 bg-sky-50 text-sky-800",
    indigo: "border-indigo-200 bg-indigo-50 text-indigo-800",
  }[tone];
  return <span className={clsx("chip", t)}>{children}</span>;
}
