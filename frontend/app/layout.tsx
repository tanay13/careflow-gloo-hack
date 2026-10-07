import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "CareFlow · Care coordination agent",
  description: "Human-in-the-loop pastoral care coordination agent (hackathon prototype, synthetic data)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="border-b border-amber-200 bg-amber-50 px-6 py-1.5 text-center text-xs text-amber-800">
              Prototype · <strong>all people, cases, schedules and resources are synthetic</strong> · escalation policy is a
              placeholder, not Flatirons&apos; real protocol
            </div>
            <main className="mx-auto w-full max-w-[1480px] flex-1 px-6 py-6">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
