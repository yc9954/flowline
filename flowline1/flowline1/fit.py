"""`fit`: the ten board files from a company's approved records alone (no world.py).

    python -m flowline1 fit --records <path.json|.ndjson> --out <dir> [--industry <naics>] [--process <prefix>]
                            [--seeds 20] [--plans auto|<plans.json>] [--since YYYY-MM-DD] [--approvals <json>]
                            [--start-step NAME] [--end-step NAME] [--board-id ID] [--city "Austin, TX"] [--zips 786,787]

What each file is derived from (every number carries `source`):
  ontology.json  measured   mined from all records (miner.mine with learned start/end steps, map rows, external parties)
  finding.json   measured   mined from the baseline cases (cases that started before --since / the first approval)
  plans.json     simulated  generic.fit on the baseline mining -> candidate plans generated from the bottleneck and the
                            repeated work -> common-random-number replay over --seeds; hours scaled to the measured baseline
  results.json   measured before (baseline cases) · simulated predicted (best plan) · measured after (cases started
                            after --since) when such cases exist, else state "awaiting_measurement"
  history.json   measured baseline + approvals (--approvals) + measured deltas where the records allow, else predicted
  model.json     the calibration checks that need no hidden truth: baseline replay vs measured, completed cases per week,
                            sign-offs per day, plan stability across seeds, miner stability on resamples; the
                            synthetic-world checks (planted bottleneck, planted synonyms) and D1 are marked n/a
  expansion.json measured   US Census backtest for --industry when it is one of the backtested NAICS codes, else
                            source "not_available" with the reason
  opening.json   measured   learned from opening/launch cases when the records contain any, else state "no_data_yet"
  surfaces.json  measured   from the people, roles and the bottleneck present in the records
Sparse data (< 20 records, < 2 roles, < 3 completed cases): finding/ontology with what there is, plans/results/history
with state "not_enough_data" and the counts needed. Never crashes on sparse input.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta

import numpy as np

from . import demand, engine as E, generic as G, miner as M, validate

MIN_RECORDS = 20
MIN_ROLES = 2
MIN_COMPLETED = 3
OPENING_RE = re.compile(r"open|launch|branch|new site|new store|new clinic", re.I)
EXTRA_FILES = ("calibration.json", "plan_detail.json", "fit_report.json")


# ----------------------------------------------------------------------------- input
def load_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text_s = text.strip()
    if not text_s:
        return []
    if text_s.startswith("["):
        rows = json.loads(text_s)
    elif text_s.startswith("{") and "\n{" not in text_s:
        obj = json.loads(text_s)
        rows = obj.get("records") or obj.get("items") or []
    else:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("steps"), list) and r.get("date") and r.get("person_id")]


def case_prefix(case_id: str) -> str:
    if not case_id:
        return ""
    if "#" in case_id:
        return case_id.split("#", 1)[0].strip()
    return re.sub(r"[\s\-_:]*\d+\s*$", "", case_id).strip() or case_id.strip()


def infer_prefix(records: list[dict]) -> str:
    """The process = the case-id prefix with the most recorded steps (a renewal is one step; a proposal is twenty)."""
    steps: Counter = Counter()
    cases: dict[str, set] = {}
    for r in records:
        for s in r["steps"]:
            cid = s.get("case_id")
            if cid:
                p = case_prefix(cid)
                steps[p] += 1
                cases.setdefault(p, set()).add(cid)
    if not steps:
        return ""
    return max(steps, key=lambda p: (steps[p], len(cases[p]), p))


def calendar_from(records: list[dict]) -> E.Calendar:
    """Working hours from the records: the 5th percentile of hands-on starts to the 95th percentile of ends, whole hours."""
    starts, ends = [], []
    for r in records:
        for s in r["steps"]:
            if s.get("kind") != "hands_on":
                continue
            try:
                a, b = M._parse(s["start"]), M._parse(s["end"])
            except (ValueError, KeyError, TypeError):
                continue
            starts.append(a.hour + a.minute / 60)
            ends.append(b.hour + b.minute / 60)
    if len(starts) < 10:
        return E.DEFAULT_CALENDAR
    lo = int(np.floor(np.percentile(starts, 5)))
    hi = int(np.ceil(np.percentile(ends, 95)))
    lo = min(max(lo, 5), 12)
    hi = min(max(hi, lo + 4), 23)
    return E.Calendar(lo * 60, hi * 60)


def _parse_when(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.replace(tzinfo=None)


def _records_for_cases(records: list[dict], cases: set[str], prefix: str, since: str | None) -> list[dict]:
    """Records restricted to the steps of the given cases (plus other work before the change)."""
    out = []
    for r in records:
        steps = [s for s in r["steps"] if s.get("case_id") in cases or
                 (not case_prefix(s.get("case_id") or "").lower() == prefix.lower() and (since is None or r["date"] < since))]
        if steps:
            rr = dict(r)
            rr["steps"] = [dict(s, idx=i) for i, s in enumerate(steps, 1)]
            out.append(rr)
    return out


def _dump(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _stats(values) -> dict:
    v = np.array(values, float)
    return {"mid": float(np.median(v)), "lo": float(np.percentile(v, 10)), "hi": float(np.percentile(v, 90))}


def _next_weekday_18(now: datetime) -> str:
    d = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if d <= now:
        d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat(timespec="seconds")


def _cut(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    head = text[: n - 1]
    return (head[: head.rfind(" ")] if " " in head[n // 2:] else head).rstrip(" ·(-+") + "…"


def _plural(unit: str) -> str:
    return unit if unit.endswith("s") else unit + "s"


# ----------------------------------------------------------------------------- stubs
def _stub_ontology(board, now, n_records, unit, roles):
    return {"source": "measured", "board_id": board, "version": 1, "recomputed_at": now, "records_used": n_records,
            "roles": [{"role": r, "steps": 0} for r in roles], "nodes": [], "edges": [],
            "counts": {"roles": len(roles), "steps": 0, "cases": 0, "files": 0, "rules": 0, "skills": 0, "customers": 0, "zip_areas": 0, "branches": 0},
            "headline": f"Nothing to map yet: {n_records} approved record{'s' if n_records != 1 else ''}.", "state": "no_data_yet"}


def _stub_finding(board, now, process, n_records, people, weeks, unit):
    return {"source": "measured", "recomputed_at": now, "board_id": board, "process": process, "records": n_records, "people": people,
            "weeks": weeks, "headline": "Not enough records to find where work waits.", "sub": f"{n_records} records from {people} people so far.",
            "kpis": {"cycle_time_h": 0.0, "waiting_share": 0.0, "small_quotes_share": 0.0, "small_quotes_unchanged": 0.0, "repeated_by_hand_h_per_wk": 0.0},
            "map": [], "to_scale": {"hands_on_h": 0.0, "waiting_h": 0.0}, "sent_back": [], "repeated": [], "state": "no_data_yet"}


def _needed(n_records, n_roles, n_completed, unit):
    return {"state": "not_enough_data",
            "needed": {"records": MIN_RECORDS, "roles": MIN_ROLES, f"completed_{_plural(unit)}": MIN_COMPLETED},
            "have": {"records": n_records, "roles": n_roles, f"completed_{_plural(unit)}": n_completed}}


def _stub_plans(board, now, weeks, today_h, unit, need):
    return {"source": "simulated", "board_id": board, "reruns": 0, "weeks": weeks,
            "headline": f"Plans need {need['needed']['records']} records from {need['needed']['roles']} roles; "
                        f"{need['have']['records']} from {need['have']['roles']} so far.",
            "today_h": today_h, "plans": [], "recomputed_at": now,
            "note": "No plan is simulated until the records cover enough of the process to fit the team simulator.", **need}


def _stub_results(board, now, n_records, people, weeks, unit, today_h, series, need):
    return {"source": "measured", "recomputed_at": now, "board_id": board,
            "headline": "Nothing to measure yet.", "sub": f"{need['have']['records']} records, {need['have']['roles']} roles, "
            f"{need['have'][f'completed_{_plural(unit)}']} completed {_plural(unit)}.",
            "records": n_records, "people": people, "weeks": weeks, "change": "", "predicted": {"mid": 0.0, "lo": 0.0, "hi": 0.0},
            "measured": 0.0, "before": today_h, "series": series, "kpis": [], "who": [],
            "next_constraint": {"headline": "Not enough records yet", "sub": "", "ready": False}, **need}


def _stub_history(board, now, today_h, n_records, people, weeks, unit, need, next_run):
    return {"source": "measured", "board_id": board, "recomputed_at": now, "baseline_h": today_h, "now_h": today_h,
            "headline": "The loop has started: people are recording.",
            "loop": [{"n": 1, "name": "Record", "status": "done" if n_records else "now", "note": f"{n_records} records from {people} people"},
                     {"n": 2, "name": "Map", "status": "done" if n_records else "pending", "note": "mapped from what there is"},
                     {"n": 3, "name": "Find", "status": "pending", "note": f"needs {need['needed']['records']} records"},
                     {"n": 4, "name": "Test", "status": "pending", "note": "plans are simulated once the process is covered"},
                     {"n": 5, "name": "Approve", "status": "pending", "note": "nothing to approve yet"},
                     {"n": 6, "name": "Ask & do", "status": "pending", "note": "each change goes only to the person it touches"},
                     {"n": 7, "name": "Measure", "status": "pending", "note": "predicted vs measured after a change"}],
            "next_run_at": next_run, "versions": [{"v": 1, "when": "now", "title": "Recording", "found": f"{n_records} approved records so far",
                                                   "status": "baseline", "delta_h": 0.0}],
            "learned": [], **need}


def _stub_expansion(board, now, industry, n_records, reason):
    naics = industry or "none"
    one = {"board_id": board, "city": "", "industries": demand.INDUSTRIES, "industry": naics,
           "headline": f"No demand model for NAICS {naics} yet." if industry else "No industry code given.",
           "sub": reason, "zips_considered": 0, "branches": 0, "records": n_records, "rank_of": 0,
           "opening": {"date": "", "was": "", "blockers_cleared": 0}, "zips": [],
           "backtest": {"frozen_at": 2020, "scored_on": 2023, "n_zips": 0, "lift": 0.0, "ci": [0.0, 0.0], "by_industry": [],
                        "pooled": {"lift": 0.0, "population_lift": 0.0}},
           "source": "not_available", "reason": reason}
    return {"source": "not_available", "recomputed_at": now, "board_id": board, "city": "", "industries": demand.INDUSTRIES,
            "default": naics, "records": n_records, "branches": 0, "reason": reason, "by_industry": {naics: one}}


def _stub_opening(board, now, today):
    return {"source": "measured", "recomputed_at": now, "board_id": board, "branch": 0, "zip": "", "name": "", "playbook_from": "",
            "steps": 0, "headline": "No opening in progress.", "opens": "", "was": "", "today": today,
            "workstreams": [], "blockers": [], "state": "no_data_yet",
            "sub": "Record a branch opening (case ids like 'opening #1') and its playbook is learned from those records."}


# ----------------------------------------------------------------------------- the pipeline
def fit(records: list[dict], out: str, board_id: str | None = None, industry: str | None = None, process: str | None = None,
        seeds: int = 20, plans: str = "auto", since: str | None = None, approvals: list[dict] | None = None,
        start_step: str | None = None, end_step: str | None = None, city: str = "Austin, TX", zips: str = "786,787",
        raw_dir: str = "", reference_dir: str = "", now: datetime | None = None, bootstrap: int = 20) -> dict:
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    now_dt = now or datetime.now().astimezone()
    now_s = now_dt.isoformat(timespec="seconds")
    today = now_dt.date().isoformat()
    next_run = _next_weekday_18(now_dt.replace(tzinfo=None))
    records = sorted((r for r in records if r.get("steps") is not None), key=lambda r: (r["date"], r.get("approved_at", "")))
    n_records = len(records)
    people = len({r["person_id"] for r in records})
    roles = sorted({r["role"] for r in records})
    board = board_id or (Counter(r.get("board_id") for r in records).most_common(1)[0][0] if records else None) or "board"
    approvals = sorted([a for a in (approvals or []) if a.get("approved_at")], key=lambda a: a["approved_at"])
    if since is None and approvals:
        since = approvals[0]["approved_at"][:10]
    weeks_all = len({M._parse(r["date"] + "T00:00:00").isocalendar()[:2] for r in records}) if records else 0

    prefix = (process or infer_prefix(records)).strip()
    unit = re.sub(r"\s+", " ", prefix).strip().lower() or "case"
    process_name = _plural(unit)
    summary = {"board_id": board, "records": n_records, "people": people, "roles": roles, "process": prefix or None}
    cal = calendar_from(records)
    ext = M.external_parties(records) if records else set()
    opts = M.MineOptions(board=board, process_prefix=prefix, process_name=process_name, start_step=start_step, end_step=end_step,
                         map_groups=None, external_roles=ext, calendar=cal, version=1 + len(approvals), branches=0,
                         source="measured", unit=unit)

    mined_all = None
    if records and prefix:
        try:
            mined_all = M.mine(records, opts)
        except Exception as exc:  # sparse or odd input: fall through to the stubs, never crash
            summary["mine_error"] = f"{type(exc).__name__}: {exc}"
    if mined_all is not None:  # the "small amount" share in the finding uses the same threshold the plans will use
        thr = G.pick_threshold([a for a, _ in mined_all["stats"]["approvals"]])
        if thr:
            opts = M.MineOptions(**{**opts.__dict__, "small_threshold_usd": thr})
            try:
                mined_all = M.mine(records, opts)
            except Exception as exc:
                summary["mine_error"] = f"{type(exc).__name__}: {exc}"
    rows_all = mined_all["stats"]["case_rows"] if mined_all else []
    origin = mined_all["stats"]["origin"] if mined_all else None
    t_since = E.dt_to_minutes(_parse_when(since), origin) if (since and origin) else None
    before_rows = [r for r in rows_all if t_since is None or r["brief_start"] < t_since]
    after_rows = [r for r in rows_all if t_since is not None and r["brief_start"] >= t_since]
    n_completed = len(before_rows)
    need = _needed(n_records, len(roles), n_completed, unit)
    sparse = n_records < MIN_RECORDS or len(roles) < MIN_ROLES or n_completed < MIN_COMPLETED or mined_all is None

    # baseline mining: the cases that started before the change (their later steps included), other work before it
    mined = None
    if mined_all is not None:
        base_cases = {case for case, seq in mined_all["stats"]["by_case"].items() if t_since is None or seq[0].start < t_since}
        base_records = _records_for_cases(records, base_cases, prefix, since) if t_since is not None else records
        try:
            mined = M.mine(base_records, opts) if base_records else None
        except Exception as exc:
            summary["mine_error"] = f"{type(exc).__name__}: {exc}"
            mined = None
    if mined is None:
        mined = mined_all
    finding = dict(mined["finding"]) if mined else _stub_finding(board, now_s, process_name, n_records, people, weeks_all, unit)
    finding["recomputed_at"] = now_s
    finding["source"] = "measured"
    ontology = dict(mined_all["ontology"]) if mined_all else _stub_ontology(board, now_s, n_records, unit, roles)
    ontology["recomputed_at"] = now_s
    ontology["source"] = "measured"
    baseline_h = float(finding["kpis"]["cycle_time_h"])
    series = [{"week": int(r["brief_start"] // (7 * E.DAY)) + 1, "value": round(r["cycle_h"], 1),
               "after": bool(t_since is not None and r["brief_start"] >= t_since)}
              for r in sorted(rows_all, key=lambda r: r["brief_start"])]
    summary.update({"baseline_h": round(baseline_h, 1), "completed_before": n_completed, "completed_after": len(after_rows),
                    "bottleneck": mined["stats"]["bottleneck"] if mined else None, "since": since, "calendar": [cal.start / 60, cal.end / 60],
                    "external_parties": sorted(x for x in ext if x), "start_step": mined["stats"]["cluster_display"].get(mined["stats"]["start_cluster"]) if mined else None,
                    "end_step": mined["stats"]["cluster_display"].get(mined["stats"]["end_cluster"]) if mined else None})

    expansion, exp_fit = _expansion(board, now_s, industry, n_records, raw_dir, reference_dir, out, city, zips, today)
    opening = _opening(records, prefix, board, now_s, today, opts)
    if sparse:
        if n_completed < 1 and "state" not in finding:
            finding["state"] = "not_enough_data"
        plans_page = _stub_plans(board, now_s, weeks_all, round(baseline_h, 1), unit, need)
        results = _stub_results(board, now_s, n_records, people, weeks_all, unit, round(baseline_h, 1), series, need)
        history = _stub_history(board, now_s, round(baseline_h, 1), n_records, people, weeks_all, unit, need, next_run)
        model_json = _model_sparse(board, now_s, n_records, ontology, need, exp_fit, unit)
        calibration = {"source": "measured", "state": "not_enough_data", **{k: need[k] for k in ("needed", "have")}}
        plan_detail = {"source": "simulated", "state": "not_enough_data"}
        fit_report = {"options": _opts_dict(opts), "state": "not_enough_data", **{k: need[k] for k in ("needed", "have")}}
        summary["state"] = "not_enough_data"
    else:
        seeds_l = list(range(seeds))
        model = G.fit(mined, cal, unit)
        catalogue = G.plan_catalogue(model) if plans in (None, "", "auto") else _load_plans(plans, model)
        weeks = model.weeks
        plans_page, plan_detail = G.plans_page(model, board, catalogue, seeds_l, weeks, now_s, measured_today_h=baseline_h)
        best = next(p for p in plans_page["plans"] if p["best"])
        today_plan = next(p for p in plans_page["plans"] if p["today"])
        # the plan to measure against: the last approved one when it can be matched, else the best
        approved_plan = _match_plan(plans_page, approvals[-1]) if approvals else None
        live = approved_plan or best
        # calibration: the baseline replay vs the measured baseline (no scaling), plan stability, miner stability
        base_sims = [r for r in plan_detail["per_plan"][today_plan["id"]] if r.get("n")]
        measured = _measured_kpis(mined, before_rows, weeks)
        calibration = _calibration(base_sims, measured, model, best, seeds_l, weeks, plan_detail, unit)
        if len(plans_page["plans"]) > 1:
            calibration["plan_stability"]["margin_to_next_h"] = round(plans_page["plans"][1]["hours"] - best["hours"], 1)
        pinned = _pin(opts, mined)
        calibration["miner_stability"] = _miner_stability(mined, records, prefix, since, pinned, bootstrap, unit)
        calibration["fit"] = model.report
        mined_after = None
        after_kpis = None
        if after_rows:
            after_cases = {r["case"] for r in after_rows}
            try:
                mined_after = M.mine(_records_for_cases(records, after_cases, prefix, None), pinned)
                after_kpis = _measured_kpis(mined_after, mined_after["stats"]["case_rows"], max(mined_after["meta"]["weeks"], 1))
            except Exception as exc:
                summary["after_mine_error"] = f"{type(exc).__name__}: {exc}"
        results = _results(board, now_s, mined, mined_after, before_rows, after_rows, after_kpis, measured, plans_page, live, series,
                           n_records, people, weeks_all, unit, approvals, model)
        history = _history(board, now_s, mined, mined_after, baseline_h, after_kpis, plans_page, best, approvals, since, n_records,
                           people, weeks_all, unit, next_run, model)
        model_json = _model(board, now_s, n_records, ontology, plans_page, live, calibration, exp_fit, unit, model, after_kpis, seeds_l)
        fit_report = {"options": _opts_dict(opts), "model": model.report, "since": since, "approvals": approvals,
                      "seeds": seeds, "weeks": weeks, "plans": [p["id"] for p in catalogue]}
        summary.update({"best_plan": f"{best['name']} {best['sub']}", "best_hours": best["hours"], "vs_today": best["vs_today"],
                        "held_best_n": best["held_best_n"], "sim_today_h": round(plan_detail["sim_today_h"], 1),
                        "baseline_error": calibration["checks"][0]["error"] if calibration["checks"] else None,
                        "measured_after_h": results["measured"] if after_rows else None,
                        "in_range": f"{sum(1 for c in model_json['sim_checks'] if c['in_range'])} of {len(model_json['sim_checks'])}",
                        "state": "fitted"})
    surfaces = _surfaces(board, now_s, records, finding, expansion, ontology, mined, unit)

    _dump(os.path.join(out, "ontology.json"), ontology)
    _dump(os.path.join(out, "finding.json"), finding)
    _dump(os.path.join(out, "plans.json"), plans_page)
    _dump(os.path.join(out, "results.json"), results)
    _dump(os.path.join(out, "history.json"), history)
    _dump(os.path.join(out, "model.json"), model_json)
    _dump(os.path.join(out, "expansion.json"), expansion)
    _dump(os.path.join(out, "opening.json"), opening)
    _dump(os.path.join(out, "surfaces.json"), surfaces)
    _write_jsonl(os.path.join(out, "records.jsonl"), records)
    _dump(os.path.join(out, "calibration.json"), calibration)
    _dump(os.path.join(out, "plan_detail.json"), plan_detail)
    _dump(os.path.join(out, "fit_report.json"), fit_report)
    if records:
        checked = validate.validate_dir(out)
    else:
        checked = [n for n in validate.FILES]
        for name, spec in validate.FILES.items():
            with open(os.path.join(out, name), encoding="utf-8") as f:
                validate._req(json.load(f), spec, name)
    summary["files"] = len(checked)
    summary["seconds"] = round(time.time() - t0, 1)
    return summary


def _rules_sig(rules: list[dict]) -> frozenset:
    out = []
    for r in rules or []:
        t = r.get("type")
        out.append((t, str(r.get("usd") or r.get("n") or r.get("skill_id") or r.get("name") or "")))
    return frozenset(out)


def _match_plan(plans_page: dict, approval: dict) -> dict | None:
    """The approved plan on this plans page: by id, else by its rules (the API stores the approved Plan object)."""
    pid = approval.get("plan_id")
    for p in plans_page["plans"]:
        if p["id"] == pid:
            return p
    rules = (approval.get("plan") or {}).get("rules") or approval.get("rules")
    if rules:
        sig = _rules_sig(rules)
        for p in plans_page["plans"]:
            if _rules_sig(p["rules"]) == sig:
                return p
        # same rule types and amounts, skill ids aside (a different board names the skill differently)
        loose = frozenset((t, v) for t, v in sig if t != "skill") | frozenset(("skill", "") for t, v in sig if t == "skill")
        for p in plans_page["plans"]:
            ps = _rules_sig(p["rules"])
            if frozenset((t, v) for t, v in ps if t != "skill") | frozenset(("skill", "") for t, v in ps if t == "skill") == loose:
                return p
    # last resort: the approved plan's name, with amounts normalised ("$5k" == "$5,000")
    name = _norm_plan_text(approval.get("plan_name") or "")
    if name:
        hits = [p for p in plans_page["plans"] if _norm_plan_text(p["name"]) == name or _norm_plan_text(f"{p['name']} {p['sub']}") == name]
        if hits:
            return min(hits, key=lambda p: p["rank"])
    return None


def _norm_plan_text(text: str) -> str:
    def amt(m):
        v = float(m.group(1).replace(",", ""))
        return str(int(v * 1000)) if m.group(2) else str(int(v))

    t = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)\s?(k)?", amt, text.lower())
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _pin(opts: M.MineOptions, mined: dict) -> M.MineOptions:
    """The same cycle definition (start/end steps) as the baseline mining, for subsets of the records."""
    disp = mined["stats"]["cluster_display"]
    start = disp.get(mined["stats"]["start_cluster"]) if opts.start_step is None else opts.start_step
    end = disp.get(mined["stats"]["end_cluster"]) if opts.end_step is None else opts.end_step
    return M.MineOptions(**{**opts.__dict__, "start_step": start, "end_step": end})


def _opts_dict(o: M.MineOptions) -> dict:
    return {"board": o.board, "process_prefix": o.process_prefix, "process_name": o.process_name, "start_step": o.start_step,
            "end_step": o.end_step, "external_roles": sorted(x for x in (o.external_roles or set()) if x),
            "calendar_hours": [o.calendar.start / 60, o.calendar.end / 60], "unit": o.unit}


def _load_plans(path: str, model: G.Model) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    plans = [{"id": "as_is__by_hand", "name": "Today", "sub": "+ as recorded", "rules": [], "today": True, "who": [], "_a": "as_is", "_d": "by_hand"}]
    for i, r in enumerate(rows if isinstance(rows, list) else rows.get("plans", [])):
        if not r.get("rules"):
            continue
        for rule in r["rules"]:
            if rule.get("type") == "skill" and rule.get("skill_id") not in model.skill_ids and model.repeated_cid is not None:
                model.skill_ids[rule["skill_id"]] = model.repeated_cid
        plans.append({"id": r.get("id") or f"custom_{i + 1}", "name": r.get("name") or f"Plan {i + 1}", "sub": r.get("sub") or "",
                      "rules": r["rules"], "today": False, "who": r.get("who") or [], "_a": "custom", "_d": "custom"})
    return plans


# ----------------------------------------------------------------------------- measured + calibration
def _measured_kpis(mined: dict, rows: list[dict], weeks: int) -> dict:
    st = mined["stats"]
    out = {"n": len(rows), "weeks": weeks, "completed_per_day": len(rows) / max(weeks * 5, 1)}
    if rows:
        cyc = np.array([r["cycle_h"] for r in rows])
        wait = np.array([r["waiting_h"] for r in rows])
        out.update({"cycle_h": float(np.median(cyc)), "work_h": float(np.median([r["work_h"] for r in rows])),
                    "waiting_h": float(np.median(wait)), "waiting_share": float(wait.sum() / max(cyc.sum(), 1e-9)),
                    "approval_wait_h": float(np.median([r["approval_wait_h"] for r in rows]))})
    workdays = max(weeks * 5, 1)
    out["signoffs_per_day"] = len(st["approval_starts"]) / workdays
    return out


def _calibration(base_sims, measured, model: G.Model, best, seeds, weeks, plan_detail, unit) -> dict:
    checks = []

    def add(label, key, unit_, mult=1.0, nd=1):
        if key not in measured or not base_sims or key not in base_sims[0]:
            return
        sim = float(np.median([b[key] for b in base_sims])) * mult
        act = float(measured[key]) * mult
        lo = float(np.percentile([b[key] for b in base_sims], 10)) * mult
        hi = float(np.percentile([b[key] for b in base_sims], 90)) * mult
        lo_r, hi_r, act_r = round(lo, nd), round(hi, nd), round(act, nd)  # the range the board shows is the one judged
        checks.append({"measure": label, "simulated": round(sim, nd), "lo": lo_r, "hi": hi_r, "measured": act_r,
                       "unit": unit_, "error": round(abs(sim - act) / act, 3) if act else None, "in_range": bool(lo_r - 1e-9 <= act_r <= hi_r + 1e-9)})

    U = unit[:1].upper() + unit[1:]
    add(f"Hours per {unit} (baseline replay)", "cycle_h", "h")
    add("Share of time waiting (baseline replay)", "waiting_share", "%", 100, 0)
    add(f"{U}s completed / day", "completed_per_day", "/day", 1, 2)
    if model.approval_cid is not None and model.batch:
        add(f"{model.approval_role} sign-offs / day", "signoffs_per_day", "/day", 1, 2)
    return {"source": "simulated", "weeks": weeks, "reruns": len(seeds), "checks": checks,
            "scale_to_measured_baseline": round(plan_detail["scale"], 4),
            "plan_stability": {"best_plan": f"{best['name']} {best['sub']}", "held_best_n": best["held_best_n"], "reruns": len(seeds),
                               "margin_to_next_h": None}}


def _miner_stability(mined, records, prefix, since, opts, b, unit) -> dict:
    """Mine `b` random 80 % subsets of the baseline completed cases: does the same bottleneck come out, how much does the median move?"""
    rows = mined["stats"]["case_rows"]
    cases = [r["case"] for r in rows]
    if len(cases) < 4 or b <= 0:
        return {"resamples": 0, "same_bottleneck": None, "cycle_h_p10_p90": None, "note": "needs at least 4 completed cases"}
    rng = np.random.default_rng(42)
    same = 0
    meds = []
    ok = 0
    full_bn = mined["stats"]["bottleneck"]
    for _ in range(b):
        k = max(3, int(round(0.8 * len(cases))))
        pick = set(rng.choice(cases, size=k, replace=False).tolist())
        sub = _records_for_cases(records, pick, prefix, since)
        try:
            m = M.mine(sub, opts)
        except Exception:
            continue
        ok += 1
        same += m["stats"]["bottleneck"] == full_bn
        meds.append(m["finding"]["kpis"]["cycle_time_h"])
    return {"resamples": ok, "same_bottleneck": round(same / ok, 2) if ok else None,
            "cycle_h_p10_p90": [round(float(np.percentile(meds, 10)), 1), round(float(np.percentile(meds, 90)), 1)] if meds else None,
            "bottleneck": full_bn}


# ----------------------------------------------------------------------------- results / history / model
def _results(board, now, mined, mined_after, before_rows, after_rows, after_kpis, measured, plans_page, best, series, n_records, people,
             weeks_all, unit, approvals, model: G.Model) -> dict:
    U = unit[:1].upper() + unit[1:]
    before_h = float(measured["cycle_h"])
    pc = {"mid": best["hours"], "lo": best["range_h"][0], "hi": best["range_h"][1]}
    after_h = float(after_kpis["cycle_h"]) if after_kpis and after_kpis.get("n") else None
    kpis = [{"label": f"Hours per {unit}", "before": f"{before_h:.1f}", "after": f"{after_h:.1f} h" if after_h is not None else "—",
             "sub": f"Test predicted {pc['mid']:.1f}" if not best["today"] else "No plan beats today yet"},
            {"label": "Share of time waiting", "before": f"{measured['waiting_share']:.0%}",
             "after": f"{after_kpis['waiting_share']:.0%}" if after_h is not None else "—", "sub": "Measured from records"}]
    if model.approval_cid is not None:
        kpis.append({"label": f"{model.approval_role} sign-offs", "before": f"{measured['signoffs_per_day']:.1f}",
                     "after": f"{after_kpis['signoffs_per_day']:.1f} / day" if after_h is not None else "—", "sub": model.name(model.approval_cid)})
    who = [{"role": w["role"], "what": w["change"][:1].upper() + w["change"][1:], "before": "", "after": ""} for w in best["who"] if "nothing" not in w["change"]]
    if any(r["type"] == "skill" for r in best["rules"]) and model.repeated_cid is not None:
        x = model.steps[model.repeated_cid]
        per_wk = sum(1 for e in mined["execs"] if e.cluster == model.repeated_cid and not e.external) / max(mined["meta"]["weeks"], 1)
        who.append({"role": x.role, "what": f"{x.name} — agent does it, {x.role} checks",
                    "before": f"{per_wk * x.median_min / 60:.1f} h / wk"[:14], "after": f"{per_wk * G.AGENT_REVIEW_MIN:.0f} m / wk"[:14]})
    if mined_after:
        nxt = _next_constraint(mined_after, unit)
    else:
        nxt = {"headline": "Not measured yet", "sub": f"Approve a plan; after two weeks of records the change is measured against the test.", "ready": False}
    if after_h is not None:
        headline = f"{U}s now take {after_h:.0f} hours, not {before_h:.0f}."
        sub = (f"The test predicted {pc['mid']:.1f} h for '{best['name']} {best['sub']}' ({pc['lo']:.1f}–{pc['hi']:.1f} across {plans_page['reruns']} reruns). "
               f"The team measured {after_h:.1f} h over {after_kpis['n']} {_plural(unit)} started after the change. "
               f"Waiting went from {measured['waiting_share']:.0%} of every cycle to {after_kpis['waiting_share']:.0%}.")
        source = "measured"
        state = {}
    else:
        headline = f"A {unit} takes {before_h:.0f} hours; the best plan predicts {pc['mid']:.0f}." if not best["today"] else f"A {unit} takes {before_h:.0f} hours today."
        sub = (f"Measured over {len(before_rows)} completed {_plural(unit)}. The test predicts {pc['mid']:.1f} h "
               f"({pc['lo']:.1f}–{pc['hi']:.1f} across {plans_page['reruns']} reruns) once a plan is approved; nothing has been measured after a change yet.")
        source = "simulated"
        state = {"state": "awaiting_measurement"}
    if len(headline) > 72:
        headline = headline[:69].rstrip() + "..."
    return {"source": source, "board_id": board, "recomputed_at": now, "headline": headline, "sub": sub,
            "records": n_records, "people": people, "weeks": weeks_all,
            "change": " · ".join(w["change"] for w in best["who"] if "nothing" not in w["change"]) if not best["today"] else "",
            "predicted": {"mid": round(pc["mid"], 1), "lo": round(pc["lo"], 1), "hi": round(pc["hi"], 1)},
            "measured": round(after_h, 1) if after_h is not None else 0.0, "measured_cases": after_kpis["n"] if after_kpis else 0,
            "before": round(before_h, 1), "series": series, "kpis": kpis, "who": who, "next_constraint": nxt, **state}


def _next_constraint(mined_after: dict, unit: str) -> dict:
    ext = set(mined_after["stats"]["external_roles"])
    nodes = [n for n in mined_after["ontology"]["nodes"] if n["role"] not in ext]
    if not nodes:
        return {"headline": "Not enough records after the change yet", "sub": "", "ready": False}
    top = max(nodes, key=lambda n: n["wait_before_h"])
    U = unit[:1].upper() + unit[1:]
    return {"headline": f"{U}s now wait longest before {top['name']}",
            "sub": f"— {top['wait_before_h']:.1f} hours for {top['role']}, across {top['cases']} {_plural(unit)}. One constraint solved shows the next.",
            "ready": top["cases"] >= 3}


def _history(board, now, mined, mined_after, baseline_h, after_kpis, plans_page, best, approvals, since, n_records, people, weeks_all, unit,
             next_run, model: G.Model) -> dict:
    by_id = {p["id"]: p for p in plans_page["plans"]}
    today_h = plans_page["today_h"]
    after_h = float(after_kpis["cycle_h"]) if after_kpis and after_kpis.get("n") else None
    bn = next((n for n in mined["ontology"]["nodes"] if n.get("bottleneck")), None)
    bn_wait = mined["stats"]["bottleneck_wait_h"] if bn else 0.0
    merges = sum(len(n["aliases"]) for n in mined["ontology"]["nodes"])
    versions = [{"v": 1, "when": "week 1", "title": f"How {_plural(unit)} moved before any change",
                 "found": f"Measured from records: {baseline_h:.1f} h per {unit}, {mined['finding']['kpis']['waiting_share']:.0%} waiting",
                 "status": "baseline", "delta_h": 0.0}]
    live = 0
    for i, a in enumerate(approvals):
        p = _match_plan(plans_page, a)
        title = _cut(f"{p['name']} {p['sub']}" if p else (a.get("plan_name") or a.get("plan_id") or "Plan approved"), 70)
        pred = round(p["hours"] - today_h, 1) if p else None
        measured_delta = round(after_h - baseline_h, 1) if (after_h is not None and i == len(approvals) - 1) else 0.0
        found = f"approved {a['approved_at'][:10]}" + (f" by {a['approved_by']}" if a.get("approved_by") else "")
        found += f" · measured {measured_delta:+.1f} h" if after_h is not None and i == len(approvals) - 1 else (f" · predicted {pred:+.1f} h" if pred is not None else "")
        versions.append({"v": i + 2, "when": a["approved_at"][:10], "title": title, "found": _cut(found, 90), "status": "live",
                         "delta_h": measured_delta, **({"predicted_delta_h": pred} if pred is not None else {})})
        live += 1
    approved_ids = {a.get("plan_id") for a in approvals}
    if not best["today"] and best["id"] not in approved_ids:
        versions.append({"v": len(versions) + 1, "when": "tonight", "title": _cut(f"{best['name']} {best['sub']}", 70),
                         "found": _cut(f"{bn_wait:.1f} h wait at {bn['name'].lower()} · {len(plans_page['plans'])} plans tested · not yet approved"
                                       if bn else f"{len(plans_page['plans'])} plans tested · not yet approved", 90),
                         "status": "needs_yes", "delta_h": 0.0, "predicted_delta_h": round(best["hours"] - today_h, 1)})
    hhmm = now[11:16]
    loop = [{"n": 1, "name": "Record", "at": hhmm, "status": "done", "note": f"{n_records} records from {people} people"},
            {"n": 2, "name": "Map", "at": hhmm, "status": "done", "note": f"v{mined['ontology']['version']}: {mined['ontology']['counts']['steps']} steps, {merges} names merged"},
            {"n": 3, "name": "Find", "at": hhmm, "status": "done", "note": mined["finding"]["headline"]},
            {"n": 4, "name": "Test", "at": hhmm, "status": "done", "note": f"{len(plans_page['plans'])} plans, same {_plural(unit)}, same luck"},
            {"n": 5, "name": "Approve", "status": "done" if approvals and best["id"] in approved_ids else "now",
             "note": f"{best['name']} needs your yes · predicted {best['hours'] - today_h:+.1f} h" if not best["today"] else "no plan beats today yet"},
            {"n": 6, "name": "Ask & do", "status": "done" if approvals else "pending", "note": "each change goes only to the person it touches"},
            {"n": 7, "name": "Measure", "status": "done" if after_h is not None else "pending",
             "note": f"measured {after_h:.1f} h after the change" if after_h is not None else "two weeks of records after a change, then predicted vs measured"}]
    learned = [{"finding": f"{merges} step names across {people} people were merged into {mined['ontology']['counts']['steps']} steps.",
                "action": "Merges above 0.8 similarity are automatic; the rest are asked at end-of-day review."}]
    if bn:
        learned.append({"finding": f"The longest wait is at {bn['name'].lower()} ({bn_wait:.1f} h, {bn['role']}).",
                        "action": f"{len(plans_page['plans'])} plans target it; the best predicts {best['hours'] - today_h:+.1f} h." if not best["today"] else "No tested plan beats today yet."})
    if after_h is not None:
        learned.append({"finding": f"{after_kpis['n']} {_plural(unit)} completed after the change: {after_h:.1f} h vs {baseline_h:.1f} h before.",
                        "action": "Kept the rule." if after_h < baseline_h else "The change did not pay off yet; the next run re-tests it."})
    headline = (f"This process changed itself {live} time{'s' if live != 1 else ''} in {weeks_all} weeks." if live
                else f"No change approved yet. {len(plans_page['plans'])} plans are tested and waiting for a yes.")
    return {"source": "measured" if after_h is not None or not approvals else "simulated", "board_id": board, "recomputed_at": now,
            "baseline_h": round(baseline_h, 1), "now_h": round(after_h if after_h is not None else baseline_h, 1), "headline": headline,
            "loop": loop, "next_run_at": next_run, "versions": versions, "learned": learned,
            "sub": f"{baseline_h:.1f} h at v1" + (f" · {after_h:.1f} h now (measured after the change)" if after_h is not None else " · nothing measured after a change yet")}


def _model(board, now, n_records, ontology, plans_page, best, calibration, exp_fit, unit, model: G.Model, after_kpis, seeds) -> dict:
    counts = ontology["counts"]
    objects = sum(counts.values())
    U = unit[:1].upper() + unit[1:]
    sim_checks = []
    for c in calibration["checks"]:
        sim_checks.append({"measure": c["measure"], "predicted": c["simulated"], "lo": c["lo"], "hi": c["hi"], "actual": c["measured"],
                           "unit": c["unit"] if c["unit"] in ("h", "%", "/day") else "/day", "in_range": c["in_range"]})
    if after_kpis and after_kpis.get("n"):
        a = round(float(after_kpis["cycle_h"]), 1)
        sim_checks.append({"measure": f"Hours per {unit} after the change", "predicted": best["hours"], "lo": best["range_h"][0],
                           "hi": best["range_h"][1], "actual": a, "unit": "h", "in_range": bool(best["range_h"][0] - 1e-9 <= a <= best["range_h"][1] + 1e-9)})
    components = [
        {"n": "01", "name": "Company knowledge", "what": "Roles, steps, cases, files, rules and skills — learned from approved records, never typed in.",
         "size": f"{len(counts)} types · {objects:,} objects · {len(ontology['edges']) + sum(len(n['aliases']) for n in ontology['nodes']):,} links"},
        {"n": "02", "name": "Team simulator", "what": f"Replays this team's recorded {_plural(unit)} under a different plan. Step times, hand-off waits, "
                                                       f"send-backs and arrivals fitted to the records; no hidden world.",
         "size": f"{counts['steps']} steps · {n_records} records fitted · {len(seeds)} reruns"},
    ]
    if exp_fit:
        components.append({"n": "03", "name": "Demand model", "what": "Ranks where your kind of business grows next, from public data around each site. One industry code switches it.",
                           "size": f"{exp_fit['backtest']['n_zips']:,} cold-start ZIPs scored · NAICS {exp_fit['industry']}"})
        demand_rows = [{"industry": b["name"], "naics": b["naics"], "lift": b["lift"], "population_lift": b["population_lift"], "ci": b["ci"], "verdict": b["verdict"]}
                       for b in exp_fit["backtest"]["by_industry"]]
    else:
        components.append({"n": "03", "name": "Demand model", "what": "Not available for this industry: the US Census backtest covers NAICS 713940, 621111 and 722515.",
                           "size": "n/a"})
        demand_rows = []
    limits = [
        {"title": "Other people's queues", "tag": "Not modelled",
         "why": "Hand-off waits are replayed as measured; freeing one person's hours does not shorten another's queue in this simulator."},
        {"title": "What an agent changes", "tag": "Declared",
         "why": f"Agent does a step in {G.AGENT_MIN:.0f} min, the person reviews in {G.AGENT_REVIEW_MIN:.0f}, {G.AGENT_UNDO_P:.0%} undone; send-backs unchanged. A template only removes layout send-backs people recorded."},
        {"title": "Hidden-truth checks", "tag": "n/a",
         "why": "Planted bottleneck rank and planted-synonym precision/recall need a synthetic world; here the checks are replay-vs-measured, plan stability and miner stability."},
    ]
    if not exp_fit:
        limits.append({"title": "Where to open next", "tag": "No data", "why": "No backtested demand model for this industry yet."})
    ms = calibration.get("miner_stability", {})
    return {
        "source": "simulated", "board_id": board, "calibrated_at": now, "records": n_records,
        "components": components, "sim_checks": sim_checks, "demand": demand_rows,
        "d1": {"dataset": "BPI Challenge 2020 Domestic Declarations", "fit_year": 2017, "test_year": 2018,
               "note": "n/a for a fitted board: the real-data check of the simulator method is produced by `build` (see data/out/model.json)."},
        "limits": limits,
        "calibration": {
            "baseline_replay": [{"measure": c["measure"], "error": c["error"], "in_range": c["in_range"]} for c in calibration["checks"]],
            "scale_to_measured_baseline": calibration["scale_to_measured_baseline"],
            "plan_stability": calibration["plan_stability"],
            "miner_stability": ms,
            "not_applicable": [{"check": "Bottleneck found (hidden constraint rank)", "why": "needs the world's answer key"},
                               {"check": "Name merging precision / recall", "why": "needs planted synonyms"},
                               {"check": "D1 BPIC 2020 fit", "why": "method check, run by `build`"}],
        },
    }


def _model_sparse(board, now, n_records, ontology, need, exp_fit, unit) -> dict:
    counts = ontology["counts"]
    return {"source": "measured", "board_id": board, "calibrated_at": now, "records": n_records,
            "components": [{"n": "01", "name": "Company knowledge", "what": "Learned from approved records.", "size": f"{counts['steps']} steps · {counts['cases']} cases"},
                           {"n": "02", "name": "Team simulator", "what": "Not fitted yet.", "size": f"needs {need['needed']['records']} records from {need['needed']['roles']} roles"},
                           {"n": "03", "name": "Demand model", "what": "Public-data demand model.", "size": "available" if exp_fit else "n/a"}],
            "sim_checks": [], "demand": [{"industry": b["name"], "naics": b["naics"], "lift": b["lift"], "population_lift": b["population_lift"], "ci": b["ci"], "verdict": b["verdict"]}
                                         for b in exp_fit["backtest"]["by_industry"]] if exp_fit else [],
            "d1": {"dataset": "BPI Challenge 2020 Domestic Declarations", "fit_year": 2017, "test_year": 2018, "note": "n/a for a fitted board"},
            "limits": [{"title": "Everything", "tag": "Needs more records", "why": f"{need['have']['records']} records so far; the simulator is fitted at {need['needed']['records']}."}],
            **need}


# ----------------------------------------------------------------------------- expansion / opening / surfaces
def _expansion(board, now, industry, n_records, raw_dir, reference_dir, out, city, zips, today):
    if not industry:
        return _stub_expansion(board, now, None, n_records, "No --industry given; pass a NAICS code to rank ZIPs for this business."), None
    if industry not in demand.TARGETS:
        return _stub_expansion(board, now, industry, n_records,
                               f"NAICS {industry} is not in the pre-computed US Census backtest (713940 fitness, 621111 physicians, 722515 coffee); "
                               f"add it to demand.TARGETS and run `python -m flowline1 demand --recompute`."), None
    proc = os.path.join(raw_dir, "census", "processed")
    gaz = os.path.join(raw_dir, "census", "geo", "2020_Gaz_zcta_national.txt")
    results_dir = reference_dir
    own = os.path.join(out, "demand", "zip_results.json")
    note = "Backtest computed on 2026-11-08 from reference/us-backtest/scripts (same code as demand.backtest); loaded, not recomputed."
    if os.path.exists(own):
        results_dir = os.path.join(out, "demand")
        note = "Backtest recomputed by flowline1 demand.backtest."
    if not (results_dir and os.path.exists(os.path.join(results_dir, "zip_results.json")) and os.path.exists(os.path.join(proc, "acs2019_zcta.csv")) and os.path.exists(gaz)):
        return _stub_expansion(board, now, industry, n_records, "Census inputs or backtest results are missing on this machine (data/raw/census, reference/us-backtest)."), None
    try:
        exp = demand.expansion(results_dir, proc, gaz, board, n_records, 0, {"date": "", "was": "", "blockers_cleared": 0}, note,
                               tuple(z.strip() for z in zips.split(",") if z.strip()), default_naics=industry, city=city)
    except Exception as exc:
        return _stub_expansion(board, now, industry, n_records, f"Demand model failed: {type(exc).__name__}: {exc}"), None
    exp["recomputed_at"] = now
    return exp, exp["by_industry"][industry]


def _opening(records, prefix, board, now, today, opts: M.MineOptions) -> dict:
    prefixes = Counter()
    for r in records:
        for s in r["steps"]:
            p = case_prefix(s.get("case_id") or "")
            if p and p.lower() != (prefix or "").lower() and OPENING_RE.search(p):
                prefixes[p] += 1
    if not prefixes:
        return _stub_opening(board, now, today)
    op = prefixes.most_common(1)[0][0]
    try:
        o = M.MineOptions(**{**opts.__dict__, "process_prefix": op, "process_name": _plural(op.lower()), "start_step": None, "end_step": None, "unit": op.lower()})
        m = M.mine(records, o)
    except Exception:
        return _stub_opening(board, now, today)
    origin = m["stats"]["origin"]
    ws = []
    ext = set(m["stats"]["external_roles"])
    for n in m["ontology"]["nodes"]:
        cid = int(n["id"][1:])
        ex = [e for e in m["execs"] if e.cluster == cid and e.case.startswith(op)]
        if not ex or n["role"] in ext:
            continue
        start = E.minutes_to_dt(min(e.start for e in ex), origin).date().isoformat()
        end = E.minutes_to_dt(max(e.end for e in ex), origin).date().isoformat()
        ws.append({"name": n["name"], "owner": n["role"], "agent": any(e.by_agent for e in ex), "start": start, "end": end,
                   "status": "done" if end < today else "on_track"})
    cases = sorted({e.case for e in m["execs"] if e.case.startswith(op)})
    opens = max((w["end"] for w in ws), default=today)
    return {"source": "measured", "recomputed_at": now, "board_id": board, "branch": len(cases), "zip": "", "name": cases[-1] if cases else "",
            "playbook_from": f"{len(cases)} recorded {_plural(op.lower())}", "steps": len(ws),
            "headline": f"{len(ws)} workstreams learned from {len(cases)} recorded {_plural(op.lower())}.", "opens": opens, "was": opens, "today": today,
            "workstreams": ws, "blockers": []}


def _surfaces(board, now, records, finding, expansion, ontology, mined, unit) -> dict:
    steps = int(np.median([len(r["steps"]) for r in records])) if records else 0
    left_out = int(np.median([r.get("kept_private", 0) for r in records])) if records else 0
    roles = [r["role"] for r in ontology.get("roles", [])]
    bn = next((n for n in ontology.get("nodes", []) if n.get("bottleneck")), None)
    ext = {r["role"] for r in ontology.get("roles", []) if r.get("external")}
    appr = G.approval_node(ontology.get("nodes", []), ext)
    bn_wait = mined["stats"]["bottleneck_wait_h"] if mined and bn else (bn["wait_before_h"] if bn else 0.0)
    exp_fit = expansion["by_industry"].get(expansion["default"]) if expansion.get("by_industry") else None
    top = exp_fit["zips"][:3] if exp_fit and exp_fit.get("zips") else []
    ceo = finding["headline"] + (f" A {unit} takes {finding['kpis']['cycle_time_h']:.0f} h; {finding['kpis']['waiting_share']:.0%} of it is waiting." if finding["kpis"]["cycle_time_h"] else "")
    inbox = []
    if appr:
        per_wk = appr["cases"] / max(finding.get("weeks", 1), 1)
        inbox.append({"title": f"{appr['name']} · {per_wk:.1f} a week · {appr['role']}", "sub": appr.get("sub", ""), "actions": ["Approve", "Ask why"]})
    blocker = {"title": (f"{bn['name']}: {bn_wait:.0f} h on the {bn['role'].lower()} per {unit}. Test a plan?" if bn["role"] in ext
                         else f"{bn['name']} waits {bn_wait:.1f} h ({bn['role']}). Test a plan?") if bn else "No bottleneck found yet.",
               "actions": ["Open it", "Not now"]}
    return {"source": "measured", "recomputed_at": now, "ceo_line": ceo[:200], "finance_inbox": inbox, "branch_mgr_blocker": blocker,
            "expansion_lead": [{"zip": z["zip"], "rank": z["rank"]} for z in top],
            "trainer_record": {"steps": steps, "left_out": left_out}, "roles": roles}
