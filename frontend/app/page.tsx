"use client";

import Link from "next/link";
import { useState } from "react";
import { Activity, AlertOctagon, CheckCircle2, ClipboardCheck, Inbox, PhoneCall, PlusCircle, RotateCcw, Radar } from "lucide-react";
import clsx from "clsx";
import CaseTable from "@/components/CaseTable";
import { ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtTime, ms } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { AuditEvent, CaseSummary } from "@/types";

interface Dashboard {
  counts: Record<string, number>;
  total: number;
  poc: { staff_id: string; name: string; role: string; campuses: string[]; weekly_capacity: { min: number; max: number }; urgent_open: number };
  backup_poc: { staff_id: string; name: string };
  recent: AuditEvent[];
  median_plan_ms: number | null;
  demo_now: string;
}

const KPIS = [
  { key: "NEW", label: "New", icon: Inbox, tone: "text-sky-700 bg-sky-50" },
  { key: "AWAITING_APPROVAL", label: "Awaiting approval", icon: ClipboardCheck, tone: "text-amber-800 bg-amber-50" },
  { key: "MONITORING", label: "Monitoring", icon: Radar, tone: "text-emerald-700 bg-emerald-50" },
  { key: "ESCALATED", label: "Escalated", icon: AlertOctagon, tone: "text-rose-700 bg-rose-50" },
  { key: "RESOLVED", label: "Resolved", icon: CheckCircle2, tone: "text-slate-700 bg-slate-100" },
];

const IN_FLIGHT = ["NORMALIZED", "SAFETY_CHECKED", "CONTEXT_GATHERED", "PLAN_PROPOSED", "VERIFIED", "APPROVED", "EXECUTING", "ERROR"];

export default function DashboardPage() {
  const dash = usePoll<Dashboard>("/dashboard", 3000);
  const cases = usePoll<CaseSummary[]>("/cases", 3000, (d) => d.some((c) => c.is_running));
  const [filter, setFilter] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  const counts = dash.data?.counts || {};
  const inflight = IN_FLIGHT.reduce((n, k) => n + (counts[k] || 0), 0);
  const list = (cases.data || []).filter((c) => !filter || c.status === filter);

  async function reset() {
    if (!confirm("Reset the demo database to its deterministic synthetic starting state?")) return;
    setResetting(true);
    try {
      await api.post("/demo/reset");
      await Promise.all([dash.reload(), cases.reload()]);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Care operations</h1>
          <p className="mt-1 text-sm text-slate-500">
            Incoming care requests, agent progress and decisions waiting on a human. Demo clock:{" "}
            {dash.data ? new Date(dash.data.demo_now).toLocaleString("en-US", { weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "…"}
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={reset} disabled={resetting}>
            <RotateCcw className={clsx("h-4 w-4", resetting && "animate-spin")} /> Reset demo data
          </button>
          <Link href="/cases/new" className="btn-primary">
            <PlusCircle className="h-4 w-4" /> New care request
          </Link>
        </div>
      </div>

      {(dash.error || cases.error) && <ErrorNote message={dash.error || cases.error || ""} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {KPIS.map(({ key, label, icon: Icon, tone }) => (
          <button
            key={key}
            onClick={() => setFilter(filter === key ? null : key)}
            className={clsx("card flex items-center gap-3 px-4 py-3.5 text-left transition hover:border-slate-300",
              filter === key && "ring-2 ring-brand-500")}
          >
            <div className={clsx("flex h-10 w-10 items-center justify-center rounded-lg", tone)}>
              <Icon className="h-5 w-5" />
            </div>
            <div>
              <div className="text-2xl font-semibold leading-none text-slate-900">{counts[key] || 0}</div>
              <div className="mt-1 text-xs text-slate-500">{label}</div>
            </div>
          </button>
        ))}
        <div className="card flex items-center gap-3 px-4 py-3.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-700">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="text-2xl font-semibold leading-none text-slate-900">{inflight}</div>
            <div className="mt-1 text-xs text-slate-500">In flight / error</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_360px]">
        <div className="card overflow-hidden">
          <div className="card-header">
            <div className="card-title">
              Case queue {filter && <span className="text-xs font-normal text-slate-500">· filtered: {filter.replace(/_/g, " ").toLowerCase()}</span>}
            </div>
            {filter && (
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setFilter(null)}>
                Clear filter
              </button>
            )}
          </div>
          <CaseTable cases={list} />
        </div>

        <div className="space-y-6">
          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <PhoneCall className="h-4 w-4 text-brand-700" /> Pastor on Call this week
              </div>
              <span className="chip border-brand-200 bg-brand-50 text-brand-800">policy</span>
            </div>
            <div className="card-body space-y-3 text-sm">
              {dash.data && (
                <>
                  <div>
                    <div className="font-semibold text-slate-900">{dash.data.poc.name}</div>
                    <div className="text-xs text-slate-500">
                      {dash.data.poc.role} · {dash.data.poc.campuses.join(", ")} · {dash.data.poc.staff_id}
                    </div>
                  </div>
                  <div className="text-xs text-slate-600">
                    Backup POC: <span className="font-medium text-slate-800">{dash.data.backup_poc.name}</span>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
                    Practitioner-validated: urgent same-day requests go to the weekly POC, who may receive roughly{" "}
                    {dash.data.poc.weekly_capacity.min}–{dash.data.poc.weekly_capacity.max} requests a week. Open urgent cases:{" "}
                    <strong>{dash.data.poc.urgent_open}</strong>.
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Activity className="h-4 w-4 text-brand-700" /> Recent agent activity
              </div>
              <Link href="/audit" className="text-xs font-medium text-brand-700 hover:underline">
                Audit log →
              </Link>
            </div>
            <ul className="divide-y divide-slate-50">
              {(dash.data?.recent || []).map((e) => (
                <li key={e.event_id} className="px-5 py-2.5 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-slate-400">{fmtTime(e.timestamp)}</span>
                    {e.case_id && (
                      <Link href={`/cases/${e.case_id}`} className="font-mono text-[11px] text-brand-700 hover:underline">
                        {e.case_id}
                      </Link>
                    )}
                  </div>
                  <div className="mt-0.5 text-slate-700">
                    <span className="font-semibold">{e.actor}</span> {e.tool_name || e.event_type}
                  </div>
                  <div className="line-clamp-1 text-slate-500">{e.output_summary}</div>
                </li>
              ))}
            </ul>
            {dash.data?.median_plan_ms != null && (
              <div className="border-t border-slate-100 px-5 py-2.5 text-xs text-slate-500">
                Median planning compute: <strong className="text-slate-700">{ms(dash.data.median_plan_ms)}</strong>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
