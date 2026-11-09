#!/usr/bin/env python3
"""Generate Resources/demo-day.jsonl: a synthetic Event log (SCHEMA.md §1) for the PM's day in
Review.dc.html, sampled every 15 s, in the machine's local timezone. Also writes demo-week.json
(repeat signatures from earlier days this week) and demo-names.json (step names used in demo mode
when no API key is present). Titles are hashed exactly as the observer does (sha256 of the title);
person names are masked the way Privacy.swift does ("client file")."""
import hashlib, json, os, sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "..", "Sources", "Flowline", "Resources")
DATE = "2026-11-06"
STEP = 15  # seconds between samples

local_tz = datetime.now().astimezone().tzinfo

def at(hhmm, s=0):
    h, m = hhmm.split(":")
    return datetime.fromisoformat(f"{DATE}T{int(h):02d}:{int(m):02d}:{s:02d}").replace(tzinfo=local_tz)

def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + d.strftime("%z")[-2:]

def h(title):
    return hashlib.sha256(title.encode("utf-8")).hexdigest()

SHEETS = ("Google Chrome", "pricing-sheet · Proposal #167 - Google Sheets", "docs.google.com")
SLIDES = ("Google Chrome", "proposal-167 deck · Investment - Google Slides", "docs.google.com")
DOCS = ("Google Chrome", "Client brief · Proposal #167 - Google Docs", "docs.google.com")
MAIL_BRIEF = ("Mail", "Re: Proposal #167 — client brief from Sales", None)
MAIL_APPROVE = ("Mail", "Proposal #167 — quote for approval · Director", None)
MAIL_SALES = ("Mail", "Proposal #167 — handing to Sales", None)
PREVIEW_NAME = ("Preview", "Kim Minji contract.pdf", None)
MESSAGES = ("Messages", "Messages", None)
BANK = ("Safari", "KB Kookmin Bank — Internet Banking", "obank.kbstar.com")
SLACK = ("Slack", "Design — Slack", None)
ZOOM = ("zoom.us", "Zoom Meeting — Design sync · Proposal #167", None)

blocks = []  # (start, end, app, title, host, idle_mode)

def block(start, end, src, idle="active"):
    blocks.append((at(*start) if isinstance(start, tuple) else at(start),
                   at(*end) if isinstance(end, tuple) else at(end), src, idle))

# 09:02–09:20 brief: mail + docs, with a 90 s glance at a file named after a person
block("09:02", "09:08", MAIL_BRIEF)
block("09:08", "09:14", DOCS)
block("09:14", ("09:15", 30), PREVIEW_NAME)
block(("09:15", 30), "09:20", MAIL_BRIEF)
# 09:20–10:48 pricing sheet
block("09:20", "10:48", SHEETS)
# 10:48–10:52 ask the Director
block("10:48", "10:52", MAIL_APPROVE)
# 10:52–13:02 waiting (idle), with planted personal items inside it
block("10:52", "12:00", MAIL_APPROVE, idle="idle")
block("12:00", "12:14", MESSAGES)
block("12:14", "12:20", MAIL_APPROVE, idle="idle")
block("12:20", "12:26", BANK)
block("12:26", "13:02", MAIL_APPROVE, idle="idle")
# 13:02–13:24 copy figures: sheets <-> slides alternating every 45 s
t = at("13:02")
flip = True
while t < at("13:24"):
    e = min(t + timedelta(seconds=40), at("13:24"))  # 33 pieces: starts and ends on the sheet
    blocks.append((t, e, SHEETS if flip else SLIDES, "active"))
    flip = not flip
    t = e
# 13:24–15:12 revise the deck with Design: slides, short Slack bursts, a 30 min Zoom call
block("13:24", "13:40", SLIDES)
block("13:40", ("13:41", 30), SLACK)
block(("13:41", 30), "14:00", SLIDES)
block("14:00", "14:30", ZOOM)
block("14:30", "14:42", SLIDES)
block("14:42", ("14:43", 45), SLACK)
block(("14:43", 45), "14:58", SLIDES)
block("14:58", ("14:59", 30), SLACK)
block(("14:59", 30), "15:12", SLIDES)
# 15:12–15:18 hand to Sales
block("15:12", "15:18", MAIL_SALES)

def mask(title):
    # mirror Privacy.maskNames for the one planted name
    return "client file" if title == PREVIEW_NAME[1] else title

events = []
for (s, e, (app, title, host), idle) in blocks:
    t = s
    idle_start = s
    while t < e:
        if idle == "idle":
            idle_s = int((t - idle_start).total_seconds())
        else:
            idle_s = (int(t.timestamp()) % 7) * 3  # fidgety, never ≥ 5 min
        ev = {"ts": iso(t), "app": app, "title_hash": h(title), "title_masked": mask(title), "idle_s": idle_s}
        if host:
            ev["url_host"] = host
        if title.endswith(".pdf"):
            ev["file_hint"] = "client file"
        events.append(ev)
        t += timedelta(seconds=STEP)

os.makedirs(RES, exist_ok=True)
with open(os.path.join(RES, "demo-day.jsonl"), "w", encoding="utf-8") as f:
    for ev in events:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")

week = [
    {"date": "2026-11-03", "signatures": ["sheets→slides"]},
    {"date": "2026-11-05", "signatures": ["sheets→slides"]},
]
with open(os.path.join(RES, "demo-week.json"), "w", encoding="utf-8") as f:
    json.dump(week, f, ensure_ascii=False, indent=1)

names = {
    "steps": [
        {"idx": 1, "name": "Read the client brief for #167", "kind": "hands_on", "case_id": "proposal #167", "tools": ["mail", "docs"], "handoff_from": "Sales"},
        {"idx": 2, "name": "Built the estimate", "kind": "hands_on", "case_id": "proposal #167", "tools": ["sheets"], "handoff_from": "Sales"},
        {"idx": 3, "name": "Asked the Director to approve the quote", "kind": "hands_on", "case_id": "proposal #167", "tools": ["mail"], "handoff_to": "Director"},
        {"idx": 4, "name": "Waited for approval", "kind": "waiting", "case_id": "proposal #167", "waiting_on": "Director", "handoff_to": "Director"},
        {"idx": 5, "name": "Copied figures from sheet into deck", "kind": "hands_on", "case_id": "proposal #167", "tools": ["sheets", "slides"]},
        {"idx": 6, "name": "Revised the deck with Design", "kind": "hands_on", "case_id": "proposal #167", "tools": ["slides", "chat", "call"]},
        {"idx": 7, "name": "Handed proposal #167 to Sales", "kind": "hands_on", "case_id": "proposal #167", "tools": ["mail"], "handoff_to": "Sales"},
    ],
    "summary": "Most of today went to proposal #167 — and 2 h 10 m of it was waiting on a signature.",
}
with open(os.path.join(RES, "demo-names.json"), "w", encoding="utf-8") as f:
    json.dump(names, f, ensure_ascii=False, indent=1)

print(f"wrote {len(events)} events to {os.path.relpath(os.path.join(RES, 'demo-day.jsonl'))}")
