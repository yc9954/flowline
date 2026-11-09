# api — notes

Board backend for Flowline (FastAPI + SQLite). Port 8787.

## Run

```sh
cd api
uv run uvicorn api.main:app --port 8787 --reload     # server; OpenAPI at /docs
uv run pytest                                        # tests (self-contained, use temp dirs)
uv run python scripts/dev_sign.py record.json        # sign a Record with ~/.flowline/dev_key
uv run python scripts/dev_sign.py --verify signed.json
uv run python scripts/dev_sign.py --pubkey
```

Environment (all optional): `FLOWLINE_DATA_OUT` (default `../data/out`), `FLOWLINE_FIXTURES` (`../fixtures`),
`FLOWLINE_DB` (`../data/api.sqlite`), `FLOWLINE_MODEL_DIR` (`../flowline1`), `FLOWLINE_BOARD_DIST` (`../board/dist`),
`FLOWLINE_EXECUTOR_URL` (`http://localhost:8790`), `FLOWLINE_CORS` (`http://localhost:5173`), `FLOWLINE_UV`,
`FLOWLINE_DEV_KEY` (for dev_sign.py). Defaults are anchored at the repo root, derived from the package location (the parent of `api/`), or `FLOWLINE_ROOT` if set. No absolute paths in the code.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/api/boards/{board}/records` | SCHEMA 2 + 12. Verifies hash + Ed25519 sig over the raw body **before** model validation. 201 `{id, accepted:true}`; 400 with a reason on any mismatch; 409 if the id exists with a different hash. |
| GET | `/api/boards/{board}/records[?person_id=&withdrawn=1]` | Active records (withdrawn hidden unless `withdrawn=1`). |
| GET | `/api/boards/{board}/records/{rid}` | One record. |
| DELETE | `/api/boards/{board}/records/{rid}` | Withdraw (soft; record stays on device). Re-posting the identical signed record re-activates it. |
| GET | `/api/boards/{board}/ontology` `/finding` `/plans` `/results` `/history` `/model` `/opening` `/surfaces` | Served from `data/out/<name>.json`, else `fixtures/<name>.json`, else 404 naming both missing paths. Re-read on mtime change. |
| GET | `/api/boards/{board}/expansion[?industry=713940]` | See "expansion layouts" below. |
| GET | `/api/boards/{board}/status` | Per file: `served_from` (`data_out`/`fixtures`/`missing`), path, mtime, the file's own `source` label; record count; recompute state; executor url; whether board/dist is served. |
| POST | `/api/boards/{board}/recompute` | Runs `uv run python -m flowline1 build --out data/out` in `flowline1/` in a background thread. 202; 503 if `flowline1/` (or its pyproject) is missing; 409 if already running. Result (rc, last 40 output lines) in `/status`. |
| POST | `/api/boards/{board}/plans/{plan_id}/approve` | Body optional `{approved_by}`. Records the approval, creates Suggestions (see below). 201. |
| GET | `/api/boards/{board}/plans/approvals` | Approval log. |
| GET | `/api/people/{person}/suggestions[?all=1]` | `offered` only unless `all=1`. Each carries `accept_rate`. |
| GET | `/api/suggestions/{id}` | |
| POST | `/api/suggestions/{id}/respond` `{answer: do_it\|not_now\|dont_ask}` | do_it→`accepted`, not_now→`declined`, dont_ask→`never` and suppresses that (person, skill) for good. 409 if already answered. |
| POST | `/api/runs` | Proxies to executor `POST /runs`; marks the suggestion `accepted` with `run_id`. 503 if executor down. 409 if the person said dont_ask. |
| GET | `/api/runs/{id}` | Proxies `GET /runs/{id}`; caches; when the run is `done` the suggestion becomes `done`. If the executor is down and a cached copy exists, returns it with `_cached: true`. |
| POST | `/api/runs/{id}/stop` | Proxies. |
| GET | `/api/health` | |
| GET | `/` and any non-`/api` path | `board/dist/index.html` (SPA fallback) when the build exists; otherwise a JSON hint. `/assets/*` static. |

CORS: `http://localhost:5173` and `http://127.0.0.1:5173`.

## Storage

SQLite at `data/api.sqlite` (WAL). Tables `records`, `suggestions`, `plan_approvals`, `runs_cache`, plus
`accept_tally` (Beta-Bernoulli per (person, skill): prior Beta(1,1); do_it → alpha+1, not_now / dont_ask →
beta+1; `never` flag). `accept_rate` in a Suggestion = `{alpha, beta, accepted, declined, mean, suppressed}`.

## Suggestion creation on approve

For every `{type:"skill"}` rule in the approved plan: one Suggestion per person who holds the rule's `actor`
role in the board's records. With no records yet, the demo map `PM → pm-1` applies. If the plan has no skill
rule at all (or plans.json is missing), the demo skill `fill_deck_from_sheet` for role PM is still offered so
the loop always demonstrates. `count_last_week` / `minutes_each` come from `finding.json` `repeated[]`
(first row with `who == actor` and `agent_can_do`), else the demo defaults 11 / 22. Body text is exactly
"You did this 11 times last week, about 22 minutes each. I'd take under a minute, and nothing is saved until
you check it." `why_now` = `your team approved "<plan name>" on <Mon D>`. People who said dont_ask for that
skill are skipped; so is anyone who already has an unanswered offer of it.

## Stubbed / pending on other components

- `flowline1`: `flowline1/` exists but `python -m flowline1` currently fails with "No module named
  flowline1.__main__" — recompute reports `failed` with that tail. Nothing for the api to change; when the
  module gains a `__main__`, `/recompute` will work as-is.
- `executor`: nothing on 8790 yet. The proxy returns 503 with a hint. The tests drive it with an in-process
  stub that follows the SCHEMA 11 `Run` shape.
- `board/dist`: absent; `/` returns a JSON hint until `pnpm build` exists.
- `fixtures/` and `data/out/` are both empty right now, so every read endpoint 404s with the file names.
  As soon as either agent writes `<name>.json` it is served without restart.
- People → role mapping: there is no people directory in SCHEMA. The api derives it from records; the
  only hard-coded fallback is `PM → pm-1` for the demo.

## Contract questions / ambiguities (for the integrator)

1. **Expansion `?industry=`** — SCHEMA 9 shows one `Expansion` object with an `industries` list and a single
   `industry`. A single file cannot answer two industries. The api accepts three layouts of `expansion.json`:
   (a) a single Expansion (then `?industry=` must equal its `industry`, else 404 that says so);
   (b) `{...shared fields, "default": "<naics>", "by_industry": {"<naics>": Expansion, ...}}` —
   recommended for flowline1; shared top-level fields are merged into the chosen entry;
   (c) a JSON list of Expansion objects. Please pick (b) in SCHEMA or tell me which to keep.
2. **Expansion `source` is `string`** while every other page's `source` is the `measured|simulated|prototype`
   enum. Models accept any string there; the rest validate the enum (unknown value → 500 on serialization
   with a clear pydantic error). Should it be the enum?
3. **`source` per block**: section 13 says every page carries `source` per block, but no section 3–11 shape
   lists a `source` field. The api treats a top-level `source` as optional on every page and passes any nested
   `source` through untouched (`extra="allow"`). `/status` reports the top-level one.
4. **`board_id` on Surfaces**: Surfaces (section 11) has no `board_id`, unlike every other page. The api does
   not inject one there; it does inject the URL's `board_id` into other pages if the file lacks it.
5. **Record 201 vs duplicate**: SCHEMA says 201 `{id, accepted}`. Re-posting the *same* record (same hash)
   returns 201 again (idempotent); a *different* body under an existing id is 409. Withdrawn + identical
   re-post re-activates. Say if you prefer 409 for the idempotent case.
6. **Hash of numbers**: section 12 says "integers without `.0`" but also "hours as decimal numbers (`19.0`)".
   Python's `json.dumps` writes a float `19.0` as `19.0` and an int `19` as `19`; they hash differently. The
   Swift signer must preserve the JSON number type it received (a `Double` 19.0 must serialize as `19.0`,
   not `19`). Records only carry integer minutes, so this does not bite today; it will for any future float.
7. **Signature coverage of `board_id` in the URL**: the api requires `record.board_id == {board_id}` in the
   path (400 otherwise). SCHEMA does not say; seemed the only safe reading.
8. **Suggestion on approve — who**: "the people the plan touches" is not defined. See "Suggestion creation"
   above for what the api does (skill rules → actor role → people with that role in records → demo fallback).
   `Plan.who[]` (role + change) is not used because it carries no skill.
9. **`Suggestion.accept_rate`** is an api addition, not in SCHEMA 11; the board should treat it as optional.
   Also added: `created_at`, `responded_at`, `run_id`.
10. **Run → suggestion link**: SCHEMA's `Run` has no `suggestion_id`; the api remembers the mapping itself
    (`runs_cache`). The executor does not need to echo it, but it would be nicer if it did.
11. **DELETE record response** is unspecified; the api returns 200 `{id, withdrawn:true}`.
12. **Role enum**: records with an unknown `role` are rejected (400) *after* signature check, so a valid
    signature on a bad role still fails. Fine for the demo; flag if agent-mac wants roles to be open.
