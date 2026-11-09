"""SCHEMA section 5: approve a plan -> record approval, create Suggestions for the
people the plan touches (section 11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends

from ..config import LEGACY_BOARD
from ..db import Database, new_id, now_iso
from ..deps import get_db
from ..files import MissingFile, store
from ..models import ApproveRequest, Message, PlanApproval
from ..people import load_people

router = APIRouter(prefix="/api/boards/{board_id}/plans", tags=["plans"])

# Demo wiring for the legacy board only: the plan's `rules` say which Role does a skill; records say which
# people hold that role. On `northwind` with neither people nor records we fall back to this map so the
# original demo always produces the pm-1 suggestion. Other boards get no suggestion they cannot address.
DEMO_PEOPLE_BY_ROLE: dict[str, list[str]] = {"PM": ["pm-1"]}
DEFAULT_DEMO_SKILL = "fill_deck_from_sheet"

# Offer copy per skill (what the notch asks). Titles are templates over the person's `inputs`: `{case}` is
# "proposal #<inputs.proposal>" when the person has one, else the generic `case_fallback`. No company text here.
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
        "title": "Get {case} ready for signature?",
        "case_fallback": "this proposal",
        "estimate_s": 90,
        "default_count": 8,
        "default_minutes": 25,
    },
    "proposal_packet": {
        "title": "Build the whole {case} packet from the quotes?",
        "case_fallback": "proposal",
        "estimate_s": 120,
        "default_count": 5,
        "default_minutes": 48,
    },
}


def skill_title(skill_id: str, inputs: dict[str, Any] | None = None) -> str:
    copy = SKILL_COPY.get(skill_id)
    if copy is None:
        return f"Let me do '{skill_id.replace('_', ' ')}' for you?"
    title = str(copy["title"])
    if "{case}" in title:
        n = (inputs or {}).get("proposal")
        case = f"proposal #{n}" if n not in (None, "") else str(copy.get("case_fallback", "this"))
        title = title.replace("{case}", case)
    return title


def _plan_from_file(board_id: str, plan_id: str) -> dict[str, Any] | None:
    try:
        doc = store.get("plans", board_id).data
    except MissingFile:
        return None
    for p in doc.get("plans", []) if isinstance(doc, dict) else []:
        if str(p.get("id")) == plan_id:
            return p
    return None


def _repeated_stats(board_id: str, skill_id: str, role: str) -> tuple[int, int]:
    """Count/week and minutes for the repeated task from the board's finding.json, else the skill copy defaults."""
    copy = SKILL_COPY.get(skill_id, {})
    count, minutes = copy.get("default_count", 10), copy.get("default_minutes", 20)
    try:
        finding = store.get("finding", board_id).data
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
    if seen or board_id != LEGACY_BOARD:
        return seen
    return DEMO_PEOPLE_BY_ROLE.get(role, [])


def _humanize_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return f"{d.strftime('%b')} {d.day}"


def _suggestion_copy(
    board_id: str, skill_id: str, role: str, plan: dict[str, Any], approved_at: str, inputs: dict[str, Any] | None = None
) -> dict[str, Any]:
    count, minutes = _repeated_stats(board_id, skill_id, role)
    copy = SKILL_COPY.get(skill_id, {})
    title = skill_title(skill_id, inputs)
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

    With people on the board (DB `people`): every person who holds a skill gets it, titled per skill from their
    inputs, on the same plan — the Mac app path is unchanged. People with a `skill_id` of null get the skill a
    `skill` rule in the plan assigns to their role, if any. Without people: one Suggestion per (person, skill) a
    `skill` rule touches (people who hold the rule's actor role in the board's records; on the legacy board also
    the demo map PM → pm-1). Skips people who said dont_ask for that skill, and people who already have one offered."""
    out: list[dict[str, Any]] = []
    rule_skills: list[tuple[str, str]] = []  # (skill_id, actor role)
    for rule in plan.get("rules", []):
        if isinstance(rule, dict) and rule.get("type") == "skill" and rule.get("skill_id"):
            rule_skills.append((str(rule["skill_id"]), str(rule.get("actor", "PM"))))

    people = load_people(db, board_id)
    if people:
        by_role = {role: skill for skill, role in reversed(rule_skills)}
        for p in people:
            skill_id = p.get("skill_id") or by_role.get(p["role"])
            if not skill_id:
                continue
            base = _suggestion_copy(board_id, skill_id, p["role"], plan, approved_at, p.get("inputs"))
            s = _offer(db, board_id, p["id"], skill_id, base, {"target": p["target"], "role": p["role"], "name": p["name"]})
            if s is not None:
                out.append(s)
        return out

    skills = list(rule_skills)
    if not skills and board_id == LEGACY_BOARD:
        # Demo guarantee on the original board: a plan with no explicit skill rule still offers the PM skill.
        skills.append((DEFAULT_DEMO_SKILL, "PM"))
    for skill_id, role in skills:
        base = _suggestion_copy(board_id, skill_id, role, plan, approved_at)
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
    plan = _plan_from_file(board_id, plan_id)
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
