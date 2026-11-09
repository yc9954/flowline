"""SCHEMA section 2 + 12: signed record ingest, list, withdraw."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError

from ..canonical import RecordVerifyError, verify_record
from ..db import Database
from ..deps import get_db
from ..files import store
from ..models import Message, Record, RecordAccepted

router = APIRouter(prefix="/api/boards/{board_id}/records", tags=["records"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=RecordAccepted,
    responses={400: {"model": Message}, 409: {"model": Message}},
)
async def ingest_record(board_id: str, request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(400, f"body is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(400, "body must be a JSON object (a Record)")

    # 1. Verify the signature over the exact bytes the client sent (before any
    #    model coercion could change a value and therefore the hash).
    try:
        verify_record(raw)
    except RecordVerifyError as exc:
        raise HTTPException(400, f"record rejected: {exc}") from exc

    # 2. Then validate the shape.
    try:
        rec = Record.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(400, f"record rejected: shape invalid: {exc.errors()[0]['msg']} at {exc.errors()[0]['loc']}") from exc

    if rec.board_id != board_id:
        raise HTTPException(400, f"record rejected: record.board_id '{rec.board_id}' does not match URL board '{board_id}'")

    if not db.insert_record(board_id, raw):
        raise HTTPException(409, f"record '{rec.id}' already exists for board '{board_id}' with a different hash")
    return {"id": rec.id, "accepted": True}


@router.get("", response_model=list[Record])
def list_records(
    board_id: str,
    person_id: str | None = Query(default=None),
    withdrawn: bool = Query(default=False, description="include withdrawn records"),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Posted (signed, source="measured") records first, then the model's simulated team
    from data/out/records.jsonl (source="simulated"); each group newest first."""
    posted = db.list_records(board_id, person_id=person_id, include_withdrawn=withdrawn)
    for r in posted:
        r["source"] = "measured"
    simulated = store.simulated_records(board_id)
    if person_id:
        simulated = [r for r in simulated if r.get("person_id") == person_id]
    return sorted(posted, key=_newest, reverse=True) + sorted(simulated, key=_newest, reverse=True)


def _newest(r: dict[str, Any]) -> tuple[str, str, str]:
    return (str(r.get("approved_at") or ""), str(r.get("date") or ""), str(r.get("id") or ""))


@router.get("/{rid}", response_model=Record, responses={404: {"model": Message}})
def get_record(board_id: str, rid: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    rec = db.get_record(board_id, rid)
    if rec is not None:
        rec["source"] = "measured"
        return rec
    for sim in store.simulated_records(board_id):
        if sim.get("id") == rid:
            return sim
    raise HTTPException(404, f"record '{rid}' not found on board '{board_id}'")


@router.delete("/{rid}", responses={404: {"model": Message}})
def withdraw_record(board_id: str, rid: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    """Withdraw: the record stays on the device; the board stops counting it."""
    if db.withdraw_record(board_id, rid):
        return {"id": rid, "withdrawn": True}
    if db.get_record(board_id, rid) is not None:
        return {"id": rid, "withdrawn": True, "note": "already withdrawn"}
    if any(s.get("id") == rid for s in store.simulated_records(board_id)):
        raise HTTPException(404, f"record '{rid}' is simulated (data/out/records.jsonl) and cannot be withdrawn")
    raise HTTPException(404, f"record '{rid}' not found on board '{board_id}'")
