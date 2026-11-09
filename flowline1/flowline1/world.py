"""Northwind Fitness world engine: runs the hidden-truth process and emits approved Records.

The world knows the truth (step names, batching rule, amounts, probabilities). Records carry only what a
device would record: per person per day, step names as *that person* calls them (planted synonyms), start
and end times, case ids, tools, hand-offs and waits. `truth()` is the answer key used by `check`.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from . import engine as E

BOARD = "northwind"
ORIGIN = E.monday_origin("2026-10-05")  # week 1 Monday, America/Chicago; wall-clock arithmetic throughout

# Planted step-name variants per step: (text, weight). {amt} is replaced with the quote amount.
VARIANTS: dict[str, list[tuple[str, int]]] = {
    "request_in": [("Request in", 5), ("New request", 2), ("Inbound request", 1)],
    "qualify": [("Qualify", 5), ("Qualify lead", 2), ("Fit check", 1)],
    "discovery": [("Discovery call", 5), ("Disco call", 2), ("Intro call with client", 1)],
    "brief": [("Write brief", 5), ("Brief", 2), ("Brief draft", 1), ("Proposal brief", 1)],
    "scope": [("Scope & staffing", 5), ("Scoping", 1), ("Scope and staffing plan", 2), ("Scope + staffing", 1)],
    "availability": [("Check availability", 5), ("Availability check", 2), ("Avail. check", 1)],
    "estimate": [("Estimate", 4), ("Quote calc", 2), ("Pricing build", 2), ("Estimate v2", 1), ("Cost estimate", 1)],
    "margin": [("Margin check", 5), ("Margin review", 2), ("Check margin", 1), ("GM check", 1)],
    "approval": [("Approval {amt}", 4), ("Sign off {amt}", 2), ("Approve quote {amt}", 2), ("Quote approval {amt}", 1)],
    "cases": [("Pick case studies", 5), ("Case studies", 2), ("Choose case studies", 1), ("Case study selection", 1)],
    "concept": [("Concept & deck", 5), ("Concept and deck", 2), ("Deck concept", 1), ("Proposal deck", 1)],
    "fill": [("Fill pricing", 4), ("Fill pricing in deck", 2), ("Pricing into deck", 1), ("Copy figures into deck", 2)],
    "review": [("Internal review", 5), ("Deck review", 2), ("Review deck", 1), ("Internal deck review", 1)],
    "terms": [("Terms / MSA", 5), ("MSA", 2), ("Terms and MSA", 1), ("MSA redlines", 1)],
    "send": [("Send", 4), ("Send proposal", 3), ("Send to client", 1)],
    "negotiate": [("Negotiate", 4), ("Negotiation", 2), ("Client negotiation", 1)],
    "signed": [("Signed", 4), ("Contract signed", 2), ("Deal signed", 1)],
    "kickoff": [("Kickoff hand-off", 4), ("Kickoff", 2), ("Handoff to delivery", 1), ("Kick-off handoff", 1)],
}
WAIT_APPROVAL = [("Waiting on approval", 3), ("Waiting for sign-off", 2), ("Awaiting Director approval", 1)]
PEOPLE = {"Sales": ["sales-1", "sales-2"], "PM": ["pm-1"], "Design": ["design-1", "design-2"], "Finance": ["finance-1"],
          "Director": ["director-1"], "Legal": ["legal-1"]}


def truth_params() -> E.Params:
    p = E.truth_params()
    p.staff = {r: len(v) for r, v in PEOPLE.items()}
    return p


def fmt_amount(a: float) -> str:
    return "${:,.0f}".format(a)


class Namer:
    """Each person has a preferred variant per step (55%), otherwise the team's canonical name.
    Choices are a pure function of (seed, person, step, occurrence) so records replay exactly."""

    def __init__(self, seed: int):
        self.seed = seed
        self.pref: dict[tuple[str, str], str] = {}

    def _u(self, *parts) -> float:
        h = hashlib.blake2b(("|".join(str(x) for x in (self.seed, *parts))).encode(), digest_size=8).digest()
        return int.from_bytes(h, "big") / 2 ** 64

    def name(self, person: str, step: str, amount: float | None, occurrence: str = "") -> str:
        vs = VARIANTS[step]
        key = (person, step)
        if key not in self.pref:
            texts = [t for t, _ in vs[1:]]
            self.pref[key] = texts[int(self._u(person, step, "pref") * len(texts))] if texts else vs[0][0]
        if self._u(person, step, occurrence, "use") < 0.55:
            text = self.pref[key]
        else:
            w = np.array([x[1] for x in vs], float)
            cdf = np.cumsum(w / w.sum())
            text = vs[int(np.searchsorted(cdf, self._u(person, step, occurrence, "pick")))][0]
        if "{amt}" in text:
            text = text.replace("{amt}", fmt_amount(amount or 0))
        return text

    def wait_name(self, occurrence: str = "") -> str:
        w = np.array([x[1] for x in WAIT_APPROVAL], float)
        cdf = np.cumsum(w / w.sum())
        return WAIT_APPROVAL[int(np.searchsorted(cdf, self._u("wait", occurrence)))][0]


def canonical_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in ("hash", "pubkey", "sig", "source")}
    s = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _clip_to_workday(s: float, e: float) -> list[tuple[int, float, float]]:
    """Split [s, e) into per-day pieces inside working hours. Returns (day, start, end)."""
    out = []
    d = E.day_of(s)
    while d * E.DAY < e:
        if d % 7 < 5:
            a = max(s, d * E.DAY + E.WORK_START)
            b = min(e, d * E.DAY + E.WORK_END)
            if b > a + 0.5:
                out.append((d, a, b))
        d += 1
    return out


def build_records(run: E.ProcessRun, weeks: int, seed: int) -> tuple[list[dict], dict[str, str]]:
    """Records (one per person per working day with activity) for days [0, weeks*7). Also the raw-name key."""
    namer = Namer(seed)
    horizon = weeks * 7 * E.DAY
    by_person_day: dict[tuple[str, int], list[dict]] = defaultdict(list)
    name_key: dict[str, str] = {}
    fills_week: dict[tuple[str, int], int] = defaultdict(int)

    all_cases = list(run.cases)
    for case in all_cases:
        runs = sorted([r for r in case.runs], key=lambda r: r.start)
        for i, r in enumerate(runs):
            if r.step == "negotiate":
                # the owner records negotiation as waiting on the client
                owner = next((x.person for x in runs if x.step == "send"), None)
                if owner and r.outcome != "lost":
                    for d, a, b in _clip_to_workday(r.start, r.end):
                        if a >= horizon:
                            continue
                        nm = namer.name(owner, "negotiate", None, f"{case.case}:{r.start:.0f}")
                        name_key[nm] = "negotiate"
                        if r.outcome == "revise quote":
                            nm = f"{nm} — revise quote"
                        by_person_day[(owner, d)].append(dict(
                            start=a, end=b, name=nm, kind="waiting", case_id=case.case, tools=["mail"],
                            waiting_on="Client", role="Sales"))
                continue
            prev = runs[i - 1] if i > 0 else None
            nxt = runs[i + 1] if i + 1 < len(runs) else None
            role = "Sales" if r.role == "Client" else r.role
            prev_role = prev.role if prev else None
            handoff_from = prev_role if prev_role and prev_role != role else None
            if r.step in ("request_in", "signed"):
                handoff_from = "Client"
            handoff_to = nxt.role if nxt and nxt.role != role and nxt.role != "Client" else None
            nm = namer.name(r.person, r.step, r.amount, f"{case.case}:{r.start:.0f}")
            name_key[nm] = r.step
            if r.outcome.startswith(("below 25% margin", "missing figures", "changes", "undone")):
                nm_full = f"{nm} — {r.outcome}"
            else:
                nm_full = nm
            for j, (a, b) in enumerate(r.segments):
                if a >= horizon:
                    continue
                d = E.day_of(a)
                step = dict(start=a, end=b, name=nm_full, kind="hands_on", case_id=case.case,
                            tools=list(E.STEP_TOOLS[r.step]), role=role)
                if j == 0 and handoff_from:
                    step["handoff_from"] = handoff_from
                if j == len(r.segments) - 1 and handoff_to:
                    step["handoff_to"] = handoff_to
                if r.step == "fill":
                    wk = (r.person, d // 7)
                    fills_week[wk] += 1
                    step["repeats"] = fills_week[wk]
                if r.by_agent:
                    step["tools"] = sorted(set(step["tools"]) | {"agent"})
                by_person_day[(r.person, d)].append(step)
            # owner waits on the Director for approval
            if r.step == "approval" and prev is not None:
                owner = next((x.person for x in runs if x.step == "brief"), None)
                if owner:
                    for d, a, b in _clip_to_workday(prev.end, r.start):
                        if a >= horizon:
                            continue
                        nm = namer.wait_name(f"{case.case}:{a:.0f}")
                        by_person_day[(owner, d)].append(dict(
                            start=a, end=b, name=nm, kind="waiting", case_id=case.case, tools=["mail"],
                            waiting_on="Director", role="Sales"))
    for r in run.extra_runs:  # renewals (another process, same PM)
        nm = namer.name(r.person, r.step, None, f"{r.case}:{r.start:.0f}")
        name_key[nm] = r.step
        for a, b in r.segments:
            if a >= horizon:
                continue
            d = E.day_of(a)
            wk = (r.person, d // 7)
            fills_week[wk] += 1
            by_person_day[(r.person, d)].append(dict(start=a, end=b, name=nm, kind="hands_on", case_id=r.case,
                                                     tools=list(E.STEP_TOOLS["fill"]) + (["agent"] if r.by_agent else []),
                                                     role="PM", repeats=fills_week[wk]))

    role_of = {p: role for role, ps in PEOPLE.items() for p in ps}
    records = []
    seq = 0
    for (person, d), steps in sorted(by_person_day.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        steps.sort(key=lambda s: s["start"])
        date = (ORIGIN + timedelta(days=d)).date()
        seq += 1
        hands = sum(s["end"] - s["start"] for s in steps if s["kind"] == "hands_on")
        waits = sum(s["end"] - s["start"] for s in steps if s["kind"] == "waiting")
        rsteps = []
        for i, s in enumerate(steps, 1):
            rs = {"idx": i, "start": E.iso(s["start"], ORIGIN), "end": E.iso(s["end"], ORIGIN), "name": s["name"],
                  "kind": s["kind"], "case_id": s["case_id"], "tools": s["tools"]}
            for k in ("handoff_from", "handoff_to", "waiting_on", "repeats"):
                if k in s:
                    rs[k] = s[k]
            rsteps.append(rs)
        last_end = max(s["end"] for s in steps)
        approved = max(last_end + 2, d * E.DAY + 18 * 60 + int(namer._u(person, d, "approved") * 25))
        rec = {
            "id": f"{date.strftime('%m%d')}-{seq:04d}",
            "board_id": BOARD,
            "person_id": person,
            "role": role_of[person],
            "date": date.isoformat(),
            "covers": {"start": E.iso(min(s["start"] for s in steps), ORIGIN), "end": E.iso(last_end, ORIGIN)},
            "steps": rsteps,
            "kept_private": int(namer._u(person, d, "private") * 4),
            "hands_on_min": int(round(hands)),
            "waiting_min": int(round(waits)),
            "approved_at": E.iso(approved, ORIGIN),
        }
        rec["hash"] = canonical_hash(rec)
        rec["pubkey"] = ""
        rec["sig"] = ""
        rec["source"] = "simulated"
        records.append(rec)
    return records, name_key


def run_world(seed: int, weeks: int, schedule: list[tuple[int, list[dict]]]) -> E.ProcessRun:
    """schedule: [(week_index_from, rules)]. Week 0 = baseline."""
    p = truth_params()
    rs = [(w * 7 * E.DAY, rules) for w, rules in schedule]
    if not rs or rs[0][0] != 0:
        rs = [(0, [])] + rs
    return E.ProcessRun(p, seed, weeks, rs).run()


def truth(run: E.ProcessRun, name_key: dict[str, str], weeks: int, change_week: int | None) -> dict:
    p = truth_params()
    t_change = (change_week or weeks) * 7 * E.DAY
    before = E.summarize(run.cases, 0, t_change, run.extra_runs)
    after = E.summarize(run.cases, t_change, weeks * 7 * E.DAY, run.extra_runs) if change_week else None
    med = {k: round(float(np.exp(mu)), 1) for k, (mu, s) in p.durations.items()}
    return {
        "source": "simulated",
        "board_id": BOARD,
        "origin": ORIGIN.isoformat(),
        "weeks": weeks,
        "change_week": change_week,
        "hidden_rules": {
            "approver_batches_per_day": len(p.approver_hours),
            "approver_hours": p.approver_hours,
            "small_quote_threshold_usd": p.small_threshold,
            "p_missing_small": p.p_missing_small,
            "p_missing_large": p.p_missing_large,
            "p_qualify": p.p_qualify, "p_margin_ok": p.p_margin_ok,
            "p_review_fail": {"figures": p.p_review_fail_figures, "layout": p.p_review_fail_layout, "other": p.p_review_fail_other},
            "p_revise": p.p_revise, "p_win": p.p_win, "p_new_client": p.p_new_client,
            "amount_lognormal": list(p.amount), "step_median_min": med, "staff": p.staff,
            "arrivals_per_weekday": p.arrivals, "skill_undo_p": p.skill_undo_p,
            "bottleneck": "approval",
        },
        "name_key": name_key,
        "kpis_before": {k: v for k, v in before.items() if k != "cases"},
        "kpis_after": ({k: v for k, v in after.items() if k != "cases"} if after else None),
        "cases_before": before.get("cases", []),
        "cases_after": after.get("cases", []) if after else [],
    }


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
