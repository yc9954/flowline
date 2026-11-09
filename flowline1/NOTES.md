# flowline1 — notes, deviations and contract questions

Build: `uv run python -m flowline1 build --out ../data/out --seed 15` (about 10 s). `uv run python -m flowline1 check`
prints the BUILD-PLAN §4 metrics. `uv run pytest` runs the tests. Paths resolve from the repo root (parent of this
directory) or `FLOWLINE_ROOT`; downloads go under `<root>/data/raw`.

## What is measured, simulated, prototype

| File | source | How it is computed |
|---|---|---|
| records.jsonl | simulated | Northwind world engine (SimPy), one record per person per working day with activity |
| ontology.json, finding.json, plans.json, results.json, history.json, opening.json, surfaces.json | simulated | mined / fitted / simulated from those records |
| model.json | simulated (top level) | `sim_checks` simulated vs records; `d1` is **measured** (BPIC 2020); `demand` is **measured** (US Census). The schema has one `source` per file, so the measured blocks inside carry their dataset names in text. |
| expansion.json | measured | US Census backtest (see D2 below) |
| truth.json, calibration.json, plan_detail.json | simulated | extra files: the world's answer key (used only by `check`), baseline-simulation error, per-plan per-seed detail |

## Contract questions / deviations (SCHEMA.md is not edited)

1. **expansion.json shape** follows the coordinator's decision: one file, shared top-level fields plus
   `default: "713940"` and `by_industry[naics]` = an Expansion object per §9. Each inner object has `source: "measured"`;
   the dataset attribution ("US Census ZBP/CBP 2014–2023, ACS 2015–19") is in `sub`.
2. **Hours are on a Mon–Fri 24 h calendar**: cycle time = brief start → first send end with weekend hours removed, nights kept.
   Waiting = cycle − union of hands-on intervals. The storyboard's 50 h / 54 % cannot be reproduced with the given step medians
   under any single calendar (22 h of hands-on plus a 19 h signature wait already exceeds 41 h), so the engine's own numbers
   are reported: baseline ≈ 100–110 h with ≈ 75–78 % waiting, the signature wait ≈ 20 h.
3. **Wait attribution**: a node's `wait_before_h` is the median time a case sat waiting for that step, plus the overnight tail
   after a step that itself ended outside working hours (the Director signs at ~18:00, so Design cannot start before 09:00:
   those hours belong to the signature). Edge `wait_h` is the raw gap. Both are medians. **Finding.map is the condensed main path**
   (7 rows, one per hand-off: Brief, Estimate, Margin check, Approval, Deck, Review, Send), "to scale, one proposal": per
   completed case, each row's **elapsed stage span** (its steps' work plus the nights inside them — a 5 h estimate always
   straddles one) and the idle gap after it (the board labels a wait with the next row's role; the overnight after a step that
   ended outside working hours belongs to the wait *for* that step, so the Director's ~18:00 signature puts its ~20 h on the
   Margin-check row as "Waiting for the Director"). Per-row medians are scaled so that hands_on + waits sum exactly to
   kpis.cycle_time_h; to_scale repeats those sums; the headline uses the longest map wait. **Caveat**: on this strip
   `hands_on_h` is therefore the stage's elapsed time, not pure hands-on, while `kpis.waiting_share` (78 %) counts nights inside
   stages as waiting. The alternative accounting (pure hands-on, nights attributed to the hand-off before them) makes the PM
   stage's wait (~29 h, mostly the night inside the estimate) the longest instead of the signature; it is a one-line switch in
   `miner.py` and the integrator should pick the convention the board explains.
   `sent_back[].cost` is the median added time per loop on the 09–18 working calendar ("+1.5 days" = 13.5 working hours).
4. **Quote amounts** are not a Record field; the Director's approval step names carry them ("Approve quote $4,400"), as a window
   title would. The miner strips them for entity resolution and reads them for `small_quotes_share` / auto-approve fitting.
   Likewise the *reason* a step was sent back is the qualifier people record after a dash ("Internal review — changes: figures").
