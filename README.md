# Flowline

Your team's work, approved by your team, improving itself.

*Built during c0mpiled-17, Seoul, 2026-11-09 (build window 10:00–15:00). One commit: the whole build.*

**In one sentence:** Flowline is the operating memory of a small multi-site business — it learns the processes nobody
wrote down from each person's approved day, and uses that one knowledge to show where work waits, test what to fix,
and do the repeated work with each person's consent.

## Who it is for, and why

**The problem.** A multi-site service business runs on processes nobody has written down. Work spends most of
its time waiting (78 % of a proposal's cycle in our simulated chain), nobody can see where, and when a person
leaves, the process leaves with them. Every tool that could fix this needs a system log the business does not
have — or a person to write it all down, which nobody will.

**The product.** Flowline is the operating memory of a multi-site service business. It learns how the business
actually works from each person's approved end-of-day record — on-device, nothing sent until approved — and
uses that one knowledge five ways: where work waits, which fix works (tested on the same team with the same
luck), agents that do the repeated steps with each person's consent, and where and when to open next.

**What it is, as a category.** Not an ERP and not a personal assistant: a company-level agent — multiplayer AI in the
sense of Instinct, Grokbot or Pickle. Many people's approved work flows into one shared hub; the hub finds the
bottleneck, proposes the fix on a dashboard everyone can see, brings the proposal to the person it affects first,
and, when they say yes, does the work on their screen.

**First customer.** Fitness and wellness chains with 2–20 studios, 5–30 staff, no ERP, an owner who operates.
Multi-site is the norm there, staff turnover takes knowledge with it, the weekly processes (corporate proposals,
class scheduling, trainer onboarding, opening a studio) cross several people, and the one decision that decides
survival — the next location — repeats. Our demand backtest (US Census, 7.4× vs 5.7× for population) is on gyms.
The same shape follows: clinics and dental chains, academies, F&B franchises, salons.

A local agent on each person's computer drafts how their day actually went. The person approves it. Approved
records join one company knowledge (roles, steps, hand-offs, waits). Flowline-1, a model fitted to that company
every night, finds where work waits, tests plans on the same team with the same luck, asks only the person a
change affects, does the repeated work on their screen when they say yes, and measures the result.

One knowledge, many surfaces: a line on the CEO's phone, one approval in Finance's inbox, a notch banner for the
branch manager, an end-of-day review for staff. Only the expansion lead opens a full board.

## Components

| Dir | What | Run |
|---|---|---|
| `agent-mac/` | macOS menu-bar agent: observer, privacy filter, end-of-day review, signed record, notch, executor view | `scripts/bundle.sh && open build/Flowline.app` |
| `executor/` | Executor service (Claude computer use) with Mac and Linux-desktop backends; actor scripts; measurement | `uv run uvicorn executor.main:app --port 8790` |
| `flowline1/` | The company model: process miner, team simulator (SimPy), calibration, demand model (US Census), BPIC 2020 fit | `uv run python -m flowline1 build --out ../data/out` |
| `api/` | Board API (FastAPI + SQLite): records ingest with signature check, knowledge, plans, results, suggestions | `uv run uvicorn api.main:app --port 8787` |
| `board/` | Board web app (React + Vite), served by the API in production | `pnpm dev` |
| `design/` | Storyboard screens (`.dc.html`) and design notes. Reference only, not served | — |
| `fixtures/` | Prototype data in the shared shapes, used until the model has computed real numbers | — |
| `data/` | `raw/` downloaded datasets (ignored by git), `out/` model output | — |

**The board never shows a person's screen.** `/run/fleet` shows who is on which step and what was left for them to
check — never a frame. The six-desk wall in the demo film is a filming rig (`video/wall.html`) pointed at the test
desktops; it is not a page of the product, and the live-frame endpoint it uses is a development/filming aid.

Shared contract: [SCHEMA.md](SCHEMA.md). Every number on screen is labelled measured, simulated or prototype.

Data: BPI Challenge 2020 Domestic Declarations (TU/e, CC BY-NC 4.0); US Census ZBP/CBP 2014–2023, ACS 2015–19.
