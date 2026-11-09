"""Shape checks for the ten output files against SCHEMA.md sections 2–11 (required keys and types)."""
from __future__ import annotations

import json
import os

NUM = (int, float)
ROLES = {"Client", "Sales", "PM", "Design", "Finance", "Director", "Legal", "Trainer", "BranchMgr", "Ops", "CEO"}
SOURCES = {"measured", "simulated", "prototype"}


class ShapeError(AssertionError):
    pass


def _req(obj: dict, spec: dict, path: str) -> None:
    if not isinstance(obj, dict):
        raise ShapeError(f"{path}: expected object, got {type(obj).__name__}")
    for key, typ in spec.items():
        optional = key.endswith("?")
        k = key.rstrip("?")
        if k not in obj:
            if optional:
                continue
            raise ShapeError(f"{path}.{k}: missing")
        v = obj[k]
        if v is None and optional:
            continue
        _check(v, typ, f"{path}.{k}")


def _check(v, typ, path: str) -> None:
    if isinstance(typ, dict):
        _req(v, typ, path)
    elif isinstance(typ, list):
        if not isinstance(v, list):
            raise ShapeError(f"{path}: expected list")
        for i, item in enumerate(v):
            _check(item, typ[0], f"{path}[{i}]")
    elif isinstance(typ, set):
        if v not in typ:
            raise ShapeError(f"{path}: {v!r} not in {sorted(typ)}")
    elif typ is NUM:
        if not isinstance(v, NUM) or isinstance(v, bool):
            raise ShapeError(f"{path}: expected number, got {type(v).__name__}")
    elif typ is int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ShapeError(f"{path}: expected integer, got {v!r}")
    elif typ is bool:
        if not isinstance(v, bool):
            raise ShapeError(f"{path}: expected boolean")
    elif typ is dict:
        if not isinstance(v, dict):
            raise ShapeError(f"{path}: expected object")
    elif typ is str:
        if not isinstance(v, str):
            raise ShapeError(f"{path}: expected string, got {type(v).__name__}")
    elif typ == "pair":
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, NUM) for x in v)):
            raise ShapeError(f"{path}: expected [number, number]")
    else:
        raise ShapeError(f"{path}: unknown spec {typ}")


RECORD_STEP = {"idx": int, "start": str, "end": str, "name": str, "kind": {"hands_on", "waiting"}, "case_id?": str,
               "tools": [str], "handoff_from?": ROLES, "handoff_to?": ROLES, "waiting_on?": ROLES, "repeats?": int}
RECORD = {"id": str, "board_id": str, "person_id": str, "role": ROLES, "date": str, "covers": {"start": str, "end": str},
          "steps": [RECORD_STEP], "kept_private": int, "hands_on_min": int, "waiting_min": int, "approved_at": str,
          "hash": str, "pubkey": str, "sig": str, "source": SOURCES}
NODE = {"id": str, "name": str, "kind": {"event", "step", "decision", "skill"}, "role": ROLES, "aliases": [str],
        "median_min?": int, "cases": int, "wait_before_h?": NUM, "share_of_cycle?": NUM, "critical_path": bool,
        "bottleneck?": bool, "sub?": str, "rule?": str}
EDGE = {"from": str, "to": str, "kind": {"then", "back", "parallel"}, "share?": NUM, "wait_h?": NUM, "label?": str}
ONTOLOGY = {"source": SOURCES, "board_id": str, "version": int, "recomputed_at": str, "records_used": int,
            "roles": [{"role": ROLES, "steps": int, "external?": bool}], "nodes": [NODE], "edges": [EDGE],
            "counts": {k: int for k in ("roles", "steps", "cases", "files", "rules", "skills", "customers", "zip_areas", "branches")},
            "headline": str}
FINDING = {"source": SOURCES, "recomputed_at": str, "board_id": str, "process": str, "records": int, "people": int, "weeks": int, "headline": str, "sub": str,
           "kpis": {"cycle_time_h": NUM, "waiting_share": NUM, "small_quotes_share": NUM, "small_quotes_unchanged": NUM,
                    "repeated_by_hand_h_per_wk": NUM},
           "map": [{"role": ROLES, "name": str, "hands_on_h": NUM, "artifact": str, "wait_after_h?": NUM, "longest_wait?": bool, "selected?": bool}],
           "to_scale": {"hands_on_h": NUM, "waiting_h": NUM},
           "sent_back": [{"reason": str, "by?": ROLES, "back_to": str, "cost": str, "share": NUM}],
           "repeated": [{"task": str, "who": ROLES, "count_per_wk": NUM, "minutes": int, "agent_can_do": bool}]}
PLAN = {"id": str, "rank": int, "name": str, "sub": str, "hours": NUM, "work_h": NUM, "waiting_h": NUM, "vs_today": NUM,
        "best": bool, "today": bool, "held_best_n": int, "range_h": "pair", "who": [{"role": ROLES, "change": str}],
        "rules": [{"type": {"auto_approve_under", "approver_batches_per_day", "skill", "template"}}]}
PLANS = {"source": SOURCES, "board_id": str, "reruns": int, "weeks": int, "headline": str, "today_h": NUM, "plans": [PLAN], "note": str}
RESULTS = {"source": SOURCES, "recomputed_at": str, "board_id": str, "headline": str, "sub": str, "records": int, "people": int, "weeks": int, "change": str,
           "predicted": {"mid": NUM, "lo": NUM, "hi": NUM}, "measured": NUM,
           "series": [{"week": int, "value": NUM, "after": bool}],
           "kpis": [{"label": str, "before": str, "after": str, "sub": str}],
           "who": [{"role": ROLES, "what": str, "before": str, "after": str}],
           "next_constraint": {"headline": str, "sub": str, "ready": bool}}
