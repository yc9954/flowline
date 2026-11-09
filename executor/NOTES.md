# executor — notes, decisions, contract questions

## How to run

```sh
cd /Users/yuchanlee/flowline/executor
set -a; source /Users/yuchanlee/flowline/.env; set +a      # ANTHROPIC_API_KEY, FLOWLINE_MODEL (never printed)

uv run pytest                                               # sheet reader, canonical hash/sig, compiler segmentation, coordinate scaling
(cd agent-ts && npm install)                                # ai + @ai-sdk/anthropic + zod (Node ≥ 24)
uv run python assets/make_assets.py                         # .fods/.fodp → ods/odp on desk1 (soffice headless) → /config/Documents + assets/
uv run uvicorn main:app --port 8790                         # Run API (SCHEMA §11). NOTE: port 8790 is taken on this Mac, see below
curl -X POST localhost:8790/runs -H 'content-type: application/json' \
     -d '{"suggestion_id":"sug-1","skill_id":"fill_deck_from_sheet","target":"desk1","inputs":{}}'
curl localhost:8790/runs/<id>            # poll 500 ms
curl -X POST localhost:8790/runs/<id>/stop
uv run python observer.py --container desk1 --time-scale 10 --duration 600   # Events → data/runs/observer/desk1/<date>.jsonl
uv run python actor.py --speed 10                                            # the PM's day on desk1; truth → data/runs/actor-<stamp>.json
uv run python compiler.py --events data/runs/observer/desk1/<date>.jsonl     # DraftDay → signed Record → POST :8787 (saved regardless)
uv run python measure.py --runs 10 --privacy --speed 10                      # data/runs/measure.json + data/runs/privacy.json
```

Files: `agent-ts/run.mjs` + `skills.mjs` (the agent loop: Vercel AI SDK `ToolLoopAgent`, Anthropic computer toolset),
`main.py` (Run API + desktop bridge), `bridge.py` (one Desktop per target, action execution, coordinate mapping),
`skills/fill_deck_from_sheet.py` (prepare → spawn agent → verify), `runs.py` (Run/RunStep, event → step mapping),
`desktop.py` (Desktop, DockerDesktop, MacDesktop, ViewScale), `lo.py` (soffice + UNO helpers inside the container),
`sheet.py`, `privacy.py` (masking, denylist), `observer.py`, `actor.py`, `compiler.py`, `measure.py`,
`assets/make_assets.py`, `bin/desk` (shell into desk1).

Deployment: `FLOWLINE_DESK_HOST` = ssh host of the docker engine (default `mini`) or `local` when running on the mini itself
(docker at /opt/homebrew/bin/docker or on PATH); `FLOWLINE_ROOT` (default: parent of this directory) for data/runs;
`FLOWLINE_EXECUTOR_PORT` / `FLOWLINE_EXECUTOR_URL` for the bridge the agent calls; `FLOWLINE_NODE` to pick a node binary.
`requires-python = ">=3.12"`; uv manages the interpreter.

## Decisions

* **Agent loop = Vercel AI SDK** (`ai` 7.0.x, `@ai-sdk/anthropic` 4.0.x): `ToolLoopAgent({model: anthropic(FLOWLINE_MODEL),
  instructions, tools, stopWhen: stepCountIs(25)})`. Tools: `anthropic.tools.computerToolset_20260801` (the only computer-use
  shape `claude-sonnet-5-5` accepts on the Claude API; GA, no beta header, no display size — coordinates are in the pixel space of
  the screenshots we return), `anthropic.tools.bash_20250124`, and `tool()`s `read_sheet`, `read_deck_cells`, `report_step`.
  The SDK starts a step's tool calls concurrently, so every `execute` goes through one promise chain (`serial`) to keep
  "click, then type" in call order — without it a batched `type` landed before its `left_click` (seen in the first run).
  The Python side never talks to the model: it owns the desktop (bridge), maps agent events to RunSteps, kills the child on
  Stop and verifies the outcome deterministically.
