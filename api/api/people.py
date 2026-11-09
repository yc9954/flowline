"""The people of the fleet demo (data/people.json): who sits at which desk, which skill they get offered,
and whether they pre-approved it (SCHEMA §11 `pre_approved`). Missing file → empty list, and the API falls
back to the plan-rule → role → person mapping in routers/plans.py."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import ROOT


def people_path() -> Path:
    return Path(os.environ.get("FLOWLINE_PEOPLE", str(ROOT / "data" / "people.json"))).expanduser()


def fleet_enabled() -> bool:
    return os.environ.get("FLOWLINE_FLEET", "0").strip().lower() in ("1", "true", "yes", "on")


def skill_override() -> str | None:
    """FLOWLINE_FLEET_SKILL_OVERRIDE=fill_deck_from_sheet runs everyone on that skill (tests before the real skills land)."""
    v = os.environ.get("FLOWLINE_FLEET_SKILL_OVERRIDE", "").strip()
    return v or None


def effective_skill(skill_id: str) -> str:
    return skill_override() or skill_id


def load_people(board_id: str | None = None) -> list[dict[str, Any]]:
    p = people_path()
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    people = doc.get("people", doc) if isinstance(doc, dict) else doc
    if not isinstance(people, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in people:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        if board_id and doc.get("board_id") and isinstance(doc, dict) and doc["board_id"] != board_id:
            continue
        out.append(
            {
                "id": str(raw["id"]),
                "name": str(raw.get("name", raw["id"])),
                "role": str(raw.get("role", "")),
                "target": str(raw.get("target", "desk1")),
                "skill_id": str(raw.get("skill_id", "fill_deck_from_sheet")),
                "pre_approved": bool(raw.get("pre_approved", False)),
                "inputs": raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {},
            }
        )
    return out


def person_by_id(person_id: str, board_id: str | None = None) -> dict[str, Any] | None:
    return next((p for p in load_people(board_id) if p["id"] == person_id), None)
