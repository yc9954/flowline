from __future__ import annotations

import os
import time

from tests.conftest import BOARD, plans_doc, write_json


def test_missing_file_404_names_both_paths(client, dirs):
    r = client.get(f"/api/boards/{BOARD}/ontology")
    assert r.status_code == 404
    d = r.json()["detail"]
    assert str(dirs["out"] / "ontology.json") in d
    assert str(dirs["fixtures"] / "ontology.json") in d


def test_fixture_then_data_out_priority_and_mtime_reload(client, dirs):
    write_json(dirs["fixtures"] / "plans.json", plans_doc(headline="from fixtures", source="prototype"))
    r = client.get(f"/api/boards/{BOARD}/plans")
    assert r.status_code == 200 and r.json()["headline"] == "from fixtures"

    st = {f["name"]: f for f in client.get(f"/api/boards/{BOARD}/status").json()["files"]}
    assert st["plans"]["served_from"] == "fixtures" and st["plans"]["source"] == "prototype"
    assert st["ontology"]["served_from"] == "missing"

    # data/out wins over fixtures.
    write_json(dirs["out"] / "plans.json", plans_doc(headline="from model", source="simulated"))
    r = client.get(f"/api/boards/{BOARD}/plans")
    assert r.json()["headline"] == "from model"
    st = {f["name"]: f for f in client.get(f"/api/boards/{BOARD}/status").json()["files"]}
    assert st["plans"]["served_from"] == "data_out" and st["plans"]["source"] == "simulated"

    # Rewriting the file with a newer mtime is picked up without restart.
    p = dirs["out"] / "plans.json"
    write_json(p, plans_doc(headline="from model v2", source="simulated"))
    future = time.time() + 5
    os.utime(p, (future, future))
    assert client.get(f"/api/boards/{BOARD}/plans").json()["headline"] == "from model v2"

    # Deleting the data/out file falls back to the fixture again.
    p.unlink()
    assert client.get(f"/api/boards/{BOARD}/plans").json()["headline"] == "from fixtures"


def test_expansion_industry_switch(client, dirs):
    base = {
        "board_id": BOARD, "city": "Austin, TX",
        "industries": [{"naics": "713940", "name": "Fitness centers"}, {"naics": "812112", "name": "Beauty salons"}],
        "headline": "", "sub": "", "zips_considered": 70, "branches": 3, "records": 100, "rank_of": 70,
        "opening": {"date": "2027-02-01", "was": "2027-05-01", "blockers_cleared": 3},
        "zips": [], "source": "measured",
        "backtest": {"frozen_at": 2020, "scored_on": 2023, "n_zips": 500, "lift": 1.3, "ci": [1.1, 1.5],
                     "by_industry": [], "pooled": {"lift": 1.3, "population_lift": 1.0}},
    }
    write_json(dirs["out"] / "expansion.json", {
        **base,
        "default": "713940",
        "by_industry": {
            "713940": {"industry": "713940", "headline": "gyms"},
            "812112": {"industry": "812112", "headline": "salons"},
        },
    })
    assert client.get(f"/api/boards/{BOARD}/expansion").json()["headline"] == "gyms"
    r = client.get(f"/api/boards/{BOARD}/expansion?industry=812112")
    assert r.status_code == 200 and r.json()["headline"] == "salons" and r.json()["city"] == "Austin, TX"
    r = client.get(f"/api/boards/{BOARD}/expansion?industry=999999")
    assert r.status_code == 404 and "713940" in r.json()["detail"]

    # Single-object layout: matching industry works, other listed industry says why not.
    write_json(dirs["out"] / "expansion.json", {**base, "industry": "713940", "headline": "only gyms"})
    assert client.get(f"/api/boards/{BOARD}/expansion?industry=713940").json()["headline"] == "only gyms"
    r = client.get(f"/api/boards/{BOARD}/expansion?industry=812112")
    assert r.status_code == 404 and "by_industry" in r.json()["detail"]


def test_status_shape_and_recompute_503(client, dirs):
    st = client.get(f"/api/boards/{BOARD}/status").json()
    assert st["board_id"] == BOARD
    assert st["data_out"] == str(dirs["out"]) and st["fixtures"] == str(dirs["fixtures"])
    assert {f["name"] for f in st["files"]} == {
        "ontology", "finding", "plans", "results", "history", "model", "expansion", "opening", "surfaces",
    }
    assert st["recompute"]["state"] == "idle"
    assert st["board_dist_served"] is False

    r = client.post(f"/api/boards/{BOARD}/recompute")
    assert r.status_code == 503 and "does not exist" in r.json()["detail"]


def test_runs_proxy_503_when_executor_down(client, dirs):
    write_json(dirs["fixtures"] / "plans.json", plans_doc())
    sid = client.post(f"/api/boards/{BOARD}/plans/plan-b/approve").json()["suggestions_created"][0]
    r = client.post("/api/runs", json={"suggestion_id": sid, "skill_id": "fill_deck_from_sheet", "target": "mac", "inputs": {}})
    assert r.status_code == 503 and "executor" in r.json()["detail"]
    assert client.get("/api/runs/run-1").status_code == 503
    assert client.post("/api/runs/run-1/stop").status_code == 503
    # Suggestion untouched by a failed start.
    assert client.get(f"/api/suggestions/{sid}").json()["status"] == "offered"


def test_root_without_board_dist_and_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and "not built" in r.json()["board"]
