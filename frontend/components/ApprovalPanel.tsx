"use client";

import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { Ban, CheckCheck, ClipboardCheck, Lock, RefreshCw, ShieldAlert, ShieldCheck, Undo2, UserRoundCog } from "lucide-react";
import type { Action, CaseDetail, Plan } from "@/types";
import { api } from "@/lib/api";
import { ErrorNote, ExecBadge } from "./ui";

const BOUNDARIES = [
  "Pastoral counseling or spiritual direction",
  "Interpreting anyone's spiritual state",
  "Medical or mental-health diagnosis",
  "Financial / benevolence approval or denial",
  "Moving money",
  "Autonomous contact with a person in crisis",
];

type Decision = "approve" | "reject" | "reassign" | null;

function ActionRow({ a, checked, rejected, onToggle, onReject, reassign, onReassign, candidates, disabled }: {
  a: Action; checked: boolean; rejected: boolean; onToggle: () => void; onReject: () => void;
  reassign?: string; onReassign?: (v: string) => void; candidates?: { staff_id: string; name: string }[]; disabled: boolean;
}) {
  const id = `act-${a.action_id}`;
  return (
    <div className={clsx("rounded-lg border px-3 py-2.5 transition",
      rejected ? "border-rose-200 bg-rose-50/60" : checked ? (a.risk_level === "safe" ? "border-teal-300 bg-teal-50/50" : "border-amber-300 bg-amber-50/60") : "border-slate-200 bg-white")}>
      <div className="flex items-start gap-3">
        <input id={id} type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-700"
          checked={checked && !rejected} disabled={disabled || rejected} onChange={onToggle} />
        <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer">
          <div className={clsx("text-[13px] font-medium text-slate-900", rejected && "line-through decoration-rose-400")}>{a.title}</div>
          {a.type !== "message.send" && a.description && <div className="mt-0.5 line-clamp-2 text-[11.5px] text-slate-500">{a.description}</div>}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10.5px] text-slate-500">
            <span className="font-mono">{a.type}</span>
            <span>·</span>
            <span className={a.reversible ? "text-slate-500" : "font-semibold text-rose-700"}>{a.reversible ? "reversible" : "irreversible"}</span>
            <span>·</span>
            <span className="font-mono">{a.action_id}</span>
          </div>
        </label>
        <button type="button" disabled={disabled} onClick={onReject}
          className={clsx("btn px-2 py-1 text-xs", rejected ? "text-slate-600 hover:bg-slate-100" : "text-rose-700 hover:bg-rose-50")}>
          {rejected ? <><Undo2 className="h-3.5 w-3.5" /> Undo</> : <><Ban className="h-3.5 w-3.5" /> Reject</>}
        </button>
      </div>
      {onReassign && candidates && candidates.length > 0 && (
        <div className="mt-2 flex items-center gap-2 pl-7">
          <UserRoundCog className="h-3.5 w-3.5 text-slate-500" />
          <select className="input max-w-xs py-1 text-xs" value={reassign || ""} disabled={disabled} onChange={(e) => onReassign(e.target.value)}>
            <option value="">Reassign to another eligible staff member…</option>
            {candidates.map((c) => <option key={c.staff_id} value={c.staff_id}>{c.name} ({c.staff_id})</option>)}
          </select>
        </div>
      )}
    </div>
  );
}

