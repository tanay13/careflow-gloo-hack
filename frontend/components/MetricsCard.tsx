import { Gauge } from "lucide-react";
import type { CaseDetail } from "@/types";
import { humanize, ms } from "@/lib/format";

export default function MetricsCard({ c }: { c: CaseDetail }) {
  const runs = c.metrics?.runs || [];
  const t = c.metrics?.totals;
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <Gauge className="h-4 w-4 text-brand-700" /> Latency &amp; cost
        </div>
        {t?.tokens_estimated && <span className="text-[10px] text-slate-400">tokens estimated</span>}
      </div>
      {!t ? (
        <div className="card-body text-xs text-slate-500">Recorded after the first agent run.</div>
      ) : (
        <div className="card-body space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {[
              ["Agent compute", ms(t.agent_ms)],
              ["Tool calls", t.tool_calls],
              ["Model calls", t.llm_calls],
              ["Est. cost", `$${Number(t.est_cost_usd).toFixed(4)}`],
              ["Input tokens", Number(t.input_tokens).toLocaleString()],
              ["Output tokens", Number(t.output_tokens).toLocaleString()],
            ].map(([k, v]) => (
              <div key={k as string} className="rounded-lg bg-slate-50 px-2.5 py-2">
                <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
                <div className="text-sm font-semibold text-slate-900">{v}</div>
              </div>
            ))}
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="font-medium">Run</th>
                <th className="text-right font-medium">Compute</th>
                <th className="text-right font-medium">Tools</th>
                <th className="text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, i) => (
                <tr key={i} className="text-slate-600">
                  <td className="py-0.5">{humanize(r.kind)}</td>
                  <td className="text-right font-mono">{ms(r.agent_ms)}</td>
                  <td className="text-right font-mono">{r.tool_calls}</td>
                  <td className="text-right font-mono">${r.est_cost_usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10.5px] leading-snug text-slate-400">
            Compute excludes the visible demo pacing delay. Provider: {runs[runs.length - 1]?.provider || "—"}.
          </div>
        </div>
      )}
    </div>
  );
}
