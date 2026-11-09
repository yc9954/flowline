"""SCHEMA section 11: what the notch shows a person, and their answer."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import Database
from ..deps import get_db
from ..models import Message, RespondRequest, Suggestion

router = APIRouter(prefix="/api", tags=["suggestions"])


@router.get("/people/{person_id}/suggestions", response_model=list[Suggestion])
def list_suggestions(
    person_id: str,
    all: bool = Query(default=False, description="1 = every status, not only offered"),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    return db.list_suggestions(person_id, all_statuses=all)


@router.get("/suggestions/{sid}", response_model=Suggestion, responses={404: {"model": Message}})
def get_suggestion(sid: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    s = db.get_suggestion(sid)
    if s is None:
        raise HTTPException(404, f"suggestion '{sid}' not found")
    return s


@router.post("/suggestions/{sid}/respond", response_model=Suggestion, responses={404: {"model": Message}, 409: {"model": Message}})
async def respond(sid: str, body: RespondRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
    s = db.get_suggestion(sid)
    if s is None:
        raise HTTPException(404, f"suggestion '{sid}' not found")
    if s["status"] not in ("offered", "accepted"):
        raise HTTPException(409, f"suggestion '{sid}' is already '{s['status']}'")

    person, skill = s["person_id"], s["skill_id"]
    if body.answer == "do_it":
        db.set_suggestion_status(sid, "accepted")
        db.tally(person, skill, accepted=1)
    elif body.answer == "not_now":
        db.set_suggestion_status(sid, "declined")
        db.tally(person, skill, declined=1)
    else:  # dont_ask
        db.set_suggestion_status(sid, "never")
        db.tally(person, skill, declined=1, never=True)
        db.suppress_skill(person, skill)

    out = db.get_suggestion(sid)
    assert out is not None
    if body.answer == "do_it":
        # FLOWLINE_FLEET=1: the first yes also starts every pre-approved colleague's run on their own desk.
        # This person's own run is started by the app's POST /api/runs (unchanged path).
        from .fleet import fan_out
        started = await fan_out(db, out["board_id"], except_person=person)
        if started:
            out["fleet_started"] = started
    return out
