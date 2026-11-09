# Flowline — shared data contract

Every component reads and writes these shapes. JSON over HTTP, snake_case keys, ISO‑8601 timestamps
with timezone, hours as decimal numbers (`19.0`), minutes as integers. Money in USD integers.
Owner of this file: integrator. Other components add questions to their own `NOTES.md` instead of editing this.

Ports: `api` 8787 · `board` dev 5173 (served by api in prod at `/`) · `executor` 8790.
Default LLM: `claude-sonnet-5-5` (env `FLOWLINE_MODEL`). API key: env `ANTHROPIC_API_KEY` (never logged).
Board id for the demo: `northwind` (Northwind Fitness, 28 people, 3 clubs, Austin TX).

## 1. On-device (never leaves the machine)

```ts
// Raw activity sample, 1/s, kept only on the device, deleted after the day's record is approved.
Event { ts: string; app: string; title_hash: string; title_masked?: string; file_hint?: string;
        idle_s: number; url_host?: string }

// Draft the compiler produces for the end-of-day review.
DraftDay { person_id: string; role: Role; date: string /* YYYY-MM-DD */; board_id: string;
           steps: DraftStep[]; left_out: LeftOut[]; summary: string /* one sentence, verdict first */ }
DraftStep { idx: number; start: string; end: string; name: string; kind: "hands_on"|"waiting";
            case_id?: string /* "proposal #167" */; tools: string[] /* "sheets","mail",... */;
            handoff_from?: Role; handoff_to?: Role; waiting_on?: Role; repeats?: number /* this week */;
            share: boolean /* checkbox in review, default true */ }
LeftOut { kind: "personal_chat"|"banking"|"name_in_filename"|"other"; label: string;
          minutes?: number; action: "counted_as_away"|"removed"|"renamed" }
```

## 2. Approved record (the only thing that leaves)

```ts
Record { id: string /* "1106-0412" */; board_id: string; person_id: string; role: Role; date: string;
         covers: { start: string; end: string }; steps: RecordStep[]; kept_private: number;
         hands_on_min: number; waiting_min: number;
         approved_at: string; hash: string /* sha256 of canonical JSON of everything above */;
         pubkey: string /* ed25519, base64 */; sig: string /* ed25519 over hash, base64 */ }
RecordStep { idx: number; start: string; end: string; name: string; kind: "hands_on"|"waiting";
             case_id?: string; tools: string[]; handoff_from?: Role; handoff_to?: Role;
             waiting_on?: Role; repeats?: number }
Role = "Client"|"Sales"|"PM"|"Design"|"Finance"|"Director"|"Legal"|"Trainer"|"BranchMgr"|"Ops"|"CEO"
```

POST `/api/boards/{board_id}/records` → 201 `{ id, accepted: true }`. API verifies `sig`, re-hashes, rejects on mismatch (400).
DELETE `/api/boards/{board_id}/records/{id}` = Withdraw (record stays on device).

## 3. Company knowledge (ontology) — `GET /api/boards/{id}/ontology`

```ts
Ontology { board_id: string; version: number /* v15 */; recomputed_at: string; records_used: number;
           roles: { role: Role; steps: number; external?: boolean }[];
           nodes: Node[]; edges: Edge[];
           counts: { roles: number; steps: number; cases: number; files: number; rules: number;
                     skills: number; customers: number; zip_areas: number; branches: number };
           headline: string /* "How a proposal really moves: 18 steps, 7 roles, ..." */ }
Node { id: string; name: string; kind: "event"|"step"|"decision"|"skill"; role: Role;
       aliases: string[]; median_min?: number; cases: number; wait_before_h?: number;
       share_of_cycle?: number /* 0..1 */; critical_path: boolean; bottleneck?: boolean;
       sub?: string /* "fit? 82% yes", "5.0 h · rate card" */; rule?: string }
Edge { from: string; to: string; kind: "then"|"back"|"parallel"; share?: number /* 0..1 */;
       wait_h?: number; label?: string /* "revise quote · 30%" */ }
```

## 4. Where work waits — `GET /api/boards/{id}/finding`

