"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Church, ClipboardList, FlaskConical, LayoutDashboard, PlusCircle, ScrollText, ShieldCheck } from "lucide-react";
import clsx from "clsx";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/cases/new", label: "New care request", icon: PlusCircle },
  { href: "/cases", label: "Requests", icon: ClipboardList },
  { href: "/audit", label: "Full record", icon: ScrollText },
  { href: "/evaluations", label: "Quality checks", icon: FlaskConical },
  { href: "/policy", label: "How it works", icon: ShieldCheck },
];

export default function Sidebar() {
  const path = usePathname();
  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-[#eadfcb] bg-gradient-to-b from-amber-50 via-[#fdf9f2] to-white">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-700 to-brand-900 text-white shadow-sm">
          <Church className="h-5 w-5" />
        </div>
        <div>
          <div className="font-display text-[17px] font-semibold text-slate-900">CareFlow</div>
          <div className="text-[11px] text-slate-500">Here to help you care for people</div>
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
                active ? "bg-amber-100/80 text-amber-950 shadow-sm" : "text-slate-600 hover:bg-amber-50 hover:text-slate-900"
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="m-3 rounded-xl border border-[#eadfcb] bg-white/80 p-3 text-[11px] leading-relaxed text-slate-600">
        <div className="font-display mb-1 text-[12px] font-semibold text-slate-700">A gentle helper, not a replacement</div>
        CareFlow handles the paperwork and logistics, so you can spend your time with people.
      </div>
    </aside>
  );
}
