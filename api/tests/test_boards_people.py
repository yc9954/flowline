"""Boards & people in the DB, invite flow, per-board data isolation, the people.json migration, records export
and the fit job (SCHEMA § Boards & people)."""

from __future__ import annotations

import json
import sys

from fastapi.testclient import TestClient

from api.db import INVITE_ALPHABET
from tests.conftest import BOARD, add_people, make_board, plans_doc, write_json

ONTOLOGY = {
    "board_id": "acme", "version": 1, "recomputed_at": "2026-11-09T03:00:00+00:00", "records_used": 12,
    "roles": [{"role": "PM", "steps": 3}], "nodes": [], "edges": [],
    "counts": {"roles": 1, "steps": 3, "cases": 2, "files": 0, "rules": 0, "skills": 0, "customers": 0, "zip_areas": 0, "branches": 1},
    "headline": "How a quote really moves at Acme", "source": "measured",
}


# ---------------------------------------------------------------- boards


def test_board_create_list_get_patch(client):
    r = client.post("/api/boards", json={"name": "Acme Dental Group", "industry_naics": "621210", "mail_domain": "Acme.Local"})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"] == "acme-dental-group" and b["mail_domain"] == "acme.local" and b["timezone"] == "UTC"
    assert b["industry_naics"] == "621210" and b["created_at"]

    # explicit id, slugified; duplicate id is a conflict
    r = client.post("/api/boards", json={"id": "Blue Sky!", "name": "Blue Sky Yoga", "timezone": "Europe/Berlin"})
    assert r.status_code == 201 and r.json()["id"] == "blue-sky" and r.json()["timezone"] == "Europe/Berlin"
    assert client.post("/api/boards", json={"id": "blue-sky", "name": "again"}).status_code == 409

    boards = client.get("/api/boards").json()
    assert [x["id"] for x in boards] == ["acme-dental-group", "blue-sky"]
    assert boards[0] == {**b, "people": 0, "records": 0, "has_data": False}

    r = client.get("/api/boards/nope")
    assert r.status_code == 404 and r.json() == {"detail": "board 'nope' does not exist; create it with POST /api/boards", "state": "no_such_board"}
    assert client.get("/api/boards/nope/people").json()["state"] == "no_such_board"
    one = client.get("/api/boards/blue-sky").json()
    assert one["name"] == "Blue Sky Yoga" and one["people"] == 0 and one["has_data"] is False
    assert one["data_dir"].endswith("/boards/blue-sky/out") and one["legacy_fallback"] is False

    r = client.patch("/api/boards/blue-sky", json={"industry_naics": "713940", "mail_domain": "bluesky.local"})
    assert r.status_code == 200 and r.json()["industry_naics"] == "713940" and r.json()["mail_domain"] == "bluesky.local"
    assert r.json()["name"] == "Blue Sky Yoga"  # untouched


# ---------------------------------------------------------------- people


