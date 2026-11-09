"""Runs proxy against a stub executor (SCHEMA section 11 Run shape)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

import pytest

from tests.conftest import BOARD, plans_doc, write_json


class _Stub(BaseHTTPRequestHandler):
    runs: dict[str, dict] = {}
    finish_after_polls = 1

    def log_message(self, *a):  # silence
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/runs":
            rid = f"run-{len(_Stub.runs) + 1}"
            run = {
                "id": rid, "skill_id": payload["skill_id"], "target": payload["target"], "status": "running",
                "started_at": "2026-11-09T10:00:00+00:00", "elapsed_s": 0,
                "steps": [{"n": 1, "label": "READ THE SHEET", "detail": "", "status": "now"}], "checks": [],
                "_polls": 0,
            }
            _Stub.runs[rid] = run
            return self._send(201, {k: v for k, v in run.items() if not k.startswith("_")})
        if self.path.endswith("/stop"):
            rid = self.path.split("/")[2]
            run = _Stub.runs.get(rid)
            if run is None:
                return self._send(404, {"detail": "no such run"})
            run["status"] = "stopped"
            return self._send(200, {k: v for k, v in run.items() if not k.startswith("_")})
        self._send(404, {"detail": "nope"})

    def do_GET(self):
        rid = self.path.split("/")[-1]
        run = _Stub.runs.get(rid)
        if run is None:
            return self._send(404, {"detail": "no such run"})
        run["_polls"] += 1
        if run["status"] == "running" and run["_polls"] >= _Stub.finish_after_polls:
            run["status"] = "done"
            run["steps"][0]["status"] = "done"
            run["checks"] = [{"name": "numbers match sheet", "ok": True, "detail": "12/12"}]
        self._send(200, {k: v for k, v in run.items() if not k.startswith("_")})


@pytest.fixture()
def executor(monkeypatch):
    _Stub.runs = {}
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("FLOWLINE_EXECUTOR_URL", f"http://127.0.0.1:{srv.server_port}")
    yield srv
    srv.shutdown()


def test_run_lifecycle_marks_suggestion_done(dirs, executor, client):
    write_json(dirs["fixtures"] / "plans.json", plans_doc())
    sid = client.post(f"/api/boards/{BOARD}/plans/plan-b/approve").json()["suggestions_created"][0]

    r = client.post("/api/runs", json={
        "suggestion_id": sid, "skill_id": "fill_deck_from_sheet", "target": "mac",
        "inputs": {"sheet": "Pricing Q4", "deck": "Northwind proposal", "slide": 7},
    })
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "running" and run["id"] == "run-1"

    s = client.get(f"/api/suggestions/{sid}").json()
    assert s["status"] == "accepted" and s["run_id"] == "run-1"
    assert s["accept_rate"]["accepted"] == 1

    r = client.get("/api/runs/run-1")
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get(f"/api/suggestions/{sid}").json()["status"] == "done"

    # Unknown run id passes the executor's 404 through.
    assert client.get("/api/runs/run-9").status_code == 404


def test_stop_run(dirs, executor, client):
    _Stub.finish_after_polls = 99
    write_json(dirs["fixtures"] / "plans.json", plans_doc())
    sid = client.post(f"/api/boards/{BOARD}/plans/plan-b/approve").json()["suggestions_created"][0]
    client.post("/api/runs", json={"suggestion_id": sid, "skill_id": "fill_deck_from_sheet", "target": "mac", "inputs": {}})
    r = client.post("/api/runs/run-1/stop")
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    assert client.get(f"/api/suggestions/{sid}").json()["status"] == "accepted"
    _Stub.finish_after_polls = 1