5. **Record.hash** is the §12 canonical SHA-256 over the Record fields; the extra top-level `source` key is excluded from the hash.
   `pubkey`/`sig` are empty strings (unsigned, as allowed).
6. **PlansPage.weeks** is the baseline length (8), not 2: plans are replayed over the same 8 weeks the baseline covered, because
   a 2-week horizon has ~6 cases and its median is too noisy to rank plans. `range_h` is the 10th–90th percentile of the per-rerun
   medians (said in `note`); ModelCheck ranges likewise.
7. **Results.predicted** repeats the Plans page figure (same test); `measured` and `sim_checks.actual` come from the records
   after the change, not from the world's answer key. The answer key is compared only in `check`. The change is measured over
   **three** weeks of records (`--weeks-after 3`), not two: cycles run ~4 working days, so a 2-week window leaves only ~3
   proposals that both started and were sent inside it.
8. **Ontology.counts**: `customers` = proposals that reached negotiation, `files` = distinct artifacts implied by step tools,
   `rules` = decisions + discovered batching rules, `zip_areas` = Austin ZIPs considered (98, prefixes 786/787), `branches` = 3.
9. **One baseline everywhere**: completed proposals whose brief started in the baseline window, measured from approved records
   (108.8 h / 78 %). **Finding** is mined from exactly those cases' records (its cycle equals that baseline; asserted in the
   build); **Ontology** from all records (v15). Finding.records counts the records holding those cases' steps.
   `History.sub` (not in the schema) carries the "v1 → now" line; extra keys `recomputed_at` on plans and `calibration_errors`,
   `entity_resolution`, `d1_detail` on model.json are additive.
10. **Design has two people** (design-1, design-2). With one designer and 9.4 h decks at ~4 requests/week the designer runs above
    90 % utilisation and queues dominate everything; the task listed roles, not head-counts.
11. **Plans/History are relative effects applied to the measured baseline**: `today_h` = 108.8 h; each plan's `hours`,
    `work_h`, `waiting_h` and `range_h` = simulated value × (measured baseline ÷ simulated baseline), so `vs_today` is the
    simulated relative change (stated in `note`). The simulator's own baseline (115.2 h, 5.8 % high) and the scale factor are in
    `calibration.json`. History version deltas are simulated deltas on the same scale, labelled "simulated" in `found`; the sum
    of v12–v14 (simulated) and the measured change are both given in `history.sub`. Results.predicted repeats the Plans figure
    and ModelCheck's "Hours per proposal" check uses that same prediction; the former degenerate "wait around the signature"
    check is now "Signature wait for quotes the Director still signs" (dropped when no such case exists in the window).

## Declared assumptions the records cannot provide (simulator.py)

- Agent fills the deck: 1 min agent + 3 min PM review, 5 % undo (then the PM redoes it by hand). The agent also removes review
  send-backs that people recorded as "changes: figures" (an exact copy from the sheet), at the share measured in the records.
- Shared deck template: removes send-backs recorded as "changes: layout"; no measured deck-time effect yet, so none is modelled.
  In this world layout send-backs are rare, so the template ties with "deck by hand".
- Export-PDF skill (v14): Send step → 1.5 min.
- Hidden truth of the world (truth.json): Director batches once a day at ~18:00; 71 % of quotes under $5k, 2 % of those sent back
  for missing figures vs 40 % of larger ones; review send-backs 18 % figures / 9 % layout / 8 % wording; margin < 25 % 22 %;
  revise 30 %; win 41 %; arrivals ≈ 4/week; the PM also fills pricing for ~5 membership renewals a week (a second process in
  the records, with its own case ids).

## Metrics vs BUILD-PLAN §4 targets

- Bottleneck: the hidden constraint (Approval) ranks #1 by wait — met.
- Name merging: precision 1.00 / recall 1.00 on the planted synonyms — met. The synonym table (13 confirmed merges) plus
  normalisation and token similarity ≥ 0.8 covers every planted variant; in a real deployment the table is what people confirm
  at end-of-day review.