```ts
Finding { board_id; process: string /* "client proposals" */; records: number; people: number; weeks: number;
          headline: string; sub: string;
          kpis: { cycle_time_h: number; waiting_share: number; small_quotes_share: number;
                  small_quotes_unchanged: number; repeated_by_hand_h_per_wk: number };
          map: MapStep[]; to_scale: { hands_on_h: number; waiting_h: number };
          sent_back: { reason: string; by?: Role; back_to: string; cost: string; share: number }[];
          repeated: { task: string; who: Role; count_per_wk: number; minutes: number;
                      agent_can_do: boolean }[] }
MapStep { role: Role; name: string; hands_on_h: number; artifact: string; wait_after_h?: number;
          longest_wait?: boolean; selected?: boolean }
```

## 5. Plans — `GET /api/boards/{id}/plans` · `POST /api/boards/{id}/plans/{plan_id}/approve`

```ts
PlansPage { board_id; reruns: number /* 20 */; weeks: number; headline: string; today_h: number;
            plans: Plan[]; note: string }
Plan { id: string; rank: number; name: string; sub: string; hours: number; work_h: number;
       waiting_h: number; vs_today: number /* -0.42 */; best: boolean; today: boolean;
       held_best_n: number /* 20 */; range_h: [number, number]; who: { role: Role; change: string }[];
       rules: PlanRule[] }
PlanRule = { type: "auto_approve_under"; usd: number } | { type: "approver_batches_per_day"; n: number }
         | { type: "skill"; skill_id: string; actor: Role; reviewer?: Role } | { type: "template"; name: string }
```

## 6. Results — `GET /api/boards/{id}/results`

```ts
Results { board_id; headline: string; sub: string; records: number; people: number; weeks: number;
          change: string; predicted: { mid: number; lo: number; hi: number }; measured: number;
          series: { week: number; value: number; after: boolean }[] /* hours per proposal, by case */;
          kpis: { label: string; before: string; after: string; sub: string }[];
          who: { role: Role; what: string; before: string; after: string }[];
          next_constraint: { headline: string; sub: string; ready: boolean } }
```

## 7. Process history — `GET /api/boards/{id}/history`

```ts
History { board_id; headline: string; baseline_h: number /* v1, measured */; now_h: number /* current, measured or simulated */;
          recomputed_at: string; loop: LoopStep[]; next_run_at: string;
          versions: Version[]; learned: { finding: string; action: string }[] }
LoopStep { n: number; name: "Record"|"Map"|"Find"|"Test"|"Approve"|"Ask & do"|"Measure";
           at?: string; status: "done"|"now"|"pending"; note: string }
Version { v: number; when: string; title: string; found: string; status: "live"|"needs_yes"|"baseline";
          delta_h: number; predicted_delta_h?: number }
```

## 8. Model check — `GET /api/boards/{id}/model`

```ts
ModelCheck { board_id; calibrated_at: string; records: number;
             components: { n: string; name: string; what: string; size: string }[];
             sim_checks: { measure: string; predicted: number; lo: number; hi: number; actual: number;
                           unit: "h"|"%"|"/day"; in_range: boolean }[];
             demand: { industry: string; naics: string; lift: number; population_lift: number;
                       ci: [number, number]; verdict: "better"|"tie" }[];
             d1: { dataset: "BPI Challenge 2020 Domestic Declarations"; fit_year: 2017; test_year: 2018;
                   median_error: number; p80_error: number; cases: number; events: number; amount_attr: boolean };
             limits: { title: string; tag: string; why: string }[] }
```

## 9. Expansion — `GET /api/boards/{id}/expansion?industry=713940`

```ts
Expansion { board_id; city: string; industries: { naics: string; name: string }[]; industry: string;
            headline: string; sub: string; zips_considered: number; branches: number; records: number;
            rank_of: number; opening: { date: string; was: string; blockers_cleared: number };
            zips: { zip: string; name: string; why: string[]; predicted: number; happened: number;
                    rank: number; pick: boolean; lat: number; lon: number }[];
            backtest: { frozen_at: 2020; scored_on: 2023; n_zips: number; lift: number; ci: [number, number];
                        by_industry: { naics: string; name: string; lift: number; population_lift: number;
                                       ci: [number, number]; verdict: "better"|"tie" }[];
                        pooled: { lift: number; population_lift: number } };
            source: string }
// expansion.json on disk holds all industries in one file (decided 2026-11-09 03:20):
// { board_id, city, industries, default: "713940", records, branches, source,
//   by_industry: { "713940": Expansion, "621111": Expansion, "722515": Expansion } }
// The API answers GET ...?industry=X with by_industry[X] merged over the shared top-level fields.
```

