"""The people of a board, from the DB (`people` table): who sits at which desk, which skill they get offered,
whether they pre-approved it (SCHEMA §11 `pre_approved`), and their mail address for the executor's skills.

`data/people.json` is legacy: on first start, if the `boards` table is empty and the file exists, it is migrated
into board `northwind` (see `migrate_legacy_people`) so nothing that works today breaks. Nothing reads it after that.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .config import LEGACY_BOARD, LEGACY_BOARD_META, LEGACY_EMAIL_LOGINS, settings
from .db import Database, IntegrityConflict

PERSON_KEYS = ("id", "name", "role", "email", "target", "skill_id", "pre_approved", "inputs")


def fleet_enabled() -> bool:
    return os.environ.get("FLOWLINE_FLEET", "0").strip().lower() in ("1", "true", "yes", "on")


def skill_override() -> str | None:
    """FLOWLINE_FLEET_SKILL_OVERRIDE=fill_deck_from_sheet runs everyone on that skill (tests before the real skills land)."""
    v = os.environ.get("FLOWLINE_FLEET_SKILL_OVERRIDE", "").strip()
    return v or None


def effective_skill(skill_id: str) -> str:
    return skill_override() or skill_id


def load_people(db: Database, board_id: str) -> list[dict[str, Any]]:
    """The board's people in the shape the fleet and plans code expects (never raises; no board → [])."""
    return [_public(p) for p in db.list_people(board_id)]


def person_by_id(db: Database, person_id: str, board_id: str | None = None) -> dict[str, Any] | None:
    p = db.get_person(board_id, person_id) if board_id else db.find_person(person_id)
    return None if p is None else _public(p)


def _public(p: dict[str, Any]) -> dict[str, Any]:
    out = {k: p.get(k) for k in PERSON_KEYS}
    out["target"] = out["target"] or "mac"
    out["pre_approved"] = bool(out["pre_approved"])
    out["inputs"] = out["inputs"] if isinstance(out["inputs"], dict) else {}
    return out


def board_block(db: Database, board_id: str) -> dict[str, Any]:
    """`board` field of the executor run request (SCHEMA §11): skills address mail by role from this.
    A board the DB does not know still gets a block (id only) so the executor never has to guess."""
    board = db.get_board(board_id)
    people = db.list_people(board_id)
    block: dict[str, Any] = {
        "id": board_id,
        "name": board["name"] if board else board_id,
        "mail_domain": board["mail_domain"] if board else None,
        "people": [{"id": p["id"], "role": p["role"], "email": p.get("email"), "name": p["name"]} for p in people],
    }
    if board_id == LEGACY_BOARD:
        block["mail_window_title"] = LEGACY_BOARD_META["mail_window_title"]
    return block


# ---------------------------------------------------------------- ids and slugs

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return s[:48] or "board"


def person_slug(name: str, role: str) -> str:
    base = slugify(name) or slugify(role) or "person"
    return base


# ---------------------------------------------------------------- legacy migration

def migrate_legacy_people(db: Database) -> dict[str, Any] | None:
    """If no board exists yet and data/people.json is there, create board `northwind` from it.
    Returns a summary, or None when nothing was migrated."""
    if not db.boards_empty():
        return None
    path = settings.people_json
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    people = doc.get("people", doc) if isinstance(doc, dict) else doc
    if not isinstance(people, list):
        return None
    board_id = (doc.get("board_id") if isinstance(doc, dict) else None) or LEGACY_BOARD
    meta = LEGACY_BOARD_META if board_id == LEGACY_BOARD else {"name": board_id}
    try:
        db.insert_board(
            board_id,
            meta.get("name", board_id),
            industry_naics=meta.get("industry_naics"),
            mail_domain=meta.get("mail_domain"),
            timezone_name=meta.get("timezone"),
        )
    except IntegrityConflict:
        pass
    domain = meta.get("mail_domain")
    n = 0
    for raw in people:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        pid = str(raw["id"])
        email = raw.get("email")
        if not email and domain and pid in LEGACY_EMAIL_LOGINS:
            email = f"{LEGACY_EMAIL_LOGINS[pid]}@{domain}"
        try:
            db.insert_person(
                board_id,
                {
                    "id": pid,
                    "name": str(raw.get("name", pid)),
                    "role": str(raw.get("role", "")),
                    "email": email,
                    "target": str(raw.get("target") or "mac"),
                    "skill_id": raw.get("skill_id"),
                    "pre_approved": bool(raw.get("pre_approved", False)),
                    "inputs": raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
                },
            )
            n += 1
        except IntegrityConflict:
            continue
    return {"board_id": board_id, "people": n, "from": str(path)}
