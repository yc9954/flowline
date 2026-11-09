from __future__ import annotations

from tests.conftest import BOARD, plans_doc, write_json


def _approve(client, dirs, plan_id="plan-b"):
    write_json(dirs["fixtures"] / "plans.json", plans_doc())
    return client.post(f"/api/boards/{BOARD}/plans/{plan_id}/approve", json={"approved_by": "ceo-1"})


def test_plan_approve_creates_pm_suggestion(client, dirs):
    r = _approve(client, dirs)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan_id"] == "plan-b"
    assert body["plan_name"].startswith("Auto-approve")
    assert len(body["suggestions_created"]) == 1

    sugs = client.get("/api/people/pm-1/suggestions").json()
    assert len(sugs) == 1
    s = sugs[0]
    assert s["id"] == body["suggestions_created"][0]
    assert s["skill_id"] == "fill_deck_from_sheet"
    assert s["title"] == "Fill this deck's pricing from your sheet?"
    assert s["body"] == (
        "You did this 11 times last week, about 22 minutes each. "
        "I'd take under a minute, and nothing is saved until you check it."
    )
    assert s["why_now"].startswith('your team approved "Auto-approve small quotes + fill deck from sheet" on ')
    assert s["status"] == "offered"
    assert s["plan_id"] == "plan-b"
    assert s["count_last_week"] == 11 and s["minutes_each"] == 22
    assert s["accept_rate"] == {"alpha": 1.0, "beta": 1.0, "accepted": 0, "declined": 0, "mean": 0.5, "suppressed": False}

    # Approval is recorded.
    appr = client.get(f"/api/boards/{BOARD}/plans/approvals").json()
    assert len(appr) == 1 and appr[0]["approved_by"] == "ceo-1"


def test_body_uses_finding_repeated_stats(client, dirs):
    write_json(dirs["fixtures"] / "finding.json", {
        "board_id": BOARD, "process": "client proposals", "records": 1, "people": 1, "weeks": 1,
        "headline": "", "sub": "",
        "kpis": {"cycle_time_h": 19, "waiting_share": 0.7, "small_quotes_share": 0.6, "small_quotes_unchanged": 0.9,
                 "repeated_by_hand_h_per_wk": 4},
        "map": [], "to_scale": {"hands_on_h": 4, "waiting_h": 15}, "sent_back": [],
        "repeated": [{"task": "fill deck pricing", "who": "PM", "count_per_wk": 7, "minutes": 15, "agent_can_do": True}],
    })
    _approve(client, dirs)
    s = client.get("/api/people/pm-1/suggestions").json()[0]
    assert s["body"].startswith("You did this 7 times last week, about 15 minutes each.")


def test_second_approval_does_not_duplicate_open_offer(client, dirs):
    _approve(client, dirs)
    r = _approve(client, dirs)
    assert r.json()["suggestions_created"] == []
    assert len(client.get("/api/people/pm-1/suggestions").json()) == 1


def test_respond_do_it_and_not_now_update_tally(client, dirs):
    sid = _approve(client, dirs).json()["suggestions_created"][0]
    r = client.post(f"/api/suggestions/{sid}/respond", json={"answer": "do_it"})
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["accept_rate"]["accepted"] == 1 and r.json()["accept_rate"]["mean"] == round(2 / 3, 4)

    # Offered list is now empty; ?all=1 shows it.
    assert client.get("/api/people/pm-1/suggestions").json() == []
    assert len(client.get("/api/people/pm-1/suggestions?all=1").json()) == 1

    # Next approval offers again (not suppressed), and not_now declines it.
    sid2 = _approve(client, dirs).json()["suggestions_created"][0]
    r = client.post(f"/api/suggestions/{sid2}/respond", json={"answer": "not_now"})
    assert r.json()["status"] == "declined"
    assert r.json()["accept_rate"] == {"alpha": 2.0, "beta": 2.0, "accepted": 1, "declined": 1, "mean": 0.5, "suppressed": False}

    # Answering twice is a conflict.
    assert client.post(f"/api/suggestions/{sid2}/respond", json={"answer": "do_it"}).status_code == 409


def test_dont_ask_suppresses_future_suggestions(client, dirs):
    sid = _approve(client, dirs).json()["suggestions_created"][0]
    r = client.post(f"/api/suggestions/{sid}/respond", json={"answer": "dont_ask"})
    assert r.status_code == 200 and r.json()["status"] == "never"
    assert r.json()["accept_rate"]["suppressed"] is True

    r = _approve(client, dirs)
    assert r.status_code == 201
    assert r.json()["suggestions_created"] == []
    assert client.get("/api/people/pm-1/suggestions").json() == []
    everything = client.get("/api/people/pm-1/suggestions?all=1").json()
    assert [s["status"] for s in everything] == ["never"]


def test_approve_unknown_plan_still_records(client, dirs):
    # No plans.json at all: approval is still accepted (demo loop), with a note.
    r = client.post(f"/api/boards/{BOARD}/plans/plan-zz/approve")
    assert r.status_code == 201
    assert "not found in plans.json" in r.json()["note"]
    # Demo guarantee: pm-1 still gets the deck suggestion.
    assert len(client.get("/api/people/pm-1/suggestions").json()) == 1


def test_bad_answer_422(client, dirs):
    sid = _approve(client, dirs).json()["suggestions_created"][0]
    assert client.post(f"/api/suggestions/{sid}/respond", json={"answer": "maybe"}).status_code == 422
    assert client.post("/api/suggestions/nope/respond", json={"answer": "do_it"}).status_code == 404
