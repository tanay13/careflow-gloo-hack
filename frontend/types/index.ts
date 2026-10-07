// Shapes returned by the CareFlow FastAPI backend.

export type CaseStatus =
  | "NEW" | "NORMALIZED" | "SAFETY_CHECKED" | "CONTEXT_GATHERED" | "PLAN_PROPOSED" | "VERIFIED"
  | "AWAITING_APPROVAL" | "APPROVED" | "EXECUTING" | "MONITORING" | "RESOLVED" | "ESCALATED" | "CANCELLED" | "ERROR";

export interface CaseSummary {
  case_id: string;
  created_at: string;
  updated_at: string;
  source: string;
  campus: string | null;
  status: CaseStatus;
  request_text: string;
  needs: string[];
  urgent: boolean;
  sensitivity_flags: string[];
  owner_name: string | null;
  plan_version: number | null;
  is_running: boolean;
  current_step: string | null;
  duplicate_of: string | null;
}

export interface AuditEvent {
  event_id: number;
  case_id: string | null;
  timestamp: string;
  actor: string;
  event_type: string;
  status: string;
  tool_name: string | null;
  input_summary: string | null;
  output_summary: string | null;
  plan_version: number | null;
  approval_ref: string | null;
  latency_ms: number | null;
  metadata: Record<string, unknown>;
}

export interface Evidence {
  campus_match?: boolean;
  role_match?: boolean;
  experience_match?: string[];
  availability_checked?: boolean;
  poc_match?: boolean;
  active?: boolean;
  free_slots_found?: number;
  routing_rule?: string;
}

export interface Owner {
  staff_id: string;
  name?: string;
  role?: string;
  reason: string;
  evidence: Evidence;
}

export interface AppointmentOption {
  option_id: string;
  staff_id: string;
  start: string;
  end: string;
  mode: string;
  reason: string;
}

export interface VolunteerTask {
  task_key: string;
  volunteer_id: string | null;
  name?: string | null;
  label?: string;
  location?: string;
  appointment_time?: string;
  start: string;
  end: string;
  reason: string;
  replacement?: boolean;
}

export interface ResourceAction {
  resource_id: string;
  name?: string;
  category?: string;
  action: "reserve" | "share_info";
  quantity: number;
  approval_required?: boolean;
  kind?: string;
  reason: string;
}

export interface Unresolved {
  need: string;
  detail: string;
  severity: "blocking" | "needs_info" | "info";
  escalate?: boolean;
}

export interface Approval {
  approval_id: string;
  reviewer: string;
  decision: string;
  timestamp: string;
  comments: string | null;
}

export interface Action {
  action_id: string;
  plan_id: string;
  type: string;
  subtype: string;
  title: string;
  description: string;
  parameters: Record<string, any>;
  risk_level: "safe" | "approval_required" | "forbidden";
  reversible: boolean;
  approval_status: string;
  execution_status: string;
  tool_result: Record<string, any>;
  carried_from: string | null;
  approval: Approval | null;
}

export interface VerifierCheck {
  check: string;
  status: "pass" | "fail" | "escalate";
  detail: string;
  field?: string;
}

export interface Plan {
  plan_id: string;
  version: number;
  status: string;
  trigger: string;
  created_at: string;
  planner_source: string;
  objective: string;
  known_facts: string[];
  missing_facts: string[];
  owner: Owner | null;
  backup_owner: Owner | null;
  appointment_options: AppointmentOption[];
  resource_actions: ResourceAction[];
  volunteer_tasks: VolunteerTask[];
  internal_tasks: { title: string; assignee_type: string; assignee_id?: string }[];
  message_draft: string | null;
  unresolved_items: Unresolved[];
  forbidden_items: { topic: string; handling: string }[];
  rationale: string;
  required_approvals: string[];
  verifier_status: "PASS" | "REPLAN" | "ESCALATE" | null;
  verifier_result: { status: string; reasons: string[]; invalid_fields: string[]; checks: VerifierCheck[]; feedback: Record<string, unknown> };
  actions: Action[];
}

export interface RunMetrics {
  kind: string;
  started: string;
  wall_ms: number;
  agent_ms: number;
  demo_pause_ms: number;
  tool_calls: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  est_cost_usd: number;
  tokens_estimated: boolean;
  provider: string | null;
  fallbacks: string[];
}

export interface CaseDetail extends CaseSummary {
  requester_ref: string;
  intake_form: Record<string, any>;
  consent_flags: Record<string, boolean>;
  structured_needs: Record<string, any>;
  safety_result: Record<string, any>;
  escalation: Record<string, any>;
  error: Record<string, any>;
  summary: string | null;
  metrics: { runs?: RunMetrics[]; totals?: Record<string, any> };
  current_plan_id: string | null;
  context: {
    staff_candidates: any[];
    staff_excluded: any[];
    routing_rule: string | null;
    availability: Record<string, { free_slots: { start: string; end: string }[]; busy: { start: string; end: string }[] }>;
    window: { start: string; end: string } | null;
    resources: any[];
    ride_tasks: any[];
    feedback: Record<string, any>;
  };
  plans: Plan[];
  changes: {
    tasks: { task_id: string; kind: string; title: string; assignee_type: string; assignee_id: string | null; assignee_name: string | null; due: string | null; status: string; details: any }[];
    calendar_holds: { block_id: number; hold_id: string; staff_id: string; staff_name: string; start: string; end: string; status: string }[];
    reservations: { reservation_id: string; resource_id: string; resource_name: string; quantity: number; status: string }[];
    messages: { message_id: string; channel: string; recipient_ref: string; body: string; status: string; created_at: string; sent_at: string | null }[];
  };
  audit: AuditEvent[];
  names: { staff: Record<string, string>; volunteers: Record<string, string>; resources: Record<string, string> };
}
