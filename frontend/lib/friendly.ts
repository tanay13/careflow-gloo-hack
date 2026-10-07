// Plain-language layer for pastors. Technical systems keep their exact names in the
// audit log and evaluations screens; everywhere else we translate.

import type { AuditEvent } from "@/types";

export const STATUS_LABELS: Record<string, string> = {
  NEW: "New",
  NORMALIZED: "Understanding",
  SAFETY_CHECKED: "Safety checked",
  CONTEXT_GATHERED: "Gathering info",
  PLAN_PROPOSED: "Making a plan",
  VERIFIED: "Double-checked",
  AWAITING_APPROVAL: "Needs your decision",
  APPROVED: "Approved",
  EXECUTING: "Putting it in motion",
  MONITORING: "Being cared for",
  RESOLVED: "Complete",
  ESCALATED: "Needs a person",
  CANCELLED: "Closed",
  ERROR: "Needs attention",
};

export function statusLabel(s: string): string {
  return STATUS_LABELS[s] || s.replace(/_/g, " ").toLowerCase();
}

export const PIPELINE_LABELS: Record<string, string> = {
  NEW: "Received",
  NORMALIZED: "Understood",
  SAFETY_CHECKED: "Safety",
  CONTEXT_GATHERED: "Gathering",
  PLAN_PROPOSED: "Plan",
  VERIFIED: "Checked",
  AWAITING_APPROVAL: "Your decision",
  APPROVED: "Approved",
  EXECUTING: "In motion",
  MONITORING: "Watching",
  RESOLVED: "Complete",
};

const TOOL_TITLES: Record<string, string> = {
  "staff.search": "Looking for the right pastor",
  "calendar.read": "Checking calendars for open times",
  "calendar.hold": "Reserving a calendar time",
  "calendar.release": "Freeing up a calendar time",
  "resource.search": "Looking through approved resources",
  "resource.reserve": "Setting aside resources",
  "resource.release": "Releasing reserved resources",
  "volunteer.search": "Looking for volunteer drivers",
  "task.create": "Organizing tasks",
  "task.cancel": "Cancelling a task",
  "task.complete": "Completing tasks",
  "message.draft": "Drafting a message (not sent)",
  "message.send": "Sending your approved message",
  "case.update": "Updating the case record",
  "audit.append": "Writing to the record",
};

/** Soften backend summaries: drop internal markers, turn codes into words. */
export function soften(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(" (mock)", "").replace(/(\w+)\(s\)/g, "$1s").replace(/_/g, " ");
}

export function friendlyTitle(e: AuditEvent): string {
  switch (e.event_type) {
    case "case.created": return "New request received";
    case "duplicate.suspected": return "Looks like a request we've seen";
    case "run.started": return "CareFlow started helping";
    case "request.normalized": return "Understood the request";
    case "safety_check": return e.status === "warn" ? "Safety concern — stopped here" : "Safety check passed";
    case "prompt_injection.neutralized": return "Ignored hidden instructions in the text";
    case "tool.call": return TOOL_TITLES[e.tool_name || ""] || e.tool_name || "Working";
    case "tool.retry": return "Trying again";
    case "tool.error": return "Something didn't work";
    case "tool.blocked": return "CareFlow stopped itself — permission needed";
    case "tool.conflict": return "Plans clashed — finding another way";
    case "plan.generated": return `Care plan v${e.plan_version} is ready`;
    case "verifier.result": {
      const s = e.output_summary || "";
      if (s.startsWith("PASS")) return "Double-checked — everything holds up";
      if (s.startsWith("ESCALATE")) return "Double-checked — a person needs to step in";
      return "Double-checked — improving the plan";
    }
    case "verifier.pre_execution": {
      const s = e.output_summary || "";
      return s.startsWith("PASS") ? "Re-checked just before acting — all good" : "Something changed — re-checking the plan";
    }
    case "replan.started": return "Improving the plan";
    case "approval.requested": return (e.output_summary || "").startsWith("New") ? "Something changed — your OK is needed again" : "Waiting for your decision";
    case "plan.reviewed": return "You reviewed the plan";
    case "reviewer.feedback": return "Your note to CareFlow";
    case "execution.completed": return "Did what you approved";
    case "volunteer.cancelled": return "A volunteer had to cancel";
    case "resource.unavailable": return "A resource ran out";
    case "calendar.conflict": return "A calendar changed";
    case "tool.outage_injected": return "A helper service went down (practice drill)";
    case "tool.restored": return "Services are back";
    case "plan.invalidated": return "The plan no longer fits — making a new one";
    case "replacement.found": return "Found someone to step in";
    case "replacement.none": return "No one available — asking a person to help";
    case "escalation.created": return "Handed to a person";
    case "case.error": return "Hit a snag — nothing was done halfway";
    case "run.resumed": return "Picked up where it left off";
    case "monitor.ok": return "Checked in — everything still good";
    case "monitor.started": return "Checking in on everything";
    case "tasks.completed": return "Tasks finished";
    case "state.changed": {
      const to = String(e.metadata?.to || "");
      if (to === "MONITORING") return "Keeping watch";
      if (to === "RESOLVED") return "All done";
      if (to === "ESCALATED") return "Handed to a person";
      return "Making progress";
    }
    default: return (e.tool_name && TOOL_TITLES[e.tool_name]) || e.event_type.replace(/_/g, " ").replace(/\./g, " · ");
  }
}

