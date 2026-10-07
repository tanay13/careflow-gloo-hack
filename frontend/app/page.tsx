"use client";

import Link from "next/link";
import { useState } from "react";
import { Activity, AlertOctagon, CheckCircle2, ClipboardCheck, Inbox, PhoneCall, PlusCircle, RotateCcw, Radar } from "lucide-react";
import clsx from "clsx";
import CaseTable from "@/components/CaseTable";
import { ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { friendlyDetail, friendlyTitle, showInFeed } from "@/lib/friendly";
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
  { key: "NEW", label: "New requests", icon: Inbox, tone: "text-sky-700 bg-sky-50" },
  { key: "AWAITING_APPROVAL", label: "Needs your decision", icon: ClipboardCheck, tone: "text-amber-800 bg-amber-50" },
  { key: "MONITORING", label: "Being cared for", icon: Radar, tone: "text-emerald-700 bg-emerald-50" },
  { key: "ESCALATED", label: "Needs a person now", icon: AlertOctagon, tone: "text-rose-700 bg-rose-50" },
  { key: "RESOLVED", label: "Complete", icon: CheckCircle2, tone: "text-slate-700 bg-slate-100" },
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
  const awaiting = counts["AWAITING_APPROVAL"] || 0;

  function greeting(): string {
    const h = dash.data ? new Date(dash.data.demo_now).getHours() : 9;
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  }

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
      <div className="overflow-hidden rounded-2xl border border-[#eadfcb] bg-gradient-to-r from-amber-50 via-[#fdf6ea] to-teal-50 px-6 py-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-semibold text-slate-900">{greeting()}, Care Team</h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">
              {awaiting > 0 ? (
                <><strong className="text-amber-900">{awaiting} {awaiting === 1 ? "request needs" : "requests need"} your decision today.</strong>{" "}</>
              ) : (
                <>Nothing is waiting on you right now.{" "}</>
              )}
              CareFlow has done the legwork — scheduling, volunteers, resources — so you can focus on the person.
              <span className="text-slate-500"> Demo day: {dash.data ? new Date(dash.data.demo_now).toLocaleString("en-US", { weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "…"}</span>
            </p>
          </div>
          <div className="flex gap-2">
            <button className="btn-secondary bg-white/80" onClick={reset} disabled={resetting}>
              <RotateCcw className={clsx("h-4 w-4", resetting && "animate-spin")} /> Reset demo data
            </button>
            <Link href="/cases/new" className="btn-primary">
              <PlusCircle className="h-4 w-4" /> New care request
            </Link>
          </div>
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
            <div className="mt-1 text-xs text-slate-500">In progress</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_360px]">
        <div className="card overflow-hidden">
          <div className="card-header">
            <div className="card-title">
              Requests {filter && <span className="text-xs font-normal text-slate-500">· showing: {filter.replace(/_/g, " ").toLowerCase()}</span>}
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
                <PhoneCall className="h-4 w-4 text-brand-700" /> On-call pastor this week
              </div>
            </div>
            <div className="card-body space-y-3 text-sm">
              {dash.data && (
                <>
                  <div>
                    <div className="font-semibold text-slate-900">{dash.data.poc.name}</div>
                    <div className="text-xs text-slate-500">
                      {dash.data.poc.role} · {dash.data.poc.campuses.join(", ")}
                    </div>
                  </div>
                  <div className="text-xs text-slate-600">
                    Backup pastor: <span className="font-medium text-slate-800">{dash.data.backup_poc.name}</span>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
                    When someone needs a pastor today, {dash.data.poc.name.split(" ")[0]} is the one who reaches out.
                    A backup pastor is ready too. Open urgent requests right now:{" "}
                    <strong>{dash.data.poc.urgent_open}</strong>.
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title">
                <Activity className="h-4 w-4 text-brand-700" /> What CareFlow has been doing
              </div>
              <Link href="/audit" className="text-xs font-medium text-brand-700 hover:underline">
                Full record →
              </Link>
            </div>
            <ul className="divide-y divide-slate-50">
              {(dash.data?.recent || []).filter(showInFeed).slice(0, 10).map((e) => (
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
                    {friendlyTitle(e)}
                  </div>
                  {friendlyDetail(e) && <div className="line-clamp-1 text-slate-500">{friendlyDetail(e)}</div>}
                </li>
              ))}
            </ul>
            {dash.data?.median_plan_ms != null && (
              <div className="border-t border-slate-100 px-5 py-2.5 text-xs text-slate-500">
                CareFlow did the checking in seconds — <strong className="text-slate-700">every decision stayed with you</strong>.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