- Plan ranking stability: the best plan held in 12 of 20 reruns — **not met** (target 18). The two leading plans differ by
  ~1.5 h on a ~95 h median; in this world removing the signature wait only pays off when it moves the deck across a day
  boundary, and "twice a day" catches many of the same cases. Reported as computed.
- Predicted vs measured: 4 of 4 checks in range (10th–90th percentile of 20 reruns over the measured horizon) — met.
  Measured after the change: 87.7 h from records (86.4 h world truth) over 6 proposals vs 91.4 h predicted (86.2–114.6, scaled).
- D1 (real): 2017 fit → 2018, cycle-time median error ≈ 17.5 %, P80 error ≈ 4.1 % — median **not within 15 %**. The model is a
  semi-Markov chain (activity routing + lognormal wait per transition) fitted on 2,240 cases from two departments; 2018 covers
  the whole university (8,260 cases). `Amount` exists (median ≈ €42, 78 % under €100). Largest 2017 wait: Request Payment → Payment
  Handled. Rejection loops in 10 % of 2017 cases. Licence CC BY-NC 4.0: demo use only.
- D2 (real): loaded from reference results computed 2026-11-08 with the same scripts (ported as `demand.backtest`, run with
  `python -m flowline1 demand --recompute`, several minutes; the build then prefers `data/out/demand/`). Fitness 7.4× vs 5.7×,
  coffee 6.0× vs 5.1×, physicians 5.4× vs 5.5× (tie), pooled 6.3× vs 5.2×. `why` tags are each ZIP's standout 2020 features
  (robust z-score vs the national distribution), not model attributions.

## Not done / known gaps

- Opening (§10) is a playbook table with declared durations from "branches 2 and 3"; the dates are computed from today's date and
  the saved days, but the playbook itself is not learned from records (there are no branch-opening records in the world).
- pm4py is not used (lxml streaming parser instead). No LLM is used anywhere: names are resolved by rules.
- The world runs on wall-clock arithmetic in local time; DST (1 Nov 2026) is handled by comparing wall-clock times, not UTC.
- `check` reports the Director sign-offs/day calibration error at ~19 % (the fitted send-back rate for large quotes comes from a
  handful of cases); the three primary KPIs are within 6 %.

## `fit` — the ten files from any company's records (branch `generalize`)

```bash
uv run python -m flowline1 fit --records <export.json|.ndjson> --out ../data/boards/<id>/out [--industry <naics>] \
    [--process <case prefix>] [--seeds 20] [--plans auto|plans.json] [--since YYYY-MM-DD] [--approvals approvals.json] \
    [--start-step NAME] [--end-step NAME] [--board-id ID] [--city "Austin, TX"] [--zips 786,787] [--bootstrap 20]
```
No world: `miner.mine(records, MineOptions(...))` learns the process (most-stepped case prefix), the measured cycle
(first main-path step done by the team → the common terminal step; `--start-step/--end-step` override), the map rows
(one per role run on the main path), the outside parties (`waiting_on` roles that never record: Client, Insurer...) and the
working hours (5th/95th percentile of hands-on times). `generic.fit` then calibrates a simulator from the mining alone:
lognormal hands-on minutes per step (first pass and redo apart), every simulated case replays an observed trace (its
parallel branches, send-back loops and amount), hand-off waits are sampled from the observed business-minute gaps per
transition, an approver whose start times cluster at one hour is a batching approver, outside parties are wall-clock
lognormals, arrivals are Poisson at the measured rate. CRN: `engine.CaseRandom` per case. **No capacity model** (waits are
replayed as measured; one person's freed hours do not shorten another's queue) — stated in `model.json.limits`.

