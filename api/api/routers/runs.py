"""SCHEMA section 11: proxy to the executor (port 8790). The board never talks to
the executor directly; the API caches the last Run it saw and marks the suggestion
done when the run reaches status done."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..config import settings
from ..db import Database
from ..deps import get_db
from ..models import Message, Run, RunRequest
from ..people import effective_skill, person_by_id

router = APIRouter(prefix="/api/runs", tags=["runs"])

TIMEOUT = httpx.Timeout(90.0, connect=2.0)


def _executor_down(exc: Exception) -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        f"executor at {settings.executor_url} is not reachable ({type(exc).__name__}); "
        f"start it with `uv run uvicorn executor.main:app --port 8790`",
    )


async def _forward(method: str, path: str, json: Any = None) -> Any:
    url = f"{settings.executor_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        raise _executor_down(exc)
    if resp.status_code >= 400:
        detail: Any
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise HTTPException(resp.status_code, {"executor": detail})
    try:
        return resp.json()
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"executor returned non-JSON from {path}") from exc


def _record_run(db: Database, run: dict[str, Any], suggestion_id: str | None = None) -> dict[str, Any]:
    if isinstance(run, dict) and run.get("id"):
        db.upsert_run(run, suggestion_id=suggestion_id)
        if run.get("status") == "done":
            db.mark_suggestion_done_by_run(run["id"])
    return run


@router.post("", response_model=Run, status_code=201, responses={503: {"model": Message}})
async def start_run(body: RunRequest, db: Database = Depends(get_db)) -> Any:
    sug = db.get_suggestion(body.suggestion_id)
    if sug is None:
        raise HTTPException(404, f"suggestion '{body.suggestion_id}' not found")
    if sug["status"] == "never":
        raise HTTPException(409, "this person asked not to be offered this skill again")
    payload = body.model_dump()
    payload["skill_id"] = effective_skill(payload.get("skill_id") or sug["skill_id"])
    payload.setdefault("person_id", sug["person_id"])
    person = person_by_id(sug["person_id"])
    if person and not payload.get("inputs"):
        payload["inputs"] = dict(person.get("inputs") or {})
    run = await _forward("POST", "/runs", payload)
    if isinstance(run, dict) and run.get("id"):
        if sug["status"] == "offered":
            db.tally(sug["person_id"], sug["skill_id"], accepted=1)
        db.set_suggestion_status(sug["id"], "accepted", run_id=run["id"])
    out = _record_run(db, run, body.suggestion_id)
    from .fleet import fan_out  # FLOWLINE_FLEET=1: the colleagues who pre-approved start now too (idempotent)
    board_id = _board_of(db, sug["id"])
    started = await fan_out(db, board_id, except_person=sug["person_id"])
    if started and isinstance(out, dict):
        out["fleet_started"] = started
    return out


def _board_of(db: Database, sid: str) -> str:
    with db.connect() as con:
        r = con.execute("SELECT board_id FROM suggestions WHERE id=?", (sid,)).fetchone()
    return r["board_id"] if r else "northwind"


@router.get("/{run_id}", response_model=Run, responses={503: {"model": Message}})
async def get_run(run_id: str, db: Database = Depends(get_db)) -> Any:
    try:
        run = await _forward("GET", f"/runs/{run_id}")
    except HTTPException as exc:
        if exc.status_code == 503:
            cached = db.get_run(run_id)
            if cached is not None:
                cached.pop("_suggestion_id", None)
                cached["_cached"] = True
                return cached
        raise
    return _record_run(db, run)


@router.post("/{run_id}/stop", response_model=Run, responses={503: {"model": Message}})
async def stop_run(run_id: str, db: Database = Depends(get_db)) -> Any:
    run = await _forward("POST", f"/runs/{run_id}/stop")
    return _record_run(db, run)
