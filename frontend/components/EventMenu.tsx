"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarX2, CarFront, ChevronDown, PackageX, PlugZap, ServerCrash, Zap } from "lucide-react";
import type { CaseDetail } from "@/types";
import { api } from "@/lib/api";

/** "Simulate Event" demo control. Each option mutates real backend state. */
export default function EventMenu({ c, onDone, onError }: { c: CaseDetail; onDone: () => void; onError: (m: string) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  const plan = c.plans.find((p) => p.plan_id === c.current_plan_id);
  const vols = (plan?.actions || []).filter((a) => a.subtype === "volunteer_assignment" &&
    ["executed", "carried_over", "pending"].includes(a.execution_status) && !["not_selected", "rejected"].includes(a.approval_status));
  const planEvents = ["MONITORING", "AWAITING_APPROVAL"].includes(c.status);

  async function fire(body: Record<string, unknown>) {
    setBusy(true);
    setOpen(false);
    try {
      await api.post(`/cases/${c.case_id}/events`, body);
      onDone();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const Item = ({ icon: Icon, label, hint, onClick, disabled }: { icon: any; label: string; hint: string; onClick: () => void; disabled?: boolean }) => (
    <button disabled={disabled} onClick={onClick}
      className="flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">
      <Icon className="mt-0.5 h-4 w-4 text-slate-500" />
      <div>
        <div className="text-[13px] font-medium text-slate-800">{label}</div>
        <div className="text-[11px] text-slate-500">{hint}</div>
      </div>
    </button>
  );

  return (
    <div className="relative" ref={ref}>
      <button className="btn-secondary" disabled={busy || c.is_running} onClick={() => setOpen(!open)}>
        <Zap className="h-4 w-4 text-amber-600" /> Simulate event <ChevronDown className="h-3.5 w-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1.5 w-80 rounded-xl border border-slate-200 bg-white p-1.5 shadow-lg">
          {vols.length > 0 ? vols.map((a) => (
            <Item key={a.action_id} icon={CarFront} label={`Volunteer cancelled: ${a.parameters.assignee_id}`}
              hint={`${a.title.replace("Assign driver ", "")}`} disabled={!planEvents}
              onClick={() => fire({ type: "volunteer_cancelled", target: a.parameters.assignee_id })} />
          )) : (
            <Item icon={CarFront} label="Volunteer cancelled" hint="No active volunteer assignment" disabled onClick={() => undefined} />
          )}
          <Item icon={PackageX} label="Resource unavailable" hint="First planned/reserved resource goes out of stock" disabled={!planEvents}
            onClick={() => fire({ type: "resource_unavailable" })} />
          <Item icon={CalendarX2} label="Staff calendar conflict" hint="External meeting lands on the first appointment slot" disabled={!planEvents}
            onClick={() => fire({ type: "staff_calendar_conflict" })} />
          <div className="my-1 border-t border-slate-100" />
          <Item icon={ServerCrash} label="Tool outage (persistent)" hint="A tool this case uses fails until restored; retry once, then ERROR"
            onClick={() => fire({ type: "tool_outage", mode: "persistent" })} />
          <Item icon={ServerCrash} label="Tool outage (transient)" hint="Fails once; the retry succeeds"
            onClick={() => fire({ type: "tool_outage", mode: "transient" })} />
          <Item icon={PlugZap} label="Restore tools" hint="Clear all simulated outages" onClick={() => fire({ type: "tool_restored" })} />
        </div>
      )}
    </div>
  );
}
