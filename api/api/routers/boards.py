"""Read endpoints for SCHEMA sections 3-11 (file-backed), plus /status and /recompute."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..config import settings
from ..db import Database
from ..deps import get_db
from ..files import MissingFile, store
from ..models import (
    BoardStatus,
    Expansion,
    Finding,
    History,
    Message,
    ModelCheck,
    Ontology,
    Opening,
    PlansPage,
    Results,
    Surfaces,
)
from ..recompute import recompute

router = APIRouter(prefix="/api/boards/{board_id}", tags=["board"])


def load(name: str) -> Any:
    try:
        return store.get(name).data
    except MissingFile as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:  # json decode error
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"'{name}.json' is not valid JSON: {exc}") from exc


def _with_board(doc: Any, board_id: str) -> Any:
    # Files are per deployment (one board for the demo); stamp the URL board id if absent.
    if isinstance(doc, dict) and "board_id" not in doc:
        doc = {"board_id": board_id, **doc}
    return doc


@router.get("/ontology", response_model=Ontology, responses={404: {"model": Message}})
def ontology(board_id: str) -> Any:
    return _with_board(load("ontology"), board_id)


@router.get("/finding", response_model=Finding, responses={404: {"model": Message}})
def finding(board_id: str) -> Any:
    return _with_board(load("finding"), board_id)


@router.get("/plans", response_model=PlansPage, responses={404: {"model": Message}})
def plans(board_id: str) -> Any:
    return _with_board(load("plans"), board_id)


@router.get("/results", response_model=Results, responses={404: {"model": Message}})
def results(board_id: str) -> Any:
    return _with_board(load("results"), board_id)


@router.get("/history", response_model=History, responses={404: {"model": Message}})
def history(board_id: str) -> Any:
    return _with_board(load("history"), board_id)


@router.get("/model", response_model=ModelCheck, responses={404: {"model": Message}})
def model(board_id: str) -> Any:
    return _with_board(load("model"), board_id)


@router.get("/expansion", response_model=Expansion, responses={404: {"model": Message}})
def expansion(
    board_id: str,
    industry: str | None = Query(default=None, description="NAICS code, e.g. 713940"),
) -> Any:
    """The file may hold one Expansion or a per-industry set. Supported layouts:

    * a single Expansion object (``industry`` must then match or be omitted);
    * ``{"industries": [...], "by_industry": {"<naics>": Expansion, ...}, "default": "<naics>"}``;
    * a JSON list of Expansion objects, each with its own ``industry``.
    """
    doc = load("expansion")
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


@router.get("/opening", response_model=Opening, responses={404: {"model": Message}})
def opening(board_id: str) -> Any:
    return _with_board(load("opening"), board_id)


@router.get("/surfaces", response_model=Surfaces, responses={404: {"model": Message}})
def surfaces(board_id: str) -> Any:
    return load("surfaces")


@router.get("/status", response_model=BoardStatus)
def board_status(board_id: str, request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    return {
        "board_id": board_id,
        "data_out": str(settings.data_out),
        "fixtures": str(settings.fixtures),
        "files": store.status(),
        "records": db.count_records(board_id),
        "recompute": dict(recompute.state),
        "executor_url": settings.executor_url,
        "board_dist_served": bool(getattr(request.app.state, "board_dist_served", False)),
    }


@router.post(
    "/recompute",
    status_code=status.HTTP_202_ACCEPTED,
    responses={503: {"model": Message}, 409: {"model": Message}},
)
def start_recompute(board_id: str) -> dict[str, Any]:
    ok, why = recompute.available()
    if not ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"cannot recompute: {why}")
    if not recompute.start():
        raise HTTPException(status.HTTP_409_CONFLICT, "a recompute is already running; see /status")
    return {"board_id": board_id, "started": True, **recompute.state}
