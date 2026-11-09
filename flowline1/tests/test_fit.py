"""`fit` on sparse data, on the dental-clinic records, the shape validator, and the generic simulator's CRN."""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone

import pytest

from flowline1 import fit as F
from flowline1 import generic as G
from flowline1 import miner as M
from flowline1 import validate as V
from flowline1.__main__ import main

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def _clinic():
    spec = importlib.util.spec_from_file_location("make_clinic_records", os.path.join(HERE, "..", "examples", "make_clinic_records.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def clinic_records():
    return _clinic().generate(seed=7, weeks=8)


def _rec(i, person, role, date, steps, board="t"):
    rs = [{"idx": k, "start": a, "end": b, "name": n, "kind": "hands_on", "case_id": c, "tools": ["docs"]} for k, (a, b, n, c) in enumerate(steps, 1)]
    return {"id": f"r{i}", "board_id": board, "person_id": person, "role": role, "date": date,
            "covers": {"start": steps[0][0], "end": steps[-1][1]}, "steps": rs, "kept_private": 0, "hands_on_min": 10,
            "waiting_min": 0, "approved_at": f"{date}T18:05:00-05:00", "hash": "", "pubkey": "", "sig": ""}


def _load(out, name):
    with open(os.path.join(out, name), encoding="utf-8") as f:
        return json.load(f)


def test_fit_with_no_records_writes_stubs(tmp_path):
    out = str(tmp_path / "out")
    s = F.fit([], out, board_id="empty", now=NOW)
    assert s["files"] == 9 and s["state"] == "not_enough_data"
    plans, results, finding = _load(out, "plans.json"), _load(out, "results.json"), _load(out, "finding.json")
    assert plans["state"] == "not_enough_data" and plans["plans"] == [] and plans["needed"]["records"] == F.MIN_RECORDS
    assert results["state"] == "not_enough_data" and results["have"]["records"] == 0
    assert finding["state"] == "no_data_yet" and finding["kpis"]["cycle_time_h"] == 0.0
    assert _load(out, "opening.json")["state"] == "no_data_yet"
    assert _load(out, "expansion.json")["source"] == "not_available"
    for name, spec in V.FILES.items():
        V._req(_load(out, name), spec, name)  # every stub has the board's shape


def test_fit_sparse_one_role_does_not_crash(tmp_path):
    recs = [_rec(i, "a", "Ops", f"2026-10-{5 + i:02d}", [(f"2026-10-{5 + i:02d}T09:00:00-05:00", f"2026-10-{5 + i:02d}T09:30:00-05:00", "Do thing", f"job #{i}")])
            for i in range(5)]
    out = str(tmp_path / "out")
    s = F.fit(recs, out, now=NOW)
    assert s["state"] == "not_enough_data" and s["roles"] == ["Ops"]
    plans = _load(out, "plans.json")
    assert plans["state"] == "not_enough_data" and plans["have"]["records"] == 5 and plans["have"]["roles"] == 1
    assert V.validate_dir(out)  # the shapes still validate, roles are free strings


def test_fit_under_twenty_records_marks_not_enough_data(tmp_path):
    recs = []
    for i in range(8):
        d = f"2026-10-{5 + i:02d}"
        recs.append(_rec(f"a{i}", "a", "Front desk", d, [(f"{d}T09:00:00-05:00", f"{d}T09:20:00-05:00", "Intake", f"ticket #{i}")]))
        recs.append(_rec(f"b{i}", "b", "Dentist", d, [(f"{d}T11:00:00-05:00", f"{d}T11:30:00-05:00", "Review", f"ticket #{i}")]))
    recs = recs[:15]
    out = str(tmp_path / "out")
    s = F.fit(recs, out, now=NOW)
    assert s["records"] == 15 and s["state"] == "not_enough_data"
    finding = _load(out, "finding.json")
    assert finding["kpis"]["cycle_time_h"] > 0 and finding["records"] == 15  # mined with what there is
    results = _load(out, "results.json")
    assert results["state"] == "not_enough_data" and results["needed"] == {"records": 20, "roles": 2, "completed_tickets": 3}
    assert _load(out, "history.json")["state"] == "not_enough_data"
    assert V.validate_dir(out)


def test_fit_clinic_finds_the_insurer_wait(tmp_path, clinic_records):
    assert len(clinic_records) >= 100 and len({r["role"] for r in clinic_records}) == 5
    out = str(tmp_path / "out")
    s = F.fit(clinic_records, out, industry="621210", seeds=8, bootstrap=4, now=NOW)
    assert s["state"] == "fitted" and s["process"] == "pre-auth"
    assert "insurer" in s["bottleneck"].lower()
    finding = _load(out, "finding.json")
    assert finding["source"] == "measured" and "insurer" in finding["headline"].lower()
    assert 40 <= finding["kpis"]["cycle_time_h"] <= 200 and finding["kpis"]["waiting_share"] > 0.8
    longest = next(m for m in finding["map"] if m.get("longest_wait"))
    assert longest["wait_after_h"] > 24  # the insurer's days show up as the longest wait on the map
    onto = _load(out, "ontology.json")
    assert any(r.get("external") and r["role"] == "Insurer" for r in onto["roles"])
    assert next(n for n in onto["nodes"] if n["bottleneck"])["role"] == "Insurer"
    plans = _load(out, "plans.json")
    assert plans["source"] == "simulated" and plans["reruns"] == 8 and len(plans["plans"]) >= 2
    assert sum(p["best"] for p in plans["plans"]) == 1 and sum(p["today"] for p in plans["plans"]) == 1
    assert any(r["type"] == "auto_approve_under" for p in plans["plans"] for r in p["rules"])
    assert any(r["type"] == "skill" and r["actor"] == "Front desk" for p in plans["plans"] for r in p["rules"])
    results = _load(out, "results.json")
    assert results["state"] == "awaiting_measurement" and results["before"] == finding["kpis"]["cycle_time_h"]
    model = _load(out, "model.json")
    assert len(model["sim_checks"]) >= 3 and model["demand"] == [] and model["calibration"]["not_applicable"]
    exp = _load(out, "expansion.json")
    assert exp["source"] == "not_available" and "621210" in exp["reason"] and exp["default"] in exp["by_industry"]
    assert _load(out, "opening.json")["state"] == "no_data_yet"
    assert set(V.validate_dir(out)) == set(V.FILES) | {"records.jsonl"}


def test_fit_cli_runs(tmp_path, clinic_records):
    path = tmp_path / "records.ndjson"
    path.write_text("\n".join(json.dumps(r) for r in clinic_records) + "\n", encoding="utf-8")
    out = str(tmp_path / "out")
    assert main(["fit", "--records", str(path), "--out", out, "--seeds", "4", "--bootstrap", "0", "--industry", "621210"]) == 0
    assert _load(out, "plans.json")["reruns"] == 4
    assert F.load_records(str(path))[0]["board_id"] == "clinic"


def test_validator_accepts_free_roles_and_rejects_broken_shapes(tmp_path, clinic_records):
    out = str(tmp_path / "out")
    F.fit(clinic_records, out, seeds=3, bootstrap=0, now=NOW)
    assert V.validate_dir(out)
    plans = _load(out, "plans.json")
    for p in plans["plans"]:
        p["best"] = True
    with open(os.path.join(out, "plans.json"), "w", encoding="utf-8") as f:
        json.dump(plans, f)
    with pytest.raises(V.ShapeError):
        V.validate_dir(out)
    with pytest.raises(V.ShapeError):
        V._req({"role": ""}, {"role": V.ROLES}, "x")
    with pytest.raises(V.ShapeError):
        V._req({"source": "guessed"}, {"source": V.SOURCES}, "x")
    V._req({"role": "Hygienist", "source": "not_available"}, {"role": V.ROLES, "source": V.SOURCES}, "x")


def test_generic_simulator_common_random_numbers(clinic_records):
    recs = clinic_records
    opts = M.MineOptions(board="clinic", process_prefix="pre-auth", process_name="pre-auths", start_step=None, end_step=None,
                         map_groups=None, external_roles=None, calendar=F.calendar_from(recs), unit="pre-auth")
    mined = M.mine(recs, opts)
    model = G.fit(mined, opts.calendar, "pre-auth")
    assert model.approval_cid is not None and model.batch and model.threshold_usd
    a = G.simulate(model, [], 5, model.weeks)
    b = G.simulate(model, [], 5, model.weeks)
    assert a["n"] == b["n"] and a["cycle_h"] == b["cycle_h"]
    c = G.simulate(model, [{"type": "auto_approve_under", "usd": model.threshold_usd}], 5, model.weeks)
    assert c["n"] == a["n"] and [x["case"] for x in c["cases"]] == [x["case"] for x in a["cases"]]
    assert c["cycle_mean_h"] <= a["cycle_mean_h"] and c["signoffs_per_day"] < a["signoffs_per_day"]
