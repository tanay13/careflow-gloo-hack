import clsx from "clsx";
import type { CaseStatus } from "@/types";
import { PIPELINE_LABELS, statusLabel } from "@/lib/friendly";

const MAIN: { key: CaseStatus; label: string }[] = [
  { key: "NEW", label: "New" },
  { key: "NORMALIZED", label: "Normalized" },
  { key: "SAFETY_CHECKED", label: "Safety" },
  { key: "CONTEXT_GATHERED", label: "Context" },
  { key: "PLAN_PROPOSED", label: "Plan" },
  { key: "VERIFIED", label: "Verified" },
  { key: "AWAITING_APPROVAL", label: "Approval" },
  { key: "APPROVED", label: "Approved" },
  { key: "EXECUTING", label: "Executing" },
  { key: "MONITORING", label: "Monitoring" },
  { key: "RESOLVED", label: "Resolved" },
];

/** Visualizes the explicit, code-enforced state machine. */
export default function StatePipeline({ status, visited }: { status: CaseStatus; visited: Set<string> }) {
  const idx = MAIN.findIndex((m) => m.key === status);
  const off = status === "ESCALATED" || status === "ERROR" || status === "CANCELLED";
  return (
    <div className="flex items-center gap-1 overflow-x-auto">
      {MAIN.map((m, i) => {
        const current = m.key === status;
        const seen = visited.has(m.key) || (idx >= 0 && i < idx);
        return (
          <div key={m.key} className="flex items-center gap-1">
            <div
              className={clsx(
                "whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-medium",
                current && m.key === "AWAITING_APPROVAL" && "bg-amber-500 text-white",
                current && m.key !== "AWAITING_APPROVAL" && "bg-brand-700 text-white",
                !current && seen && "bg-brand-50 text-brand-800",
                !current && !seen && "bg-slate-100 text-slate-400"
              )}
            >
              {PIPELINE_LABELS[m.key] || m.label}
            </div>
            {i < MAIN.length - 1 && <div className={clsx("h-px w-2", seen ? "bg-brand-300" : "bg-slate-200")} />}
          </div>
        );
      })}
      {off && (
        <div className={clsx("ml-2 whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold text-white",
          status === "ESCALATED" ? "bg-rose-600" : status === "ERROR" ? "bg-orange-600" : "bg-slate-500")}>
          {statusLabel(status)}
        </div>
      )}
    </div>
  );
}
