# executor/skills

Each module here is one skill id: it exposes `SKILL` (SCHEMA §11 Skill), `title(inputs)` and
`run(ctx, desktop, inputs)`. `skills/__init__.py` loads a module by id and `GET /skills` lists every
module that does not start with `_`.

| id | steps | agent tools |
|---|---|---|
| `fill_deck_from_sheet` | READ THE SHEET · FILL THE DECK · CHECK THE TOTAL · LEAVE IT FOR YOU | computer, bash, read_sheet, read_deck_cells, report_step |
| `proposal_packet` | READ THE QUOTES · UPDATE THE SHEET · FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER | computer, report_step |
| `reconcile_quotes` | READ THE QUOTES · UPDATE THE SHEET · HAND IT OVER | computer, report_step |
| `signature_packet` | FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER | computer, report_step |

The three packet skills share one engine, `_packet.py`; `proposal_packet.py`, `reconcile_quotes.py` and
`signature_packet.py` are thin wrappers that pick the step subset. The agent loop is `agent-ts/run.mjs`
(Vercel AI SDK `ToolLoopAgent`, Anthropic computer toolset); the prompt per skill id is in
`agent-ts/skills.mjs`, which also says which tools the model gets. The packet skills get the screen only:
`computer` (screenshot, zoom, click, type, key, scroll …) and `report_step` (the skill's own step labels and
progress). No shell, no file readers — everything the agent learns it reads from 1280×720 screenshots of the
1920×1080 XFCE desk, and everything it does goes through Thunar, Atril, Calc, Impress and the team webmail
(Roundcube in the pinned Chromium window, see MAIL.md).

## The task (packet skills)

On the desk, under `/config/Documents`:

* `Quotes/` — three vendor quote PDFs (Downtown Athletic Club → memberships, MoveWell Studio → lunchtime
  classes, Kickoff Coaching → onboarding week), one per row of `pricing-sheet.ods`. Generated fresh per run
  by `assets/quotes.py` (reportlab): two equal the sheet, exactly one differs by 5–20 % rounded to $10.
* `pricing-sheet.ods` — Item / Amount / Total(=SUM); the deck's source of truth once corrected.
* `proposal-172.odp` — slide 6 "Investment", a 4-row table whose amount cells are empty.
* `For signature/` — where the exported `proposal-172.pdf` goes.
* The inbox window "(N) Northwind Mail :: Inbox" (WM_CLASS `FlowlineMail`), logged in, always there.

The agent reads each quote PDF in Atril from the Thunar window, fixes the row that differs in Calc and saves,
types the four amounts on slide 6 in Impress, exports the deck with File › Export As › Export Directly as PDF
into `For signature/`, and then HANDS IT OVER by e-mail from the webmail window: Compose → To → Subject →
plain-text body → Attach (GTK chooser: ctrl+L, type the full path, then **click the Open button** — in this
Chromium 156 + GTK 3.24 chooser Enter or a double-click closes the dialog without handing the file to the page; if the
attachment list stays empty, Attach again, single-click the file, click Open) → Send, always from a fresh Compose. `reconcile_quotes` mails
pm@northwind.local "Quotes reconciled — proposal 172 · <Role>" without attachment (body: vendor, old → new, new
total, sheet saved on the desk — the .ods never uploads through the chooser on some desks, the PDF does); the
two packet skills mail director@northwind.local, cc finance@, "Proposal 172 — for signature · <Role>" with
`proposal-172.pdf` attached (body: the three line items and the total). `<Role>` is the sending desk's mailbox
(desk1 pm → PM, desk2 Finance, desk3 Sales, desk4 Ops, desk5 Studio, desk6 Director; the run's `person_id`
wins when it names a login), so six desks mailing director@ in the same minute never match each other's mail. The deck stays modified and
unsaved. The prompt's rule: the internal hand-off mail is part of the approved plan and is sent; nothing goes
to anyone outside @northwind.local.

## Proposal variants (`inputs.proposal`)