export default function ApprovalPanel({ c, plan, onDone }: { c: CaseDetail; plan: Plan; onDone: () => void }) {
  const live = c.status === "AWAITING_APPROVAL" && plan.plan_id === c.current_plan_id && !c.is_running;
  const pending = plan.actions.filter((a) => a.approval_status === "pending" && a.risk_level !== "forbidden");
  const needApproval = pending.filter((a) => a.risk_level === "approval_required");
  const safe = pending.filter((a) => a.risk_level === "safe");
  const decided = plan.actions.filter((a) => a.approval_status !== "pending" && a.risk_level !== "forbidden");
  const forbiddenActions = plan.actions.filter((a) => a.risk_level === "forbidden");

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [reassign, setReassign] = useState<string>("");
  const [reviewer, setReviewer] = useState("Dana Ellison (Care Coordinator)");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset local selection whenever a new plan version arrives. Safe actions are pre-selected (policy-permitted).
  useEffect(() => {
    setSelected(new Set(safe.map((a) => a.action_id)));
    setRejected(new Set());
    setReassign("");
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.plan_id]);

  const ownerAction = needApproval.find((a) => a.subtype === "assign_owner");
  const candidates = useMemo(
    () => c.context.staff_candidates.filter((s) => s.staff_id !== ownerAction?.parameters?.value).map((s) => ({ staff_id: s.staff_id, name: s.name })),
    [c.context.staff_candidates, ownerAction]
  );

  function toggle(id: string) {
    const n = new Set(selected);
    n.has(id) ? n.delete(id) : n.add(id);
    setSelected(n);
  }
  function toggleReject(id: string) {
    const n = new Set(rejected);
    n.has(id) ? n.delete(id) : n.add(id);
    setRejected(n);
  }

  async function submit(mode: "selected" | "all" | "replan") {
    setBusy(true);
    setError(null);
    const decisions: { action_id: string; decision: Decision; staff_id?: string; comments?: string }[] = [];
    for (const a of pending) {
      if (ownerAction && a.action_id === ownerAction.action_id && reassign) {
        decisions.push({ action_id: a.action_id, decision: "reassign", staff_id: reassign, comments: feedback || undefined });
      } else if (rejected.has(a.action_id)) {
        decisions.push({ action_id: a.action_id, decision: "reject", comments: feedback || undefined });
      } else if (mode === "all" || (mode !== "replan" && selected.has(a.action_id))) {
        decisions.push({ action_id: a.action_id, decision: "approve" });
      }
    }
    try {
      await api.post(`/cases/${c.case_id}/approve`, { reviewer, decisions, feedback: feedback || null, request_replan: mode === "replan" });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const nSel = pending.filter((a) => selected.has(a.action_id) && !rejected.has(a.action_id)).length;
  const willReplan = !!reassign || (ownerAction && rejected.has(ownerAction.action_id));

  return (
    <div className="space-y-4">
      {live ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
          <ClipboardCheck className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" />
          <div className="text-sm text-amber-900">
            <div className="font-semibold">
              Your decision is needed: {needApproval.length} consequential action{needApproval.length === 1 ? "" : "s"}
              {plan.version > 1 ? ` (new in plan v${plan.version})` : ""}
            </div>
            <div className="text-[13px]">
              Nothing below has run. CareFlow executes only what you approve; external messages are irreversible and always gated.
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-2.5 text-[13px] text-slate-600">
          {c.is_running ? "The agent is working on this case…" : `Review closed for plan v${plan.version} (${plan.status.replace(/_/g, " ")}).`}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-3">
        <div className="space-y-2 2xl:col-span-2">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-amber-900">
            <Lock className="h-4 w-4" /> Requires approval
            <span className="text-xs font-normal text-slate-500">external communication · staff assignment · holds · volunteer commitments</span>
          </div>
          {needApproval.length === 0 && <div className="text-xs text-slate-500">No consequential actions pending.</div>}
          {needApproval.map((a) => (
            <ActionRow key={a.action_id} a={a} checked={selected.has(a.action_id)} rejected={rejected.has(a.action_id)}
              onToggle={() => toggle(a.action_id)} onReject={() => toggleReject(a.action_id)} disabled={!live || busy}
              {...(a.subtype === "assign_owner" ? { reassign, onReassign: setReassign, candidates } : {})} />
          ))}

          <div className="flex items-center gap-2 pt-3 text-[13px] font-semibold text-teal-900">
            <ShieldCheck className="h-4 w-4" /> Safe &amp; reversible
            <span className="text-xs font-normal text-slate-500">policy-permitted · pre-selected · runs with your submission</span>
          </div>
          {safe.length === 0 && <div className="text-xs text-slate-500">None.</div>}
          {safe.map((a) => (
            <ActionRow key={a.action_id} a={a} checked={selected.has(a.action_id)} rejected={rejected.has(a.action_id)}
              onToggle={() => toggle(a.action_id)} onReject={() => toggleReject(a.action_id)} disabled={!live || busy} />
          ))}
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[13px] font-semibold text-rose-900">
            <ShieldAlert className="h-4 w-4" /> Forbidden for CareFlow
          </div>
          <div className="rounded-lg border border-rose-200 bg-rose-50/50 p-3">
            {forbiddenActions.length > 0 && (
              <ul className="mb-3 space-y-2">
                {forbiddenActions.map((a) => (
                  <li key={a.action_id} className="text-[12.5px]">
                    <div className="font-semibold text-rose-900">{a.title}</div>
                    <div className="text-rose-800">{a.description}</div>
                  </li>
                ))}
              </ul>
            )}
            <div className="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Always human-only</div>
            <ul className="mt-1 space-y-0.5 text-[12px] text-rose-900">
              {BOUNDARIES.map((b) => <li key={b}>· {b}</li>)}
            </ul>
            <div className="mt-2 text-[10.5px] text-rose-700">Enforced by server-side tool permissions, not by prompt.</div>
          </div>
        </div>
      </div>

      {live && (
        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3.5">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[240px_1fr]">
            <div>
              <label className="label">Reviewer</label>
              <input className="input mt-1" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </div>
            <div>
              <label className="label">Feedback to the agent (optional)</label>
              <input className="input mt-1" value={feedback} onChange={(e) => setFeedback(e.target.value)}
                placeholder="e.g. Prefer an in-person visit; requester knows Maya" />
            </div>
          </div>
          {error && <ErrorNote message={error} />}
          <div className="flex flex-wrap items-center justify-end gap-2">
            {willReplan && <span className="mr-auto text-xs text-amber-800">Owner change will trigger a re-plan with your feedback.</span>}
            <button className="btn-secondary" disabled={busy} onClick={() => submit("replan")}>
              <RefreshCw className="h-4 w-4" /> Request re-plan
            </button>
            <button className="btn-secondary" disabled={busy || (nSel === 0 && !willReplan)} onClick={() => submit("selected")}>
              <ClipboardCheck className="h-4 w-4" /> Approve selected ({nSel})
            </button>
            <button className="btn-amber" disabled={busy} onClick={() => submit("all")}>
              <CheckCheck className="h-4 w-4" /> Approve all permitted ({pending.length - rejected.size})
            </button>
          </div>
        </div>
      )}

      {decided.length > 0 && (
        <div>
          <div className="mb-1.5 text-[13px] font-semibold text-slate-700">Decisions &amp; execution in this version</div>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {decided.map((a) => (
              <li key={a.action_id} className="flex items-center justify-between gap-3 px-3 py-2 text-[12.5px]">
                <div className="min-w-0">
                  <div className="truncate text-slate-800">{a.title}</div>
                  <div className="text-[11px] text-slate-500">
                    {a.approval_status === "carried_over" ? `carried over from ${a.carried_from}` : a.approval_status.replace(/_/g, " ")}
                    {a.approval?.reviewer ? ` · ${a.approval.reviewer.replace("HUMAN:", "")}` : ""}
                    {a.tool_result?.error ? ` · ${a.tool_result.error}` : a.tool_result?.summary ? ` · ${a.tool_result.summary}` : ""}
                  </div>
                </div>
                <ExecBadge status={a.execution_status} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
