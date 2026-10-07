"use client";

import { Fragment, useState } from "react";
import clsx from "clsx";
import { Check, ChevronRight, FlaskConical, Loader2, Play, X } from "lucide-react";
import { ErrorNote, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { ms } from "@/lib/format";
import { usePoll } from "@/lib/hooks";

interface EvalResult {
  id: string;
  title: string;
  category: string;
  expected: string;
  passed: boolean;
  error: string | null;
  duration_ms: number;
  checks: { label: string; ok: boolean }[];
}
interface Evals {
  available: boolean;
  generated_at?: string;
  mode?: string;
  total?: number;
  passed?: number;
  failed?: number;
  metrics?: Record<string, number | null>;
  results?: EvalResult[];
}

export default function EvaluationsPage() {
  const { data, error, reload } = usePoll<Evals>("/evals/results", 15000);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setRunError(null);
    try {
      await api.post("/evals/run");
      await reload();
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  const m = data?.metrics || {};
  const cards: [string, string, string, boolean | null][] = data?.available ? [
    ["Tests passed", `${data.passed} / ${data.total}`, `${data.failed} failed`, data.failed === 0],
    ["Routing validity", `${m.routing_validity_pct}%`, `${m.routing_checked_owners} proposed owners checked`, m.routing_validity_pct === 100],
    ["Guardrail recall", `${m.guardrail_recall_pct}%`, "red-flag cases stopped & escalated", m.guardrail_recall_pct === 100],
    ["Unsupported claim rate", `${m.unsupported_claim_rate_pct}%`, `${m.grounded_items_checked} IDs traced to tool output`, m.unsupported_claim_rate_pct === 0],
    ["Unsafe actions executed", `${m.unsafe_actions_executed}`, `${m.unsafe_attempts_blocked} unsafe attempts blocked server-side`, m.unsafe_actions_executed === 0],
    ["Recovery rate", `${m.recovery_rate_pct}%`, "cancellations, outages, drift re-planned or escalated", m.recovery_rate_pct === 100],
    ["Median planning latency", ms(m.median_plan_latency_ms), `${m.planning_runs_measured} runs · agent compute`, null],
    ["p95 planning latency", ms(m.p95_plan_latency_ms), "target < 15 s", null],
    ["Avg cost / case (est.)", `$${Number(m.avg_cost_per_case_usd_est ?? 0).toFixed(4)}`, `${m.avg_tokens_per_case_est} tokens est.`, null],
  ] : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900"><FlaskConical className="h-6 w-6 text-brand-700" /> Evaluations</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            {data?.total ?? 26} scenario tests run end-to-end against the real orchestrator, tools, verifier and permission layer in an isolated database.
            {data?.generated_at && <> Last run {new Date(data.generated_at).toLocaleString()} · {data.mode}.</>}
          </p>
        </div>
        <button className="btn-primary" onClick={run} disabled={running}>
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {running ? "Running suite…" : "Run evaluation suite"}
        </button>
      </div>
      {(error || runError) && <ErrorNote message={error || runError || ""} />}
      {data && !data.available && <div className="text-sm text-slate-500">No results yet — run the suite.</div>}

      {data?.available && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {cards.map(([label, value, sub, good]) => (
              <div key={label} className="card px-4 py-3.5">
                <div className="label">{label}</div>
                <div className={clsx("mt-1 text-2xl font-semibold", good === true ? "text-emerald-700" : good === false ? "text-rose-700" : "text-slate-900")}>{value}</div>
                <div className="text-xs text-slate-500">{sub}</div>
              </div>
            ))}
          </div>

          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="w-8 px-3 py-2.5" />
                  <th className="px-3 py-2.5 font-semibold">ID</th>
                  <th className="px-3 py-2.5 font-semibold">Case</th>
                  <th className="px-3 py-2.5 font-semibold">Category</th>
                  <th className="px-3 py-2.5 font-semibold">Expected</th>
                  <th className="px-3 py-2.5 font-semibold">Result</th>
                  <th className="px-3 py-2.5 text-right font-semibold">Time</th>
                </tr>
              </thead>
              <tbody>
                {data.results!.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="cursor-pointer border-b border-slate-50 hover:bg-slate-50" onClick={() => setOpen(open === r.id ? null : r.id)}>
                      <td className="px-3 py-2.5"><ChevronRight className={clsx("h-4 w-4 text-slate-400 transition", open === r.id && "rotate-90")} /></td>
                      <td className="px-3 py-2.5 font-mono text-[13px] font-semibold">{r.id}</td>
                      <td className="px-3 py-2.5 font-medium text-slate-800">{r.title}</td>
                      <td className="px-3 py-2.5"><Tag>{r.category.replace(/_/g, " ")}</Tag></td>
                      <td className="max-w-md px-3 py-2.5 text-xs text-slate-600">{r.expected}</td>
                      <td className="px-3 py-2.5">
                        {r.passed ? <span className="chip border-emerald-300 bg-emerald-50 text-emerald-800"><Check className="h-3 w-3" /> PASS</span>
                          : <span className="chip border-rose-300 bg-rose-50 text-rose-800"><X className="h-3 w-3" /> FAIL</span>}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-xs text-slate-500">{ms(r.duration_ms)}</td>
                    </tr>
                    {open === r.id && (
                      <tr className="border-b border-slate-100 bg-slate-50/60">
                        <td />
                        <td colSpan={6} className="px-3 py-2.5">
                          <ul className="grid grid-cols-1 gap-1 md:grid-cols-2">
                            {r.checks.map((ch) => (
                              <li key={ch.label} className="flex items-center gap-1.5 text-xs text-slate-700">
                                {ch.ok ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <X className="h-3.5 w-3.5 text-rose-600" />} {ch.label}
                              </li>
                            ))}
                          </ul>
                          {r.error && <div className="mt-1 text-xs text-rose-700">{r.error}</div>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
