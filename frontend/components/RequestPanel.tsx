import { Check, FileText, ListChecks, Search, ShieldCheck, X } from "lucide-react";
import type { CaseDetail } from "@/types";
import { fmtDateTime, humanize } from "@/lib/format";
import { Tag } from "./ui";

export function OriginalRequest({ c }: { c: CaseDetail }) {
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <FileText className="h-4 w-4 text-brand-700" /> Original request
        </div>
        <span className="text-xs text-slate-500">
          {humanize(c.source)} · {c.requester_ref}
        </span>
      </div>
      <div className="card-body">
        <blockquote className="border-l-4 border-brand-200 pl-4 text-[14.5px] leading-relaxed text-slate-800">{c.request_text}</blockquote>
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {Object.entries(c.consent_flags || {}).map(([k, v]) => (
            <Tag key={k} tone={v ? "teal" : "slate"}>
              {v ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />} {humanize(k)}
            </Tag>
          ))}
          {(c.intake_form?.appointments || []).length > 0 && (
            <Tag tone="sky">{c.intake_form.appointments.length} appointment time(s) on intake form</Tag>
          )}
        </div>
      </div>
    </div>
  );
}

export function ExtractedNeeds({ c }: { c: CaseDetail }) {
  const n = c.structured_needs || {};
  const s = c.safety_result || {};
  if (!n.needs) return null;
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <ListChecks className="h-4 w-4 text-brand-700" /> What CareFlow understood
        </div>
        {s.decision && (
          <span className={s.decision === "PASS" ? "chip border-emerald-300 bg-emerald-50 text-emerald-800" : "chip border-rose-300 bg-rose-50 text-rose-800"}>
            <ShieldCheck className="h-3 w-3" /> Safety gate: {s.decision}
          </span>
        )}
      </div>
      <div className="card-body grid grid-cols-2 gap-x-6 gap-y-3 text-[13px] md:grid-cols-4">
        <Field label="Campus" value={c.campus || <span className="text-amber-700">not stated</span>} />
        <Field label="Timeframe" value={humanize(n.timeframe)} />
        <Field label="Same-day / urgent" value={n.urgent_same_day ? "Yes" : "No"} />
        <Field label="Routing type" value={humanize(n.primary_request_type) || "—"} />
        <div className="col-span-2 md:col-span-4">
          <div className="label mb-1">Needs</div>
          <div className="flex flex-wrap gap-1">
            {(n.needs || []).map((x: string) => <Tag key={x} tone="teal">{humanize(x)}</Tag>)}
            {(n.experience_tags || []).map((x: string) => <Tag key={x} tone="indigo">exp: {humanize(x)}</Tag>)}
            {(s.routing_flags || []).map((x: string) => <Tag key={x} tone="amber">flag: {humanize(x)}</Tag>)}
          </div>
        </div>
        {(n.appointments || []).length > 0 && (
          <div className="col-span-2 md:col-span-4">
            <div className="label mb-1">Transportation windows</div>
            <ul className="space-y-0.5 text-slate-700">
              {n.appointments.map((a: any) => (
                <li key={a.appointment_time}>
                  {a.label}: appt {fmtDateTime(a.appointment_time)} · pickup {fmtDateTime(a.ride_start)}
                </li>
              ))}
            </ul>
          </div>
        )}
        {(n.missing_facts || []).length > 0 && (
          <div className="col-span-2 md:col-span-4">
            <div className="label mb-1">Missing information (flagged, not invented)</div>
            <ul className="list-inside list-disc text-amber-800">
              {n.missing_facts.map((m: string) => <li key={m}>{m}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-0.5 text-slate-800">{value}</div>
    </div>
  );
}

export function ContextEvidence({ c }: { c: CaseDetail }) {
  const ctx = c.context;
  if (!ctx.staff_candidates.length && !ctx.resources.length && !ctx.ride_tasks.length) return null;
  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">
          <Search className="h-4 w-4 text-brand-700" /> How CareFlow chose
        </div>
      </div>
      <div className="card-body space-y-4 text-[13px]">
        {ctx.routing_rule && (
          <div>
            <div className="label mb-1">Pastors CareFlow could choose from</div>
            <div className="mb-1.5 text-[11.5px] text-slate-500">Rule: {ctx.routing_rule}</div>
            <div className="flex flex-wrap gap-1.5">
              {ctx.staff_candidates.map((s) => (
                <Tag key={s.staff_id} tone="teal">
                  {s.name} · {s.staff_id} · {(ctx.availability[s.staff_id]?.free_slots || []).length} free slots
                </Tag>
              ))}
            </div>
            <details className="mt-2 text-[11.5px] text-slate-500">
              <summary className="cursor-pointer">Why others weren't chosen ({ctx.staff_excluded.length})</summary>
              <ul className="mt-1 space-y-0.5">
                {ctx.staff_excluded.map((s) => (
                  <li key={s.staff_id}>
                    <span className="font-mono">{s.staff_id}</span> {s.name}: {s.reasons.join(", ")}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}
        {ctx.ride_tasks.length > 0 && (
          <div>
            <div className="label mb-1">Drivers for each ride</div>
            {ctx.ride_tasks.map((rt) => (
              <div key={rt.task_key} className="mb-1">
                <span className="font-medium text-slate-800">{rt.label}</span>{" "}
                <span className="text-slate-500">— {rt.candidates.length} eligible, {rt.excluded.length} excluded</span>
                <details className="text-[11.5px] text-slate-500">
                  <summary className="cursor-pointer">Details</summary>
                  <ul className="mt-1 space-y-0.5">
                    {rt.candidates.map((v: any) => <li key={v.volunteer_id} className="text-emerald-700">✓ {v.volunteer_id} {v.name} (load {v.current_load})</li>)}
                    {rt.excluded.map((v: any) => <li key={v.volunteer_id}>✗ {v.volunteer_id}: {v.reasons.join("; ")}</li>)}
                  </ul>
                </details>
              </div>
            ))}
          </div>
        )}
        {ctx.resources.length > 0 && (
          <div>
            <div className="label mb-1">Resources from the approved list</div>
            <ul className="space-y-0.5 text-[12px]">
              {ctx.resources.map((r) => (
                <li key={r.resource_id} className={r.available && r.restrictions_satisfied ? "text-slate-700" : "text-slate-400"}>
                  <span className="font-mono">{r.resource_id}</span> {r.name} ({r.campus}) — {r.status}
                  {r.quantity != null ? `, qty ${r.quantity}` : ""}
                  {!r.restrictions_satisfied && <span className="text-amber-700"> · restriction unmet</span>}
                  {r.approval_required && <span className="text-amber-700"> · approval required</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
