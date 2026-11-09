"""Fleet: people.json → one suggestion per person; do_it fans out to the pre-approved people (FLOWLINE_FLEET=1);
GET /fleet merges people, suggestions and runs; reset clears the board."""

from __future__ import annotations

import json

from tests.conftest import BOARD, plans_doc, write_json
from tests.test_runs_proxy import _Stub, executor  # noqa: F401  (fixture)

PEOPLE = {
    "board_id": BOARD,
    "people": [
        {"id": "pm-1", "name": "Dana", "role": "PM", "target": "desk1", "skill_id": "fill_deck_from_sheet", "pre_approved": False},
        {"id": "fin-1", "name": "Marcus", "role": "Finance", "target": "desk2", "skill_id": "reconcile_quotes", "pre_approved": True},
        {"id": "sales-1", "name": "Priya", "role": "Sales", "target": "desk3", "skill_id": "fill_deck_from_sheet", "pre_approved": True,
         "inputs": {"deck": "/config/Documents/proposal-172.odp"}},
        {"id": "ops-1", "name": "Tomás", "role": "Ops", "target": "desk4", "skill_id": "signature_packet", "pre_approved": True},
    ],
}


def _setup(dirs, monkeypatch, fleet="1", override=None):
    write_json(dirs["fixtures"] / "plans.json", plans_doc())
    write_json(dirs["tmp"] / "people.json", PEOPLE)
    monkeypatch.setenv("FLOWLINE_FLEET", fleet)
    if override:
        monkeypatch.setenv("FLOWLINE_FLEET_SKILL_OVERRIDE", override)


def test_people_json_gives_one_suggestion_per_person(dirs, monkeypatch, client):
    _setup(dirs, monkeypatch)
    body = client.post(f"/api/boards/{BOARD}/plans/plan-b/approve").json()
    assert len(body["suggestions_created"]) == 4
    fin = client.get("/api/people/fin-1/suggestions").json()
    assert len(fin) == 1 and fin[0]["skill_id"] == "reconcile_quotes"
    assert fin[0]["title"].startswith("Reconcile")
    assert fin[0]["target"] == "desk2"
    pm = client.get("/api/people/pm-1/suggestions").json()
    assert pm[0]["skill_id"] == "fill_deck_from_sheet" and pm[0]["title"].startswith("Fill this deck")
    # second approval: nobody gets a duplicate offer
    assert client.post(f"/api/boards/{BOARD}/plans/plan-b/approve").json()["suggestions_created"] == []


def test_do_it_fans_out_to_pre_approved_people(dirs, monkeypatch, executor, client):  # noqa: F811
    _Stub.finish_after_polls = 99
    _setup(dirs, monkeypatch, override="fill_deck_from_sheet")
    client.post(f"/api/boards/{BOARD}/plans/plan-b/approve")
    pm_sid = client.get("/api/people/pm-1/suggestions").json()[0]["id"]

    r = client.post(f"/api/suggestions/{pm_sid}/respond", json={"answer": "do_it"})
    assert r.status_code == 200, r.text
    started = r.json()["fleet_started"]
    assert sorted(s["person_id"] for s in started) == ["fin-1", "ops-1", "sales-1"]
    assert {s["target"] for s in started} == {"desk2", "desk3", "desk4"}
    # the override ran everyone on the deck skill; the suggestions keep their own skill
    assert all(run["skill_id"] == "fill_deck_from_sheet" for run in _Stub.runs.values())
    fin = client.get("/api/people/fin-1/suggestions?all=1").json()[0]
    assert fin["status"] == "accepted" and fin["pre_approved"] is True and fin["run_id"]
    # pm-1 answered live: accepted later by POST /api/runs (the Mac app's path), not pre_approved
    pm = client.get(f"/api/suggestions/{pm_sid}").json()
    assert pm["status"] == "accepted" and pm.get("pre_approved") is None and pm["run_id"] is None
    r = client.post("/api/runs", json={"suggestion_id": pm_sid, "skill_id": "fill_deck_from_sheet", "target": "desk1", "inputs": {}})
    assert r.status_code == 201 and r.json().get("fleet_started") is None  # idempotent: nothing left to start
    assert len(_Stub.runs) == 4
    assert _Stub.runs["run-4"]["target"] == "desk1"

    fleet = client.get(f"/api/boards/{BOARD}/fleet").json()
    assert [p["person"]["id"] for p in fleet["people"]] == ["pm-1", "fin-1", "sales-1", "ops-1"]
    assert all(p["run"] is not None and p["state"] == "running" for p in fleet["people"])
    assert fleet["counters"]["running"] == 4 and fleet["counters"]["saved_without_review"] == 0
    assert fleet["agent"].startswith("Vercel AI SDK ToolLoopAgent · ")

    reset = client.post(f"/api/boards/{BOARD}/fleet/reset").json()
    assert reset["suggestions"] == 4 and sorted(reset["stopped"]) == ["run-1", "run-2", "run-3", "run-4"]
    assert client.get("/api/people/fin-1/suggestions?all=1").json() == []
    fleet = client.get(f"/api/boards/{BOARD}/fleet").json()
    assert all(p["run"] is None and p["state"] == "waiting" for p in fleet["people"])
    _Stub.finish_after_polls = 1


def test_fleet_off_keeps_single_run(dirs, monkeypatch, executor, client):  # noqa: F811
    _setup(dirs, monkeypatch, fleet="0")
    client.post(f"/api/boards/{BOARD}/plans/plan-b/approve")
    pm_sid = client.get("/api/people/pm-1/suggestions").json()[0]["id"]
    r = client.post(f"/api/suggestions/{pm_sid}/respond", json={"answer": "do_it"})
    assert "fleet_started" not in r.json()
    assert client.get("/api/people/fin-1/suggestions").json()[0]["status"] == "offered"


def test_frame_proxy_reports_executor_down(dirs, monkeypatch, client):
    r = client.get("/api/desk/desk2/frame.jpg?w=320")
    assert r.status_code == 503
    assert client.get("/api/desk/bogus/frame.jpg").status_code == 400