* **Screenshots** are scaled to 1280×720 for the model (`ViewScale`), the model's coordinates are multiplied by 1.5 in
  `bridge.perform`; full-size PNGs of every screenshot are kept under data/runs/<id>/.
* **Reading the deck back without saving**: the GUI soffice is started with a UNO socket (`--accept=socket,host=127.0.0.1,port=2002`)
  and `lo.py` reads the live table model (`cells`), jumps to the slide (`goto`), checks `isModified`, and closes without saving
  (`close`, used by measure.py to reset). This is more exact than `--convert-to txt` on a temp copy (which would need a Save-a-Copy
  through the GUI) and leaves the document modified-and-unsaved as the design requires. The file's sha256 is compared before/after.
* **Cell positions** come from the model's own screenshot (one before filling); the skill opens the deck on the slide and
  checks the amount cells are empty first (`amount_cells_empty_before`). Impress has no reliable keyboard "select cell text"
  (ctrl+a / Home-End either do nothing in edit mode or jump slides), so a dirty deck is reset by closing without saving
  (measure.py) rather than cleared through the GUI. Verification after the agent exits: UNO read-back of the four cells vs
  the sheet, items sum, file sha256 unchanged, `isModified` true.
* **Per-action latency** is dominated by the ssh round trip to `mini` (~0.3 s even over the ControlMaster; the mini is not on
  the LAN). A persistent `docker exec -i python3` helper inside the container keeps it to one round trip per action
  (click ≈ 0.3–0.4 s, type ≈ 0.4 s, screenshot ≈ 0.5–0.7 s incl. 230 KB transfer). The observer streams one line per second
  through one such pipe instead of three execs per sample.
* **Observer idle**: `xprintidle` was not in the image (installed into the running desk1 with apt; **add it to
  `flowline/desk:1`**). Without it idle is derived from title/pointer changes, which counts typing as idle (the first privacy
  run split the mail step on that).
  `--time-scale N` stamps events as if the actor's day at `--speed N` were real time (both share `--origin`), so the compiler's
  5-min/2-min thresholds apply unchanged.
* **Privacy**: denylisted windows (chat / bank keywords on title or WM_CLASS) are recorded with empty `title_hash`/`title_masked`
  and a device-only `private` kind; names are masked from `names.txt` plus Title-Case bigrams (allow-list for app words);
  `file_hint` is the masked file name. The compiler turns these into `left_out` (`counted_as_away`, `removed`, `renamed`).
* **Mac backend**: screenshot (Retina: 3024×1964 px for 1512×982 pt, `Screenshot.scale == 2`), mouse move, idle, window title
  tested; clicks/typing/keys implemented with CGEvents but not exercised on this machine, per the brief.
* **Fast `POST /runs`**: the Run (status running, `title` "Filling proposal #172 pricing from your sheet", step 1 "now") is
  returned at once; desktop setup, soffice, the agent and verification all run in the background thread. `POST
  /desk/{target}/warm` (also run at service startup for `FLOWLINE_WARM_TARGETS`, default `desk1`) starts an *invisible* GUI
  soffice with the UNO socket, so the first run opens the deck in ~2 s instead of a cold start. At the end of a run the deck is
  closed without saving (file untouched) so the desktop is clean for the next run; `inputs.leave_open: true` keeps it open.
* Actor/observer clocks: both take `--origin` and the observer `--time-scale` = actor `--speed`, so the recorded day reads as
  real time. Each actor step's clock starts once its document is on screen (LibreOffice launches are not the PM's work).