HISTORY = {"source": SOURCES, "board_id": str, "headline": str, "baseline_h": NUM, "now_h": NUM, "recomputed_at": str,
           "loop": [{"n": int, "name": {"Record", "Map", "Find", "Test", "Approve", "Ask & do", "Measure"}, "at?": str,
                     "status": {"done", "now", "pending"}, "note": str}],
           "next_run_at": str,
           "versions": [{"v": int, "when": str, "title": str, "found": str, "status": {"live", "needs_yes", "baseline"},
                         "delta_h": NUM, "predicted_delta_h?": NUM}],
           "learned": [{"finding": str, "action": str}]}
MODEL = {"source": SOURCES, "board_id": str, "calibrated_at": str, "records": int,
         "components": [{"n": str, "name": str, "what": str, "size": str}],
         "sim_checks": [{"measure": str, "predicted": NUM, "lo": NUM, "hi": NUM, "actual": NUM, "unit": {"h", "%", "/day"}, "in_range": bool}],
         "demand": [{"industry": str, "naics": str, "lift": NUM, "population_lift": NUM, "ci": "pair", "verdict": {"better", "tie"}}],
         "d1": {"dataset": str, "fit_year": int, "test_year": int, "median_error?": NUM, "p80_error?": NUM, "cases?": int,
                "events?": int, "amount_attr?": bool},
         "limits": [{"title": str, "tag": str, "why": str}]}
EXPANSION_ONE = {"board_id": str, "city": str, "industries": [{"naics": str, "name": str}], "industry": str, "headline": str, "sub": str,
                 "zips_considered": int, "branches": int, "records": int, "rank_of": int,
                 "opening": {"date": str, "was": str, "blockers_cleared": int},
                 "zips": [{"zip": str, "name": str, "why": [str], "predicted": NUM, "happened": NUM, "rank": int, "pick": bool,
                           "lat": NUM, "lon": NUM}],
                 "backtest": {"frozen_at": int, "scored_on": int, "n_zips": int, "lift": NUM, "ci": "pair",
                              "by_industry": [{"naics": str, "name": str, "lift": NUM, "population_lift": NUM, "ci": "pair",
                                               "verdict": {"better", "tie"}}],
                              "pooled": {"lift": NUM, "population_lift": NUM}},
                 "source": str}
EXPANSION = {"source": SOURCES, "recomputed_at": str, "board_id": str, "city": str, "industries": [{"naics": str, "name": str}], "default": str,
             "records": int, "branches": int, "by_industry": dict}
OPENING = {"source": SOURCES, "recomputed_at": str, "board_id": str, "branch": int, "zip": str, "name": str, "playbook_from": str, "steps": int, "headline": str,
           "opens": str, "was": str, "today": str,
           "workstreams": [{"name": str, "owner": ROLES, "agent": bool, "start": str, "end": str,
                            "status": {"done", "on_track", "waiting", "todo"}, "saved_d?": int, "due?": str, "progress?": "pair"}],
           "blockers": [{"id": str, "title": str, "status": {"cleared", "waiting_on_you", "in_progress"}, "saved_d?": int, "due?": str,
                         "was": str, "agent": str, "decided_by": ROLES, "surface": {"inbox", "notch", "weekly_digest"}}]}
SURFACES = {"source": SOURCES, "recomputed_at": str, "ceo_line": str, "finance_inbox": [{"title": str, "sub": str, "actions": [str]}],
            "branch_mgr_blocker": {"title": str, "actions": [str]}, "expansion_lead": [{"zip": str, "rank": int}],
            "trainer_record": {"steps": int, "left_out": int}}

FILES = {"ontology.json": ONTOLOGY, "finding.json": FINDING, "plans.json": PLANS, "results.json": RESULTS, "history.json": HISTORY,
         "model.json": MODEL, "expansion.json": EXPANSION, "opening.json": OPENING, "surfaces.json": SURFACES}


def validate_dir(out: str) -> list[str]:
    """Validate every output file; returns the list of file names checked. Raises ShapeError on the first problem."""
    checked = []
    for name, spec in FILES.items():
        path = os.path.join(out, name)
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        _req(obj, spec, name)
        if name == "expansion.json":
            if obj["default"] not in obj["by_industry"]:
                raise ShapeError("expansion.json: default industry missing from by_industry")
            for naics, e in obj["by_industry"].items():
                _req(e, EXPANSION_ONE, f"expansion.json.by_industry[{naics}]")
                if e["source"] not in SOURCES:
                    raise ShapeError(f"expansion.json.by_industry[{naics}].source: {e['source']!r}")
        if name == "plans.json":
            if sum(1 for p in obj["plans"] if p["best"]) != 1 or sum(1 for p in obj["plans"] if p["today"]) != 1:
                raise ShapeError("plans.json: exactly one best and one today plan expected")
        checked.append(name)
    path = os.path.join(out, "records.jsonl")
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            _req(rec, RECORD, f"records.jsonl[{n}]")
            n += 1
    if n == 0:
        raise ShapeError("records.jsonl: empty")
    checked.append("records.jsonl")
    return checked
