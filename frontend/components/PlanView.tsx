"use client";

import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, BookOpen, CalendarClock, Car, Check, ChevronDown, Info, MessageSquareText, Package, ShieldCheck, UserCheck, X } from "lucide-react";
import type { CaseDetail, Owner, Plan } from "@/types";
import { fmtDateTime, humanize } from "@/lib/format";
import { checkName, soften, triggerText } from "@/lib/friendly";
import { Tag, VerifierBadge } from "./ui";

function EvidenceRow({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <span className={clsx("chip", ok ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-slate-50 text-slate-500")}>
      {ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />} {label}
    </span>
  );
}

function OwnerCard({ o, title, primary }: { o: Owner; title: string; primary?: boolean }) {
  const e = o.evidence || {};
  return (
    <div className={clsx("rounded-lg border p-3.5", primary ? "border-brand-200 bg-brand-50/40" : "border-slate-200")}>
      <div className="label mb-1">{title}</div>
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-[15px] font-semibold text-slate-900">{o.name}</div>
        <span className="font-mono text-[11px] text-slate-500">{o.staff_id}</span>
      </div>
      <div className="text-xs text-slate-600">{o.role}</div>
      <p className="mt-2 text-xs leading-relaxed text-slate-700">{soften(o.reason)}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        <EvidenceRow ok={e.campus_match} label="campus" />
        <EvidenceRow ok={e.role_match} label="request type" />
        <EvidenceRow ok={e.availability_checked} label="times checked" />
        {e.poc_match && <EvidenceRow ok label="on-call pastor" />}
        {(e.experience_match || []).map((x) => (
          <Tag key={x} tone="teal">{humanize(x)}</Tag>
        ))}
      </div>
      {e.routing_rule && <div className="mt-2 text-[10.5px] text-slate-500">Rule: {e.routing_rule}</div>}
    </div>
  );
}

function Section({ icon: Icon, title, children, right }: { icon: any; title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800">
          <Icon className="h-4 w-4 text-slate-500" /> {title}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

export default function PlanView({ c, plan }: { c: CaseDetail; plan: Plan }) {
  const [showChecks, setShowChecks] = useState(false);
  const blocking = plan.unresolved_items.filter((u) => u.severity === "blocking");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[15px] font-semibold text-slate-900">{plan.objective}</div>
          <div className="mt-0.5 text-xs text-slate-500">
            Plan v{plan.version} · {triggerText(plan.trigger)} · {plan.status.replace(/_/g, " ")}
          </div>
        </div>
        <VerifierBadge status={plan.verifier_status} />
      </div>

      {plan.rationale && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-[13px] leading-relaxed text-slate-700">
          <span className="font-semibold text-slate-800">What was understood: </span>
          {soften(plan.rationale)}
        </div>
      )}

      {(plan.owner || plan.backup_owner) && (
        <Section icon={UserCheck} title="Suggested pastor">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {plan.owner && <OwnerCard o={plan.owner} title="Owner" primary />}
            {plan.backup_owner && <OwnerCard o={plan.backup_owner} title="Backup" />}
          </div>
        </Section>
      )}

      {plan.appointment_options.length > 0 && (
        <Section icon={CalendarClock} title="Possible visit times">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {plan.appointment_options.map((o) => (
              <div key={o.option_id} className="rounded-lg border border-slate-200 px-3 py-2.5">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-slate-900">{fmtDateTime(o.start)}</div>
                  <span className="text-[11px] text-slate-500">{o.option_id}</span>
                </div>
                <div className="text-xs text-slate-600">
                  {c.names.staff[o.staff_id]} · {o.mode} · {Math.round((+new Date(o.end) - +new Date(o.start)) / 60000)} min
                </div>
                <div className="mt-1 text-[11px] text-slate-500">{soften(o.reason)}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {plan.volunteer_tasks.length > 0 && (
        <Section icon={Car} title="Transportation">
          <div className="space-y-2">
            {plan.volunteer_tasks.map((t) => (
              <div key={t.task_key} className={clsx("flex items-start justify-between gap-3 rounded-lg border px-3 py-2.5",
                t.volunteer_id ? "border-slate-200" : "border-rose-200 bg-rose-50/50")}>
                <div>
                  <div className="text-sm font-medium text-slate-900">
                    {t.label} <span className="font-normal text-slate-500">· appt {fmtDateTime(t.appointment_time)}</span>
                  </div>
                  <div className="text-xs text-slate-600">Pickup window {fmtDateTime(t.start)} · {t.location}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500">{soften(t.reason)}</div>
                </div>
                <div className="text-right">
                  {t.volunteer_id ? (
                    <>
                      <div className="text-sm font-semibold text-slate-900">{t.name}</div>
                      <div className="font-mono text-[11px] text-slate-500">{t.volunteer_id}</div>
                      {t.replacement && <Tag tone="indigo">replacement</Tag>}
                    </>
                  ) : (
                    <Tag tone="rose">unfilled</Tag>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {plan.resource_actions.length > 0 && (
        <Section icon={Package} title="Helpful resources">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {plan.resource_actions.map((r) => (
              <div key={r.resource_id} className="rounded-lg border border-slate-200 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm font-medium text-slate-900">{r.name}</div>
                  {r.action === "reserve" ? (
                    <Tag tone={r.approval_required ? "amber" : "teal"}>reserve{r.approval_required ? " · approval" : ""}</Tag>
                  ) : (
                    <Tag tone="sky">
                      <BookOpen className="h-3 w-3" /> share info
                    </Tag>
                  )}
                </div>
                <div className="font-mono text-[11px] text-slate-500">{r.resource_id} · {humanize(r.category)}</div>
                <div className="mt-1 text-[11px] text-slate-500">{soften(r.reason)}</div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {plan.unresolved_items.length > 0 && (
        <Section icon={AlertTriangle} title={`Open items${blocking.length ? ` (${blocking.length} blocking)` : ""}`}>
          <ul className="space-y-1.5">
            {plan.unresolved_items.map((u, i) => (
              <li key={i} className={clsx("flex gap-2 rounded-lg border px-3 py-2 text-[13px]",
                u.severity === "blocking" ? "border-rose-200 bg-rose-50 text-rose-900" :
                  u.severity === "needs_info" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700")}>
                {u.severity === "info" ? <Info className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
                <div>
                  <span className="font-semibold">{humanize(u.need)}: </span>
                  {u.detail}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {plan.message_draft && (
        <Section icon={MessageSquareText} title="Message draft (stays unsent until you say so)">
          <div className="rounded-lg border border-dashed border-slate-300 bg-white px-3.5 py-3 text-[13px] leading-relaxed text-slate-700">
            {plan.message_draft}
          </div>
        </Section>
      )}

      <div className="rounded-lg border border-slate-200">
        <button className="flex w-full items-center justify-between px-3.5 py-2.5 text-left" onClick={() => setShowChecks(!showChecks)}>
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-800">
            <ShieldCheck className="h-4 w-4 text-slate-500" /> CareFlow's double-checks ({plan.verifier_result?.checks?.length || 0})
          </span>
          <ChevronDown className={clsx("h-4 w-4 text-slate-400 transition", showChecks && "rotate-180")} />
        </button>
        {showChecks && (
          <ul className="space-y-1 border-t border-slate-100 px-3.5 py-2.5">
            {(plan.verifier_result?.checks || []).map((ch, i) => (
              <li key={i} className="flex gap-2 text-xs">
                {ch.status === "pass" ? <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" /> :
                  <X className="h-3.5 w-3.5 shrink-0 text-rose-600" />}
                <span className="text-slate-700">{checkName(ch.check)}{ch.status !== "pass" ? ` — ${ch.detail}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
