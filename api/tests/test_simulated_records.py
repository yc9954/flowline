"""data/out/records.jsonl (the model's simulated team) is listed after posted records."""

from __future__ import annotations

import json
import os
import time

from tests.conftest import BOARD, make_record


def _sim(i: int, **over):
    r = make_record(id=f"sim-{i:03d}", person_id=f"trainer-{i}", role="Trainer",
                    approved_at=f"2026-11-0{i}T18:00:00-06:00", date=f"2026-11-0{i}")
    r.update(hash="", pubkey="", sig="", source="simulated")
    r.update(over)
    return r


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_simulated_records_listed_after_posted(client, dirs, signed_record):
    path = dirs["out"] / "records.jsonl"
    _write_jsonl(path, [_sim(1), _sim(3), _sim(2), _sim(4, board_id="other-board")])
    assert client.post(f"/api/boards/{BOARD}/records", json=signed_record).status_code == 201

    rows = client.get(f"/api/boards/{BOARD}/records").json()
    assert [r["id"] for r in rows] == ["1106-0412", "sim-003", "sim-002", "sim-001"]  # posted first, then newest first
    assert rows[0]["source"] == "measured" and rows[0]["sig"] == signed_record["sig"]
    assert {r["source"] for r in rows[1:]} == {"simulated"}
    assert rows[1]["pubkey"] == "" and rows[1]["sig"] == ""

    # person filter applies to both groups
    assert [r["id"] for r in client.get(f"/api/boards/{BOARD}/records?person_id=trainer-2").json()] == ["sim-002"]

    # detail works for both; withdraw only for posted
    assert client.get(f"/api/boards/{BOARD}/records/sim-002").json()["source"] == "simulated"
    assert client.get(f"/api/boards/{BOARD}/records/1106-0412").json()["source"] == "measured"
    r = client.delete(f"/api/boards/{BOARD}/records/sim-002")
    assert r.status_code == 404 and "simulated" in r.json()["detail"]
    assert client.delete(f"/api/boards/{BOARD}/records/1106-0412").status_code == 200
    assert [r["id"] for r in client.get(f"/api/boards/{BOARD}/records").json()] == ["sim-003", "sim-002", "sim-001"]

    # mtime change re-reads the file without restart (blank and broken lines are skipped)
    with path.open("a") as fh:
        fh.write("\n{not json\n" + json.dumps(_sim(5)) + "\n")
    future = time.time() + 5
    os.utime(path, (future, future))
    ids = [r["id"] for r in client.get(f"/api/boards/{BOARD}/records").json()]
    assert ids == ["sim-005", "sim-003", "sim-002", "sim-001"]

    # no file -> only posted
    path.unlink()
    assert client.get(f"/api/boards/{BOARD}/records").json() == []
