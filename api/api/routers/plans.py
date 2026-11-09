"""SCHEMA section 5: approve a plan -> record approval, create Suggestions for the
people the plan touches (section 11)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from ..db import Database, new_id, now_iso
from ..deps import get_db
from ..files import MissingFile, store
from ..models import ApproveRequest, Message, PlanApproval
from ..people import load_people

router = APIRouter(prefix="/api/boards/{board_id}/plans", tags=["plans"])

# Demo wiring: which person performs which skill. The plan's `rules` say which Role
# does a skill; records say which people hold that role. Until records exist we
# fall back to this map so the demo always produces the pm-1 suggestion.
DEMO_PEOPLE_BY_ROLE: dict[str, list[str]] = {"PM": ["pm-1"]}
DEFAULT_DEMO_SKILL = "fill_deck_from_sheet"
SKILL_COPY: dict[str, dict[str, Any]] = {
    "fill_deck_from_sheet": {
        "title": "Fill this deck's pricing from your sheet?",
        "estimate_s": 45,
        "default_count": 11,
        "default_minutes": 22,
    },
    "reconcile_quotes": {
        "title": "Reconcile this week's quotes into your pricing sheet?",
        "estimate_s": 90,
        "default_count": 6,
        "default_minutes": 35,
    },
    "signature_packet": {
        "title": "Get proposal #172 ready for signature?",
        "estimate_s": 90,
        "default_count": 8,
        "default_minutes": 25,
    },
    "proposal_packet": {
        "title": "Build the whole proposal packet from the quotes?",
        "estimate_s": 120,
        "default_count": 5,
        "default_minutes": 48,
    },
}


def _plan_from_file(plan_id: str) -> dict[str, Any] | None:
    try:
        doc = store.get("plans").data
    except MissingFile:
        return None
    for p in doc.get("plans", []) if isinstance(doc, dict) else []:
        if str(p.get("id")) == plan_id:
            return p
    return None


def _repeated_stats(skill_id: str, role: str) -> tuple[int, int]:
    """Count/week and minutes for the repeated task from finding.json, else the demo copy."""
    copy = SKILL_COPY.get(skill_id, {})
    count, minutes = copy.get("default_count", 10), copy.get("default_minutes", 20)
    try:
        finding = store.get("finding").data
    except MissingFile:
        return count, minutes
    for r in finding.get("repeated", []) if isinstance(finding, dict) else []:
        if r.get("who") == role and r.get("agent_can_do"):
            return int(r.get("count_per_wk", count)), int(r.get("minutes", minutes))
    return count, minutes


def _people_for_role(db: Database, board_id: str, role: str) -> list[str]:
    seen: list[str] = []
    for rec in db.list_records(board_id):
        if rec.get("role") == role and rec["person_id"] not in seen:
            seen.append(rec["person_id"])
    return seen or DEMO_PEOPLE_BY_ROLE.get(role, [])


def _humanize_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return f"{d.strftime('%b')} {d.day}"


def _suggestion_copy(skill_id: str, role: str, plan: dict[str, Any], approved_at: str) -> dict[str, Any]:
    count, minutes = _repeated_stats(skill_id, role)
    copy = SKILL_COPY.get(skill_id, {})
    title = copy.get("title", f"Let me do '{skill_id}' for you?")
    estimate_s = int(copy.get("estimate_s", 60))
    est_phrase = "under a minute" if estimate_s < 60 else f"about {round(estimate_s / 60)} minute{'s' if estimate_s >= 90 else ''}"
    body = (
        f"You did this {count} times last week, about {minutes} minutes each. "
        f"I'd take {est_phrase}, and nothing is saved until you check it."
    )
    return {
        "skill_id": skill_id,
        "title": title,
        "body": body,
        "why_now": f'your team approved "{plan.get("name", plan.get("id"))}" on {_humanize_date(approved_at)}',
        "count_last_week": count,
        "minutes_each": minutes,
        "estimate_s": estimate_s,
        "plan_id": str(plan["id"]),
        "status": "offered",
        "created_at": approved_at,
    }


def _offer(db: Database, board_id: str, person_id: str, skill_id: str, base: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if db.is_suppressed(person_id, skill_id):
        return None
    if any(s["skill_id"] == skill_id for s in db.list_suggestions(person_id)):
        return None  # already offered and unanswered
    s = {"id": new_id("sug"), "person_id": person_id, **base, **(extra or {})}
    db.insert_suggestion(board_id, s)
    return s


def build_suggestions(db: Database, board_id: str, plan: dict[str, Any], approved_at: str) -> list[dict[str, Any]]:
    """One Suggestion per person.

    With data/people.json (the fleet): every person listed gets the skill they hold, titled per skill, on the same
    plan — pm-1 included, so the Mac app path is unchanged. Without it: one Suggestion per (person, skill) that a
    `skill` rule in the plan touches (people who hold the rule's actor role in the board's records, demo map
    PM → pm-1). Skips people who said dont_ask for that skill, and people who already have one offered."""
    out: list[dict[str, Any]] = []
    people = load_people(board_id)
    if people:
        for p in people:
            base = _suggestion_copy(p["skill_id"], p["role"], plan, approved_at)
            s = _offer(db, board_id, p["id"], p["skill_id"], base, {"target": p["target"], "role": p["role"], "name": p["name"]})
            if s is not None:
                out.append(s)
        return out

    skills: list[tuple[str, str]] = []  # (skill_id, actor role)
    for rule in plan.get("rules", []):
        if isinstance(rule, dict) and rule.get("type") == "skill" and rule.get("skill_id"):
            skills.append((str(rule["skill_id"]), str(rule.get("actor", "PM"))))
    if not skills:
        # Demo guarantee: a plan with no explicit skill rule still offers the PM skill.
        skills.append((DEFAULT_DEMO_SKILL, "PM"))
    for skill_id, role in skills:
        base = _suggestion_copy(skill_id, role, plan, approved_at)
        for person_id in _people_for_role(db, board_id, role):
            s = _offer(db, board_id, person_id, skill_id, base)
            if s is not None:
                out.append(s)
    return out


@router.post("/{plan_id}/approve", response_model=PlanApproval, status_code=201, responses={404: {"model": Message}})
def approve_plan(
    board_id: str,
    plan_id: str,
    body: ApproveRequest | None = Body(default=None),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    plan = _plan_from_file(plan_id)
    if plan is None:
        # Plans file may be missing while flowline1/board are still building. Accept the
        # approval anyway so the demo loop works, but say the plan was not found in the file.
        plan = {"id": plan_id, "name": plan_id, "rules": [], "_not_in_plans_file": True}
    approved_at = now_iso()
    created = build_suggestions(db, board_id, plan, approved_at)
    row = db.insert_approval(board_id, plan, body.approved_by if body else None, [s["id"] for s in created])
    row["approved_at"] = approved_at
    if plan.get("_not_in_plans_file"):
        row["note"] = f"plan '{plan_id}' was not found in plans.json; approval recorded with the id only"
    return row


@router.get("/approvals", response_model=list[PlanApproval])
def list_approvals(board_id: str, db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return db.list_approvals(board_id)
