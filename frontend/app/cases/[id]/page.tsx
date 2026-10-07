"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { AlertOctagon, ArrowLeft, CheckCircle2, ClipboardCheck, ListChecks, Loader2, Play, Radar, RotateCw, ServerCrash, Zap } from "lucide-react";
import ApprovalPanel from "@/components/ApprovalPanel";
import AuditTable from "@/components/AuditTable";
import ChangesPanel from "@/components/ChangesPanel";
import EventMenu from "@/components/EventMenu";
import MetricsCard from "@/components/MetricsCard";
import PlanView from "@/components/PlanView";
import { ContextEvidence, ExtractedNeeds, OriginalRequest } from "@/components/RequestPanel";
import StatePipeline from "@/components/StatePipeline";
import WorkflowTimeline from "@/components/WorkflowTimeline";
import { EmptyState, ErrorNote, StatusBadge, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtShort, humanize } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import type { CaseDetail } from "@/types";

type TabKey = "plan" | "request" | "changes" | "audit";

export default function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: c, error, reload } = usePoll<CaseDetail>(`/cases/${id}`, 2500, (d) => d.is_running);
  const [tab, setTab] = useState<TabKey>("plan");
  const [version, setVersion] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lastPlans = useRef<number>(-1);
  const timelineRef = useRef<HTMLDivElement>(null);
  const auditLen = c?.audit.length ?? 0;

  // Keep the live workflow timeline scrolled to the newest step.
  useEffect(() => {
    const el = timelineRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [auditLen, c?.is_running]);

  // Follow the newest plan version automatically when the agent produces one.
  useEffect(() => {
    if (!c) return;
    const n = c.plans.length;
    if (lastPlans.current === -1) {
      setTab(n ? "plan" : "request");
    } else if (n > lastPlans.current) {
      setTab("plan");
      setVersion(null);
    }
    lastPlans.current = n;
  }, [c]);

  if (error && !c) return <ErrorNote message={error} />;
  if (!c) return <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading case…</div>;

  const current = c.plans.find((p) => p.plan_id === c.current_plan_id) || c.plans[c.plans.length - 1];
  const shown = (version != null && c.plans.find((p) => p.version === version)) || current;
  const visited = new Set<string>(c.audit.filter((e) => e.event_type === "state.changed").flatMap((e) => [String(e.metadata.from), String(e.metadata.to)]));
  const pendingApprovals = current ? current.actions.filter((a) => a.approval_status === "pending" && a.risk_level === "approval_required").length : 0;

  async function post(path: string, body?: unknown) {
    setBusy(true);
    setActionError(null);
    try {
      await api.post(path, body);
      await reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const TABS: { key: TabKey; label: string; badge?: number }[] = [
    { key: "plan", label: "Plan & approval", badge: c.status === "AWAITING_APPROVAL" ? pendingApprovals : undefined },
    { key: "request", label: "Request & evidence" },
    { key: "changes", label: "Executed changes" },
    { key: "audit", label: "Audit log" },
  ];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/" className="mb-1 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800">
            <ArrowLeft className="h-3.5 w-3.5" /> Dashboard
          </Link>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="font-mono text-2xl font-semibold text-slate-900">{c.case_id}</h1>
            <StatusBadge status={c.status} className="text-[13px]" />
            {c.campus && <Tag tone="slate">{c.campus} campus</Tag>}
            {c.urgent && <Tag tone="amber"><Zap className="h-3 w-3" /> same-day</Tag>}
            {current && <Tag tone="indigo">plan v{current.version}</Tag>}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Created {fmtShort(c.created_at)} · {humanize(c.source)} · owner: {c.owner_name || "not yet assigned"}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {c.status === "NEW" && (
            <button className="btn-primary px-5 py-2.5 text-[15px]" disabled={busy || c.is_running} onClick={() => post(`/cases/${c.case_id}/run`)}>
              <Play className="h-4 w-4" /> Run CareFlow
            </button>
          )}
          {c.status === "ERROR" && (
            <button className="btn-primary" disabled={busy || c.is_running} onClick={() => post(`/cases/${c.case_id}/run`)}>
              <RotateCw className="h-4 w-4" /> Retry from {humanize(c.error?.resume_state || "")}
            </button>
          )}
          {c.status === "MONITORING" && (
            <>
              <button className="btn-secondary" disabled={busy || c.is_running} onClick={() => post(`/cases/${c.case_id}/run`)}>
                <Radar className="h-4 w-4" /> Run monitoring check
              </button>
              <button className="btn-secondary" disabled={busy || c.is_running} onClick={() => post(`/cases/${c.case_id}/events`, { type: "tasks_completed" })}>
                <CheckCircle2 className="h-4 w-4" /> Mark tasks complete
              </button>
            </>
          )}
          {!["NEW", "RESOLVED", "CANCELLED", "ESCALATED"].includes(c.status) && (
            <EventMenu c={c} onDone={reload} onError={setActionError} />
          )}
        </div>
      </div>

      <div className="card px-4 py-3">
        <StatePipeline status={c.status} visited={visited} />
      </div>

      {actionError && <ErrorNote message={actionError} />}

      {/* Status banners */}
      {c.is_running && (
        <div className="flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900">
          <Loader2 className="h-5 w-5 animate-spin text-brand-700" />
          <div>
            <span className="font-semibold">CareFlow is working autonomously</span> — {c.current_step || "…"}
          </div>
        </div>
      )}
      {c.status === "AWAITING_APPROVAL" && !c.is_running && tab !== "plan" && (
        <button onClick={() => setTab("plan")} className="flex w-full items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-left text-sm text-amber-900">
          <ClipboardCheck className="h-5 w-5 text-amber-700" />
          <span><span className="font-semibold">{pendingApprovals} action(s) await your approval.</span> Open the review →</span>
        </button>
      )}
      {c.status === "ESCALATED" && c.escalation?.reason && (
        <div className="rounded-xl border border-rose-300 bg-rose-50 px-4 py-3.5">
          <div className="flex items-start gap-3">
            <AlertOctagon className="mt-0.5 h-5 w-5 shrink-0 text-rose-700" />
            <div className="space-y-1 text-sm text-rose-900">
              <div className="font-semibold">Escalated to a human — automation stopped</div>
              <div>{c.escalation.reason}</div>
              {c.escalation.unresolved_need && (
                <div className="rounded-md bg-white/70 px-2.5 py-1.5 text-[13px]"><span className="font-semibold">Unresolved need: </span>{c.escalation.unresolved_need}</div>
              )}
              <div className="text-[13px]">
                Route to: <span className="font-semibold">{c.escalation.handler?.name}</span> ({c.escalation.handler?.role}) ·{" "}
                {c.escalation.protocol}
              </div>
              {String(c.escalation.category || "").startsWith("safety") && (
                <div className="text-[12px] text-rose-800">
                  CareFlow does not counsel, assess, or contact the requester. This case must follow the configured human escalation protocol.
                  <strong> This demo policy is synthetic and is not Flatirons&apos; real crisis protocol.</strong>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {c.status === "ERROR" && (
        <div className="flex items-start gap-3 rounded-xl border border-orange-300 bg-orange-50 px-4 py-3.5 text-sm text-orange-900">
          <ServerCrash className="mt-0.5 h-5 w-5 shrink-0 text-orange-700" />
          <div>
            <div className="font-semibold">Recoverable error — CareFlow stopped instead of continuing silently</div>
            <div>{c.error?.message}</div>
            <div className="mt-1 text-[12.5px]">Restore the tool (Simulate event → Restore tools), then retry. Resume point: {humanize(c.error?.resume_state)}.</div>
          </div>
        </div>
      )}
      {c.status === "RESOLVED" && c.summary && (
        <div className="flex items-start gap-3 rounded-xl border border-slate-300 bg-white px-4 py-3.5 text-sm text-slate-800">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div><div className="font-semibold">Operational closure summary</div>{c.summary}</div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <div className="flex gap-1 border-b border-slate-200">
            {TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={clsx("-mb-px flex items-center gap-1.5 border-b-2 px-3.5 py-2 text-sm font-medium transition",
                  tab === t.key ? "border-brand-700 text-brand-800" : "border-transparent text-slate-500 hover:text-slate-800")}>
                {t.label}
                {!!t.badge && <span className="rounded-full bg-amber-500 px-1.5 text-[11px] font-semibold text-white">{t.badge}</span>}
              </button>
            ))}
          </div>

          {tab === "plan" && (
            shown ? (
              <div className="space-y-4">
                {c.plans.length > 1 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-xs text-slate-500">Plan versions:</span>
                    {c.plans.map((p) => (
                      <button key={p.plan_id} onClick={() => setVersion(p.version)}
                        className={clsx("rounded-md border px-2.5 py-1 text-xs font-medium",
                          p.plan_id === shown.plan_id ? "border-brand-700 bg-brand-700 text-white" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50")}>
                        v{p.version} <span className="opacity-75">· {p.status.replace(/_/g, " ")}</span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="card"><div className="card-header"><div className="card-title"><ClipboardCheck className="h-4 w-4 text-amber-600" /> Human review</div></div>
                  <div className="card-body"><ApprovalPanel c={c} plan={shown} onDone={reload} /></div>
                </div>
                <div className="card"><div className="card-header"><div className="card-title"><ListChecks className="h-4 w-4 text-brand-700" /> Proposed care logistics plan</div></div>
                  <div className="card-body"><PlanView c={c} plan={shown} /></div>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <OriginalRequest c={c} />
                {c.status === "NEW" ? (
                  <div className="card flex flex-col items-center gap-3 px-6 py-10 text-center">
                    <div className="text-[15px] font-semibold text-slate-900">Ready to coordinate</div>
                    <p className="max-w-lg text-sm text-slate-500">
                      CareFlow will normalize the request, run the safety gate, query staff, calendars, resources and volunteers,
                      build and verify a plan, then stop for your approval.
                    </p>
                    <button className="btn-primary px-5 py-2.5 text-[15px]" disabled={busy || c.is_running} onClick={() => post(`/cases/${c.case_id}/run`)}>
                      <Play className="h-4 w-4" /> Run CareFlow
                    </button>
                  </div>
                ) : (
                  <>
                    <ExtractedNeeds c={c} />
                    {!c.is_running && <EmptyState>No plan was generated for this case{c.status === "ESCALATED" ? " — automation stopped by policy." : "."}</EmptyState>}
                  </>
                )}
              </div>
            )
          )}
          {tab === "request" && (
            <div className="space-y-4">
              <OriginalRequest c={c} />
              <ExtractedNeeds c={c} />
              <ContextEvidence c={c} />
            </div>
          )}
          {tab === "changes" && <ChangesPanel c={c} />}
          {tab === "audit" && (
            <div className="card overflow-hidden">
              <div className="card-header">
                <div className="card-title">Append-only audit log · {c.audit.length} events</div>
                <span className="text-xs text-slate-500">UPDATE/DELETE blocked by database triggers</span>
              </div>
              <AuditTable events={c.audit} />
            </div>
          )}
        </div>

        <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
          <div className="card">
            <div className="card-header">
              <div className="card-title"><Radar className="h-4 w-4 text-brand-700" /> Agent workflow</div>
              {c.is_running && <span className="flex items-center gap-1.5 text-xs text-brand-700"><span className="pulse-dot h-2 w-2 rounded-full bg-brand-600" /> live</span>}
            </div>
            <div ref={timelineRef} className="card-body max-h-[62vh] overflow-y-auto">
              {c.audit.length ? <WorkflowTimeline c={c} /> : <div className="text-xs text-slate-500">No activity yet.</div>}
            </div>
          </div>
          <MetricsCard c={c} />
        </div>
      </div>
    </div>
  );
}
