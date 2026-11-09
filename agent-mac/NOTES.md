# agent-mac — notes and contract questions

Build: `scripts/bundle.sh` (release) → `build/Flowline.app`, ad-hoc signed, `LSUIElement` (no Dock icon).
Run: `open build/Flowline.app --args --demo-day --eod-now`. Tests: `swift test` (canonical hash vs Python, demo-day compile, privacy).
Mock board: `python3 -u scripts/mock_api.py` (port 8787; `--offer` offers the suggestion at once, otherwise
`curl -X POST localhost:8787/api/boards/northwind/plans/plan-2/approve`).
Debug driving (only with `--debug-control`): `scripts/drive.sh review|approve|withdraw|done|banner|menu|poll|do-it|stop…`.

## Decisions worth knowing

- **Fonts.** Instrument Sans, Geist Mono and Host Grotesk are picked up from ~/Library/Fonts when installed
  (checked by family name at launch) and fall back to SF Pro / SF Mono otherwise.
- **Hotkey is ⌃⌘P, not ⌘P.** A global ⌘P would take Print from every app. ⌘P still works as the panel's own shortcut.
- **Notch is Dynamic-Island sized** (Panels.swift `NotchPanel`, NotchViews.swift). One panel, three states, always centred on
  the camera housing (measured from `auxiliaryTopLeftArea`/`auxiliaryTopRightArea` + `safeAreaInsets.top`; 200×37 fallback):
  CLOSED = housing + 62 pt wings (289→309×32 on a 14"; +4 pt lip with the 2-pt progress line while a run is active) showing
  a breathing violet dot / "1 screen"; PEEK = 340×64 one-liner with its buttons; OPEN ≤ 400×140 (EOD 112, suggestion 134,
  agent 140). Radius 12 closed/peek, 18 open. Hover expands to OPEN, leaving collapses after 0.6 s; an untouched PEEK folds
  into CLOSED after 12 s; a run stays OPEN (click the black to fold it); a finished run hides itself after 4 s. All frame
  changes are 220 ms ease-out. Long copy lives in the menu-bar panel, never in the notch. Debug: `drive.sh notch-closed |
  notch-peek | notch-open`.
- **Device key.** Ed25519 key is written to the login keychain. An ad-hoc signed build gets a new code identity on every
  rebuild, so an item written by the previous build would trigger a keychain password dialog; the app never prompts
  (non-interactive reads) and falls back to `~/Library/Application Support/Flowline/device.key` (0600). Set
  `CODESIGN_IDENTITY="Flowline Dev"` (a self-signed Code Signing certificate from Keychain Access) for `bundle.sh` to
  make the identity stable; then the keychain copy is used and Accessibility / Automation grants survive rebuilds.
- **Browser URL host** is off by default (`Settings → Note browser site names`) because asking Safari/Chrome via
  AppleScript triggers an Automation prompt the moment a browser is frontmost. Without it the banking denylist only sees
  window titles.
- **Micro-switch rules in the compiler** (Compiler.swift): switches under 2 min merge into the surrounding step; idle ≥ 5 min
  or a denylisted app = waiting; a chat/call app sandwiched between two stretches of the same document joins that step;
  a short stretch on the same case as its neighbour joins it unless it is a mail that hands work to another role; a block
  where two document tools each hold ≥ 2 min gets a composite key so "copy sheet → deck" stays its own step.
- **Repeats** are counted from per-day signature files (`history/YYYY-MM-DD.json`, tool patterns only, no titles) within
  the same ISO week. Demo mode adds `demo-week.json` so the storyboard's "3× this week" appears.
- **Demo names.** With no API key, demo mode names steps from `Resources/demo-names.json` (the storyboard copy) on top
  of the rule-based namer. With `ANTHROPIC_API_KEY` set the Claude namer runs for real (`FLOWLINE_MODEL`, default
  `claude-sonnet-5-5`); it receives app names, masked titles, durations and the switch order only.
- **Name masking** uses NLTagger `.personalName` plus a surname/document-word heuristic, because NLTagger does not tag
  romanised Korean names ("Kim Minji contract.pdf" → no tag). Any detected name turns the whole title into "client file".
- Events are appended 1/s to `days/YYYY-MM-DD.jsonl`; the file is deleted when the day's record is accepted by the board.
  Approved records are also kept in `records/<id>.json` (they stay on the device after Withdraw).

## Contract questions for the integrator (SCHEMA.md)

1. **Runs endpoint.** §11 puts the executor at `http://localhost:8790/runs`; the brief says the Mac app posts to
   `{api_base}/api/runs` and polls `{api_base}/api/runs/{id}`. The app uses `{api_base}/api/runs…` (API proxies the
   executor). Confirm, or the app needs an `executor_base` setting.
2. **Suggestions response shape.** The app accepts either a bare array or `{ "suggestions": [...] }` from
   `GET /api/people/{id}/suggestions`. Which is canonical?
3. **Record id format.** "1106-0412" — is it `MMDD-hhmm`, `MMDD-####`, or server-assigned? The app sends `MMDD-####`
   (random) and uses whatever `id` the 201 returns for Withdraw.
4. **Run title.** `Run` has no title; the agent panel derives "Filling …" from the suggestion title. A `title` on `Run`
   (or `Skill.name`) would be cleaner.
5. **`Event.file_hint`.** The app sets it to "client file" when a name was masked; the compiler also recognises
   `title_masked == "client file"`. Is `file_hint` meant for the document name instead?
6. **`LeftOut.minutes`** for `name_in_filename` is omitted (the storyboard shows "—"). OK?
7. **Timezone.** Record times carry the device offset (`+09:00`); the board presumably displays in the board's zone.
8. **Hash of numbers.** The app only ever puts integers in a Record, so the Python/Swift shortest-float question
   does not arise; if the API adds decimal hours to records, both sides must agree on float repr.
9. **Handoff on waiting steps.** The storyboard shows "PM → Director" on the waiting step; the app sets
   `handoff_to` on the mail step that asked and `waiting_on` on the waiting step. Both are fine for the ontology?

## Not done / known gaps

- Date navigation arrows and the search field in the review header are visual only (one day at a time).
- "Edit steps" reveals Rename / Merge / Hide on every row; Merge joins a step with the next one, Hide unchecks Share.
- The notch panel is non-activating and cannot take keyboard focus; the review window can (⌘↵ approves).
- `activeScreens` (the "1 screen" label in the CLOSED notch) counts runs this app started; the fleet count is a TODO.
- No launch-at-login, no update mechanism, no multi-display notch (built-in display only).
- Accessibility and Automation grants are tied to the ad-hoc signature (see Device key above).
