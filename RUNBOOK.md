# Flowline — runbook (event day)

Everything heavy runs on the Mac mini (`ssh mini`, repo mirrored at `~/flowline`). This laptop runs the menu-bar
app and records the video. Secrets live in `.env` (gitignored): `ANTHROPIC_API_KEY`, `FLOWLINE_MODEL`.

## Sync and services on the mini

```bash
scripts/sync-mini.sh            # rsync repo + .env to mini:~/flowline (add --setup once on a fresh machine)
```

On the mini (all bound to 127.0.0.1; reach them from the laptop through the tunnels below):

```bash
ssh mini 'bash -lc "cd ~/flowline/api && nohup uv run uvicorn api.main:app --host 127.0.0.1 --port 8787 > ~/flowline/data/api.log 2>&1 &"'
ssh mini 'bash -lc "set -a; source ~/flowline/.env; set +a; export FLOWLINE_DESK_HOST=local FLOWLINE_ROOT=\$HOME/flowline; cd ~/flowline/executor && nohup uv run uvicorn main:app --host 127.0.0.1 --port 8790 > ~/flowline/data/executor.log 2>&1 &"'
ssh -fN -L 18787:localhost:8787 mini      # board + API  → http://localhost:18787
ssh -fN -L 3101:localhost:3101 mini       # desk1 viewer → http://localhost:3101
```

Health: `curl localhost:18787/api/health`, `curl localhost:18787/api/boards/northwind/status` (which file is served from
where, with its `source`), `ssh mini curl -s localhost:8790/health` (executor, shows model and whether the key is set).

Desktops: `ssh mini /opt/homebrew/bin/docker ps` — `desk1` from image `flowline/desk:1` (XFCE 1920×1080, LibreOffice,
xdotool, scrot, xprintidle). New desktop: `docker run -d --name desk2 --network flownet --shm-size=1g -e PUID=1000 -e PGID=1000
-e TZ=America/Chicago -e SELKIES_MANUAL_WIDTH=1920 -e SELKIES_MANUAL_HEIGHT=1080 -p 127.0.0.1:3102:3000 flowline/desk:1`.

## Fleet — six desks, team mail

```bash
scripts/desks.sh up 6 | ls | reset 6 | tunnels 6     # desk1..desk6 (flowline/desk:1) on the mini, viewers 3101–3106
scripts/mail.sh up && scripts/mail.sh seed           # greenmail (SMTP 3025 / IMAP 3143) + Roundcube http://127.0.0.1:3180 — see executor/MAIL.md
scripts/mail.sh desks                                # pinned, logged-in "Northwind Mail :: Inbox" window on every desk
ssh -fN -L 3143:localhost:3143 -L 3025:localhost:3025 mini   # mail helper from the laptop: cd executor && uv run python mail.py list pm
```
API with the fleet on: `FLOWLINE_FLEET=1` (first "Do it" on a plan also starts the pre-approved teammates' runs — the board's people
in the DB, `GET /api/boards/northwind/people`; `data/people.json` was migrated there on first start);
`FLOWLINE_FLEET_SKILL_OVERRIDE=fill_deck_from_sheet` runs everyone on the short skill. Board: `/run/fleet` (state only — role, step rail, last action; the
board never shows a screen; `?frames=1` turns live frames on for development). The six-desk wall for the film is `video/wall.html`
(filming rig, recorded by `record_board.mjs --only 10`). Re-take: `scripts/desks.sh reset 6 && scripts/mail.sh reset all && scripts/mail.sh seed &&
curl -X POST localhost:18787/api/boards/northwind/fleet/reset`. Mail is in-memory: a mini reboot needs `mail.sh up && mail.sh seed` again.

## Onboarding a company (boards & people)

One board per company; boards and people live in the API's SQLite (`data/api.sqlite`, SCHEMA §14). On the first start after
this change the API migrates `data/people.json` into board `northwind` by itself — nothing to do for the demo.

```bash
API=http://localhost:18787
curl -s $API/api/boards | jq                                                  # every board: people, records, has_data
curl -s -X POST $API/api/boards -H 'content-type: application/json' \
  -d '{"name":"Acme Dental Group","industry_naics":"621210","mail_domain":"acme.local","timezone":"America/Chicago"}'
#  → {"id":"acme-dental-group", ...}   (pass "id" to pick the slug yourself)
curl -s -X POST $API/api/boards/acme-dental-group/people -H 'content-type: application/json' \
  -d '{"name":"Dana Whitfield","role":"PM","email":"dana@acme.local","target":"desk1","skill_id":"fill_deck_from_sheet"}'
#  → {"id":"dana-whitfield","invite_code":"K7PX2MRQ","invite_status":"invited", ...}
curl -s $API/api/boards/acme-dental-group/people | jq '.[] | {id, role, email, target, invite_code, invite_status}'
curl -s -X PATCH $API/api/boards/acme-dental-group/people/dana-whitfield -H 'content-type: application/json' -d '{"pre_approved":true}'
curl -s -X POST $API/api/boards/acme-dental-group/people/dana-whitfield/invite      # new code (old one dies), + api_url
curl -s -X POST $API/api/invites/K7PX2MRQ/claim -H 'content-type: application/json' -d '{"device":"Dana MacBook"}'
#  → {"board_id","board_name","person_id","name","role","target","skill_id","api_base_hint"}; a second claim is 409
curl -s $API/api/boards/acme-dental-group/status | jq '{data_dir, legacy_fallback, has_data, files: [.files[] | {name, served_from}]}'
curl -s $API/api/boards/acme-dental-group/ontology   # 404 {"detail","state":"no_data_yet","needs":"approved records → nightly fit ..."}
```

