"""The fleet: a board's people, their desks, one plan (SCHEMA §11 + the DB `people` table).

  GET  /api/boards/{board}/fleet         people with their latest suggestion and run, counters, event feed
  POST /api/boards/{board}/fleet/reset   stop the board's running runs, clear its suggestions and cached runs (re-take)
  GET  /api/desk/{target}/frame.jpg?w=   live JPEG of a desk, streamed from the executor (Cache-Control: no-store)

Fan-out (`fan_out`, called by suggestions.respond on do_it and by runs.start_run): when FLOWLINE_FLEET=1, every
person of the board with `pre_approved: true` and a still-offered suggestion gets their run started on their own
desk and the suggestion marked accepted with `pre_approved: true`. The person who answered keeps the normal path
(the Mac app POSTs /api/runs itself). Every run request carries the board block (id, name, mail_domain, people).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import Database
from ..deps import get_db
from ..people import board_block, effective_skill, fleet_enabled, load_people, skill_override
from .runs import _forward

router = APIRouter(prefix="/api", tags=["fleet"])

FINAL = ("done", "stopped", "failed")
AGENT_LABEL = "Vercel AI SDK ToolLoopAgent"
_frame_client: httpx.AsyncClient | None = None


def _model() -> str:
    return os.environ.get("FLOWLINE_MODEL", "claude-sonnet-5-5")


# ---------------------------------------------------------------- starting runs

async def start_person_run(
    db: Database, sug: dict[str, Any], person: dict[str, Any], *, pre_approved: bool, board: dict[str, Any] | None = None
) -> dict[str, Any]:
    """POST the run for one person's suggestion to the executor and record it. Never raises: errors come back as {error}."""
    body = {
        "suggestion_id": sug["id"],
        "skill_id": effective_skill(sug["skill_id"]),
        "target": person["target"],
        "person_id": person["id"],
        "inputs": dict(person.get("inputs") or {}),
        "board": board if board is not None else board_block(db, sug["board_id"]),
    }
    try:
        run = await _forward("POST", "/runs", body)
    except HTTPException as exc:
        return {"person_id": person["id"], "error": exc.detail, "status_code": exc.status_code}
    if not isinstance(run, dict) or not run.get("id"):
        return {"person_id": person["id"], "error": "executor returned no run id"}
    if sug["status"] == "offered":
        db.tally(person["id"], sug["skill_id"], accepted=1)
    db.set_suggestion_status(sug["id"], "accepted", run_id=run["id"])
    if pre_approved:
        db.set_suggestion_body(sug["id"], {"pre_approved": True})
    db.upsert_run(run, suggestion_id=sug["id"])
    if run.get("status") == "done":
        db.mark_suggestion_done_by_run(run["id"])
    return {"person_id": person["id"], "run_id": run["id"], "target": person["target"], "status": run.get("status")}


async def fan_out(db: Database, board_id: str, *, except_person: str | None = None) -> list[dict[str, Any]]:
    """Start the runs of every pre-approved person whose suggestion is still offered (idempotent)."""
    if not fleet_enabled():
        return []
    people = load_people(db, board_id)
    if not people:
        return []
    offered: dict[str, dict[str, Any]] = {}
    for s in db.list_board_suggestions(board_id):  # newest first → first seen per person wins
        if s["status"] == "offered" and s["person_id"] not in offered:
            offered[s["person_id"]] = s
    block = board_block(db, board_id)
    jobs = []
    for p in people:
        if not p["pre_approved"] or p["id"] == except_person:
            continue
        s = offered.get(p["id"])
        if s is not None:
            jobs.append(start_person_run(db, s, p, pre_approved=True, board=block))
    return list(await asyncio.gather(*jobs)) if jobs else []


# ---------------------------------------------------------------- reading state

async def _fetch_run(run_id: str) -> dict[str, Any] | None:
    try:
        return await _forward("GET", f"/runs/{run_id}?compact=1")
    except HTTPException:
        return None


async def _active_runs() -> dict[str, dict[str, Any]]:
    try:
        data = await _forward("GET", "/runs/active")
    except HTTPException:
        return {}
    return {r["id"]: r for r in data.get("runs", []) if isinstance(r, dict) and r.get("id")}


