# Flowline design notes — reuse SimOff + Obolus (2026-11-08)

Both repos share one kit (simoff `app/static/kit.css` is literally "the Obolus kit"). Light only.

## Tokens
- bg `#fff` · fg `#000` · card `#f2f5f6` · muted-2 `#edf0f2` · border `#d8dddf` · muted text `#4d5353`
- primary (buttons, selection, Best) `#171717` · sidebar `#eaecee` (border `#dcdfe1`)
- teal `#0F766E` = good / done / ours · violet `#6D5BD0` = agent/AI content · amber `#B45309` (warn chip `#f6ebd3`/`#6b4a00`) · red `#e40014`
- data colours only as 8px squares (`.sq`): `#3B73FF` `#FCBB00` `#88ACFA` `#B8BEC2`
- tints: `color-mix(in oklab, <hex> 4%, #fff)` bg, 24% border

## Type
- Instrument Sans (simoff) / Inter (obolus) for prose; Pretendard / Wanted Sans for Korean, `word-break: keep-all`
- Geist Mono for every label, number, chip, tab: label = 10px uppercase, 1px tracking, `#4d5353`
- Host Grotesk 500 for big stats (26px; up to 56px, letter-spacing -.04em), `tabular-nums`
- page title tiny (16px/500); the FINDING is the big headline (28–44px/600, -.018em)

## Geometry
- buttons/tabs 2px radius, h 36, black fill or 1px `rgba(0,0,0,.12)` outline; cards/tables 6px; status chips 2px square; pills only for counts
- hairlines, not shadows. Black 1px rule = "this is the answer" (stat tops, Actual row)
- selection = black border + 1px black ring; Best = 2px ring + black "Best" badge, others `opacity:.5; saturate(.55)`
- square status dots (`border-radius:1px`)

## Patterns to reuse
- simoff sidebar step-flow with vertical progress track (`app.css:207-219`)
- simoff 3×3 plan grid `gridHTML()/markBestGrid()` (`app.js:494-516`) — "same people, same luck"
- simoff step-foot: sticky bottom bar = bold verdict sentence + one black next button (`STEP_FOOT`)
- simoff `stat()` light KPI: top rule, mono label, Host Grotesk number, muted sub-line
- obolus `SettlementInvoiceDialog` paper receipt (`#f8f8f6`, dashed rules, numbered line items, black proof callout) → approved end-of-day record
- obolus `Archive` ThreadCard row `120px | 1fr | auto` → end-of-day review list
- obolus `TraceSteps` (STEP n · LABEL, teal check) → agent doing a task
- obolus desktop app (git `c426621`, `apps/obulus-desktop/src/renderer/styles.css`): approval sheet, tool-call cards, black LOCAL CUSTODY card
- No notch/menubar component exists in either repo — design new, from square dot + mono label + black boundary card.

## Voice
Plain, declarative, verdict first then caveat. No "AI-powered", no emoji. Middle dots separate metadata.
e.g. "Nine plans, the same shoppers." · "Time to decide." · "What we couldn't call"
