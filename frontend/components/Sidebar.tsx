"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ClipboardList, FlaskConical, HeartHandshake, LayoutDashboard, PlusCircle, ScrollText, ShieldCheck } from "lucide-react";
import clsx from "clsx";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/cases/new", label: "New care request", icon: PlusCircle },
  { href: "/cases", label: "Case queue", icon: ClipboardList },
  { href: "/audit", label: "Audit log", icon: ScrollText },
  { href: "/evaluations", label: "Evaluations", icon: FlaskConical },
  { href: "/policy", label: "Policy & tools", icon: ShieldCheck },
];

export default function Sidebar() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-700 text-white">
          <HeartHandshake className="h-5 w-5" />
        </div>
        <div>
          <div className="text-[15px] font-semibold text-slate-900">CareFlow</div>
          <div className="text-[11px] text-slate-500">Care coordination agent</div>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 px-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" : path === href || (href !== "/cases" && path.startsWith(href)) ||
            (href === "/cases" && path.startsWith("/cases/") && !path.startsWith("/cases/new"));
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                active ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="m-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-600">
        <div className="mb-1 font-semibold text-slate-700">Bounded autonomy</div>
        CareFlow coordinates logistics. Pastoral, crisis and financial judgment stay with people.
      </div>
    </aside>
  );
}