/** Events worth showing in a pastor-facing feed. Low-level transitions are hidden. */
export function showInFeed(e: AuditEvent): boolean {
  if (e.event_type === "state.changed") {
    const to = String(e.metadata?.to || "");
    return to === "MONITORING" || to === "RESOLVED" || to === "ESCALATED";
  }
  return !["run.started", "context.gathered", "replan.started", "run.resumed",
    "monitor.started", "tool.retry", "tool.restored", "reviewer.feedback"].includes(e.event_type);
}

export function friendlyDetail(e: AuditEvent): string | null {
  const s = e.output_summary || "";
  switch (e.event_type) {
    case "case.created": return "The original words are kept exactly as written.";
    case "request.normalized": return prettyNormalized(s);
    case "plan.generated": return prettyPlan(s);
    case "verifier.result": {
      const m = s.match(/(\d+) checks passed/);
      return m ? `${m[1]} separate checks passed.` : soften(s.replace(/^\w+ - /, ""));
    }
    case "approval.requested": return prettyApproval(s);
    case "replacement.found": return soften(s);
    case "state.changed": return null;
    case "tool.call":
      if (e.tool_name === "message.draft") return "The message is ready — it stays unsent until you approve.";
      return soften(s);
    default: return soften(s) || null;
  }
}

/** "campus=Lafayette; needs=pastoral conversation, transportation; timeframe=this week; urgent=False"
 *  → "Campus: Lafayette · Needs: pastoral conversation, transportation · When: this week". */
function prettyNormalized(s: string): string {
  const parts: string[] = [];
  const campus = s.match(/campus=([^;]+)/);
  if (campus && campus[1].trim() && campus[1].trim() !== "unknown") parts.push(`Campus: ${campus[1].trim()}`);
  const needs = s.match(/needs=([^;]+)/);
  if (needs && needs[1].trim() && needs[1].trim() !== "unclear") parts.push(`Needs: ${soften(needs[1].trim())}`);
  const when = s.match(/timeframe=([^;]+)/);
  if (when && when[1].trim() !== "unspecified") parts.push(`When: ${soften(when[1].trim())}`);
  if (/urgent=True/.test(s)) parts.push("Same-day request");
  return parts.join(" · ") || soften(s);
}

/** "Approval required: 7 consequential action(s), 2 policy-permitted reversible action(s)"
 *  → "7 things need your OK · 2 simple tasks included". */
function prettyApproval(s: string): string {
  const m = s.match(/(\d+) consequential action\(s\), (\d+) policy-permitted reversible action\(s\)/);
  if (m) {
    const simple = m[2] === "0" ? "" : ` · ${m[2]} simple ${m[2] === "1" ? "task" : "tasks"} included`;
    return `${m[1]} ${m[1] === "1" ? "thing needs" : "things need"} your OK${simple}.`;
  }
  return soften(s);
}

/** "Plan v1 (mock): owner=Jordan Lee; 2 appointment option(s); ..." → plain words. */
function prettyPlan(s: string): string {
  let t = soften(s).replace(/^Plan v\d+: /, "");
  t = t.replace(/owner=([^;]+)/, "Suggested: $1");
  t = t.replace(/(\d+) appointment option\(s\)/, "$1 visit times");
  t = t.replace(/(\d+) volunteer task\(s\)/, "$1 volunteer rides");
  t = t.replace(/(\d+) resource\(s\)/, "$1 resources");
  t = t.replace(/0 unresolved/, "nothing left open");
  t = t.replace(/(\d+) unresolved/, "$1 open items");
  return t;
}

const CHECK_NAMES: Record<string, string> = {
  safety_flags: "Safety re-checked",
  entity_provenance: "Everyone and everything comes from trusted lists",
  entity_exists: "Everyone and everything is real",
  staff_eligibility: "Right person for the need",
  availability_checked: "Times were actually looked up",
  calendar_conflict: "No double-booking",
  appointment_owner: "Visit is with the assigned pastor",
  double_booking: "No overlapping bookings",
  volunteer_eligibility: "Volunteer is qualified and free",
  resource_check: "Resources available and allowed",
  resource_availability: "Resources available and allowed",
  resource_restriction: "Resources available and allowed",
  tool_permission: "Nothing beyond CareFlow's permission",
  forbidden_action: "Nothing off-limits included",
  forbidden_judgment: "Respectful, appropriate wording",
  unsupported_claim: "Every detail traced to a real record",
  data_minimization: "Private details kept private",
  content_scan: "Respectful, appropriate wording",
  approval_gate: "Your approval required",
  completeness: "Plan is complete",
  unresolved_need: "Open item handed to a person",
};

export function checkName(check: string): string {
  return CHECK_NAMES[check] || check.replace(/_/g, " ");
}

const TRIGGER_TEXT: Record<string, string> = {
  initial: "First plan",
  reviewer_feedback: "Updated with your feedback",
  pre_execution_drift: "Updated after something changed",
  resume: "Updated after a retry",
};

const EVENT_TRIGGER_TEXT: Record<string, string> = {
  volunteer_cancelled: "Updated after a volunteer cancelled",
  resource_unavailable: "Updated after a resource ran out",
  staff_calendar_conflict: "Updated after a calendar changed",
  tool_outage: "Updated after a service hiccup",
  execution_conflict: "Updated after plans clashed",
  monitor_detected_change: "Updated after a routine check-in",
};

export function triggerText(trigger: string | null | undefined): string {
  if (!trigger) return "";
  if (TRIGGER_TEXT[trigger]) return TRIGGER_TEXT[trigger];
  if (trigger.startsWith("event:")) {
    const key = trigger.slice("event:".length);
    return EVENT_TRIGGER_TEXT[key] || "Updated after something changed";
  }
  return trigger.replace(/_/g, " ");
}
