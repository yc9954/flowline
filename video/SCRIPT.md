# Flowline — 90-second demo video, production script

Format 1920×1080 · 30 fps. Voice first (Higgsfield · Eleven v4, preset voice Holden): lay the narration down, cut screens to it.
Story v3: **problem → market → product → test case → the simulation (time-lapse) → demo (collect · learn · act: six desks live, then the whole runs at 50×) → results → close.** The gym chain is
introduced as the *test case* (cut 04), never as the problem. Cuts 07–11 come from one model run (`data/out`) so every
number agrees; cards take their numbers from `out/cards.json`. Cuts 06, 07, 10 are real Mac takes; cut 11 is the live six-desk wall (filming rig), cut 12 its time-lapse.
Honest labels: "simulated team" on the test card and cut 05; the only real-data number is 7.4× vs 5.7× (US Census backtest).

Sources: `card` = `cards.html?card=…` recorded by `record_board.mjs`; `board` = web app route recorded with Playwright at
1920×1080 (1440×900 @ DPR 4/3); `mac` = screen recording of the Flowline menu-bar app (ffmpeg avfoundation, 3024×1964 →
crop below the menu bar → 1920×1080).

> **v4 (final, 2-minute cut, 117.8 s):** the order became problem → market → product → test case → collect (notch, review) → learn (knowledge, zoomed) → find (waits → nine plans) → **propose** (suggestion notch, never on its own) → **act** (six desks, one knowledge, mid-work) → **hand back** (the whole runs at 50×) → **the simulation** (eleven weeks replayed) → results → results card → the loop → end card. Cut numbers, targets and narration lines are the source of truth in `vo.py` (`CUTS`), supers/chapter chips in `supers_from_data.py` / `build.py` (`CHAPTER`), recording recipes in `record_board.mjs`. Subtitles = the narration, centred; chapter chips top-left/centre. The table below is the earlier 90-second version kept for reference.