def test_people_crud_and_invite_codes(client):
    make_board(client, "acme", "Acme Dental")
    # people need a board
    assert client.post("/api/boards/nope/people", json={"name": "X", "role": "PM"}).status_code == 404

    r = client.post("/api/boards/acme/people", json={"name": "Dana Whitfield", "role": "PM", "email": "Dana@Acme.Local"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["id"] == "dana-whitfield" and p["board_id"] == "acme" and p["email"] == "dana@acme.local"
    assert p["target"] == "mac" and p["skill_id"] is None and p["pre_approved"] is False and p["inputs"] == {}
    assert len(p["invite_code"]) == 8 and set(p["invite_code"]) <= set(INVITE_ALPHABET)
    assert p["claimed_at"] is None and p["joined_at"] is None and p["invite_status"] == "invited" and p["invited_at"]

    r = client.post("/api/boards/acme/people", json={
        "id": "fin-1", "name": "Marcus", "role": "Finance", "target": "desk2", "skill_id": "reconcile_quotes",
        "pre_approved": True, "inputs": {"proposal": 173},
    })
    assert r.status_code == 201
    fin = r.json()
    assert fin["target"] == "desk2" and fin["pre_approved"] is True and fin["inputs"] == {"proposal": 173}
    assert fin["invite_code"] != p["invite_code"]
    assert client.post("/api/boards/acme/people", json={"id": "fin-1", "name": "dup", "role": "Finance"}).status_code == 409

    people = client.get("/api/boards/acme/people").json()
    assert [x["id"] for x in people] == ["dana-whitfield", "fin-1"]
    assert client.get("/api/boards/acme").json()["people"] == 2
    assert client.get("/api/boards/acme/people/fin-1").json()["name"] == "Marcus"

    r = client.patch("/api/boards/acme/people/fin-1", json={"target": "desk5", "pre_approved": False, "inputs": {"proposal": 174}})
    assert r.status_code == 200
    assert r.json()["target"] == "desk5" and r.json()["pre_approved"] is False and r.json()["inputs"] == {"proposal": 174}
    assert r.json()["name"] == "Marcus" and r.json()["invite_code"] == fin["invite_code"]  # untouched
    assert client.patch("/api/boards/acme/people/nope", json={"name": "x"}).status_code == 404

    assert client.delete("/api/boards/acme/people/fin-1").json()["deleted"] is True
    assert client.delete("/api/boards/acme/people/fin-1").status_code == 404
    assert [x["id"] for x in client.get("/api/boards/acme/people").json()] == ["dana-whitfield"]


def test_invite_claim_once_then_reissue(client):
    make_board(client, "acme", "Acme Dental")
    [p] = add_people(client, "acme", [{"id": "pm-1", "name": "Dana", "role": "PM", "target": "desk1", "skill_id": "fill_deck_from_sheet"}])
    code = p["invite_code"]

    assert client.post("/api/invites/NOPE1234/claim", json={"device": "x"}).status_code == 404

    r = client.post(f"/api/invites/{code.lower()}/claim", json={"device": "Dana's MacBook"})  # case-insensitive
    assert r.status_code == 200, r.text
    assert r.json() == {
        "board_id": "acme", "board_name": "Acme Dental", "person_id": "pm-1", "name": "Dana", "role": "PM",
        "target": "desk1", "skill_id": "fill_deck_from_sheet", "api_base_hint": "http://testserver",
    }
    got = client.get("/api/boards/acme/people/pm-1").json()
    assert got["claimed_at"] and got["claimed_device"] == "Dana's MacBook"
    assert got["invite_status"] == "joined" and got["joined_at"] == got["claimed_at"]

    # a second claim of the same code is refused
    r = client.post(f"/api/invites/{code}/claim", json={})
    assert r.status_code == 409 and "already claimed" in r.json()["detail"]

    # a new code: the old one is dead, the new one works once, and the claim is cleared until then
    r = client.post("/api/boards/acme/people/pm-1/invite")
    assert r.status_code == 200
    new = r.json()["invite_code"]
    assert new != code and r.json()["claimed_at"] is None and r.json()["invite_status"] == "invited"
    assert r.json()["api_url"] == "http://testserver" and r.json()["invited_at"] >= p["invited_at"]
    assert client.post(f"/api/invites/{code}/claim").status_code == 404
    assert client.post(f"/api/invites/{new}/claim").status_code == 200
    assert client.post(f"/api/invites/{new}/claim").status_code == 409
    assert client.post("/api/boards/acme/people/nope/invite").status_code == 404


def test_api_base_hint_from_env(dirs, monkeypatch):
    monkeypatch.setenv("FLOWLINE_PUBLIC_URL", "http://mini.local:18787/")
    import api.main

    with TestClient(api.main.create_app()) as c:
        make_board(c, "acme", "Acme")
        [p] = add_people(c, "acme", [{"name": "Dana", "role": "PM"}])
        assert c.post(f"/api/invites/{p['invite_code']}/claim").json()["api_base_hint"] == "http://mini.local:18787"


# ---------------------------------------------------------------- per-board data


def test_per_board_data_isolation(client, dirs):
    make_board(client, "acme", "Acme Dental")
    make_board(client, "blue-sky", "Blue Sky Yoga")
    # a legacy data/out file exists (northwind's) — it must never show up under another board
    write_json(dirs["out"] / "ontology.json", {**ONTOLOGY, "board_id": BOARD, "headline": "northwind only"})
    (dirs["boards"] / "acme" / "out").mkdir(parents=True)
    write_json(dirs["boards"] / "acme" / "out" / "ontology.json", ONTOLOGY)

    r = client.get("/api/boards/acme/ontology")
    assert r.status_code == 200 and r.json()["headline"] == "How a quote really moves at Acme"

    r = client.get("/api/boards/blue-sky/ontology")
    assert r.status_code == 404
    body = r.json()
    assert body["state"] == "no_data_yet" and "northwind" not in body["detail"]
    assert str(dirs["boards"] / "blue-sky" / "out" / "ontology.json") in body["detail"]
    assert str(dirs["out"]) not in body["detail"]  # no legacy fallback for a new board
    assert "approved records" in body["needs"]

    # legacy board still reads data/out while it has no directory of its own
    assert client.get(f"/api/boards/{BOARD}/ontology").json()["headline"] == "northwind only"

    boards = {b["id"]: b for b in client.get("/api/boards").json()}
    assert boards["acme"]["has_data"] is True and boards["blue-sky"]["has_data"] is False

    st = client.get("/api/boards/acme/status").json()
    files = {f["name"]: f for f in st["files"]}
    assert st["legacy_fallback"] is False and st["has_data"] is True and st["board"]["name"] == "Acme Dental"
    assert files["ontology"]["served_from"] == "board" and files["ontology"]["source"] == "measured"
    assert files["finding"]["served_from"] == "missing" and files["finding"]["state"] == "no_data_yet"
    st = client.get(f"/api/boards/{BOARD}/status").json()
    assert st["legacy_fallback"] is True
    assert {f["name"]: f["served_from"] for f in st["files"]}["ontology"] == "data_out"

    # once the legacy board has its own directory, data/out is no longer consulted
    (dirs["boards"] / BOARD / "out").mkdir(parents=True)
    r = client.get(f"/api/boards/{BOARD}/ontology")
    assert r.status_code == 404 and r.json()["state"] == "no_data_yet"
    assert client.get(f"/api/boards/{BOARD}/status").json()["legacy_fallback"] is False


def test_plans_approve_uses_the_boards_own_people_and_files(client, dirs):
    make_board(client, "acme", "Acme Dental")
    add_people(client, "acme", [
        {"id": "pm-9", "name": "Ola", "role": "PM"},  # no skill of her own: gets the plan rule's PM skill
        {"id": "ops-9", "name": "Ben", "role": "Ops"},  # no rule for Ops: nothing offered
    ])
    (dirs["boards"] / "acme" / "out").mkdir(parents=True)
    write_json(dirs["boards"] / "acme" / "out" / "plans.json", plans_doc(board_id="acme"))
    r = client.post("/api/boards/acme/plans/plan-b/approve")
    assert r.status_code == 201 and len(r.json()["suggestions_created"]) == 1
    s = client.get("/api/people/pm-9/suggestions").json()[0]
    assert s["skill_id"] == "fill_deck_from_sheet" and s["board_id"] == "acme"
    assert client.get("/api/people/ops-9/suggestions").json() == []
    # a board with no people, no records and no plans file gets no demo suggestion (that is northwind-only)
    make_board(client, "empty", "Empty Co")
    r = client.post("/api/boards/empty/plans/plan-b/approve")
    assert r.status_code == 201 and r.json()["suggestions_created"] == []
    assert client.get("/api/people/pm-1/suggestions").json() == []


# ---------------------------------------------------------------- migration


def test_people_json_migrates_into_northwind_once(dirs, monkeypatch):
    legacy = {
        "board_id": BOARD,
        "people": [
            {"id": "pm-1", "name": "Dana Whitfield", "role": "PM", "target": "desk1", "skill_id": "fill_deck_from_sheet", "pre_approved": False, "inputs": {}},
            {"id": "fin-1", "name": "Marcus Reyes", "role": "Finance", "target": "desk2", "skill_id": "reconcile_quotes", "pre_approved": True, "inputs": {"proposal": 173}},
        ],
    }
    write_json(dirs["tmp"] / "people.json", legacy)
    import api.main

    with TestClient(api.main.create_app()) as c:
        assert c.app.state.migration == {"board_id": BOARD, "people": 2, "from": str(dirs["tmp"] / "people.json")}
        b = c.get(f"/api/boards/{BOARD}").json()
        assert b["name"] == "Northwind Fitness" and b["industry_naics"] == "713940" and b["mail_domain"] == "northwind.local"
        assert b["timezone"] == "America/Chicago" and b["people"] == 2
        fin = c.get(f"/api/boards/{BOARD}/people/fin-1").json()
        assert fin["pre_approved"] is True and fin["inputs"] == {"proposal": 173} and fin["target"] == "desk2"
        assert fin["invite_code"] and fin["claimed_at"] is None
        # people.json had no addresses: the demo mailboxes (executor/MAIL.md) are filled in so skills can mail by role
        assert fin["email"] == "finance@northwind.local"
        assert c.get(f"/api/boards/{BOARD}/people/pm-1").json()["email"] == "pm@northwind.local"
        # the fleet reads the migrated people
        assert [p["person"]["id"] for p in c.get(f"/api/boards/{BOARD}/fleet").json()["people"]] == ["pm-1", "fin-1"]
        c.delete(f"/api/boards/{BOARD}/people/fin-1")

    # second start: boards is not empty, so the file is not re-imported (the deletion sticks)
    with TestClient(api.main.create_app()) as c:
        assert c.app.state.migration is None
        assert [p["id"] for p in c.get(f"/api/boards/{BOARD}/people").json()] == ["pm-1"]


def test_no_people_json_no_migration(client):
    assert client.app.state.migration is None
    assert client.get("/api/boards").json() == []


# ---------------------------------------------------------------- records → fit


def test_records_export_and_fit_job_writes_board_files(client, dirs, signed_record, monkeypatch):
    make_board(client, BOARD, "Northwind Fitness")
    assert client.post(f"/api/boards/{BOARD}/records", json=signed_record).status_code == 201
    # a withdrawn record is not exported
    other = dict(signed_record)
    write_json(dirs["out"] / "records.jsonl", [])  # simulated records are never exported either

    r = client.get(f"/api/boards/{BOARD}/records/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(l) for l in r.text.splitlines()]
    assert [l["id"] for l in lines] == ["1106-0412"] and lines[0]["sig"] == signed_record["sig"]
    assert r.headers["x-record-count"] == "1"
    client.delete(f"/api/boards/{BOARD}/records/1106-0412")
    assert client.get(f"/api/boards/{BOARD}/records/export").text == ""
    client.post(f"/api/boards/{BOARD}/records", json=other)  # re-activate

    # a stand-in for `flowline1 fit`: reads the NDJSON, writes ontology.json into --out
    script = dirs["tmp"] / "fake_fit.py"
    script.write_text(
        "import json, sys, pathlib\n"
        "args = sys.argv[1:]\n"
        "rec, out, ind = args[args.index('--records')+1], args[args.index('--out')+1], args[args.index('--industry')+1]\n"
        "rows = [json.loads(l) for l in open(rec) if l.strip()]\n"
        "pathlib.Path(out).mkdir(parents=True, exist_ok=True)\n"
        "doc = " + json.dumps({**ONTOLOGY, "board_id": BOARD}) + "\n"
        "doc['records_used'] = len(rows); doc['headline'] = f'fit {len(rows)} records for naics {ind}'\n"
        "json.dump(doc, open(pathlib.Path(out) / 'ontology.json', 'w'))\n"
        "print('ok')\n"
    )
    monkeypatch.setenv("FLOWLINE_FIT_CMD", f"{sys.executable} {script} --records {{records}} --out {{out}} --industry {{industry}}")

    r = client.post(f"/api/boards/{BOARD}/recompute")
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["state"] == "running" and job["records_exported"] == 1 and job["industry"] == "713940"
    assert job["out"] == str(dirs["boards"] / BOARD / "out")
    assert client.get(f"/api/boards/{BOARD}/status").json()["recompute"]["job_id"] == job["job_id"]

    import api.recompute

    api.recompute.recompute.wait(job["job_id"], timeout=20)
    done = client.get(f"/api/boards/{BOARD}/recompute/{job['job_id']}").json()
    assert done["state"] == "done" and done["returncode"] == 0 and "ok" in done["tail"], done
    # the board now serves its own file (and legacy fallback is off since the directory exists)
    ont = client.get(f"/api/boards/{BOARD}/ontology").json()
    assert ont["headline"] == "fit 1 records for naics 713940" and ont["records_used"] == 1
    st = client.get(f"/api/boards/{BOARD}/status").json()
    assert st["legacy_fallback"] is False and {f["name"]: f["served_from"] for f in st["files"]}["ontology"] == "board"


def test_recompute_409_while_running(client, dirs, monkeypatch):
    make_board(client, "acme", "Acme")
    monkeypatch.setenv("FLOWLINE_FIT_CMD", f"{sys.executable} -c \"import time; time.sleep(2)\"")
    r = client.post("/api/boards/acme/recompute")
    assert r.status_code == 202
    assert client.post("/api/boards/acme/recompute").status_code == 409
    # another board is independent
    make_board(client, "blue", "Blue")
    assert client.post("/api/boards/blue/recompute").status_code == 202
