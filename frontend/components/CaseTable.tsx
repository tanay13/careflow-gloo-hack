"use client";

import Link from "next/link";
import { Loader2, Zap } from "lucide-react";
import type { CaseSummary } from "@/types";
import { fmtShort, humanize } from "@/lib/format";
import { StatusBadge, Tag } from "./ui";

export default function CaseTable({ cases }: { cases: CaseSummary[] }) {
  if (!cases.length) return <div className="px-5 py-8 text-center text-sm text-slate-500">No cases.</div>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
          <th className="px-5 py-2.5 font-semibold">Case</th>
          <th className="px-3 py-2.5 font-semibold">Request</th>
          <th className="px-3 py-2.5 font-semibold">Campus</th>
          <th className="px-3 py-2.5 font-semibold">Owner</th>
          <th className="px-3 py-2.5 font-semibold">Status</th>
          <th className="px-5 py-2.5 text-right font-semibold">Updated</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr key={c.case_id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/70">
            <td className="px-5 py-3 align-top">
              <Link href={`/cases/${c.case_id}`} className="whitespace-nowrap font-mono text-[13px] font-semibold text-brand-700 hover:underline">
                {c.case_id}
              </Link>
              {c.plan_version ? <div className="text-[11px] text-slate-500">plan v{c.plan_version}</div> : null}
            </td>
            <td className="max-w-[480px] px-3 py-3 align-top">
              <Link href={`/cases/${c.case_id}`} className="line-clamp-2 text-slate-700 hover:text-slate-900">
                {c.request_text}
              </Link>
              <div className="mt-1 flex flex-wrap gap-1">
                {c.urgent && (
                  <Tag tone="amber">
                    <Zap className="h-3 w-3" /> same-day
                  </Tag>
                )}
                {c.needs.slice(0, 4).map((n) => (
                  <Tag key={n}>{humanize(n)}</Tag>
                ))}
                {c.duplicate_of && <Tag tone="rose">possible duplicate of {c.duplicate_of}</Tag>}
              </div>
            </td>
            <td className="px-3 py-3 align-top text-slate-700">{c.campus || <span className="text-slate-400">—</span>}</td>
            <td className="px-3 py-3 align-top text-slate-700">{c.owner_name || <span className="text-slate-400">—</span>}</td>
            <td className="px-3 py-3 align-top">
              <div className="flex items-center gap-1.5">
                <StatusBadge status={c.status} />
                {c.is_running && <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-600" />}
              </div>
            </td>
            <td className="whitespace-nowrap px-5 py-3 text-right align-top text-xs text-slate-500">{fmtShort(c.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
