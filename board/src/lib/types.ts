// Shapes from /Users/yuchanlee/flowline/SCHEMA.md. The UI renders exactly these; nothing here is invented.

export type Source = 'measured' | 'simulated' | 'prototype';

export type Role =
  | 'Client' | 'Sales' | 'PM' | 'Design' | 'Finance' | 'Director' | 'Legal'
  | 'Trainer' | 'BranchMgr' | 'Ops' | 'CEO';

export interface Sourced { source?: Source | string; recomputed_at?: string }

// §2 Approved record
export interface RecordStep {
  idx: number; start: string; end: string; name: string; kind: 'hands_on' | 'waiting';
  case_id?: string; tools: string[]; handoff_from?: Role; handoff_to?: Role; waiting_on?: Role; repeats?: number;
}
export interface WorkRecord {
  id: string; board_id: string; person_id: string; role: Role; date: string;
  covers: { start: string; end: string }; steps: RecordStep[]; kept_private: number;
  hands_on_min: number; waiting_min: number; approved_at: string; hash: string; pubkey: string; sig: string;
}

// §3 Ontology
export interface OntNode {
  id: string; name: string; kind: 'event' | 'step' | 'decision' | 'skill'; role: Role; aliases: string[];
  median_min?: number; cases: number; wait_before_h?: number; share_of_cycle?: number; critical_path: boolean;
  bottleneck?: boolean; sub?: string; rule?: string;
}
export interface OntEdge { from: string; to: string; kind: 'then' | 'back' | 'parallel'; share?: number; wait_h?: number; label?: string }
export interface Ontology extends Sourced {
  board_id: string; version: number; recomputed_at: string; records_used: number;
  roles: { role: Role; steps: number; external?: boolean }[];
  nodes: OntNode[]; edges: OntEdge[];
  counts: { roles: number; steps: number; cases: number; files: number; rules: number; skills: number; customers: number; zip_areas: number; branches: number };
  headline: string;
}

// §4 Finding
export interface MapStep { role: Role; name: string; hands_on_h: number; artifact: string; wait_after_h?: number; longest_wait?: boolean; selected?: boolean }
export interface Finding extends Sourced {
  board_id: string; process: string; records: number; people: number; weeks: number; headline: string; sub: string;
  kpis: { cycle_time_h: number; waiting_share: number; small_quotes_share: number; small_quotes_unchanged: number; repeated_by_hand_h_per_wk: number };
  map: MapStep[]; to_scale: { hands_on_h: number; waiting_h: number };
  sent_back: { reason: string; by?: Role; back_to: string; cost: string; share: number }[];
  repeated: { task: string; who: Role; count_per_wk: number; minutes: number; agent_can_do: boolean }[];
}

// §5 Plans
export type PlanRule =
  | { type: 'auto_approve_under'; usd: number }
  | { type: 'approver_batches_per_day'; n: number }
  | { type: 'skill'; skill_id: string; actor: Role; reviewer?: Role }
  | { type: 'template'; name: string };
export interface Plan {
  id: string; rank: number; name: string; sub: string; hours: number; work_h: number; waiting_h: number; vs_today: number;
  best: boolean; today: boolean; held_best_n: number; range_h: [number, number]; who: { role: Role; change: string }[]; rules: PlanRule[];
}
export interface PlansPage extends Sourced { board_id: string; reruns: number; weeks: number; headline: string; today_h: number; plans: Plan[]; note: string }

// §6 Results
export interface Results extends Sourced {
  board_id: string; headline: string; sub: string; records: number; people: number; weeks: number; weeks_after?: number; change: string;
  predicted: { mid: number; lo: number; hi: number }; measured: number;
  series: { week: number; value: number; after: boolean }[];
  kpis: { label: string; before: string; after: string; sub: string }[];
  who: { role: Role; what: string; before: string; after: string }[];
  next_constraint: { headline: string; sub: string; ready: boolean };
}

// §7 History
export interface LoopStep { n: number; name: string; at?: string; status: 'done' | 'now' | 'pending'; note: string }
export interface Version { v: number; when: string; title: string; found: string; status: 'live' | 'needs_yes' | 'baseline'; delta_h: number; predicted_delta_h?: number }
export interface History extends Sourced { board_id: string; headline: string; baseline_h?: number; now_h?: number; loop: LoopStep[]; next_run_at: string; versions: Version[]; learned: { finding: string; action: string }[] }

// §8 Model check
export interface ModelCheck extends Sourced {
  board_id: string; calibrated_at: string; records: number;
  components: { n: string; name: string; what: string; size: string }[];
  sim_checks: { measure: string; predicted: number; lo: number; hi: number; actual: number; unit: 'h' | '%' | '/day'; in_range: boolean }[];
  demand: { industry: string; naics: string; lift: number; population_lift: number; ci: [number, number]; verdict: 'better' | 'tie' }[];
  d1: { dataset: string; fit_year: number; test_year: number; median_error: number; p80_error: number; cases: number; events: number; amount_attr: boolean };
  limits: { title: string; tag: string; why: string }[];
}

// §9 Expansion (flat, as the API returns it)
export interface ZipRow { zip: string; name: string; why: string[]; predicted: number; happened: number; rank: number; pick: boolean; lat: number; lon: number }
export interface BacktestIndustry { naics: string; name: string; lift: number; population_lift: number; ci: [number, number]; verdict: 'better' | 'tie' }
export interface Expansion extends Sourced {
  board_id: string; city: string; industries: { naics: string; name: string }[]; industry: string;
  headline: string; sub: string; zips_considered: number; branches: number; records: number; rank_of: number;
  opening: { date: string; was: string; blockers_cleared: number };
  zips: ZipRow[];
  backtest: { frozen_at: number; scored_on: number; n_zips: number; lift: number; ci: [number, number]; by_industry: BacktestIndustry[]; pooled: { lift: number; population_lift: number } };
}
// Fixture file shape: shared fields + by_industry[naics] = the industry-specific part of Expansion.
export interface ExpansionFixture extends Sourced {
  board_id: string; city: string; industries: { naics: string; name: string }[]; default: string; records: number; branches: number;
  by_industry: Record<string, Omit<Expansion, 'board_id' | 'city' | 'industries' | 'records' | 'branches' | 'source'>>;
}

// §10 Opening
export interface Workstream { name: string; owner: Role; agent: boolean; start: string; end: string; status: 'done' | 'on_track' | 'waiting' | 'todo'; saved_d?: number; due?: string; progress?: [number, number] }
export interface Blocker { id: string; title: string; status: 'cleared' | 'waiting_on_you' | 'in_progress'; saved_d?: number; due?: string; was: string; agent: string; decided_by: Role; surface: 'inbox' | 'notch' | 'weekly_digest' }
export interface Opening extends Sourced {
  board_id: string; branch: number; zip: string; name: string; playbook_from: string; steps: number; headline: string;
  opens: string; was: string; today: string; workstreams: Workstream[]; blockers: Blocker[];
}

// §11 Surfaces
export interface Surfaces extends Sourced {
  ceo_line: string; finance_inbox: { title: string; sub: string; actions: string[] }[];
  branch_mgr_blocker: { title: string; actions: string[] }; expansion_lead: { zip: string; rank: number }[];
  trainer_record: { steps: number; left_out: number };
}
