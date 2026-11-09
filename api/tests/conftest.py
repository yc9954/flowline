"""Every test gets its own temp data_out / fixtures / sqlite via env vars, so the
suite never depends on what the other agents have written."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from api.canonical import sign_record

BOARD = "northwind"


@pytest.fixture()
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    out = tmp_path / "out"
    fx = tmp_path / "fixtures"
    out.mkdir()
    fx.mkdir()
    monkeypatch.setenv("FLOWLINE_DATA_OUT", str(out))
    monkeypatch.setenv("FLOWLINE_BOARDS_DIR", str(tmp_path / "boards"))  # per-board dirs; absent unless a test writes one
    monkeypatch.setenv("FLOWLINE_FIXTURES", str(fx))
    monkeypatch.setenv("FLOWLINE_DB", str(tmp_path / "api.sqlite"))
    monkeypatch.setenv("FLOWLINE_MODEL_DIR", str(tmp_path / "no-flowline1"))
    monkeypatch.setenv("FLOWLINE_BOARD_DIST", str(tmp_path / "no-dist"))
    monkeypatch.setenv("FLOWLINE_EXECUTOR_URL", "http://127.0.0.1:1")  # nothing listens here
    monkeypatch.setenv("FLOWLINE_PEOPLE", str(tmp_path / "people.json"))  # absent unless a test writes it
    monkeypatch.setenv("FLOWLINE_FLEET", "0")
    monkeypatch.delenv("FLOWLINE_FLEET_SKILL_OVERRIDE", raising=False)
    monkeypatch.delenv("FLOWLINE_FIT_CMD", raising=False)
    monkeypatch.delenv("FLOWLINE_PUBLIC_URL", raising=False)
    return {"out": out, "fixtures": fx, "tmp": tmp_path, "boards": tmp_path / "boards"}


@pytest.fixture()
def client(dirs: dict[str, Path]) -> TestClient:
    import api.files
    import api.main
    import api.recompute

    api.files.store.clear()  # fresh cache per test
    api.recompute.recompute.reset()
    app = api.main.create_app()
    with TestClient(app) as c:
        yield c


def make_board(client: TestClient, board_id: str = BOARD, name: str = "Northwind Fitness", **over: Any) -> dict[str, Any]:
    body = {"id": board_id, "name": name, "industry_naics": "713940", "mail_domain": f"{board_id}.local", **over}
    r = client.post("/api/boards", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def add_people(client: TestClient, board_id: str, people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in people:
        r = client.post(f"/api/boards/{board_id}/people", json=p)
        assert r.status_code == 201, r.text
        out.append(r.json())
    return out


@pytest.fixture()
def signing_key() -> SigningKey:
    return SigningKey.generate()


def make_record(**over: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": "1106-0412",
        "board_id": BOARD,
        "person_id": "pm-1",
        "role": "PM",
        "date": "2026-11-06",
        "covers": {"start": "2026-11-06T09:00:00-06:00", "end": "2026-11-06T17:30:00-06:00"},
        "steps": [
            {
                "idx": 0,
                "start": "2026-11-06T09:00:00-06:00",
                "end": "2026-11-06T09:40:00-06:00",
                "name": "Fill pricing into proposal deck",
                "kind": "hands_on",
                "case_id": "proposal #167",
                "tools": ["sheets", "slides"],
                "repeats": 3,
            },
            {
                "idx": 1,
                "start": "2026-11-06T09:40:00-06:00",
                "end": "2026-11-06T14:00:00-06:00",
                "name": "Waiting on Finance — rate card",
                "kind": "waiting",
                "case_id": "proposal #167",
                "tools": [],
                "waiting_on": "Finance",
            },
        ],
        "kept_private": 2,
        "hands_on_min": 40,
        "waiting_min": 260,
        "approved_at": "2026-11-06T17:35:12-06:00",
    }
    rec.update(over)
    return rec


@pytest.fixture()
def signed_record(signing_key: SigningKey) -> dict[str, Any]:
    return sign_record(make_record(), signing_key)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def plans_doc(**over: Any) -> dict[str, Any]:
    doc = {
        "board_id": BOARD,
        "reruns": 20,
        "weeks": 6,
        "headline": "Plan B saves 8.2 h per proposal",
        "today_h": 19.0,
        "source": "simulated",
        "note": "Same team, same luck, 20 reruns.",
        "plans": [
            {
                "id": "plan-b",
                "rank": 1,
                "name": "Auto-approve small quotes + fill deck from sheet",
                "sub": "Finance approves twice a day; PM's pricing filled by the agent",
                "hours": 10.8,
                "work_h": 4.1,
                "waiting_h": 6.7,
                "vs_today": -0.43,
                "best": True,
                "today": False,
                "held_best_n": 20,
                "range_h": [9.9, 11.6],
                "who": [{"role": "PM", "change": "deck pricing filled for you"}],
                "rules": [
                    {"type": "auto_approve_under", "usd": 5000},
                    {"type": "approver_batches_per_day", "n": 2},
                    {"type": "skill", "skill_id": "fill_deck_from_sheet", "actor": "PM", "reviewer": "Finance"},
                ],
            }
        ],
    }
    doc.update(over)
    return doc
