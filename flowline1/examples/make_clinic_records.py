"""Synthesise ~120 plausible approved Records for a five-person dental clinic — a second, different company for `fit`.

No world.py, no flowline1 imports: a small stand-alone generator (stdlib only). Process "pre-auth" (insurance
pre-authorisation): intake -> eligibility check -> submit pre-auth -> waits on the insurer (days) -> charting ->
dentist note -> claim -> office-manager approval (batched once a day at 16:30; amounts in the step name, send-backs
for missing codes) -> schedule treatment. Routine "visit" eligibility checks run alongside (the repeated hands-on
step). People name steps their own way (variants that an end-of-day review would confirm as the same step).

    python examples/make_clinic_records.py [out.json] [--seed 7] [--weeks 8]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

BOARD = "clinic"
TZ = "-05:00"  # America/Chicago, CDT
ORIGIN = date(2026, 9, 7)  # a Monday
DAY = 1440
OPEN, CLOSE = 8 * 60, 17 * 60

PEOPLE = {"front-1": "Front desk", "hyg-1": "Hygienist", "dentist-1": "Dentist", "mgr-1": "Office manager", "billing-1": "Billing"}
# step: (person, median minutes, sigma, tools, name variants)
STEPS = {
    "intake": ("front-1", 10, 0.35, ["pms", "phone"], ["Intake", "Patient intake", "Intake call"]),
    "eligibility": ("front-1", 14, 0.35, ["portal", "browser"], ["Eligibility check", "Check eligibility", "Eligibility checks"]),
    "submit": ("front-1", 12, 0.35, ["portal", "fax"], ["Submit pre-auth", "Submit pre-authorization", "Pre-auth submit"]),
    "charting": ("hyg-1", 20, 0.30, ["ehr"], ["Perio charting", "Charting", "Perio chart"]),
    "note": ("dentist-1", 22, 0.35, ["ehr"], ["Dentist note", "Dentist notes", "Note by dentist"]),
    "claim": ("billing-1", 25, 0.35, ["pms", "forms"], ["Claim form", "Prepare claim form", "Claim form prep"]),
    "approval": ("mgr-1", 8, 0.30, ["pms"], ["Approve claim {amt}", "Claim approval {amt}", "Approve the claim {amt}"]),
    "schedule": ("front-1", 8, 0.35, ["pms", "phone"], ["Schedule treatment", "Schedule the treatment", "Treatment scheduling"]),
}
WAIT_NAMES = ["Waiting on insurer", "Insurer wait", "Waiting for the insurer"]
HANDOFF_WAIT_MIN = {"eligibility": (5, 0.8), "submit": (10, 0.8), "charting": (90, 0.7), "note": (150, 0.7), "claim": (120, 0.8), "schedule": (30, 0.8)}


def lognorm(rng: random.Random, median: float, sigma: float) -> float:
    return median * math.exp(sigma * rng.gauss(0, 1))


def is_work(t: float) -> bool:
    d, m = divmod(t, DAY)
    return int(d) % 7 < 5 and OPEN <= m < CLOSE


def to_work(t: float) -> float:
    d, m = divmod(t, DAY)
    d = int(d)
    if d % 7 < 5:
        if OPEN <= m < CLOSE:
            return t
        if m < OPEN:
            return d * DAY + OPEN
    d += 1
    while d % 7 >= 5:
        d += 1
    return d * DAY + OPEN


def work(t: float, minutes: float) -> list[tuple[float, float]]:
    segs = []
    t = to_work(t)
    while minutes > 1e-9:
        eod = int(t // DAY) * DAY + CLOSE
        chunk = min(minutes, eod - t)
        segs.append((t, t + chunk))
        t += chunk
        minutes -= chunk
        if minutes > 1e-9:
            t = to_work(t)
    return segs


def add_work(t: float, minutes: float) -> float:
    return work(t, minutes)[-1][1] if minutes > 0 else to_work(t)


def iso(t: float) -> str:
    return (datetime(ORIGIN.year, ORIGIN.month, ORIGIN.day) + timedelta(minutes=t)).isoformat(timespec="seconds") + TZ


def clip_days(s: float, e: float):
    d = int(s // DAY)
    while d * DAY < e:
        if d % 7 < 5:
            a, b = max(s, d * DAY + OPEN), min(e, d * DAY + CLOSE)
            if b > a + 0.5:
                yield d, a, b
        d += 1


def canonical_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in ("hash", "pubkey", "sig", "source")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def generate(seed: int = 7, weeks: int = 8) -> list[dict]:
    rng = random.Random(seed)
    by_person_day: dict[tuple[str, int], list[dict]] = defaultdict(list)
    pref = {(p, s): rng.randrange(len(STEPS[s][4])) for p in PEOPLE for s in STEPS}

    def name(step: str, amount: float | None = None) -> str:
        person = STEPS[step][0]
        vs = STEPS[step][4]
        text = vs[pref[(person, step)]] if rng.random() < 0.6 else vs[0]
        return text.replace("{amt}", f"${amount:,.0f}") if amount is not None else text

    def put(person, step_key, segs, nm, case, kind="hands_on", tools=None, **extra):
        for j, (a, b) in enumerate(segs):
            st = {"start": a, "end": b, "name": nm, "kind": kind, "case_id": case, "tools": list(tools or STEPS[step_key][3]) if step_key else list(tools or [])}
            if "waiting_on" in extra:
                st["waiting_on"] = extra["waiting_on"]  # every day's chunk of a wait says who it waits on
            if j == 0:
                st.update({k: v for k, v in extra.items() if k in ("handoff_from", "repeats")})
            if j == len(segs) - 1 and "handoff_to" in extra:
                st["handoff_to"] = extra["handoff_to"]
            by_person_day[(person, int(a // DAY))].append(st)

    # approver batches once a day at 16:30 (+-10 min)
    def next_session(t: float) -> float:
        d = int(t // DAY)
        while True:
            if d % 7 < 5:
                s = d * DAY + 16 * 60 + 30 + rng.gauss(0, 10)
                if s > t:
                    return s
            d += 1

    horizon = weeks * 7 * DAY
    n = 0
    for d in range(weeks * 7):
        if d % 7 >= 5:
            continue
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            n += 1
            case = f"pre-auth #{100 + n}"
            amount = round(lognorm(rng, 420, 0.8), -1)
            t = d * DAY + OPEN + rng.random() * (CLOSE - OPEN - 60)
            # intake (the patient's call) -> eligibility -> submit
            segs = work(t, lognorm(rng, *STEPS["intake"][1:3])); put("front-1", "intake", segs, name("intake"), case, handoff_from="Patient"); t = segs[-1][1]
            t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["eligibility"]))
            segs = work(t, lognorm(rng, *STEPS["eligibility"][1:3])); put("front-1", "eligibility", segs, name("eligibility"), case); t = segs[-1][1]
            attempt = 0
            while True:
                attempt += 1
                t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["submit"]))
                segs = work(t, lognorm(rng, *STEPS["submit"][1:3])); put("front-1", "submit", segs, name("submit"), case, handoff_to="Insurer"); t = segs[-1][1]
                # the insurer answers in 1-5 working days (wall clock), the front desk records the wait day by day
                wait_end = t + lognorm(rng, 2.3 * DAY, 0.45)
                denied = attempt == 1 and rng.random() < 0.12
                wn = WAIT_NAMES[rng.randrange(3)] + (" — denied, resubmit" if denied else "")
                put("front-1", None, list((a, b) for _, a, b in clip_days(t, wait_end)), wn, case, kind="waiting", tools=["portal"], waiting_on="Insurer")
                t = wait_end
                if not denied:
                    break
            # hygienist charting, dentist note
            t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["charting"]))
            segs = work(t, lognorm(rng, *STEPS["charting"][1:3])); put("hyg-1", "charting", segs, name("charting"), case, handoff_from="Front desk", handoff_to="Dentist"); t = segs[-1][1]
            t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["note"]))
            segs = work(t, lognorm(rng, *STEPS["note"][1:3])); put("dentist-1", "note", segs, name("note"), case, handoff_from="Hygienist", handoff_to="Billing"); t = segs[-1][1]
            # claim -> manager approval (batched), send-backs for missing codes
            while True:
                t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["claim"]))
                segs = work(t, lognorm(rng, *STEPS["claim"][1:3])); put("billing-1", "claim", segs, name("claim"), case, handoff_from="Dentist", handoff_to="Office manager"); t = segs[-1][1]
                s = next_session(t)
                dur = lognorm(rng, *STEPS["approval"][1:3])
                sent_back = rng.random() < (0.18 if amount >= 500 else 0.03)
                nm = name("approval", amount) + (" — missing code" if sent_back else "")
                put("mgr-1", "approval", [(s, s + dur)], nm, case, handoff_from="Billing")
                t = s + dur
                if not sent_back:
                    break
            t = add_work(t, lognorm(rng, *HANDOFF_WAIT_MIN["schedule"]))
            segs = work(t, lognorm(rng, *STEPS["schedule"][1:3])); put("front-1", "schedule", segs, name("schedule"), case, handoff_from="Office manager")
    # routine visits: the front desk checks eligibility for the day's patients (the repeated step)
    v = 0
    for d in range(weeks * 7):
        if d % 7 >= 5:
            continue
        reps = 0
        for _ in range(rng.choice([2, 3, 3, 4])):
            v += 1
            reps += 1
            t = d * DAY + OPEN + rng.random() * (CLOSE - OPEN - 30)
            segs = work(t, lognorm(rng, 7, 0.3))
            put("front-1", "eligibility", segs, name("eligibility"), f"visit #{500 + v}", repeats=reps)

    records = []
    seq = 0
    for (person, d), steps in sorted(by_person_day.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if d * DAY >= horizon + 7 * DAY:
            continue
        steps.sort(key=lambda s: s["start"])
        day = ORIGIN + timedelta(days=d)
        seq += 1
        hands = sum(s["end"] - s["start"] for s in steps if s["kind"] == "hands_on")
        waits = sum(s["end"] - s["start"] for s in steps if s["kind"] == "waiting")
        rsteps = []
        for i, s in enumerate(steps, 1):
            rs = {"idx": i, "start": iso(s["start"]), "end": iso(s["end"]), "name": s["name"], "kind": s["kind"], "case_id": s["case_id"], "tools": s["tools"]}
            for k in ("handoff_from", "handoff_to", "waiting_on", "repeats"):
                if k in s:
                    rs[k] = s[k]
            rsteps.append(rs)
        last_end = max(s["end"] for s in steps)
        rec = {"id": f"{day.strftime('%m%d')}-{seq:04d}", "board_id": BOARD, "person_id": person, "role": PEOPLE[person], "date": day.isoformat(),
               "covers": {"start": iso(min(s["start"] for s in steps)), "end": iso(last_end)}, "steps": rsteps,
               "kept_private": rng.randrange(3), "hands_on_min": int(round(hands)), "waiting_min": int(round(waits)),
               "approved_at": iso(max(last_end + 2, d * DAY + CLOSE + 5 + rng.randrange(20)))}
        rec["hash"] = canonical_hash(rec)
        rec["pubkey"] = ""
        rec["sig"] = ""
        records.append(rec)
    return records


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="../data/boards/clinic/records.json")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--weeks", type=int, default=8)
    args = ap.parse_args()
    recs = generate(args.seed, args.weeks)
    import os

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    cases = {s["case_id"] for r in recs for s in r["steps"] if s["case_id"].startswith("pre-auth")}
    print(f"{len(recs)} records, {len({r['person_id'] for r in recs})} people, {len(cases)} pre-auth cases -> {args.out}")


if __name__ == "__main__":
    main()
