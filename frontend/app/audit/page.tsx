"use client";

import { useState } from "react";
import { ScrollText } from "lucide-react";
import AuditTable from "@/components/AuditTable";
import { ErrorNote } from "@/components/ui";
import { usePoll } from "@/lib/hooks";
import type { AuditEvent } from "@/types";

const ACTORS = ["", "SYSTEM", "AGENT", "POLICY", "TOOL", "VERIFIER", "HUMAN", "EVENT"];

export default function AuditPage() {
  const [caseId, setCaseId] = useState("");
  const [actor, setActor] = useState("");
  const q = new URLSearchParams({ limit: "500" });
  if (caseId) q.set("case_id", caseId.trim().toUpperCase());
  if (actor) q.set("actor", actor);
  const { data, error } = usePoll<AuditEvent[]>(`/audit?${q.toString()}`, 3000);
  const events = [...(data || [])].reverse();
  const blocked = events.filter((e) => e.status === "blocked").length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900"><ScrollText className="h-6 w-6 text-brand-700" /> Full record</h1>
          <p className="mt-1 text-sm text-slate-500">
            Every step CareFlow takes, written down where everyone can see it. Nothing here can be edited or deleted afterwards.
          </p>
        </div>
        <div className="flex gap-2">
          <input className="input w-36" placeholder="Case e.g. CF-1042" value={caseId} onChange={(e) => setCaseId(e.target.value)} />
          <select className="input w-36" value={actor} onChange={(e) => setActor(e.target.value)}>
            {ACTORS.map((a) => <option key={a} value={a}>{a || "All actors"}</option>)}
          </select>
        </div>
      </div>
      {error && <ErrorNote message={error} />}
      <div className="flex gap-3 text-xs text-slate-600">
        <span className="chip border-slate-200 bg-white">{events.length} entries</span>
        <span className="chip border-rose-200 bg-rose-50 text-rose-800">{blocked} stopped for safety</span>
      </div>
      <div className="card overflow-hidden">
        <AuditTable events={events} showCase />
      </div>
    </div>
  );
}
