import Link from "next/link";
import clsx from "clsx";
import type { AuditEvent } from "@/types";
import { fmtTime, ms } from "@/lib/format";

const ACTOR_TONE: Record<string, string> = {
  SYSTEM: "bg-slate-100 text-slate-700",
  AGENT: "bg-brand-50 text-brand-800",
  POLICY: "bg-indigo-50 text-indigo-800",
  TOOL: "bg-sky-50 text-sky-800",
  VERIFIER: "bg-violet-50 text-violet-800",
  HUMAN: "bg-amber-50 text-amber-900",
  EVENT: "bg-orange-50 text-orange-800",
};

export default function AuditTable({ events, showCase }: { events: AuditEvent[]; showCase?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wide text-slate-500">
            <th className="px-3 py-2 font-semibold">Time</th>
            {showCase && <th className="px-3 py-2 font-semibold">Case</th>}
            <th className="px-3 py-2 font-semibold">Actor</th>
            <th className="px-3 py-2 font-semibold">Event</th>
            <th className="px-3 py-2 font-semibold">Tool</th>
            <th className="px-3 py-2 font-semibold">Summary</th>
            <th className="px-3 py-2 font-semibold">Plan</th>
            <th className="px-3 py-2 font-semibold">Approval</th>
            <th className="px-3 py-2 text-right font-semibold">Latency</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.event_id} className={clsx("border-b border-slate-50 align-top",
              e.status === "blocked" && "bg-rose-50/60", e.status === "error" && "bg-orange-50/60", e.status === "warn" && "bg-amber-50/40")}>
              <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11.5px] text-slate-500">{fmtTime(e.timestamp)}</td>
              {showCase && (
                <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11.5px]">
                  {e.case_id ? <Link className="text-brand-700 hover:underline" href={`/cases/${e.case_id}`}>{e.case_id}</Link> : "—"}
                </td>
              )}
              <td className="px-3 py-1.5">
                <span className={clsx("rounded px-1.5 py-0.5 text-[10.5px] font-semibold", ACTOR_TONE[e.actor] || ACTOR_TONE.SYSTEM)}>{e.actor}</span>
              </td>
              <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11.5px] text-slate-700">
                {e.event_type}
                {e.status !== "ok" && <span className="ml-1 text-[10px] uppercase text-slate-500">({e.status})</span>}
              </td>
              <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11.5px] text-sky-800">{e.tool_name || ""}</td>
              <td className="min-w-[320px] px-3 py-1.5 text-slate-700">{e.output_summary}</td>
              <td className="px-3 py-1.5 text-center text-slate-600">{e.plan_version ? `v${e.plan_version}` : ""}</td>
              <td className="whitespace-nowrap px-3 py-1.5 font-mono text-[11px] text-amber-800">{e.approval_ref || ""}</td>
              <td className="whitespace-nowrap px-3 py-1.5 text-right font-mono text-[11px] text-slate-500">{e.latency_ms != null ? ms(e.latency_ms) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
