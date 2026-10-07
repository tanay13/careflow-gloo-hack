import { Sparkles } from "lucide-react";
import type { CaseDetail } from "@/types";
import { ms } from "@/lib/format";

export default function MetricsCard({ c }: { c: CaseDetail }) {
  const t = c.metrics?.totals;
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <Sparkles className="h-4 w-4 text-brand-700" /> How hard CareFlow worked
        </div>
      </div>
      {!t ? (
        <div className="card-body text-xs text-slate-500">This fills in once CareFlow has had a go.</div>
      ) : (
        <div className="card-body space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {[
              ["Time spent working", ms(t.agent_ms)],
              ["Checks & lookups", t.tool_calls],
              ["Plans prepared", c.plans.length],
              ["Estimated cost", `$${Number(t.est_cost_usd).toFixed(4)}`],
            ].map(([k, v]) => (
              <div key={k as string} className="rounded-lg bg-slate-50 px-2.5 py-2">
                <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
                <div className="text-sm font-semibold text-slate-900">{v}</div>
              </div>
            ))}
          </div>
          <div className="text-[10.5px] leading-snug text-slate-400">
            Hours of legwork in seconds — and every decision stayed with you.
          </div>
        </div>
      )}
    </div>
  );
}