* Key for the Linux compiler: `~/.flowline/key` (base64 Ed25519 seed, 0600). `~/.flowline/dev_key` already existed (another
  component's) and is untouched.

## Measured (2026-11-09, desk1 on the mini over ssh from this Mac, model claude-sonnet-5-5)

Execution agent — `data/runs/measure.json` (10 runs through POST /runs, deck reset between runs by closing without saving):
* success **10/10** (all four cells exact, items sum = deck total = sheet total $4,290, file sha256 unchanged, document left modified)
* run duration median **36.5 s**, P90 **40.3 s**, min 33.6 s, max 45.9 s (wall clock from POST /runs to status done; includes
  ~6 s to open/activate the deck and ~1 s of Python verification); median 8 model turns, 3 screenshots per run
* Stop honoured: run stopped **2.1 s** after POST /runs/{id}/stop (sent once FILL THE DECK showed [1, 4])
* per action (ssh+docker round trip dominated, mini is not on the LAN): click 410 ms, type 391 ms, key 403 ms, screenshot 501 ms
  (1920×1080 PNG ≈ 230 KB, then scaled to 1280×720 for the model), active title 284 ms
* the first end-to-end run before `serial` (see Decisions) took 80 s: a batched `type` ran before its `left_click`, the agent
  then repaired the cells itself through read_deck_cells — the deterministic checks still passed.

Privacy test — `data/runs/privacy.json` (actor at --speed 10 ≈ 6.5 min real = 63 min of PM day; observer at --time-scale 10;
compiler with Claude step names):
* planted personal items in the signed Record: **0 of 3** (Personal chat · Mom, First National Bank — Login, Kim Minji
  contract.odt); `left_out` = personal_chat/counted_as_away, banking/removed, name_in_filename/renamed
* step-boundary F1 **0.80** (precision 0.667, recall 1.0, 6/6 true boundaries found within 90 s; 3 extra boundaries: an idle
  stretch while LibreOffice launched before the first document appeared, a 2-min "review email and pricing" segment while the
  deck was being opened, and the fill step split in two) — below the ≥ 0.85 target; the extra boundaries are real app switches,
  so the next lever is a longer merge window for same-case alternation (calc ↔ impress on proposal #172), not the model.
* 382 events, 9 record steps, hands-on/waiting minutes computed from the scaled clock; POST to :8787 refused (API not up) —
  record saved at data/runs/record-1109-3fa9.json and verifies (`compiler.verify_record`).

## Needs attention

* **Port 8790 is already bound** on this Mac by an unrelated `python -m http.server 8790` (cwd `/Users/yuchanlee/airlock/demo`,
  started Sep 19). Everything here was tested on **8791** (`FLOWLINE_EXECUTOR_PORT=8791`); stop that process or point the board
  at 8791. A service instance is still running on 8791 from this session.
* `xprintidle` must be added to the `flowline/desk:1` image (installed by hand into the running desk1).
* Instrument Sans is not installed in `flowline/desk:1`; the assets use DejaVu Sans.
* Board API (`:8787`) was not up during testing; records were saved to `data/runs/record-<id>.json` (POST result recorded in
  `privacy.json`).

## Contract questions (for SCHEMA.md owner)

1. `Run` has no field for the final screenshot path, the action log, the model used or the error text. Added as extra keys
   (`final_screenshot`, `actions[]`, `model`, `error`, `finished_at`, `timing`). Should any become part of §11?
2. `RunStep.progress` while filling is `[k, 4]` (3 items + Total = four cells). The Agent design text says "Four line items and the
   total" — the sheet has three items; step 1 detail reads "3 line items and the total … $4,290".
3. `Record.id` example `"1106-0412"`: I use `MMDD-<first 4 hex of sha256(person_id)>`. Is the suffix a person code or a time?
4. `Event` has no slot for the on-device privacy classification; I added `private: "personal_chat"|"banking"|null` (never leaves
   the device). OK to document in §1?
5. `Skill.inputs` is `{sheet, deck, slide}`; I also accept `max_steps` (agent step limit, default 25).
6. Idle events with `idle_s ≥ 300` become a `waiting` step named "Away from desk"; `DraftStep.kind` only has hands_on|waiting —
   is "away" (no `waiting_on`) acceptable or should it be a `LeftOut`?
7. Which Role is the actor's `person_id`? Using `pm-1`, role `PM`, board `northwind`.
