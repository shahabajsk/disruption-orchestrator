export interface Step {
  state: string;
  note: string;
}

export interface Row {
  id: string;
  kind: string;
  says: string;
  replies: string | null;
  expected: string;
  got: string;
  ok: boolean;
  reason: string;
  fingerprint: string;
  skill_calls: number;
  retries: number;
  rolled_back: boolean;
  trace: Step[];
  messages: string[];
}

export interface Run {
  model: string;
  contacts: number;
  correct_resolution: number;
  resolved_without_agent: number;
  duplicate_payments: number;
  seats_leaked: number;
  out_of_policy_payments: number;
  ungrounded_messages_sent: number;
  out_of_policy_requests_blocked: number;
  ungrounded_drafts_caught: number;
  retries_absorbed: number;
  rollbacks: number;
  rows: Row[];
}

export interface Report {
  runs: Run[];
}
