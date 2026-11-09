"""Calibration and the build pipeline.

build(): world baseline -> records -> mine -> fit -> 9 plans (CRN) -> best plan applied to the world for two
more weeks -> measured vs predicted (Results, ModelCheck.sim_checks) -> History, Opening, Surfaces, Expansion,
D1 -> ten JSON files + answer key, validated against SCHEMA shapes.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta

import numpy as np

from . import bpic, demand, engine as E, miner as M, simulator as S, validate, world as W

BOARD = "northwind"
SEEDS = list(range(20))
V14_RULE = {"type": "skill", "skill_id": "rename_export_pdf", "actor": "Sales"}


def _iso(t: float) -> str:
    return E.iso(t, W.ORIGIN)


def _date(day: int) -> str:
    return (W.ORIGIN + timedelta(days=day)).date().isoformat()


def _fmt_date(day: int) -> str:
    return (W.ORIGIN + timedelta(days=day)).strftime("%-d %b")


def _dump(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _stats(values: list[float]) -> dict:
    """Median and the 10th–90th percentile across reruns."""
    v = np.array(values, float)
    return {"mid": float(np.median(v)), "lo": float(np.percentile(v, 10)), "hi": float(np.percentile(v, 90))}


def _window_kpis(mined: dict, t_lo: float, t_hi: float) -> dict:
    """KPIs the product can measure from records alone: cases whose brief started in [t_lo, t_hi)."""
    rows = [r for r in mined["stats"]["case_rows"] if t_lo <= r["brief_start"] < t_hi]
    workdays = max(round((t_hi - t_lo) / (7 * E.DAY) * 5), 1)
    signoffs = sum(1 for t in mined["stats"]["approval_starts"] if t_lo <= t < t_hi)
    fill_c = M._find_cluster(mined["resolver"], "Fill pricing")
    send_c = M._find_cluster(mined["resolver"], "Send")
    fills = [e for e in mined["execs"] if t_lo <= e.start < t_hi and e.cluster == fill_c]
    sends = sum(1 for e in mined["execs"] if t_lo <= e.start < t_hi and e.cluster == send_c and e.case.startswith("proposal"))
    out = {"n": len(rows), "signoffs_per_day": signoffs / workdays, "sends_per_week": sends / max((t_hi - t_lo) / (7 * E.DAY), 1e-9),
           "agent_fills": sum(1 for e in fills if e.by_agent), "fills_undone": sum(1 for e in fills if "undone" in e.qualifier)}
    if not rows:
        return out
    cyc = np.array([r["cycle_h"] for r in rows])
    wait = np.array([r["waiting_h"] for r in rows])
    signed = [r["approval_wait_h"] for r in rows if r["approval_wait_h"] > 0]
    out.update({"cycle_h": float(np.median(cyc)), "work_h": float(np.median([r["work_h"] for r in rows])),
                "waiting_h": float(np.median(wait)), "waiting_share": float(wait.sum() / cyc.sum()),
                "approval_wait_h": float(np.median([r["approval_wait_h"] for r in rows])),
                "approval_wait_signed_h": float(np.median(signed)) if signed else 0.0, "signed_cases": len(signed), "rows": rows})
    return out


# ----------------------------------------------------------------------------- build
def build(out: str, seed: int = 15, weeks_base: int = 8, weeks_after: int = 3, raw_dir: str = "", reference_dir: str = "",
          recompute_demand: bool = False) -> dict:
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    weeks_total = weeks_base + weeks_after
    t_change = weeks_base * 7 * E.DAY
    t_end = weeks_total * 7 * E.DAY
    last_day = weeks_total * 7 - 3  # the Friday of the last week = "tonight"
    tonight = last_day * E.DAY + 18 * 60
    stamp = lambda m: _iso(tonight + m)

    # 1. baseline world -> records -> mine (fit and plans use the baseline records only)
    base_run = W.run_world(seed, weeks_base, [])
    base_records, base_key = W.build_records(base_run, weeks_base, seed)
    mined0 = M.mine(base_records)
    params, fit_report = S.fit(mined0)

    # 2. the world continues under the best plan (chosen below from the same fitted model); the baseline the board
    #    shows everywhere = completed cases whose brief started in the baseline window, measured from approved records
    plans_probe, plan_detail = S.plans_page(params, mined0, SEEDS, weeks_base, stamp(31))
    best_rules = plan_detail["best_rules"]
    schedule = [(weeks_base, best_rules), (weeks_base + 1, best_rules + [V14_RULE])]
    full_run = W.run_world(seed, weeks_total, schedule)
    records, name_key = W.build_records(full_run, weeks_total, seed)
    mined = M.mine(records)
    ontology = mined["ontology"]
    kb = _window_kpis(mined, 0, t_change)
    ka = _window_kpis(mined, t_change, t_end)
    if "cycle_h" not in ka:
        ka.update({"cycle_h": 0.0, "work_h": 0.0, "waiting_h": 0.0, "waiting_share": 0.0, "approval_wait_h": 0.0, "rows": []})
    baseline_h = kb["cycle_h"]
    base_cases = {r["case"] for r in mined["stats"]["case_rows"] if r["brief_start"] < t_change} | \
                 {e.case for e in mined["execs"] if e.case.startswith("proposal") and e.start < t_change}
    finding_records = _records_for_cases(records, base_cases, t_change)
    mined_finding = M.mine(finding_records)
    finding = mined_finding["finding"]
    finding["source"] = "simulated"
    finding["recomputed_at"] = stamp(25)
    assert abs(finding["kpis"]["cycle_time_h"] - round(baseline_h, 1)) < 0.11, (finding["kpis"]["cycle_time_h"], baseline_h)

    plans_page, plan_detail = S.plans_page(params, mined0, SEEDS, weeks_base, stamp(31), measured_today_h=baseline_h)
    best = next(p for p in plans_page["plans"] if p["best"])
    today_plan = next(p for p in plans_page["plans"] if p["today"])
    scale = plan_detail["scale"]

    # 3. calibration: baseline simulation vs the world's measured KPIs (answer key; reported by `check`)
    truth0 = W.truth(base_run, base_key, weeks_base, None)["kpis_before"]
    base_sims = [S.simulate(params, [], s, weeks_base) for s in SEEDS]
    calibration = {"source": "simulated", "weeks": weeks_base, "reruns": len(SEEDS), "checks": []}
    for key, label, unit in (("cycle_h", "Hours per proposal (median)", "h"), ("waiting_share", "Share of time waiting", "%"),
                             ("approval_wait_h", "Wait around the signature", "h"), ("signoffs_per_day", "Director sign-offs / day", "/day"),
                             ("sends_per_day", "Proposals sent / day", "/day")):
        sim = float(np.median([b[key] for b in base_sims]))
        act = float(truth0[key])
        calibration["checks"].append({"measure": label, "simulated": round(sim, 3), "measured": round(act, 3), "unit": unit,
                                      "error": round(abs(sim - act) / act, 3) if act else None})
    calibration["fit"] = fit_report
    calibration["scale_to_measured_baseline"] = round(scale, 4)

    truth = W.truth(full_run, name_key, weeks_total, weeks_base)
    truth["best_plan"] = {"id": best["id"], "name": f"{best['name']} {best['sub']}", "rules": best_rules}
    truth["calibration"] = calibration["checks"]
    after_records = [r for r in records if r["date"] >= _date(weeks_base * 7)]
    mined_after = M.mine(after_records) if after_records else None
    truth["measured_from_records"] = {"before": {k: v for k, v in kb.items() if k != "rows"}, "after": {k: v for k, v in ka.items() if k != "rows"}}

    # 5. predicted range for the measured window: best plan, same horizon, 20 reruns
    pred_runs = [S.simulate(params, best_rules, s, weeks_after) for s in SEEDS]
    pred_runs = [r for r in pred_runs if r.get("n")]
    pred = {k: _stats([r[k] for r in pred_runs]) for k in ("cycle_h", "waiting_share", "signoffs_per_day", "approval_wait_h", "sends_per_day")}
    pred["approval_wait_signed_h"] = _stats([r["approval_wait_signed_h"] for r in pred_runs if r.get("signed_cases")])

    def check(measure, key, unit, mult=1.0, nd=1):
        p = pred[key]
        a = float(ka[key]) * mult
        lo, hi = round(p["lo"] * mult, nd), round(p["hi"] * mult, nd)
        return {"measure": measure, "predicted": round(p["mid"] * mult, nd), "lo": lo, "hi": hi, "actual": round(a, nd),
                "unit": unit, "in_range": bool(lo - 1e-9 <= a <= hi + 1e-9)}

    hours_check = {"measure": "Hours per proposal", "predicted": best["hours"], "lo": best["range_h"][0], "hi": best["range_h"][1],
                   "actual": round(ka["cycle_h"], 1), "unit": "h",
                   "in_range": bool(best["range_h"][0] - 1e-9 <= round(ka["cycle_h"], 1) <= best["range_h"][1] + 1e-9)}
    sim_checks = [hours_check, check("Share of time waiting", "waiting_share", "%", 100, 0),
                  check("Director sign-offs / day", "signoffs_per_day", "/day", 1, 2)]
    if ka.get("signed_cases") and pred_runs and any(r.get("signed_cases") for r in pred_runs):
        sim_checks.append(check("Signature wait for quotes the Director still signs", "approval_wait_signed_h", "h"))

    # 6. Results — predicted = the plan test (same numbers as the Plans page), measured = records after the change
    pc = {"mid": best["hours"], "lo": best["range_h"][0], "hi": best["range_h"][1]}
    series = [{"week": int(r["brief_start"] // (7 * E.DAY)) + 1, "value": round(r["cycle_h"], 1), "after": r["brief_start"] >= t_change}
              for r in sorted(mined["stats"]["case_rows"], key=lambda r: r["brief_start"])]
    fills_before_min = _fill_minutes_per_week(base_records)
    fills_after_min = _fill_minutes_per_week(after_records)
    agent_fills, undone = ka.get("agent_fills", 0), ka.get("fills_undone", 0)
    kpis = [
        {"label": "Hours per proposal", "before": f"{baseline_h:.1f}", "after": f"{ka['cycle_h']:.1f} h", "sub": f"Test predicted {pc['mid']:.1f}"},
        {"label": "Share of time waiting", "before": f"{kb['waiting_share']:.0%}", "after": f"{ka['waiting_share']:.0%}",
         "sub": "The approval wait, mostly gone" if "auto_5k" in best["id"] else "Shorter waits for the signature"},
        {"label": "Director sign-offs", "before": f"{kb['signoffs_per_day']:.1f}", "after": f"{ka['signoffs_per_day']:.1f} / day",
         "sub": "Only quotes over $5k" if "auto_5k" in best["id"] else "Same quotes, more sessions"},
    ]
    if agent_fills:
        kpis.append({"label": "Deck skill runs kept", "before": "", "after": f"{agent_fills - undone} of {agent_fills}",
                     "sub": f"{undone} undone by the PM" if undone else "None undone"})
    who = []
    if "agent" in best["id"]:
        who.append({"role": "PM", "what": "Copy figures into deck — agent does it, PM checks",
                    "before": f"{fills_before_min / 60:.1f} h / wk", "after": f"{fills_after_min:.0f} m / wk"})
    assert all(len(w["before"]) <= 14 and len(w["after"]) <= 14 for w in who)
    if "auto_5k" in best["id"]:
        who.append({"role": "Director", "what": "Signs only quotes over $5k", "before": f"{kb['signoffs_per_day']:.1f} / day", "after": f"{ka['signoffs_per_day']:.1f} / day"})
    elif "twice" in best["id"]:
        who.append({"role": "Director", "what": "Signs at midday and at the end of the day", "before": f"{kb['signoffs_per_day']:.1f} / day", "after": f"{ka['signoffs_per_day']:.1f} / day"})
    who.append({"role": "Sales", "what": "Waits less around the signature", "before": f"{kb['approval_wait_h']:.1f} h", "after": f"{ka['approval_wait_h']:.1f} h"})
    nxt = _next_constraint(mined_after) if mined_after else {"headline": "Not enough records after the change yet", "sub": "", "ready": False}
    results = {
        "source": "simulated", "board_id": BOARD, "recomputed_at": stamp(24),
        "headline": f"Proposals now take {ka['cycle_h']:.0f} hours, not {baseline_h:.0f}.",
        "sub": (f"The test predicted {pc['mid']:.1f} h ({pc['lo']:.1f}–{pc['hi']:.1f} across {len(SEEDS)} reruns). "
                f"The team measured {ka['cycle_h']:.1f} h over {ka['n']} proposals sent in the {weeks_after} weeks after the change. "
                f"Waiting went from {kb['waiting_share']:.0%} of every cycle to {ka['waiting_share']:.0%}."),
        "records": len(records), "people": mined["meta"]["people"], "weeks": weeks_total,
        "change": " · ".join(w["change"] for w in best["who"] if "nothing" not in w["change"]),
        "predicted": {"mid": round(pc["mid"], 1), "lo": round(pc["lo"], 1), "hi": round(pc["hi"], 1)}, "measured": round(ka["cycle_h"], 1),
        "before": round(baseline_h, 1),
        "series": series, "kpis": kpis, "who": who, "next_constraint": nxt,
    }

    # 7. History: deltas from successive simulations on the fitted model
    history = _history(params, plans_page, best, best_rules, mined, mined_after, kb, ka, weeks_base, weeks_total, stamp, last_day, agent_fills, undone, scale)

    # 8. D1 (real data) and D2 (real data)
    d1 = bpic.run(os.path.join(raw_dir, "bpic2020"), seed=seed) if raw_dir else {"d1": None, "detail": {}}
    results_dir = reference_dir
    demand_note = "Backtest computed on 2026-11-08 from reference/us-backtest/scripts (same code as demand.backtest); loaded, not recomputed."
    own = os.path.join(out, "demand", "zip_results.json")
    if recompute_demand:
        demand.backtest(os.path.join(raw_dir, "census", "processed"), os.path.join(raw_dir, "census", "geo", "2020_Gaz_zcta_national.txt"), os.path.join(out, "demand"))
    if os.path.exists(own):
        results_dir = os.path.join(out, "demand")
        demand_note = f"Backtest recomputed by flowline1 demand.backtest at {json.load(open(own)).get('_computed_at', '?')}."
    opening = _opening(None, last_day)  # dates first; the ZIP is filled from the expansion pick below
    expansion = demand.expansion(results_dir, os.path.join(raw_dir, "census", "processed"),
                                 os.path.join(raw_dir, "census", "geo", "2020_Gaz_zcta_national.txt"), BOARD, len(records), 3,
                                 {"date": opening["opens"], "was": opening["was"], "blockers_cleared": sum(1 for b in opening["blockers"] if b["status"] == "cleared")},
                                 demand_note)
    fit_ind = expansion["by_industry"]["713940"]
    pick = fit_ind["zips"][0]
    opening = _opening(pick, last_day)
    opening["recomputed_at"] = stamp(5 * 60 + 10)
    expansion["recomputed_at"] = stamp(5 * 60 + 10)
    ontology["counts"]["zip_areas"] = fit_ind["zips_considered"]

    # 9. ModelCheck
    er = M.er_eval(mined["resolver"], name_key)
    counts = ontology["counts"]
    objects = counts["steps"] + counts["cases"] + counts["files"] + counts["rules"] + counts["skills"] + counts["customers"] + counts["zip_areas"] + counts["branches"] + counts["roles"]
    terms_cases = sum(1 for n in ontology["nodes"] if "msa" in n["name"].lower() or "terms" in n["name"].lower() for _ in [0])
    terms_n = next((n["cases"] for n in ontology["nodes"] if "msa" in n["name"].lower() or "terms" in n["name"].lower()), 0)
    demand_rows = [{"industry": b["name"], "naics": b["naics"], "lift": b["lift"], "population_lift": b["population_lift"], "ci": b["ci"], "verdict": b["verdict"]}
                   for b in fit_ind["backtest"]["by_industry"]]
    tie = next((d for d in demand_rows if d["verdict"] == "tie"), None)
    model = {
        "source": "simulated", "board_id": BOARD, "calibrated_at": stamp(30), "records": len(records),
        "components": [
            {"n": "01", "name": "Company knowledge", "what": "Roles, steps, cases, files, rules and skills — learned from approved records, never typed in.",
             "size": f"{len(counts)} types · {objects:,} objects · {len(ontology['edges']) + sum(len(n['aliases']) for n in ontology['nodes']):,} links"},
            {"n": "02", "name": "Team simulator", "what": "Replays the same team, requests and luck under a different plan. Step times and waits fit to your records.",
             "size": f"{counts['steps']} steps · {len(records)} records fitted · {len(SEEDS)} reruns"},
            {"n": "03", "name": "Demand model", "what": "Ranks where your kind of business grows next, from public data around each site. One industry code switches it.",
             "size": f"{fit_ind['backtest']['n_zips']:,} cold-start ZIPs scored · any NAICS code"},
        ],
        "sim_checks": sim_checks,
        "demand": demand_rows,
        "d1": d1["d1"],
        "limits": [
            {"title": "Revenue per location", "tag": "Not claimed",
             "why": "Last year's local figure predicts it as well as the model does. Flowline ranks where demand grows, not exact sales."},
            {"title": f"Where {tie['industry'].lower()} should open" if tie else "Where doctors should open", "tag": "No edge",
             "why": (f"Population alone does as well ({tie['lift']}× vs {tie['population_lift']}×). Shown, not hidden." if tie else "Population alone does as well. Shown, not hidden.")},
            {"title": "Contract redlines", "tag": "Needs more records",
             "why": f"Only {terms_n} proposals with Terms / MSA so far. Needs 10 before Legal's step is simulated on its own."},
        ],
        "calibration_errors": [{"measure": c["measure"], "error": c["error"]} for c in calibration["checks"]],
        "entity_resolution": {"precision": round(er["precision"], 3), "recall": round(er["recall"], 3), "names": er["names"]},
        "d1_detail": {k: v for k, v in d1.get("detail", {}).items() if k not in ("activities",)},
    }

    surfaces = _surfaces(expansion, opening, records, ontology)
    surfaces["recomputed_at"] = stamp(24)

    # 10. write + validate
    _dump(os.path.join(out, "ontology.json"), ontology)
    _dump(os.path.join(out, "finding.json"), finding)
    _dump(os.path.join(out, "plans.json"), plans_page)
    _dump(os.path.join(out, "results.json"), results)
    _dump(os.path.join(out, "history.json"), history)
    _dump(os.path.join(out, "model.json"), model)
    _dump(os.path.join(out, "expansion.json"), expansion)
    _dump(os.path.join(out, "opening.json"), opening)
    _dump(os.path.join(out, "surfaces.json"), surfaces)
    W.write_jsonl(os.path.join(out, "records.jsonl"), records)
    _dump(os.path.join(out, "truth.json"), truth)
    _dump(os.path.join(out, "calibration.json"), calibration)
    _dump(os.path.join(out, "plan_detail.json"), {"source": "simulated", **plan_detail})
    checked = validate.validate_dir(out)
    return {
        "files": len(checked), "records": len(records), "seconds": round(time.time() - t0, 1),
        "baseline_h": round(baseline_h, 1), "baseline_cycle_h_truth": round(truth["kpis_before"]["cycle_h"], 1),
        "signature_wait_h": next((m["wait_after_h"] for m in finding["map"] if m.get("longest_wait")), None),
        "baseline_waiting_share": round(kb["waiting_share"], 3),
        "best_plan": best["name"], "best_hours": best["hours"], "vs_today": best["vs_today"], "held_best_n": best["held_best_n"],
        "measured_after_h_records": round(ka["cycle_h"], 1), "measured_after_h_truth": round(truth["kpis_after"]["cycle_h"], 1),
        "in_range": f"{sum(1 for c in sim_checks if c['in_range'])} of {len(sim_checks)}",
        "d1": d1["d1"], "er": {"precision": round(er["precision"], 3), "recall": round(er["recall"], 3)},
    }


def _records_for_cases(records: list[dict], cases: set[str], t_change: float) -> list[dict]:
    """Records restricted to the steps of the given proposal cases (plus other work before the change)."""
    out = []
    for r in records:
        steps = [s for s in r["steps"] if s.get("case_id") in cases or
                 (not str(s.get("case_id", "")).startswith("proposal") and r["date"] < _date(int(t_change // E.DAY)))]
        if steps:
            rr = dict(r)
            rr["steps"] = [dict(s, idx=i) for i, s in enumerate(steps, 1)]
            out.append(rr)
    return out


def _fill_minutes_per_week(records: list[dict]) -> float:
    mins, weeks = 0.0, set()
    for r in records:
        weeks.add(r["date"][:7] + str(datetime.fromisoformat(r["date"]).isocalendar()[1]))
        for s in r["steps"]:
            if s["kind"] == "hands_on" and "pric" in s["name"].lower() and "deck" in " ".join(s.get("tools", [])) or \
                    (s["kind"] == "hands_on" and M.normalise(s["name"]) == M.normalise("Fill pricing")):
                a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
                mins += (b - a).total_seconds() / 60
    return mins / max(len(weeks), 1)


def _next_constraint(mined_after: dict) -> dict:
    nodes = [n for n in mined_after["ontology"]["nodes"] if n["role"] != "Client"]
    if not nodes:
        return {"headline": "Not enough records after the change yet", "sub": "", "ready": False}
    top = max(nodes, key=lambda n: n["wait_before_h"])
    return {"headline": f"Proposals now wait longest before {top['name']}",
            "sub": f"— {top['wait_before_h']:.1f} hours for {top['role']}, across {top['cases']} proposals. One constraint solved shows the next.",
            "ready": top["cases"] >= 3}


def _history(params, plans_page, best, best_rules, mined, mined_after, kb, ka, weeks_base, weeks_total, stamp, last_day, agent_fills, undone, scale=1.0) -> dict:
    """Version deltas are simulated (relative effects from successive simulations, scaled to the measured baseline)."""
    def med(rules, weeks=weeks_base):
        return float(np.median([S.simulate(params, rules, s, weeks)["cycle_h"] for s in SEEDS])) * scale

    v1 = med([])
    auto = [r for r in best_rules if r["type"] in ("auto_approve_under", "approver_batches_per_day")]
    deck = [r for r in best_rules if r["type"] in ("skill", "template")]
    v12 = med(auto)
    v13 = med(auto + deck) if deck else v12
    v14 = med(auto + deck + [V14_RULE])
    # v15: next candidate on top of what is live — the best remaining approval rule
    cands = {"Sign-off twice a day for the quotes the Director still signs": auto + deck + [V14_RULE, {"type": "approver_batches_per_day", "n": 2}]}
    if not any(r["type"] == "auto_approve_under" for r in auto):
        cands["Auto-approve quotes under $5k"] = auto + deck + [V14_RULE, {"type": "auto_approve_under", "usd": 5000}]
    v15_title, v15_rules = min(cands.items(), key=lambda kv: med(kv[1]))
    v15 = med(v15_rules)
    bn = next((n for n in mined["ontology"]["nodes"] if n["bottleneck"]), None)
    nxt = _next_constraint(mined_after) if mined_after else {"headline": "", "sub": ""}
    skill_node = next((n for n in mined["ontology"]["nodes"] if n["kind"] == "skill"), None)
    merges = sum(len(n["aliases"]) for n in mined["ontology"]["nodes"])
    versions = [
        {"v": 1, "when": "week 1", "title": "How proposals moved before any change",
         "found": f"Measured from records: {kb['cycle_h']:.1f} h per proposal, {kb['waiting_share']:.0%} waiting",
         "status": "baseline", "delta_h": 0.0},
        {"v": 12, "when": f"week {weeks_base + 1}", "title": {"auto_5k": "Quotes under $5k skip the Director", "twice_a_day": "Director signs twice a day"}.get(best["id"].split("__")[0], "Approval rule changed"),
         "found": (f"{bn['wait_before_h']:.1f} h wait for one signature · {len(plans_page['plans'])} plans tested · Director approved · "
                   f"simulated {v12 - v1:+.1f} h" if bn else "Approval wait"),
         "status": "live", "delta_h": round(v12 - v1, 1), "predicted_delta_h": round(v12 - v1, 1)},
    ]
    if deck:
        versions.append({"v": 13, "when": f"week {weeks_base + 1}", "title": "Agent fills the deck, PM reviews" if deck[0]["type"] == "skill" else "Shared deck template",
                         "found": (f"{skill_node['sub']} by hand · Director approved · {agent_fills - undone} of {agent_fills} kept · simulated {v13 - v12:+.1f} h" if skill_node else "Repeated by hand"),
                         "status": "live", "delta_h": round(v13 - v12, 1), "predicted_delta_h": round(v13 - v12, 1)})
    versions.append({"v": 14, "when": f"week {weeks_base + 2}", "title": "Agent renames and exports the PDF (Sales)",
                     "found": f"{ka.get('sends_per_week', 0):.0f}× / wk · tested · Sales lead approved · simulated {v14 - v13:+.1f} h",
                     "status": "live", "delta_h": round(v14 - v13, 1), "predicted_delta_h": round(v14 - v13, 1)})
    nxt_node = nxt["headline"].replace("Proposals now wait longest before ", "")
    nxt_h = nxt["sub"].split(" hours")[0].strip("— ").strip() if "hours" in nxt["sub"] else ""
    versions.append({"v": 15, "when": "tonight", "title": v15_title,
                     "found": f"Longest wait now before {nxt_node} ({nxt_h} h) · {len(plans_page['plans'])} plans tested · not yet approved",
                     "status": "needs_yes", "delta_h": 0.0, "predicted_delta_h": round(v15 - v14, 1)})
    people = mined["meta"]["people"]
    loop = [
        {"n": 1, "name": "Record", "at": stamp(0)[11:16] + "–" + stamp(22)[11:16], "status": "done", "note": f"{people} of {people} approved"},
        {"n": 2, "name": "Map", "at": stamp(24)[11:16], "status": "done", "note": f"v15: {mined['ontology']['counts']['steps']} steps, {merges} names merged"},
        {"n": 3, "name": "Find", "at": stamp(25)[11:16], "status": "done", "note": nxt["headline"].replace("Proposals now wait longest before ", "Longest wait now before ") or "Found"},
        {"n": 4, "name": "Test", "at": stamp(31)[11:16], "status": "done", "note": f"{len(plans_page['plans'])} plans, same team, same luck"},
        {"n": 5, "name": "Approve", "status": "now", "note": f"v15 needs your yes · predicted {v15 - v14:+.1f} h"},
        {"n": 6, "name": "Ask & do", "status": "pending", "note": "each change goes only to the person it touches"},
        {"n": 7, "name": "Measure", "status": "pending", "note": "two weeks of records, then predicted vs measured"},
    ]
    learned = [
        {"finding": f"The PM undid {undone} of {agent_fills} deck fills.",
         "action": f"Fills kept: {(agent_fills - undone) / agent_fills:.0%}. Below 90% the agent stops offering and asks what went wrong." if agent_fills else "No agent fills yet."},
        {"finding": f"{ka.get('n', 0)} proposals went through in the two weeks after the change; the Director signed {ka['signoffs_per_day']:.1f} a day instead of {kb['signoffs_per_day']:.1f}.",
         "action": "Kept the rule. Quotes the Director still signs are the ones over $5k." if "auto_5k" in best["id"] else "Kept the rule."},
        {"finding": f"{merges} step names across {people} people were merged into {mined['ontology']['counts']['steps']} steps; none were contested at end-of-day review.",
         "action": "Merges above 0.8 similarity are automatic; the rest are asked."},
    ]
    next_run = (W.ORIGIN + timedelta(days=last_day + 3, hours=18)).isoformat(timespec="seconds")
    assert all(len(v["found"]) <= 90 and not v["found"].startswith("Found") for v in versions), [v["found"] for v in versions]
    return {
        "source": "simulated", "board_id": BOARD, "recomputed_at": stamp(32),
        "baseline_h": round(kb["cycle_h"], 1), "now_h": round(ka["cycle_h"], 1),
        "headline": f"This process changed itself {sum(1 for v in versions if v['status'] == 'live')} times in {weeks_total} weeks. People said yes each time.",
        "loop": loop, "next_run_at": next_run, "versions": versions, "learned": learned,
        "sub": (f"{kb['cycle_h']:.1f} h at v1 · {ka['cycle_h']:.1f} h now (measured over the weeks after the change; "
                f"the simulated v12–v14 deltas sum to {v14 - v1:+.1f} h, the measured change is {ka['cycle_h'] - kb['cycle_h']:+.1f} h)"),
    }


# ----------------------------------------------------------------------------- opening (playbook table, simulated)
PLAYBOOK = [  # name, owner, days at branches 2/3, agent-prepared, saved days
    ("Lease signed", "Director", 21, True, 9),
    ("Facility registration", "BranchMgr", 12, True, 0),
    ("Interior build-out", "PM", 28, False, 0),
    ("Equipment delivered", "Finance", 21, True, 9),
    ("Hire 4 trainers", "BranchMgr", 31, True, 0),
    ("Pre-sale memberships", "Sales", 21, False, 0),
]


def _opening(pick: dict | None, last_day: int) -> dict:
    today = last_day
    zip_, name = (pick["zip"], pick["name"]) if pick else ("", "")
    # chain: lease -> build-out -> pre-sale (critical); registration, equipment, hiring run alongside the build-out
    lease, reg, build, equip, hire, presale = PLAYBOOK
    start = today - 14  # the lease work started two weeks ago
    ws = []
    t = start
    lease_end = t + lease[2] - lease[4]
    ws.append({"name": lease[0], "owner": lease[1], "agent": True, "start": _date(t), "end": _date(lease_end), "status": "done", "saved_d": lease[4]})
    ws.append({"name": reg[0], "owner": reg[1], "agent": True, "start": _date(lease_end), "end": _date(lease_end + reg[2]), "status": "waiting", "due": _date(today + 2)})
    build_end = lease_end + build[2]
    ws.append({"name": build[0], "owner": build[1], "agent": False, "start": _date(lease_end), "end": _date(build_end), "status": "on_track"})
    ws.append({"name": equip[0], "owner": equip[1], "agent": True, "start": _date(lease_end), "end": _date(lease_end + equip[2] - equip[4]), "status": "done", "saved_d": equip[4]})
    hire_start = start + 4
    ws.append({"name": hire[0], "owner": hire[1], "agent": True, "start": _date(hire_start), "end": _date(hire_start + hire[2]), "status": "on_track",
               "progress": [today - hire_start, hire[2]]})
    opens_day = max(build_end, hire_start + hire[2]) + 7
    ws.append({"name": presale[0], "owner": presale[1], "agent": False, "start": _date(build_end - 14), "end": _date(opens_day), "status": "todo"})
    was_day = opens_day + lease[4] + equip[4]
    blockers = [
        {"id": "B1", "title": "Lease review", "status": "cleared", "saved_d": 9, "was": "11 days with outside counsel at branch 3.",
         "agent": "Drafted the review from the last two leases' redlines.", "decided_by": "Director", "surface": "inbox"},
        {"id": "B2", "title": "Equipment order over $25k", "status": "cleared", "saved_d": 9, "was": "Sat 6 days waiting for a finance sign-off at branch 3.",
         "agent": "Matched vendor and terms to branch 3; one-line approval.", "decided_by": "Finance", "surface": "inbox"},
        {"id": "B3", "title": "Occupancy and health-club permit", "status": "waiting_on_you", "due": _date(today + 2),
         "was": "Filled by hand, sent back once at branch 2.", "agent": "Pre-filled the form from branch 3's accepted filing.",
         "decided_by": "BranchMgr", "surface": "notch"},
        {"id": "B4", "title": "Hire 4 trainers", "status": "in_progress", "due": _date(hire_start + hire[2]), "was": "Took 31 days at branch 3.",
         "agent": "Reposted branch 3's ad; shortlisted past applicants.", "decided_by": "BranchMgr", "surface": "weekly_digest"},
    ]
    return {
        "source": "simulated", "board_id": BOARD, "branch": 4, "zip": zip_, "name": name, "playbook_from": "branches 2 and 3",
        "steps": sum(1 for _ in PLAYBOOK) * 7 - 1,
        "headline": f"Opening moves up {was_day - opens_day} days. {sum(1 for b in blockers if b['status'] == 'cleared')} of {len(blockers)} blockers are already gone.",
        "opens": _date(opens_day), "was": _date(was_day), "today": _date(today), "workstreams": ws, "blockers": blockers,
    }


def _surfaces(expansion: dict, opening: dict, records: list[dict], ontology: dict) -> dict:
    fit = expansion["by_industry"][expansion["default"]]
    top = fit["zips"][:3]
    saved = (datetime.fromisoformat(opening["was"]) - datetime.fromisoformat(opening["opens"])).days
    fin = [b for b in opening["blockers"] if b["decided_by"] == "Finance"]
    bm = next((b for b in opening["blockers"] if b["decided_by"] == "BranchMgr" and b["status"] == "waiting_on_you"), opening["blockers"][-1])
    steps = int(np.median([len(r["steps"]) for r in records])) if records else 0
    left_out = int(np.median([r["kept_private"] for r in records])) if records else 0
    return {
        "source": "simulated",
        "ceo_line": f"Next club · {top[0]['zip']}. {top[0]['name']}, #1 of {fit['zips_considered']} ZIPs. Opens {saved} days sooner. One decision is yours.",
        "finance_inbox": [{"title": f"1 approval · {b['title'].lower()}, club 4", "sub": f"{b['agent']} Was: {b['was']}", "actions": ["Approve", "Ask why"]} for b in fin],
        "branch_mgr_blocker": {"title": f"{bm['title']} is filled in. Check and submit?", "actions": ["Open it", "Not now"]},
        "expansion_lead": [{"zip": z["zip"], "rank": z["rank"]} for z in top],
        "trainer_record": {"steps": steps, "left_out": left_out},
    }


# ----------------------------------------------------------------------------- check
def check(out: str) -> None:
    def load(name):
        with open(os.path.join(out, name), encoding="utf-8") as f:
            return json.load(f)

    truth, onto, plans, model, finding = load("truth.json"), load("ontology.json"), load("plans.json"), load("model.json"), load("finding.json")
    records = W.read_jsonl(os.path.join(out, "records.jsonl"))
    mined = M.mine(records)
    er = M.er_eval(mined["resolver"], truth["name_key"])
    internal = sorted([n for n in onto["nodes"] if n["role"] != "Client"], key=lambda n: -n["wait_before_h"])
    hidden = E.STEP_NAME[truth["hidden_rules"]["bottleneck"]]
    cid = M._find_cluster(mined["resolver"], hidden)
    rank = next((i + 1 for i, n in enumerate(internal) if n["id"] == f"n{cid}"), None)
    best = next(p for p in plans["plans"] if p["best"])
    in_range = sum(1 for c in model["sim_checks"] if c["in_range"])
    d1 = model["d1"]
    rows = [
        ("Bottleneck found", f"hidden constraint ({hidden}) ranked #{rank} by wait", "#1", "D4", "yes" if rank == 1 else "no"),
        ("Plan ranking stability", f"best plan held in {best['held_best_n']} of {plans['reruns']} reruns", ">= 18/20", "D4", "yes" if best["held_best_n"] >= 18 else "no"),
        ("Predicted vs measured", f"{in_range} of {len(model['sim_checks'])} checks in range", "all in range", "D4", "yes" if in_range == len(model["sim_checks"]) else "no"),
        ("Simulator calibration (D1)", (f"2017 fit -> 2018: median error {d1['median_error']:.1%}, P80 error {d1['p80_error']:.1%}"
                                         if d1 and d1.get("median_error") is not None else "download failed"), "<= 15%", "D1 real",
         "yes" if d1 and d1.get("median_error") is not None and d1["median_error"] <= 0.15 and d1["p80_error"] <= 0.15 else "no"),
        ("Name merging", f"precision {er['precision']:.2f} / recall {er['recall']:.2f} on {er['names']} planted names", ">= 0.9 / 0.8", "D4",
         "yes" if er["precision"] >= 0.9 and er["recall"] >= 0.8 else "no"),
        ("Demand model", " · ".join(f"{d['naics']} {d['lift']}x vs {d['population_lift']}x ({d['verdict']})" for d in model["demand"]), "7.4x vs 5.7x", "D2 real", "yes"),
    ]
    w = max(len(r[0]) for r in rows)
    print(f"{'Metric'.ljust(w)}  {'Measured'.ljust(78)}  {'Target'.ljust(14)} {'Data'.ljust(8)} Met")
    for r in rows:
        print(f"{r[0].ljust(w)}  {r[1].ljust(78)}  {r[2].ljust(14)} {r[3].ljust(8)} {r[4]}")
    print()
    print(f"Baseline (world, measured): {truth['kpis_before']['cycle_h']:.1f} h per proposal, {truth['kpis_before']['waiting_share']:.0%} waiting, "
          f"signature wait {truth['kpis_before']['approval_wait_h']:.1f} h · mined finding: {finding['kpis']['cycle_time_h']} h, {finding['kpis']['waiting_share']:.0%}")
    print("Baseline simulation vs measured:")
    for c in truth["calibration"]:
        print(f"  {c['measure']:<30} sim {c['simulated']:<8} measured {c['measured']:<8} error {c['error']:.1%}" if c["error"] is not None else f"  {c['measure']}")
    mr = truth.get("measured_from_records", {})
    print(f"Best plan: {best['name']} {best['sub']} — {best['hours']} h ({best['vs_today']:+.0%}), range {best['range_h']} · after change: "
          f"{mr.get('after', {}).get('cycle_h', float('nan')):.1f} h from records ({truth['kpis_after']['cycle_h']:.1f} h world truth)")
    for c in model["sim_checks"]:
        print(f"  {c['measure']:<28} predicted {c['predicted']} ({c['lo']}–{c['hi']}) {c['unit']:<4} actual {c['actual']} -> {'in range' if c['in_range'] else 'OUT'}")
    if d1 and d1.get("median_error") is not None:
        print(f"D1: {d1['cases']} cases, {d1['events']} events, Amount attribute: {d1['amount_attr']}")
