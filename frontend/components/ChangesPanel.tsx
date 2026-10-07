import clsx from "clsx";
import { CalendarCheck2, ListTodo, Mail, Package } from "lucide-react";
import type { CaseDetail } from "@/types";
import { fmtDateTime } from "@/lib/format";
import { EmptyState } from "./ui";

function StatusPill({ s }: { s: string }) {
  const tone =
    s === "open" || s === "held" || s === "active" ? "border-emerald-300 bg-emerald-50 text-emerald-800" :
      s === "done" ? "border-slate-300 bg-slate-100 text-slate-700" :
        s === "sent_demo_outbox" ? "border-indigo-300 bg-indigo-50 text-indigo-800" :
          s === "draft" ? "border-slate-200 bg-white text-slate-600" : "border-orange-300 bg-orange-50 text-orange-800";
  return <span className={clsx("chip", tone)}>{s === "sent_demo_outbox" ? "sent (demo outbox)" : s}</span>;
}

/** Real records created by approved tool executions (not UI state). */
export default function ChangesPanel({ c }: { c: CaseDetail }) {
  const ch = c.changes;
  const empty = !ch.tasks.length && !ch.calendar_holds.length && !ch.reservations.length && !ch.messages.length;
  if (empty) return <EmptyState>No changes yet. Records appear here once approved actions execute.</EmptyState>;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="card">
        <div className="card-header"><div className="card-title"><CalendarCheck2 className="h-4 w-4 text-brand-700" /> Calendar holds</div></div>
        <ul className="divide-y divide-slate-50">
          {ch.calendar_holds.map((h) => (
            <li key={h.block_id} className="flex items-center justify-between px-5 py-2.5 text-[13px]">
              <div>
                <div className="font-medium text-slate-800">{fmtDateTime(h.start)}</div>
                <div className="text-xs text-slate-500">{h.staff_name} · {h.hold_id}</div>
              </div>
              <StatusPill s={h.status} />
            </li>
          ))}
          {!ch.calendar_holds.length && <li className="px-5 py-3 text-xs text-slate-500">None</li>}
        </ul>
      </div>
      <div className="card">
        <div className="card-header"><div className="card-title"><ListTodo className="h-4 w-4 text-brand-700" /> Tasks</div></div>
        <ul className="divide-y divide-slate-50">
          {ch.tasks.map((t) => (
            <li key={t.task_id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-[13px]">
              <div className="min-w-0">
                <div className={clsx("truncate font-medium text-slate-800", t.status === "cancelled" && "line-through text-slate-400")}>{t.title}</div>
                <div className="text-xs text-slate-500">
                  {t.task_id} · {t.kind === "volunteer_assignment" ? "volunteer" : t.assignee_type}: {t.assignee_name || t.assignee_id || "—"}
                  {t.due ? ` · ${fmtDateTime(t.due)}` : ""}
                  {t.details?.cancel_reason ? ` · ${t.details.cancel_reason}` : ""}
                </div>
              </div>
              <StatusPill s={t.status} />
            </li>
          ))}
          {!ch.tasks.length && <li className="px-5 py-3 text-xs text-slate-500">None</li>}
        </ul>
      </div>
      <div className="card">
        <div className="card-header"><div className="card-title"><Package className="h-4 w-4 text-brand-700" /> Resource reservations</div></div>
        <ul className="divide-y divide-slate-50">
          {ch.reservations.map((r) => (
            <li key={r.reservation_id} className="flex items-center justify-between px-5 py-2.5 text-[13px]">
              <div>
                <div className="font-medium text-slate-800">{r.resource_name}</div>
                <div className="text-xs text-slate-500">{r.reservation_id} · {r.resource_id} · qty {r.quantity}</div>
              </div>
              <StatusPill s={r.status} />
            </li>
          ))}
          {!ch.reservations.length && <li className="px-5 py-3 text-xs text-slate-500">None</li>}
        </ul>
      </div>
      <div className="card">
        <div className="card-header"><div className="card-title"><Mail className="h-4 w-4 text-brand-700" /> Messages</div></div>
        <ul className="divide-y divide-slate-50">
          {ch.messages.map((m) => (
            <li key={m.message_id} className="px-5 py-2.5 text-[13px]">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-500">{m.message_id} · {m.channel}</span>
                <StatusPill s={m.status} />
              </div>
              <p className="mt-1 line-clamp-3 text-xs text-slate-600">{m.body}</p>
            </li>
          ))}
          {!ch.messages.length && <li className="px-5 py-3 text-xs text-slate-500">None</li>}
        </ul>
      </div>
    </div>
  );
}