So the six-desk wall does not show six copies of one deck, a run can work on another proposal
(`assets/make_assets.VARIANTS`): **172** Halden Logistics (default; the original files, byte-identical),
**171** Harbor Ridge Clinic (Physio sessions, 60 · Staff wellness classes, 6 / mo · Ergonomics audit — $3,900 /
$1,320 / $780) and **173** Kickoff Coaching (Team memberships, 45 · Nutrition workshops, 4 / mo · Opening-week
trainers — $1,750 / $920 / $610). Files on the desk: `pricing-sheet-<n>.ods`, `proposal-<n>.odp`,
`For signature/proposal-<n>.pdf` (172 keeps `pricing-sheet.ods`/`proposal-172.odp`); quotes come from that
variant's vendors (`assets/quotes.VENDORS_BY_PROPOSAL`); the mail subject is "Proposal <n> — for signature ·
<Role>"; titles read "… proposal #<n> …". `inputs.sheet`/`inputs.deck` given explicitly still win. The assets
are generated once with `uv run python assets/make_assets.py --container deskN --proposal 171` (soffice
headless on a desk) and live in `assets/`; prepare only copies them. `fill_deck_from_sheet` stays on 172.

Inputs shape: `{"proposal": 171, "seed": 7, "dress": true, "leave_open": true, "max_steps": 90}` (all
optional; `sheet`, `deck`, `slide`, `quotes_dir`, `out_dir` override the paths).

## prepare (deterministic, before the agent starts)

`_packet.prepare()` stages the desk: closes Atril/Mousepad/Thunar/app-finder windows and every LibreOffice
document (UNO, without saving — checked again with `uno list` + `wmctrl`; a document that survives, e.g. a
modified sheet from an earlier reconcile run, gets a second closeall and then a soffice restart, because
`uno open` of an already-open URL would hand that stale document back), restores the canonical sheet **and**
deck from `assets/` on every run and verifies their sha256, empties
`For signature/`, removes stale `.~lock.*#` files, writes the new quote PDFs, and writes the truth
(`quotes`, `changed`, `sheet_after`, `total_after`, expected paths) to `data/runs/<id>/truth.json`.
`inputs.seed` fixes the quotes for a repeatable demo take. The inbox window is never closed.

Then, with `inputs.dress` (default true), the desk is dressed like a person's working screen: Calc with the
sheet on the left half, Impress with the deck on the right half on slide 6, Thunar at `Documents/Quotes`
bottom-left, the inbox window where it was. The prompt tells the agent what is open and where and that it
switches windows (click, panel button, alt+tab) instead of launching apps. `fill_deck_from_sheet` is
untouched (maximised deck, its own prepare).

It also makes sure the GUI soffice with the UNO socket (port 2002) was started **visibly**: an instance
started with `--invisible` (what `lo.warm` does) accepts the IPC request from a Thunar double-click and
shows nothing. The recipe is start with the Start Center, open and close one document through UNO — the
process stays alive without windows and from then on double-clicked documents open normally in the
instance we can read back.

## verify (deterministic, after the agent exits)

Checks on the Run (SCHEMA §11 `checks`), independent of anything the model said:

* `sheet_row_corrected`, `sheet_other_rows_unchanged`, `sheet_total_recomputed`, `sheet_saved_on_disk` —
  the saved `.ods` (pandas/odf) against `truth.json`
* `deck_open_in_impress`, `cell_1..4`, `deck_items_sum_equals_total` — the live table on slide 6 read through
  UNO (nothing saved); `deck_file_unchanged_on_disk` (sha256 before/after), `deck_left_modified_unsaved`
* `pdf_exported`, `pdf_contains_amounts` — `For signature/proposal-172.pdf` exists and its text (pypdf)
  carries the four amounts
* `mail_received`, `mail_attachment_matches_file`, `mail_body_complete`, `mail_cc_received` — over IMAP
  (`mail.py`): the newest message in the recipient's INBOX **from this desk's own mailbox** with the subject
  tail ("for signature · Ops") and, for the signature mails, the attachment, dated after the run start;
  attachment bytes sha256-equal to the exported PDF on the desk; body names the vendor and the new total
  (reconcile) or the four amounts (packet); finance@ got the copy
* `nothing_else_changed` — a `find | sha256sum` listing of `/config/Documents` before and after; only the
  sheet and the PDF may differ (lock files ignored)
* `agent_finished` — exit code 0 (2 = step limit)