Records → fit (nightly, or by hand): the board's approved records go out as NDJSON and `flowline1 fit` writes the board's files.

```bash
curl -s $API/api/boards/acme-dental-group/records/export > acme.ndjson        # approved, non-withdrawn, one Record per line
curl -s -X POST $API/api/boards/acme-dental-group/recompute                    # 202 {"job_id":"fit-…","state":"running",...}
curl -s $API/api/boards/acme-dental-group/recompute/fit-…                      # done | failed (stderr in the body)
```
`FLOWLINE_FIT_CMD` overrides the command (placeholders `{records} {out} {industry} {board_id}`); the default runs
`uv run --directory flowline1 python -m flowline1 fit --records … --out data/boards/<id>/out --industry <naics>`. Until
`flowline1 fit` exists the job ends `failed` with the command's stderr. Every run the API posts to the executor carries
`board: {id, name, mail_domain, people: [{id, role, email, name}]}` so skills mail by role (SCHEMA §11). The Mac app
learns its board from the invite claim (`api_base_hint`); the board shows `/` (boards) and `/b/<id>/people`.

## Model (Flowline-1)

```bash
cd flowline1 && uv run python -m flowline1 build --out ../data/out --seed 15   # ~10 s, writes the 10 board files
uv run python -m flowline1 check                                              # metrics vs BUILD-PLAN targets
uv run python -m flowline1 demand --recompute                                 # full Census backtest (minutes)
```
The API picks up `data/out/*.json` on mtime (the legacy location: `northwind` reads it until `data/boards/northwind/` exists;
every other board reads `data/boards/<id>/out/`); sync to the mini after a rebuild. Baseline numbers (seed 15): 108.8 h per
proposal, 78 % waiting, signature wait 24.7 h; best plan auto-approve < $5k + agent fills the deck 91.4 h (−16 %),
measured after the change 87.7 h; 4/4 model checks in range; D1 BPIC 2020 median error 17.5 % / P80 4.1 %; D2 7.4× vs 5.7×.

## Board

Dev: `cd board && FLOWLINE_API=http://localhost:18787 pnpm dev` (5173). Prod: `pnpm build` then the API serves `dist/` at `/`.
Routes: /surfaces · /know/knowledge · /know/waits · /know/records · /improve/plans · /improve/results · /improve/history ·
/trust/model · /decide/expand · /decide/opening. `?fixtures=1` forces prototype data.

## Mac menu-bar app

```bash
cd agent-mac && scripts/bundle.sh                       # swift build + ad-hoc sign → build/Flowline.app
defaults write co.sweetspot.flowline api_base http://localhost:18787
defaults write co.sweetspot.flowline run_target desk1   # or mac
open build/Flowline.app --args --demo-day --eod-now     # demo day + banner now; add --debug-control for scripts/drive.sh
```
Each rebuild changes the ad-hoc code identity: macOS asks for Accessibility again (only needed outside --demo-day).
Real step naming: launch the binary from a shell after `set -a; source .env; set +a`.

## Executor (Vercel AI SDK agent)

```bash
cd executor && uv run pytest && (cd agent-ts && npm install)
FLOWLINE_EXECUTOR_URL=http://127.0.0.1:8790 uv run python measure.py --runs 10 --privacy --speed 10   # on the mini
```
Measured 2026-11-09: 10/10 fills correct, median 36.5 s, P90 40.3 s, Stop honoured in 2.1 s; privacy 0/3 planted items
leaked, step-boundary F1 0.80. Flow: board approves a plan → suggestion for pm-1 → app "Do it" → `POST /api/runs` →
executor → desk1 (viewer at :3101).

## Video

```bash
cd video
python3 supers_from_data.py && python3 vo.py          # supers + VO text from data/out and data/runs/measure.json
python3 vo_higgsfield.py [--cuts N ...] [--force]      # narration via Higgsfield (Eleven v4, voice Holden) → out/vo/NN.wav; then vo.py again
node record_board.mjs --base http://localhost:5173     # board cuts 1,4,5,6,8,9,10,11 (dev server proxying to 18787)
./stage_mac.sh sheet && ./record_mac_cuts.sh 2 && ./record_mac_cuts.sh 3
./stage_mac.sh viewer && ./record_mac_cuts.sh 7        # live take: executor fills the deck on desk1
./stage_mac.sh clear
node render_endcard.mjs github.com/yc9954/flowline        # end card with the repo URL
python3 build.py [--music track.mp3]                   # → out/flowline-90s.mp4
```
Mac takes: light mode, Dock hidden by the crop, menu bar cropped (real clock), backdrop hides the desktop.
