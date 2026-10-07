"use client";

import { useEffect, useState } from "react";
import { BadgeCheck, Lock, ShieldAlert, ShieldCheck, Wrench } from "lucide-react";
import { ErrorNote, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";

export default function PolicyPage() {
  const [policy, setPolicy] = useState<any>(null);
  const [tools, setTools] = useState<any[]>([]);
  const [config, setConfig] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([api.get("/policies"), api.get<any[]>("/tools"), api.get("/config")])
      .then(([p, t, c]) => { setPolicy(p); setTools(t); setConfig(c); })
      .catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorNote message={error} />;
  if (!policy) return <div className="text-sm text-slate-500">Loading…</div>;
  const r = policy.routing;
  const risk = policy.action_risk_policy;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">How CareFlow works</h1>
        <p className="mt-1 text-sm text-slate-500">
          The guardrails CareFlow cannot change, and the helpers it is allowed to use. Policy version <span className="font-mono">{policy.version}</span> · model:{" "}
          <span className="font-mono">{config?.provider} / {config?.model}</span>
        </p>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="card">
          <div className="card-header"><div className="card-title"><BadgeCheck className="h-4 w-4 text-emerald-600" /> Practitioner-validated routing (Flatirons feedback)</div></div>
          <div className="card-body space-y-3 text-[13px]">
            <ul className="space-y-1.5">
              {r.practitioner_validated.map((x: string) => <li key={x} className="flex gap-2"><span className="text-emerald-600">✓</span>{x}</li>)}
            </ul>
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              Synthetic configuration: current POC <span className="font-mono">{r.current_poc_staff_id}</span>, backup POC{" "}
              <span className="font-mono">{r.backup_poc_staff_id}</span>, escalation to Care Coordinator{" "}
              <span className="font-mono">{r.care_coordinator_staff_id}</span>. Eligibility filters: {r.eligibility_filters.join(" → ")}.
            </div>
            <div className="text-xs text-amber-800">Everything else in Flatirons&apos; workflow remains unvalidated and is modeled with synthetic placeholders.</div>
          </div>
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title"><Lock className="h-4 w-4 text-amber-600" /> Approval matrix</div></div>
          <div className="card-body space-y-3 text-[13px]">
            {[
              ["Safe / reversible", risk.safe, "teal", ShieldCheck],
              ["Requires approval", risk.approval_required, "amber", Lock],
              ["Forbidden", risk.forbidden, "rose", ShieldAlert],
            ].map(([label, items, tone, Icon]: any) => (
              <div key={label}>
                <div className="mb-1 flex items-center gap-1.5 font-semibold text-slate-800"><Icon className="h-4 w-4" /> {label}</div>
                <div className="flex flex-wrap gap-1">{items.map((i: string) => <Tag key={i} tone={tone}>{i}</Tag>)}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="card lg:col-span-2">
          <div className="card-header">
            <div className="card-title"><ShieldAlert className="h-4 w-4 text-rose-600" /> Safety gate categories</div>
            <Tag tone="rose">synthetic placeholder - not a real crisis protocol</Tag>
          </div>
          <div className="card-body grid grid-cols-1 gap-3 text-[12.5px] md:grid-cols-3">
            {Object.entries(policy.safety_gate.escalation_categories).map(([k, v]: any) => (
              <div key={k}>
                <div className="font-semibold text-slate-800">{humanize(k)}</div>
                <div className="text-slate-500">{v.join(", ")}</div>
              </div>
            ))}
            <div className="md:col-span-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">{policy.safety_gate.protocol_label}</div>
          </div>
        </div>

        <div className="card lg:col-span-2 overflow-hidden">
          <div className="card-header"><div className="card-title"><Wrench className="h-4 w-4 text-brand-700" /> Tool registry (server-enforced)</div></div>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-5 py-2 font-semibold">Tool</th>
                <th className="px-3 py-2 font-semibold">Access</th>
                <th className="px-3 py-2 font-semibold">Approval token</th>
                <th className="px-3 py-2 font-semibold">Allowed actors</th>
                <th className="px-3 py-2 font-semibold">Purpose</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((t) => (
                <tr key={t.name} className="border-b border-slate-50">
                  <td className="px-5 py-2 font-mono text-[12.5px] font-semibold text-slate-800">{t.name}</td>
                  <td className="px-3 py-2"><Tag tone={t.access === "read" ? "sky" : t.access === "write_irreversible" ? "rose" : t.access === "draft" ? "slate" : "amber"}>{t.access}</Tag></td>
                  <td className="px-3 py-2">{t.requires_approval ? <Tag tone="amber">required</Tag> : <span className="text-xs text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{t.allowed_actors.join(", ")}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{t.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