A run is `done` only when every check passes; otherwise `failed` with the first problem as `error`. The
subsets check what they do: `reconcile_quotes` the sheet and the mail to pm@, `signature_packet` the deck, the
PDF and the mail to director@ (the sheet is taken as it is).

## Measuring

```sh
uv run python measure.py --skill proposal_packet --runs 8        # → data/runs/measure-proposal_packet.json
uv run python measure.py --skill reconcile_quotes --runs 3 --no-stop
uv run python measure.py --skill signature_packet --runs 3 --no-stop
```

Success rate, median/P90 seconds, model turns, screenshots and zooms per run, failure reasons, and one
extra Stop run (stopped 25 s after the agent starts). `--from-runs id1,id2` assembles the same JSON from
runs that already happened (an interrupted batch, runs started by hand with `POST /runs`).

Measured 2026-11-09 (claude-sonnet-5-5, desks on the mini over ssh), see `data/runs/measure-*.json`:
* `proposal_packet` (pre-mail version with a Mousepad note, desk1): 2/2 pass, 357 s and 677 s (the long one lost
  ~4 min to a foreign `fill_deck_from_sheet` run from the app flow that closed the deck under the agent), 23–32
  turns, 21–30 screenshots. Not yet re-measured with the e-mail hand-off.
* `signature_packet` (mail hand-off, dressed desk, desk5): 1/1 pass, 604 s, 33 turns, 31 screenshots + 2 zooms,
  120 desktop actions; the mail to director@ (cc finance@) carried the exported PDF byte-for-byte.
* `reconcile_quotes` (desk4): first run failed at HAND IT OVER — steps 1–2 correct (sheet fixed and saved in
  232 s) but the agent typed the attachment path before the GTK chooser was up, never got the sheet attached
  and stopped honestly without sending; the prompt now spells out the attach sequence (wait for the chooser,
  ctrl+L, path, Enter, confirm). See the measure JSON for the retry.
Small samples: the batch was cut short on the integrator's request.

Note: desk1 is also the default target of the app flow (the mini's executor on :8790). A run started there
mid-take closes the deck without saving; stage demo takes on a desk nobody else targets.

## Staging a desk for a demo take

1. The executor service up (the laptop instance on :8792 reaches every desk over ssh; `FLOWLINE_DESK_HOST=mini`).
   Use a desk nobody else targets (desk1/3 belong to the app flow; a foreign run there closes the deck under
   the agent). The mail tunnel must be open on the machine that verifies:
   `ssh -fN -L 3143:localhost:3143 -L 3025:localhost:3025 mini`.
2. Mail: nothing to reset for a take — verification looks for the newest matching message dated after the
   run start. For a clean inbox on camera: `scripts/mail.sh reset all && scripts/mail.sh seed` (MAIL.md).
   The pinned inbox window must exist on the desk (`scripts/mail.sh desks deskN` if it is gone); prepare never
   closes it.
3. `POST /runs {"skill_id":"proposal_packet","target":"desk4","inputs":{"seed":7}}` — prepare() stages
   everything in ~20-30 s: closes Atril/Thunar/Mousepad and every LibreOffice document (unsaved), restarts
   soffice if it was started `--invisible`, restores the canonical sheet ($2,600/$1,150/$540 = $4,290) and deck
   from `assets/`, empties `For signature/`, removes stale locks, writes the three quote PDFs and
   `data/runs/<id>/truth.json`, then dresses the desk (Calc left, Impress right on slide 6, Thunar at Quotes,
   Start Center minimised — never close that minimised LibreOffice window: closing the Start Center quits
   LibreOffice with all documents). Seed 7: MoveWell Studio quotes **$920** for lunchtime classes (sheet
   $1,150), new total **$4,060**. To stage without running: start the run and `POST /runs/<id>/stop` within
   ~5 s of the agent starting; the next run re-stages identically.
4. After the run: Calc shows the corrected sheet (saved), Impress slide 6 filled and unsaved,
   `For signature/proposal-172.pdf` present, the webmail back in the inbox with the mail in Sent, and the
   recipient's inbox (director@ / pm@) holds the hand-off with the attachment. `inputs.leave_open` defaults to
   true; the next run's `prepare()` cleans up.
5. Expect ~6 min for proposal_packet, ~3 min for the subsets; allow up to 11 min.
