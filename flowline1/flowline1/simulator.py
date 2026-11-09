"""Team simulator fitted to the mined ontology and the approved records.

Fit: lognormal MLE per step (hands-on minutes), approver batching schedule from approval timestamps,
Bernoulli rework per decision from back-edge shares, Poisson arrivals by weekday, amount distribution
from the approval step names, staff from the records. Plans are PlanRule lists (SCHEMA §5) run with common
random numbers: 20 seeds, the same seed for every plan, so the gap between plans is the plan.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

from . import engine as E
from . import miner as M

# Assumptions the records cannot tell us yet (declared, see NOTES.md).
AGENT_FILL_MIN = 1.0  # agent fills the deck's pricing (D3 measured ~41 s per run)
AGENT_REVIEW_MIN = 3.0  # PM checks the fill
AGENT_UNDO_P = 0.05  # PM undoes a fill and redoes it by hand
EXPORT_PDF_MIN = 1.0

APPROVAL_OPTIONS = [
    ("signs_all", "Director signs all", [{"type": "approver_batches_per_day", "n": 1}]),
    ("twice_a_day", "Sign-off twice a day", [{"type": "approver_batches_per_day", "n": 2}]),
    ("auto_5k", "Auto-approve under $5k", [{"type": "auto_approve_under", "usd": 5000}]),
]
DECK_OPTIONS = [
    ("by_hand", "deck by hand", []),
    ("template", "shared deck template", [{"type": "template", "name": "shared deck template"}]),
    ("agent", "agent fills the deck (PM reviews)", [{"type": "skill", "skill_id": "fill_deck_from_sheet", "actor": "PM", "reviewer": "PM"}]),
]


def _mle(values: list[float], floor_sigma: float = 0.15, default: tuple[float, float] | None = None) -> tuple[float, float]:
    v = np.array([x for x in values if x > 0], float)
    if len(v) == 0:
        return default or (math.log(30.0), 0.4)
    lv = np.log(v)
    mu = float(lv.mean())
    sigma = float(lv.std(ddof=1)) if len(v) > 2 else 0.35
    return mu, max(sigma, floor_sigma)


def fit(mined: dict) -> tuple[E.Params, dict]:
    """Return fitted Params and a fit report (what came from where)."""
    execs = mined["execs"]
    res = mined["resolver"]
    meta = mined["meta"]
    weeks = max(meta["weeks"], 1)
    report = {"steps": {}, "notes": []}
    node_of = {}
    for sid in E.SEQUENCE:
        cid = M._find_cluster(res, E.STEP_NAME[sid])
        node_of[sid] = cid
        if cid is None:
            report["notes"].append(f"no mined node for '{E.STEP_NAME[sid]}', using default duration")

    by_cluster: dict[int, list[M.Exec]] = defaultdict(list)
    for e in execs:
        by_cluster[e.cluster].append(e)
    by_case: dict[str, list[M.Exec]] = defaultdict(list)
    for e in execs:
        if e.case.startswith("proposal"):
            by_case[e.case].append(e)
    for v in by_case.values():
        v.sort(key=lambda e: e.start)

    # durations: first executions of a step in a case are full; re-occurrences are rework
    full: dict[str, list[float]] = defaultdict(list)
    redo: dict[str, list[float]] = defaultdict(list)
    cluster_to_step = {c: s for s, c in node_of.items() if c is not None}
    for case, seq in by_case.items():
        seen = set()
        for e in seq:
            sid = cluster_to_step.get(e.cluster)
            if sid is None or e.external:
                continue
            (redo if sid in seen else full)[sid].append(e.hands_min)
            seen.add(sid)
    for e in execs:  # renewals: fill pricing happens outside proposals too
        if e.case.startswith("renewal") and cluster_to_step.get(e.cluster) == "fill":
            full["fill"].append(e.hands_min)
    truth_default = E.truth_params().durations
    durations = {}
    for sid in E.SEQUENCE:
        if sid == "negotiate":
            vals = [(e.end - e.start) for e in by_cluster.get(node_of[sid], []) if e.external and e.end > e.start]
            durations[sid] = _mle(vals, default=(math.log(3 * E.DAY), 0.5))
        else:
            durations[sid] = _mle(full[sid], default=truth_default[sid] if not full[sid] else None)
        report["steps"][sid] = {"n": len(full[sid]), "median_min": round(math.exp(durations[sid][0]), 1), "sigma": round(durations[sid][1], 2)}
    rf = []
    for sid in ("estimate", "concept"):
        if redo[sid] and full[sid]:
            rf.append(float(np.median(redo[sid]) / np.median(full[sid])))
    rework_factor = float(np.clip(np.mean(rf), 0.1, 1.0)) if rf else 0.35

    # decisions
    def back_share(sid: str) -> float | None:
        cid = node_of[sid]
        if cid is None:
            return None
        outs = [e for e in mined["ontology"]["edges"] if e["from"] == f"n{cid}"]
        tot = sum(1 for case in by_case.values() for e in case if e.cluster == cid)
        backs = sum(e["share"] for e in outs if e["kind"] == "back")
        return min(backs, 0.95) if tot else None

    cases_with = lambda sid: sum(1 for seq in by_case.values() if any(e.cluster == node_of[sid] for e in seq))
    n_req = max(cases_with("request_in"), 1)
    p_qualify = cases_with("brief") / n_req if n_req else 0.8
    p_margin_ok = 1 - (back_share("margin") or 0.2)
    # review send-backs by reason, from the outcome qualifiers people recorded
    rv = [e for e in by_cluster.get(node_of["review"], [])]
    n_rv = max(len(rv), 1)
    p_fig = sum(1 for e in rv if "figure" in e.qualifier.lower()) / n_rv
    p_lay = sum(1 for e in rv if "layout" in e.qualifier.lower()) / n_rv
    p_oth = sum(1 for e in rv if e.qualifier and "figure" not in e.qualifier.lower() and "layout" not in e.qualifier.lower()) / n_rv
    if not rv:
        p_fig, p_lay, p_oth = 0.18, 0.09, 0.08
    p_revise = back_share("negotiate") or 0.3
    approvals = mined["stats"]["approvals"]
    small = [sb for a, sb in approvals if a < M.SMALL_QUOTE_USD]
    large = [sb for a, sb in approvals if a >= M.SMALL_QUOTE_USD]
    p_missing_small = (sum(small) / len(small)) if small else 0.02
    p_missing_large = (sum(large) / len(large)) if large else 0.4
    if not approvals:
        report["notes"].append("no amounts found in approval step names; using default send-back rates")
    amounts = [a for a, _ in approvals]
    amount = _mle(amounts, default=(math.log(3000), 0.9)) if amounts else (math.log(3000), 0.9)
    negotiated = [seq for seq in by_case.values() if any(e.cluster == node_of["negotiate"] for e in seq)]
    won = sum(1 for seq in negotiated if any(e.cluster == node_of["signed"] for e in seq))
    finished = sum(1 for seq in negotiated if any(e.cluster in (node_of["signed"], node_of["kickoff"]) for e in seq)
                   or seq[-1].cluster == node_of["negotiate"] and seq[-1].end < max(x.end for s in by_case.values() for x in s) - 3 * E.DAY)
    p_win = won / finished if finished >= 3 else 0.41
    sent = cases_with("send")
    p_new_client = cases_with("terms") / sent if sent else 0.4

    # approver batching from approval start times
    appr = [e for e in by_cluster.get(node_of["approval"], [])]
    sessions_per_day = []
    hours = []
    for d, es in _group_by_day(appr).items():
        starts = sorted(e.start for e in es)
        sessions = 1
        for a, b in zip(starts, starts[1:]):
            if b - a > 90:
                sessions += 1
        sessions_per_day.append(sessions)
        hours.append((starts[0] % E.DAY) / 60)
    batches = int(np.median(sessions_per_day)) if sessions_per_day else 1
    evening = float(np.median(hours)) if hours else 18.0
    jitter = float(np.std(hours) * 60) if len(hours) > 2 else 10.0  # spread of the day's first signature
    approver_hours = [round(evening, 2)] if batches <= 1 else [round(12.5, 2), round(evening, 2)]

    # arrivals per weekday
    req = by_cluster.get(node_of["request_in"], [])
    per_wd = Counter(E.weekday(e.start) for e in req)
    arrivals = [per_wd.get(wd, 0) / weeks for wd in range(5)]
    mean_rate = sum(arrivals) / 5
    arrivals = [0.5 * a + 0.5 * mean_rate for a in arrivals]  # shrink weekday rates toward the mean
    if sum(arrivals) == 0:
        arrivals = [0.8] * 5

    # wait before internal review (business minutes) — the Director's other work, seen only as a wait
    rv_waits = []
    for seq in by_case.values():
        for i, e in enumerate(seq):
            if e.cluster == node_of["review"] and i > 0:
                rv_waits.append(E.business_minutes(seq[i - 1].end, e.start) + 1.0)
    review_wait = _mle(rv_waits, floor_sigma=0.3, default=(math.log(30), 0.8))

    staff = Counter(meta["roles"].values())
    renewals = sum(1 for e in execs if e.case.startswith("renewal")) / weeks

    params = E.Params(
        durations=durations, p_qualify=p_qualify, p_margin_ok=p_margin_ok, p_missing_small=p_missing_small,
        p_missing_large=p_missing_large, p_review_fail_figures=p_fig, p_review_fail_layout=p_lay,
        p_review_fail_other=p_oth, p_revise=p_revise, p_win=p_win,
        p_new_client=p_new_client, amount=amount, small_threshold=M.SMALL_QUOTE_USD, approver_hours=approver_hours,
        approver_jitter_min=max(jitter, 3.0), arrivals=arrivals,
        staff={r: staff.get(r, 1) for r in ("Sales", "PM", "Design", "Finance", "Director", "Legal")},
        rework_factor=rework_factor, director_blocks=None, review_wait=review_wait, renewals_per_week=renewals,
        skill_fill_min=AGENT_FILL_MIN, skill_review_min=AGENT_REVIEW_MIN, skill_undo_p=AGENT_UNDO_P,
        export_pdf_min=EXPORT_PDF_MIN,
    )
    report.update({
        "p_qualify": round(p_qualify, 3), "p_margin_ok": round(p_margin_ok, 3), "p_missing_small": round(p_missing_small, 3),
        "p_missing_large": round(p_missing_large, 3), "p_review_fail": {"figures": round(p_fig, 3), "layout": round(p_lay, 3), "other": round(p_oth, 3)},
        "p_revise": round(p_revise, 3),
        "p_win": round(p_win, 3), "p_new_client": round(p_new_client, 3), "amount_median_usd": round(math.exp(amount[0])),
        "amount_sigma": round(amount[1], 2), "approver_batches_per_day": batches, "approver_hours": approver_hours,
        "approver_jitter_min": round(jitter, 1), "arrivals_per_weekday": [round(a, 2) for a in arrivals],
        "rework_factor": round(rework_factor, 2), "review_wait_median_min": round(math.exp(review_wait[0]), 1),
        "staff": params.staff, "renewals_per_week": round(renewals, 1),
        "assumptions": {"agent_fill_min": AGENT_FILL_MIN, "agent_review_min": AGENT_REVIEW_MIN, "agent_undo_p": AGENT_UNDO_P,
                        "template": "removes review send-backs recorded as layout problems; no measured deck-time effect yet",
                        "agent": "removes review send-backs recorded as wrong figures (exact copy from the sheet)",
                        "export_pdf_min": EXPORT_PDF_MIN},
    })
    return params, report


def _group_by_day(execs):
    out = defaultdict(list)
    for e in execs:
        out[E.day_of(e.start)].append(e)
    return out


# ----------------------------------------------------------------------------- plans
def plan_catalogue() -> list[dict]:
    plans = []
    for a_id, a_name, a_rules in APPROVAL_OPTIONS:
        for d_id, d_name, d_rules in DECK_OPTIONS:
            plans.append({"id": f"{a_id}__{d_id}", "name": a_name, "sub": f"+ {d_name}", "rules": a_rules + d_rules,
                          "today": a_id == "signs_all" and d_id == "by_hand", "_a": a_id, "_d": d_id})
    return plans


def simulate(params: E.Params, rules: list[dict], seed: int, weeks: int) -> dict:
    run = E.ProcessRun(params, seed, weeks, [(0, rules)]).run()
    return E.summarize(run.cases, 0, weeks * 7 * E.DAY, run.extra_runs)


def run_plans(params: E.Params, plans: list[dict], seeds: list[int], weeks: int) -> dict:
    """Common random numbers: each seed is one 'luck'; every plan replays it."""
    per_plan = {p["id"]: [] for p in plans}
    for seed in seeds:
        for p in plans:
            per_plan[p["id"]].append(simulate(params, p["rules"], seed, weeks))
    return per_plan


def who_changes(plan: dict, today_signoffs: float, auto_share: float) -> tuple[list[dict], str]:
    who = []
    a, d = plan["_a"], plan["_d"]
    if a == "signs_all":
        who.append({"role": "Director", "change": "keeps signing every quote"})
    elif a == "twice_a_day":
        who.append({"role": "Director", "change": "signs at midday and at 18:00"})
    else:
        who.append({"role": "Director", "change": "signs only quotes over $5k"})
    if d == "by_hand":
        who.append({"role": "PM", "change": "nothing to change"})
    elif d == "template":
        who.append({"role": "Design", "change": "starts decks from the template"})
    else:
        who.append({"role": "PM", "change": "checks the deck, doesn't type it"})
    who.append({"role": "Sales", "change": "nothing to change"})
    assert all(len(w["change"]) <= 40 for w in who)
    return who, plan["sub"]


def plans_page(params: E.Params, mined: dict, seeds: list[int], weeks: int, recomputed_at: str,
               measured_today_h: float | None = None) -> tuple[dict, dict]:
    """measured_today_h: when given, every plan's hours = measured baseline x (sim_plan / sim_today), so the
    simulator contributes relative effects and the board shows one baseline number everywhere."""
    plans = plan_catalogue()
    per_plan = run_plans(params, plans, seeds, weeks)
    today = next(p for p in plans if p["today"])
    today_runs = per_plan[today["id"]]
    sim_today_h = float(np.median([r["cycle_h"] for r in today_runs if r.get("n")]))
    f = (measured_today_h / sim_today_h) if measured_today_h else 1.0
    today_h = sim_today_h * f
    # amounts under $5k share (from the fitted amount distribution)
    mu, sg = params.amount
    from scipy.stats import norm
    auto_share = float(norm.cdf((math.log(5000) - mu) / sg))

    rows = []
    for p in plans:
        runs = [r for r in per_plan[p["id"]] if r.get("n")]
        med = np.array([r["cycle_h"] for r in runs])
        rows.append({"plan": p, "hours": float(np.median(med)), "work_h": float(np.median([r["work_h"] for r in runs])),
                     "waiting_h": float(np.median([r["waiting_h"] for r in runs])),
                     "range": (float(np.percentile(med, 10)), float(np.percentile(med, 90))), "per_seed": med})
    rows.sort(key=lambda r: r["hours"])
    best = rows[0]
    # held_best_n: in how many seeds was the best plan the fastest of all plans?
    n_seeds = len(seeds)
    held = 0
    for i in range(n_seeds):
        vals = {r["plan"]["id"]: r["per_seed"][i] for r in rows if len(r["per_seed"]) > i}
        if vals and min(vals, key=vals.get) == best["plan"]["id"]:
            held += 1
    out_plans = []
    for rank, r in enumerate(rows, 1):
        p = r["plan"]
        who, sub = who_changes(p, today_runs[0].get("signoffs_per_day", 0), auto_share)
        out_plans.append({
            "id": p["id"], "rank": rank, "name": p["name"], "sub": sub,
            "hours": round(r["hours"] * f, 1), "work_h": round(r["work_h"] * f, 1), "waiting_h": round(r["waiting_h"] * f, 1),
            "vs_today": round(r["hours"] / sim_today_h - 1, 3) if sim_today_h else 0.0,
            "best": r is best, "today": p["today"],
            "held_best_n": held if r is best else int(sum(1 for i in range(n_seeds) if all(r["per_seed"][i] <= o["per_seed"][i] for o in rows))),
            "range_h": [round(r["range"][0] * f, 1), round(r["range"][1] * f, 1)],
            "who": who, "rules": p["rules"],
        })
    second = (rows[1]["hours"] - best["hours"]) * f if len(rows) > 1 else 0.0
    page = {
        "source": "simulated",
        "board_id": mined["ontology"]["board_id"], "reruns": n_seeds, "weeks": weeks,
        "headline": f"{best['plan']['name']} {best['plan']['sub']}: {today_h:.0f} hours → {best['hours'] * f:.0f}.",
        "today_h": round(today_h, 1), "plans": out_plans,
        "note": (f"Every plan replays the same requests and meetings over {weeks} weeks, {n_seeds} times with new luck. "
                 f"The best plan held in {held} of {n_seeds} reruns; the next best is {second:.1f} h slower. "
                 f"Ranges are the 10th–90th percentile across reruns"
                 + (f"; relative effects from {n_seeds} reruns applied to the measured baseline of {today_h:.1f} h" if measured_today_h else "")
                 + ". Nothing changes until you approve."),
        "recomputed_at": recomputed_at,
    }
    detail = {"per_plan": {pid: [{k: v for k, v in r.items() if k != "cases"} for r in runs] for pid, runs in per_plan.items()},
              "best_id": best["plan"]["id"], "best_rules": best["plan"]["rules"], "auto_share": auto_share,
              "sim_today_h": sim_today_h, "scale": f}
    return page, detail
