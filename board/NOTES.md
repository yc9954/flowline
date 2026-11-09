# board — notes and contract questions

Owner: board (web app). Questions here are for the integrator who owns `SCHEMA.md`; nothing in that file was edited.

## Run

```
cd board
pnpm install
pnpm dev            # http://localhost:5173, proxies /api → http://localhost:8787
pnpm build          # tsc -b && vite build → dist/ (served by the API in production)
scripts/shots.sh fixture | api | 1280   # headless-Chrome renders into board/shots/
```

Every page fetches `/api/boards/northwind/...`. If the request fails (API down, non-2xx, or the JSON lacks the
arrays the page needs) it falls back to the matching file in `../fixtures` and the header stamp says
`fixture · API offline` (or `· API shape mismatch`). Append `?fixtures=1` to any route to force fixture mode for
QA. The stamp shows the API's `Date` header when the data came from the API.

Routes: `/decide/expand[?industry=NAICS]`, `/decide/opening`, `/improve/plans`, `/improve/results`,
`/improve/history`, `/know/knowledge`, `/know/waits`, `/know/records[/:id]`, `/trust/model`, `/surfaces`.
`/` redirects to `/know/waits`.

## Fixtures (`../fixtures/*.json`, all `"source": "prototype"`)

`ontology`, `finding`, `plans`, `results`, `history`, `model`, `opening`, `surfaces` are the §3–§11 shapes.
`expansion.json` holds every industry: `{ board_id, city, industries, default, records, branches, source,
by_industry: { "713940": <§9 minus shared fields>, "621111": …, "722515": … } }`; the app merges
`by_industry[industry]` over the shared fields when falling back (the API returns the flat §9 object).
`records.json` is a `Record[]` (§2) with 10 signed-looking records; hashes/signatures are placeholders.
`plans`, `results.series`, `expansion`, `records` are produced by a small generator so the numbers agree with
the storyboard (sums, ranks, means); the others were typed from the storyboard data-props.

## What the UI derives (not in the contract)

- Verdict-bar sentences and the "next" button label on every page are UI copy, lightly templated from data
  (e.g. Plans: runner-up gap; History: the `needs_yes` version). **Q: should each page carry a
  `verdict: { strong, rest, next_label }` so the model can own that sentence too?**
- `ModelCheck` has no `headline`; the page picks one of two sentences from `sim_checks[].in_range`.
  **Q: add `headline` to §8?**
- Header "recomputed Wed 18:24" exists only for Ontology (`recomputed_at`) and ModelCheck (`calibrated_at`).
  Other pages show "fetched <time>" from the response `Date` header. **Q: add `recomputed_at` to §4–§7, §9–§11?**
- Finding KPI sub-lines ("brief → sent", "of each cycle", "98% approved unchanged") are derived from `map`,
  `kpis.small_quotes_unchanged` and `repeated[0]`. The storyboard's "avg of 23 proposals" needs a case count
  that §4 lacks. **Q: add `cases: number` to Finding?**
- Finding's `MapStep.role` is a single `Role`; the storyboard shows "PM · Design" on the Deck step. Fixture uses
  `Design`. **Q: allow `roles: Role[]` or keep one owner?**
- Finding's "to scale" marker is labelled `${artifact} ${hands_on_h} h` of the `selected` step ("quote 0.3 h");
  the storyboard said "signature 0.3 h".
- Ontology: the storyboard's "no · 18% declined" stub is modelled as an edge to a non-existent node id
  (`to: "declined"`); the renderer draws a stub with the label when `to` is unknown. **Q: is a dangling edge
  acceptable, or should decisions carry `exits: { label, share }[]`?**
- Ontology layout is computed, not stored: lanes = `roles` order, x = longest path over `then`/`parallel`
  edges, wider gap when the hop stays in one lane, extra gap before a `bottleneck` node with `wait_h`. Edge labels
  are drawn only from `Edge.label` (so the model decides which waits are worth a label). The amber "long wait"
  underlay = edge with `wait_h` into a node with `bottleneck: true`.
- Expansion: `source` is the honest label (§13), so the storyboard's "Source: US Census …" citation line is
  hardcoded from §13's dataset list. **Q: add `dataset: string` to §9/§8?** The hex map is a hex-binned
  projection of `zips[].lat/lon`; river/I‑35/MoPac are fixed geography drawn only when `city` starts with
  "Austin". "29% vs 4%" (hit rates behind the lift) is not in §9 and is omitted. The top-5 table's "metro
  average / median" are computed over all `zips`.
- Opening: workstream `todo` renders hatched ("still to go"); `progress: [done, total]` splits a bar into solid
  + hatched. Blocker cards look up the workstream with the same `title` for the progress bar. Week labels are
  ISO weeks computed from `start`/`end`/`opens`/`was`.
- Surfaces needs more than §11 to draw the hero: it also loads `ontology` (`counts`, `version`,
  `recomputed_at`), `expansion` (map + predicted lift per ZIP for `expansion_lead`) and `model.records` (total
  approved records; also the sidebar "Records" figure). "28 people" and "Screens shared 0" are constants from the
  brief. **Q: should `Surfaces` carry `company: { name, people, clubs }` and `records`?**
- Records list: accepts a bare `Record[]` or `{ records: [...] }`. Withdraw = `DELETE /records/{id}` after an
  inline confirm; the API's `{ id, withdrawn: true }` is treated as optional.
- Plans: "Approve this plan" POSTs `/plans/{id}/approve`; any 2xx counts as approved and the confirmation line
  names the roles in `who` whose `change` is not "nothing to change". Partial plan objects (the current stub
  omits `work_h`, `waiting_h`, `vs_today`, `range_h`, `who`) are defaulted rather than crashing.
- Timestamps are shown in the timezone written in the ISO string (the board's time), never the viewer's.
- Honest labels: a 10px mono chip `SIMULATED`/`PROTOTYPE` sits top-right of each page from the top-level
  `source`; `measured` shows none. The Records page labels itself `measured` when the list came from the API.

## Fidelity gaps I could not close

- Fonts come from Google Fonts; offline, the fallbacks (system-ui / Menlo) change metrics slightly.
- Ontology edge routing is algorithmic; a few label positions differ from the hand-placed storyboard
  (e.g. "parallel · 87%" sits on the vertical run, "missing figures · 13%" is centred on its horizontal run).
- Expansion hex map: real ZIP centroids are N–S elongated, so the blob is narrower than the storyboard's
  illustrative grid; rank badges and the pick label are placed by data.
- Dates follow the fixture calendar (2026-11-06 is a Friday; 13 Dec 2026 is a Sunday), so weekday words differ
  from the storyboard's fictional "Wednesday 6 November" / "due Fri 13 Dec".
- Results chart dots are spread evenly within each week band (no day resolution in `series`).
- Live API today (stub): only `/plans` (one partial plan) and `/records` answer; everything else 404s and renders
  from fixtures with the amber stamp.

## Serving `dist/`

The app uses history routing. When the API serves `dist/` at `/`, every non-`/api` path that is not a file must
fall back to `dist/index.html` (e.g. `/decide/expand`, `/know/records/1106-0412`), or deep links 404.