async def collect_runs(db: Database, run_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Latest Run per id: running ones from /runs/active, finished ones from the cache, the rest fetched once."""
    active = await _active_runs()
    out: dict[str, dict[str, Any]] = {}
    fetch: list[str] = []
    for rid in run_ids:
        if rid in active:
            out[rid] = active[rid]
            continue
        cached = db.get_run(rid)
        if cached and cached.get("status") in FINAL and "recent_actions" in cached:
            cached.pop("_suggestion_id", None)
            out[rid] = cached
        else:
            fetch.append(rid)
    if fetch:
        for rid, run in zip(fetch, await asyncio.gather(*(_fetch_run(r) for r in fetch))):
            if run is None:
                cached = db.get_run(rid)
                if cached:
                    cached.pop("_suggestion_id", None)
                    out[rid] = cached
                continue
            out[rid] = run
    for rid, run in out.items():
        if rid in active or rid in fetch:
            db.upsert_run(run)
            if run.get("status") == "done":
                db.mark_suggestion_done_by_run(rid)
    return out


def _state(sug: dict[str, Any] | None, run: dict[str, Any] | None) -> str:
    """waiting · running · left_for_you · stopped · failed"""
    if run is not None:
        st = run.get("status")
        return {"running": "running", "done": "left_for_you", "stopped": "stopped", "failed": "failed"}.get(st, str(st))
    if sug is None:
        return "waiting"
    # declined / never = the person said not now: there is no run, so the desk simply waits
    return {"offered": "waiting", "accepted": "running", "done": "left_for_you"}.get(sug["status"], "waiting")


@router.get("/boards/{board_id}/fleet")
async def fleet(board_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    people = load_people(db, board_id)
    sugs = db.list_board_suggestions(board_id)
    latest: dict[str, dict[str, Any]] = {}
    for s in sugs:  # newest first
        latest.setdefault(s["person_id"], s)
    run_ids = [s["run_id"] for s in latest.values() if s.get("run_id")]
    runs = await collect_runs(db, run_ids)

    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    running = done = stopped = failed = actions = 0
    minutes = 0.0
    model = None
    for p in people:
        s = latest.get(p["id"])
        run = runs.get(s["run_id"]) if s and s.get("run_id") else None
        if run is not None:
            model = model or run.get("model")
            st = run.get("status")
            running += st == "running"
            done += st == "done"
            stopped += st == "stopped"
            failed += st == "failed"
            n = run.get("actions") if isinstance(run.get("actions"), int) else run.get("action_count", 0)
            actions += int(n or 0)
            minutes += float(run.get("elapsed_s") or 0) / 60.0
            for a in run.get("recent_actions") or []:
                events.append({"at": a.get("at"), "at_s": a.get("at_s"), "kind": a.get("kind"), "text": a.get("text"),
                               "person_id": p["id"], "name": p["name"], "role": p["role"], "target": p["target"]})
        rows.append({
            "person": {k: p.get(k) for k in ("id", "name", "role", "email", "target", "skill_id", "pre_approved")},
            "suggestion": None if s is None else {k: s.get(k) for k in ("id", "status", "title", "skill_id", "plan_id", "run_id", "pre_approved", "responded_at")},
            "run": run,
            "state": _state(s, run),
        })
    events.sort(key=lambda e: (e.get("at") or "", e.get("at_s") or 0), reverse=True)
    return {
        "board_id": board_id,
        "people": rows,
        "counters": {
            "running": running,
            "done": done,
            "failed": failed,
            "actions": actions,
            "actions_per_min": round(actions / minutes, 1) if minutes > 0 else 0.0,
            "saved_without_review": 0,
            "stopped_by_people": stopped,
        },
        "events": events[:30],
        "agent": f"{AGENT_LABEL} · {model or _model()}",
        "fleet_enabled": fleet_enabled(),
        "skill_override": skill_override(),
        "source": "measured",
    }


@router.post("/boards/{board_id}/fleet/reset")
async def fleet_reset(board_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    sugs = db.list_board_suggestions(board_id)
    run_ids = sorted({s["run_id"] for s in sugs if s.get("run_id")})
    stopped: list[str] = []
    for rid in run_ids:  # stop whatever is not known to be finished; the executor answers 404 for finished runs
        cached = db.get_run(rid)
        if cached and cached.get("status") in FINAL:
            continue
        try:
            await _forward("POST", f"/runs/{rid}/stop")
            stopped.append(rid)
        except HTTPException:
            pass
    if stopped:
        await asyncio.sleep(1.0)  # let the agents die before the desks are reused
    cleared = db.clear_board_fleet(board_id)
    return {"board_id": board_id, "stopped": stopped, **cleared}


# ---------------------------------------------------------------- live frames

@router.get("/desk/{target}/frame.jpg")
async def desk_frame(target: str, request: Request, w: int = 960):
    global _frame_client
    if not target.replace("desk", "").isdigit() and target != "mac":
        raise HTTPException(400, f"bad target {target!r}")
    if _frame_client is None:
        _frame_client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=2.0))
    url = f"{settings.executor_url}/desk/{target}/frame.jpg"
    try:
        req = _frame_client.build_request("GET", url, params={"w": w})
        resp = await _frame_client.send(req, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"executor at {settings.executor_url} is not reachable ({type(exc).__name__})")
    if resp.status_code >= 400:
        detail = (await resp.aread()).decode("utf-8", "replace")[:300]
        await resp.aclose()
        raise HTTPException(resp.status_code, {"executor": detail})
    headers = {"Cache-Control": "no-store", "X-Frame-Age": resp.headers.get("x-frame-age", ""), "X-Target": target}
    return StreamingResponse(resp.aiter_bytes(), media_type="image/jpeg", headers=headers, background=None)