| # | Target | VO (Holden, tempo 1.15) | Super | Source | Motion |
|---|---|---|---|---|---|
| 01 | 8.5 s | Small multi-site businesses run on processes nobody wrote down. Work waits more than it's worked — and when someone leaves, the process leaves with them. | — | card `problem` | Three lines land with the voice; evidence row (58 % use AI · 14 % in operations · 0 system logs). Fade in. |
| 02 | 6 s | Six million small firms in the US alone. The tools that map work need system logs. They have none. | — | card `market` | 6.4 M firms · $3.1 B → $23 B process mining · $121 B fitness; the gap line; first customer. |
| 03 | 7.5 s | Not an ERP — a company-level agent. Everyone's approved days join one hub; it finds the bottleneck, proposes the fix to the people it affects, and does the work. | Multiplayer AI for the whole company · one hub · proposes first, then does the work | board `/surfaces` | Five surfaces assemble fast (≤ 1.3 s), wires draw. |
| 04 | 4.5 s | Our test case: Northwind Fitness, a simulated chain — three gyms, eight people. | — | card `test` | Name, facts, simulated/real-data note. |
| 05 | 8.5 s | We ran the chain for eleven simulated weeks: eight people, three hundred approved days, every hand-off and every wait — on a world engine, not a script. | — | `sim.html` (records replayed) | Time-lapse: 55 working days × 8 people fill in; counters run (week, approved days, steps, hands-on h, waiting h, proposals). |
| 06 | 4.3 s | At six, each laptop drafts how the day actually went. | Northwind Fitness · simulated team · on-device, nothing sent until approved | mac: `--demo-day --eod-now`, notch open | "Your day is drafted · 7 items · Review"; menu-bar panel. |
| 07 | 4.3 s | Personal things are left out. Nothing leaves until you approve it. | Personal items never leave the laptop | mac: review → Approve → record sheet | Left-out column; Approve; record sheet. |
| 08 | 5 s | Approved records become one knowledge of how the business works — learned, not drawn. | 18 steps · 7 roles — learned, not drawn | board `/know/knowledge` | Lanes, nodes, loops. |
| 09 | 7 s | It finds a proposal takes a hundred and nine hours, eighty-five waiting — and tests nine fixes on the same team, same luck. | 25 h for one signature · 9 plans tested on the same team | board `/know/waits` → `/improve/plans` | Wait bar; hard cut to the nine plans. |
| 10 | 3.2 s | Then it asks only the people it affects. | Asked only of the person it affects | mac, live: busy desk (deck · sheet · inbox) → open suggestion notch → Do it → wave glow | The six runs start here. |
| 11 | 8.5 s | Six desks start at once, each on its own job: quotes read off PDFs, a sheet corrected, decks filled, packets exported and mailed to the director. | Six desks · six jobs · one approval each · filmed side by side for this demo | `wall.html` (filming rig), live | 3×2 live desks, wave glow, labelled cursors; window chosen with `out/start.json` (11). |
| 12 | 5.5 s | Seven minutes at fifty times speed: every run ends left for a person to check. Nothing saved, nothing sent outside, without one. | The whole runs at 50× · every one left for a person · nothing saved or sent outside without one | cut 11's whole take at 50× (build.py) | Time-lapse to "left for you ✓" on every desk. |
| 13 | 4.5 s | Cycle time: a hundred and nine hours to eighty-eight. The test said ninety-one. | 109 h → 87.7 h · the test predicted 91.4 | board `/improve/results` → `/decide/expand` | Dots drop; 7.4× counts up. |
| 14 | 7.5 s | Ten of ten runs correct, zero leaks. On real Census data, its picks were 7.4 times as likely to get new gyms. | — | card `results` | Six stats: 109 → 88 h · 10/10 · 0 leaks · 7.4× (real) · 18 days · 4/4 checks with the misses named. |
| 15 | 4.2 s | Flowline. The agent that runs your company's work — with your people. | Flowline — the agent that runs the company's work, with its people | board `/improve/history` | The loop fills (no return to the hero). |
| 16 | 1.8 s | — | — | `endcard.html` → PNG | Logo, tagline, GitHub URL (placeholder), fade out. |

Targets sum to 90.3 s; `build.py` stretches a cut to its VO + 0.6 s when the voice runs longer, so trim VO text first, not the cuts.

## Pipeline (`video/`)

1. `supers_from_data.py` — reads `data/out` + `data/runs/measure*.json`, writes `supers.json`, `out/vo_text.json` (data-driven lines 08, 11, 12) and `out/cards.json`.
2. `vo.py` — writes `out/timing.json`; `vo_higgsfield.py [--cuts …] [--force]` generates the narration into `out/vo/NN.wav` (vo.py prefers an existing wav; `say` is only the fallback).
3. `record_board.mjs --base http://localhost:5173 --only 1,2,3,4,5,8,9,13,14,15` — cards and board routes via the CDP screencast → `out/cuts/NN.mp4`.
4. `stage_mac.sh sheet && record_mac_cuts.sh 6 && record_mac_cuts.sh 7` · `stage_mac.sh busy && record_mac_cuts.sh 10` (starts the PM's run; the API fans out the five pre-approved runs; the script launches `record_board.mjs --only 11` for the wall — a 7-minute take, `FLEET_HOLD_MS`; build.py derives cut 12 at 50×).
5. `out/start.json` — `{"11": <seconds>}` to choose the live window. `node render_endcard.mjs <github url>` → `out/cuts/16.png`.
6. `build.py [--music track.mp3]` — crop/scale, supers (Pillow PNG overlay), VO mix, fades on 01 and 16, concat → `out/flowline-90s.mp4`.

Capture notes: Retina 3024×1964 → crop below the menu bar (its clock is the real time) → 1920×1080. Light mode, Dock hidden,
backdrop window hides the desktop. No zoom pushes anywhere (ffmpeg zoompan jitters at small zoom factors).
