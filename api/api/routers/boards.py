"""Read endpoints for SCHEMA sections 3-11 (file-backed, per board), plus /status and /recompute.

Every file comes from data/boards/{board_id}/out/ (the legacy board `northwind` falls back to data/out and
fixtures/ while it has no directory of its own). A missing file is 404 with
{"detail", "state": "no_data_yet", "needs"} — never another board's data.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..config import settings
from ..db import Database
from ..deps import get_db
from ..files import store
from ..models import (
    BoardStatus,
    Expansion,
    Finding,
    History,
    Message,
    ModelCheck,
    NoData,
    Ontology,
    Opening,
    PlansPage,
    RecomputeJob,
    Results,
    Surfaces,
)
from ..recompute import recompute

router = APIRouter(prefix="/api/boards/{board_id}", tags=["board"])

NO_DATA = {404: {"model": NoData}}


def load(name: str, board_id: str) -> Any:
    """MissingFile propagates: main.create_app turns it into the flat 404 {detail, state: no_data_yet, needs}."""
    try:
        return store.get(name, board_id).data
    except ValueError as exc:  # json decode error
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"'{name}.json' for board '{board_id}' is not valid JSON: {exc}") from exc


def _with_board(doc: Any, board_id: str) -> Any:
    # Stamp the URL board id if the file lacks it (files inside data/boards/{id}/ are that board's by location).
    if isinstance(doc, dict) and "board_id" not in doc:
        doc = {"board_id": board_id, **doc}
    return doc


@router.get("/ontology", response_model=Ontology, responses=NO_DATA)
def ontology(board_id: str) -> Any:
    return _with_board(load("ontology", board_id), board_id)


@router.get("/finding", response_model=Finding, responses=NO_DATA)
def finding(board_id: str) -> Any:
    return _with_board(load("finding", board_id), board_id)


@router.get("/plans", response_model=PlansPage, responses=NO_DATA)
def plans(board_id: str) -> Any:
    return _with_board(load("plans", board_id), board_id)


@router.get("/results", response_model=Results, responses=NO_DATA)
def results(board_id: str) -> Any:
    return _with_board(load("results", board_id), board_id)


@router.get("/history", response_model=History, responses=NO_DATA)
def history(board_id: str) -> Any:
    return _with_board(load("history", board_id), board_id)


@router.get("/model", response_model=ModelCheck, responses=NO_DATA)
def model(board_id: str) -> Any:
    return _with_board(load("model", board_id), board_id)


@router.get("/expansion", response_model=Expansion, responses=NO_DATA)
def expansion(
    board_id: str,
    industry: str | None = Query(default=None, description="NAICS code, e.g. 713940"),
) -> Any:
    """The file may hold one Expansion or a per-industry set. Supported layouts:

    * a single Expansion object (``industry`` must then match or be omitted);
    * ``{"industries": [...], "by_industry": {"<naics>": Expansion, ...}, "default": "<naics>"}``;
    * a JSON list of Expansion objects, each with its own ``industry``.
    """
    doc = load("expansion", board_id)
    chosen = _select_industry(doc, industry)
    return _with_board(chosen, board_id)


def _select_industry(doc: Any, industry: str | None) -> Any:
    # Layout 3: list of Expansion objects.
    if isinstance(doc, list):
        if not doc:
            raise HTTPException(404, "expansion.json is an empty list")
        if industry is None:
            return doc[0]
        for item in doc:
            if str(item.get("industry")) == industry:
                return item
        known = [str(i.get("industry")) for i in doc]
        raise HTTPException(404, f"industry '{industry}' not in expansion.json; available: {', '.join(known)}")

    if not isinstance(doc, dict):
        raise HTTPException(502, "expansion.json must be an object or a list")

    # Layout 2: keyed set.
    by = doc.get("by_industry")
    if isinstance(by, dict) and by:
        key = industry or doc.get("default") or doc.get("industry") or next(iter(by))
        if key not in by:
            raise HTTPException(404, f"industry '{key}' not in expansion.json; available: {', '.join(by)}")
        chosen = dict(by[key])
        # Carry shared fields (industries list, city, source...) down if the entry lacks them.
        for k, v in doc.items():
            if k not in ("by_industry", "default") and k not in chosen:
                chosen[k] = v
        chosen.setdefault("industry", key)
        return chosen

    # Layout 1: single object.
    if industry is not None and str(doc.get("industry")) != industry:
        listed = [i.get("naics") for i in doc.get("industries", []) if isinstance(i, dict)]
        if industry in listed:
            # The file lists the industry but only computed one. Say so instead of lying.
            raise HTTPException(
                404,
                f"expansion.json lists industry '{industry}' but only contains numbers for '{doc.get('industry')}'; "
                f"ask flowline1 to emit a by_industry map",
            )
        raise HTTPException(404, f"industry '{industry}' not in expansion.json; available: {doc.get('industry')}")
    return doc


@router.get("/opening", response_model=Opening, responses=NO_DATA)
def opening(board_id: str) -> Any:
    return _with_board(load("opening", board_id), board_id)


@router.get("/surfaces", response_model=Surfaces, responses=NO_DATA)
def surfaces(board_id: str) -> Any:
    return load("surfaces", board_id)


# ---------------------------------------------------------------- status


@router.get("/status", response_model=BoardStatus)
def board_status(board_id: str, request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    return {
        "board_id": board_id,
        "board": db.get_board(board_id),
        "data_dir": str(store.board_out(board_id)),
        "legacy_fallback": store.legacy_fallback(board_id),
        "data_out": str(settings.data_out),
        "fixtures": str(settings.fixtures),
        "files": store.status(board_id),
        "people": db.count_people(board_id),
        "records": db.count_records(board_id),
        "has_data": store.has_data(board_id),
        "recompute": recompute.latest(board_id),
        "executor_url": settings.executor_url,
        "board_dist_served": bool(getattr(request.app.state, "board_dist_served", False)),
    }


# ---------------------------------------------------------------- records → fit


def export_records_ndjson(db: Database, board_id: str) -> tuple[str, int]:
    """NDJSON of the board's approved, non-withdrawn (posted, signed) records — the input of `flowline1 fit`."""
    rows = db.list_records(board_id)
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    return text, len(rows)


@router.post(
    "/recompute",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RecomputeJob,
    responses={409: {"model": Message}},
)
def start_recompute(board_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    """Export the records, then run `flowline1 fit` in the background. 202 with the job; poll /recompute/{job_id}."""
    if recompute.running(board_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"a fit is already running for board '{board_id}'; see /status")
    board = db.get_board(board_id)
    board_dir = settings.board_dir(board_id)
    board_dir.mkdir(parents=True, exist_ok=True)
    text, n = export_records_ndjson(db, board_id)
    records_path = board_dir / "records.ndjson"
    records_path.write_text(text, encoding="utf-8")
    job = recompute.start(
        board_id,
        records_path,
        settings.board_out(board_id),
        industry=board["industry_naics"] if board else None,
        records_exported=n,
    )
    if job is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"a fit is already running for board '{board_id}'; see /status")
    return job


@router.get("/recompute/{job_id}", response_model=RecomputeJob, responses={404: {"model": Message}})
def get_recompute(board_id: str, job_id: str) -> dict[str, Any]:
    job = recompute.job(job_id)
    if job is None or job["board_id"] != board_id:
        raise HTTPException(404, f"no fit job '{job_id}' for board '{board_id}' (jobs are kept in memory until restart)")
    return job
