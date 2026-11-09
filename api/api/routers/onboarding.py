"""Onboarding: boards, their people, and invite codes (SCHEMA § Boards & people).

  POST   /api/boards                          create a board (id slugified from name when absent)
  GET    /api/boards                          list: board + people count, records count, has_data
  GET    /api/boards/{id}                     board + counts
  PATCH  /api/boards/{id}                     rename, set industry / mail_domain / timezone
  POST   /api/boards/{id}/people              add a person → Person with a fresh invite_code
  GET    /api/boards/{id}/people
  GET    /api/boards/{id}/people/{pid}
  PATCH  /api/boards/{id}/people/{pid}
  DELETE /api/boards/{id}/people/{pid}
  POST   /api/boards/{id}/people/{pid}/invite  issue a new code (old one stops working, claim cleared)
  POST   /api/invites/{code}/claim {device?}   the device learns who it is; 409 when the code was already claimed
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from ..config import settings
from ..db import Database, IntegrityConflict
from ..deps import get_db
from ..files import store
from ..models import (
    Board,
    BoardCreate,
    BoardDetail,
    BoardPatch,
    BoardSummary,
    ClaimRequest,
    ClaimResponse,
    Message,
    NoSuchBoard,
    Person,
    PersonCreate,
    PersonInvite,
    PersonPatch,
)
from ..people import person_slug, slugify

router = APIRouter(prefix="/api", tags=["onboarding"])

NO_BOARD = {404: {"model": NoSuchBoard}}


class BoardNotFound(Exception):
    """main.create_app turns this into 404 {detail, state: "no_such_board"}."""

    def __init__(self, board_id: str):
        self.board_id = board_id
        super().__init__(f"board '{board_id}' does not exist; create it with POST /api/boards")

    def detail(self) -> dict[str, str]:
        return {"detail": str(self), "state": "no_such_board"}


def _api_url(request: Request) -> str:
    return settings.public_url or str(request.base_url).rstrip("/")


def _summary(db: Database, board: dict[str, Any]) -> dict[str, Any]:
    bid = board["id"]
    return {
        **board,
        "people": db.count_people(bid),
        "records": db.count_records(bid),
        "has_data": store.has_data(bid),
    }


def require_board(db: Database, board_id: str) -> dict[str, Any]:
    board = db.get_board(board_id)
    if board is None:
        raise BoardNotFound(board_id)
    return board


# ---------------------------------------------------------------- boards


@router.post("/boards", response_model=Board, status_code=status.HTTP_201_CREATED, responses={409: {"model": Message}})
def create_board(body: BoardCreate, db: Database = Depends(get_db)) -> dict[str, Any]:
    board_id = slugify(body.id) if body.id else slugify(body.name)
    if not body.name.strip():
        raise HTTPException(422, "name must not be empty")
    try:
        return db.insert_board(
            board_id,
            body.name.strip(),
            industry_naics=body.industry_naics,
            mail_domain=(body.mail_domain or "").strip().lower() or None,
            timezone_name=body.timezone,
        )
    except IntegrityConflict as exc:
        raise HTTPException(409, f"{exc}; pass a different id") from exc


@router.get("/boards", response_model=list[BoardSummary])
def list_boards(db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return [_summary(db, b) for b in db.list_boards()]


@router.get("/boards/{board_id}", response_model=BoardDetail, responses=NO_BOARD)
def get_board(board_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    board = require_board(db, board_id)
    return {
        **_summary(db, board),
        "data_dir": str(store.board_out(board_id)),
        "legacy_fallback": store.legacy_fallback(board_id),
    }


@router.patch("/boards/{board_id}", response_model=Board, responses=NO_BOARD)
def patch_board(board_id: str, body: BoardPatch, db: Database = Depends(get_db)) -> dict[str, Any]:
    require_board(db, board_id)
    patch = body.model_dump(exclude_unset=True)
    if "mail_domain" in patch and patch["mail_domain"] is not None:
        patch["mail_domain"] = patch["mail_domain"].strip().lower() or None
    out = db.update_board(board_id, patch)
    assert out is not None
    return out


# ---------------------------------------------------------------- people


@router.post(
    "/boards/{board_id}/people",
    response_model=Person,
    status_code=status.HTTP_201_CREATED,
    responses={**NO_BOARD, 409: {"model": Message}},
)
def add_person(board_id: str, body: PersonCreate, db: Database = Depends(get_db)) -> dict[str, Any]:
    require_board(db, board_id)
    pid = slugify(body.id) if body.id else person_slug(body.name, body.role)
    if not body.name.strip() or not body.role.strip():
        raise HTTPException(422, "name and role must not be empty")
    person = {
        "id": pid,
        "name": body.name.strip(),
        "role": body.role.strip(),
        "email": (body.email or "").strip().lower() or None,
        "target": (body.target or "mac").strip() or "mac",
        "skill_id": body.skill_id,
        "pre_approved": body.pre_approved,
        "inputs": body.inputs or {},
    }
    try:
        return db.insert_person(board_id, person)
    except IntegrityConflict as exc:
        raise HTTPException(409, f"{exc}; pass a different id") from exc


@router.get("/boards/{board_id}/people", response_model=list[Person], responses=NO_BOARD)
def list_people(board_id: str, db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    require_board(db, board_id)
    return db.list_people(board_id)


@router.get("/boards/{board_id}/people/{pid}", response_model=Person, responses={404: {"model": Message}})
def get_person(board_id: str, pid: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    p = db.get_person(board_id, pid)
    if p is None:
        raise HTTPException(404, f"person '{pid}' not on board '{board_id}'")
    return p


@router.patch("/boards/{board_id}/people/{pid}", response_model=Person, responses={404: {"model": Message}})
def patch_person(board_id: str, pid: str, body: PersonPatch, db: Database = Depends(get_db)) -> dict[str, Any]:
    if db.get_person(board_id, pid) is None:
        raise HTTPException(404, f"person '{pid}' not on board '{board_id}'")
    patch = body.model_dump(exclude_unset=True)
    if "email" in patch and patch["email"] is not None:
        patch["email"] = patch["email"].strip().lower() or None
    if "target" in patch and not (patch["target"] or "").strip():
        patch["target"] = "mac"
    out = db.update_person(board_id, pid, patch)
    assert out is not None
    return out


@router.delete("/boards/{board_id}/people/{pid}", responses={404: {"model": Message}})
def delete_person(board_id: str, pid: str, db: Database = Depends(get_db)) -> dict[str, Any]:
    if not db.delete_person(board_id, pid):
        raise HTTPException(404, f"person '{pid}' not on board '{board_id}'")
    return {"board_id": board_id, "id": pid, "deleted": True}


@router.post("/boards/{board_id}/people/{pid}/invite", response_model=PersonInvite, responses={404: {"model": Message}})
def reissue_invite(board_id: str, pid: str, request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    p = db.reissue_invite(board_id, pid)
    if p is None:
        raise HTTPException(404, f"person '{pid}' not on board '{board_id}'")
    return {**p, "api_url": _api_url(request)}


# ---------------------------------------------------------------- invites


@router.post(
    "/invites/{code}/claim",
    response_model=ClaimResponse,
    responses={404: {"model": Message}, 409: {"model": Message}},
)
def claim_invite(
    code: str,
    request: Request,
    body: ClaimRequest | None = Body(default=None),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    code = code.strip().upper()
    existing = db.person_by_invite(code)
    if existing is None:
        raise HTTPException(404, "unknown invite code")
    if existing["claimed_at"] is not None:
        raise HTTPException(409, "this invite code was already claimed; ask for a new one (POST .../people/{pid}/invite)")
    p = db.claim_invite(code, body.device if body else None)
    if p is None:  # lost a race with another device
        raise HTTPException(409, "this invite code was already claimed; ask for a new one (POST .../people/{pid}/invite)")
    board = db.get_board(p["board_id"])
    return {
        "board_id": p["board_id"],
        "board_name": board["name"] if board else p["board_id"],
        "person_id": p["id"],
        "name": p["name"],
        "role": p["role"],
        "target": p["target"],
        "skill_id": p["skill_id"],
        "api_base_hint": _api_url(request),
    }