## 10. Opening — `GET /api/boards/{id}/opening`

```ts
Opening { board_id; branch: number; zip: string; name: string; playbook_from: string; steps: number;
          headline: string; opens: string; was: string; today: string;
          workstreams: { name: string; owner: Role; agent: boolean; start: string; end: string;
                         status: "done"|"on_track"|"waiting"|"todo"; saved_d?: number; due?: string;
                         progress?: [number, number] }[];
          blockers: { id: string; title: string; status: "cleared"|"waiting_on_you"|"in_progress";
                      saved_d?: number; due?: string; was: string; agent: string;
                      decided_by: Role; surface: "inbox"|"notch"|"weekly_digest" }[] }
```

## 11. Suggestions, runs, surfaces

```ts
// What the notch shows a person. GET /api/people/{person_id}/suggestions
Suggestion { id: string; person_id: string; skill_id: string; title: string /* "Fill this deck's pricing from your sheet?" */;
             body: string; why_now: string; count_last_week: number; minutes_each: number;
             estimate_s: number; plan_id: string; status: "offered"|"accepted"|"declined"|"never"|"done";
             pre_approved?: boolean /* true when the API accepted it on the person's standing yes (data/people.json, FLOWLINE_FLEET=1) */ }
// pre_approved: set only by the fleet fan-out, never by a live answer; the Mac notch shows such a run as "started for you".
// POST /api/suggestions/{id}/respond { answer: "do_it"|"not_now"|"dont_ask" }

// Executor. POST http://localhost:8790/runs { suggestion_id, skill_id, target: "mac"|"desk1", inputs }
Run { id: string; skill_id: string; target: string; title?: string /* "Filling proposal #172 pricing from your sheet" */;
      suggestion_id?: string; status: "running"|"done"|"stopped"|"failed";
      started_at: string; elapsed_s: number; steps: RunStep[]; checks: { name: string; ok: boolean; detail: string }[] }
RunStep { n: number; label: string /* "READ THE SHEET" */; detail: string; status: "done"|"now"|"pending";
          progress?: [number, number]; at_s?: number }
// GET /runs/{id} (poll 500 ms) · POST /runs/{id}/stop

Skill { id: "fill_deck_from_sheet"; version: number; actor: Role; reviewer?: Role;
        steps: string[]; inputs: { sheet: string; deck: string; slide: number }; saves: false }

// Surfaces for the "one knowledge, many surfaces" hero: GET /api/boards/{id}/surfaces
Surfaces { ceo_line: string; finance_inbox: { title: string; sub: string; actions: string[] }[];
           branch_mgr_blocker: { title: string; actions: string[] }; expansion_lead: { zip: string; rank: number }[];
           trainer_record: { steps: number; left_out: number } }
```

## 12. Canonical hash and signature (Mac app, Linux compiler and API must agree)

1. Take the Record without `hash`, `pubkey`, `sig`.
2. Canonical JSON = keys sorted recursively, separators `,` and `:` with no spaces, UTF‑8, non‑ASCII unescaped
   (Python: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`), numbers as shortest
   round‑trip (integers without `.0`).
3. `hash` = lowercase hex SHA‑256 of those bytes.
4. `sig` = Ed25519 signature over the UTF‑8 bytes of the hex `hash` string; `pubkey` and `sig` are standard base64.
Device key: generated once per machine, kept in the OS keychain (Mac) or `~/.flowline/key` (Linux, 0600).

## 13. Honest labels

Every top-level file also carries `recomputed_at` (ISO) so the board can show "recomputed <weekday HH:MM>".


Every page carries `source: "measured"|"simulated"|"prototype"` per block. The board shows a small mono
chip for `simulated` and `prototype`; `measured` shows none. Nothing on screen may claim a number the
API did not compute. Datasets: "BPI Challenge 2020 (TU/e, CC BY-NC 4.0)", "US Census ZBP/CBP 2014–2023, ACS 2015–19".