Plans are generated from the mining: approval options (as recorded · twice a day when the approver batches once ·
auto-approve under a round threshold ~65 % of recorded amounts fall under) × work options (by hand · shared template for
the artefact the layout send-backs point at, else the most used document tool · agent does the most repeated hands-on step,
the person reviews). Effects are **relative means over every replayed case** (with 20–30 traces the median flips between
the before/after-the-weekend modes) applied to the measured baseline; ranges are p10–p90 of per-rerun means; a plan within
1 % of the best is a tie broken by how often it won. Declared assumptions: agent 1 min + 3 min review after the usual
hand-off wait, 5 % undone, send-backs unchanged (the gain is the person's hours, shown in `results.who`); a template only
removes send-back loops whose recorded reason mentions layout/format/template/form; auto-approval skips the approval step
and the send-backs it caused.

Baseline = completed cases that *started* before `--since` (or the first approval's date), their later steps included;
"after" = cases started after it. `results.predicted` is the approved plan when it can be matched (id, rules, or name with
"$5k" == "$5,000"), else the best plan. `model.json.sim_checks` are the checks that need no hidden truth: baseline replay
vs measured (hours, waiting share, completed/day, sign-offs/day) and, once measured, hours after the change; plus
`calibration.plan_stability` and `calibration.miner_stability` (20 random 80 % subsets of the completed cases: same
bottleneck? median spread). Planted-bottleneck rank, planted-synonym precision/recall and D1 are listed under
`not_applicable`. Expansion: `--industry` in {713940, 621111, 722515} → the Census backtest (Austin ZIPs by default; `--zips`,
`--city`), else `source: "not_available"` with the reason. Opening: learned only from cases whose prefix looks like an
opening/launch, else `state: "no_data_yet"`. Sparse data (< 20 records, < 2 roles or < 3 completed cases): finding/ontology
from what there is, plans/results/history `state: "not_enough_data"` with `needed`/`have`; never crashes (0 records → stubs).

Validator deviations (validate.py): Role is any non-empty string (a clinic has hygienists — the API's `Role` Literal in
api/api/models.py would need the same relaxation to serve such a board), `source` may be `"not_available"`, Record.source is
optional, pages may carry `state` ∈ {not_enough_data, no_data_yet, awaiting_measurement} (plans may then be empty).
`build` is unchanged: its ten files are byte-identical before and after this branch (`/tmp/fl-build-{before,after}`).

**Northwind fit vs build** (`data/boards/northwind-fit/out`, 309 records from the API, `--approvals` with the chain's change
date 2026-11-30): same 22 baseline cases; learned cycle Qualify → Send = 115.0 h (build's Brief → Send = 108.8 h; with
`--start-step "Write brief" --end-step Send` the fit gives exactly 108.8 h and measured-after exactly 87.7 h), 78 % waiting
both, bottleneck Quote approval both (22.7 h vs 24.7 h on the map), identical send-back table, same repeated step
(fill pricing 8.5×/wk, 16 min). Baseline replay 119.4 h vs 115.0 measured (3.8 %). Plans are more conservative than the
engine's: auto-approve −6 % (build −7 %), twice a day −5 % (build −14 %: the engine's Design queue), agent −1 % (build −5 %:
the engine assumes the agent removes figure send-backs), best = auto-approve + deck template −9 % (build auto + agent −16 %).
Measured after the change 96.4 h over 6 proposals (Qualify → Send) vs the approved plan's prediction 106.9 h (96.2–117.3) —
in range; on Brief → Send 87.7 h vs 100.9 (91.2–111.1) — 3.5 h outside: the fit under-predicts the agent's effect.

**Clinic** (`examples/make_clinic_records.py`, stdlib only, no world.py: 135 records, 5 people, 29 pre-auths, 8 weeks):
bottleneck = Insurer wait (49 h per pre-auth, external), baseline 90.7 h, 98 % waiting; best plan auto-approve claims under
$500 + agent does the eligibility check (−8.6 %, held 15/20); expansion `not_available` for NAICS 621210; 4/4 replay checks.
