"use client";

import Link from "next/link";
import { PlusCircle } from "lucide-react";
import CaseTable from "@/components/CaseTable";
import { ErrorNote } from "@/components/ui";
import { usePoll } from "@/lib/hooks";
import type { CaseSummary } from "@/types";

export default function CasesPage() {
  const { data, error } = usePoll<CaseSummary[]>("/cases", 3000, (d) => d.some((c) => c.is_running));
  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Case queue</h1>
          <p className="mt-1 text-sm text-slate-500">All care requests and where each one sits in the workflow.</p>
        </div>
        <Link href="/cases/new" className="btn-primary">
          <PlusCircle className="h-4 w-4" /> New care request
        </Link>
      </div>
      {error && <ErrorNote message={error} />}
      <div className="card overflow-hidden">
        <CaseTable cases={data || []} />
      </div>
    </div>
  );
}
