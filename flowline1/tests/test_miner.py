import math

from flowline1 import engine as E
from flowline1 import miner as M
from flowline1 import world as W


def _rec(person, role, date, steps):
    rs = []
    for i, (start, end, name, case) in enumerate(steps, 1):
        rs.append({"idx": i, "start": start, "end": end, "name": name, "kind": "hands_on", "case_id": case, "tools": ["docs"]})
    return {"id": f"{date[5:7]}{date[8:10]}-{person}", "board_id": "t", "person_id": person, "role": role, "date": date,
            "covers": {"start": steps[0][0], "end": steps[-1][1]}, "steps": rs, "kept_private": 0, "hands_on_min": 0,
            "waiting_min": 0, "approved_at": f"{date}T18:05:00-05:00", "hash": "", "pubkey": "", "sig": "", "source": "simulated"}


def test_tiny_graph_and_wait():
    # Monday 2026-10-05: Sales writes the brief 09:00-10:00; PM sends it on at 12:00-12:30 (2 h wait);
    # Tuesday: Sales does the brief again 09:00-09:30 (a back edge) then sends 10:00-10:06.
    recs = [
        _rec("s1", "Sales", "2026-10-05", [("2026-10-05T09:00:00-05:00", "2026-10-05T10:00:00-05:00", "Write brief", "proposal #1")]),
        _rec("p1", "PM", "2026-10-05", [("2026-10-05T12:00:00-05:00", "2026-10-05T12:30:00-05:00", "Estimate", "proposal #1")]),
        _rec("s1", "Sales", "2026-10-06", [("2026-10-06T09:00:00-05:00", "2026-10-06T09:30:00-05:00", "Brief draft", "proposal #1"),
                                           ("2026-10-06T10:00:00-05:00", "2026-10-06T10:06:00-05:00", "Send", "proposal #1")]),
    ]
    res = M.mine(recs)
    nodes = {}
    for n in res["ontology"]["nodes"]:
        key = "Write brief" if "brief" in n["name"].lower() else n["name"]
        nodes[key] = n
    assert set(nodes) == {"Write brief", "Estimate", "Send"}  # 'Brief draft' and 'Write brief' resolved into one node
    assert {nodes["Write brief"]["name"], *nodes["Write brief"]["aliases"]} == {"Write brief", "Brief draft"}
    edges = {(e["from"], e["to"], e["kind"]): e for e in res["ontology"]["edges"]}
    brief, est, send = nodes["Write brief"]["id"], nodes["Estimate"]["id"], nodes["Send"]["id"]
    assert (brief, est, "then") in edges
    assert (est, brief, "back") in edges
    assert (brief, send, "then") in edges
    # the wait before Estimate is 2 h (10:00 -> 12:00, inside working hours)
    assert math.isclose(edges[(brief, est, "then")]["wait_h"], 2.0, abs_tol=0.05)
    assert math.isclose(nodes["Estimate"]["wait_before_h"], 2.0, abs_tol=0.05)
    # Estimate ended 12:30, the Tuesday redo started 09:00 next day: 20.5 h on the Mon-Fri calendar, owned by the back edge
    assert math.isclose(edges[(est, brief, "back")]["wait_h"], 20.5, abs_tol=0.1)
    assert res["finding"]["kpis"]["cycle_time_h"] == 25.1  # 09:00 Mon -> 10:06 Tue


def test_normalise_and_similarity():
    assert M.normalise("Quote calc") == M.normalise("Estimate")
    assert M.normalise("Approval $4,400 — missing figures") == M.normalise("Approve quote $12,000")
    assert M.similarity(M.normalise("Fill pricing"), M.normalise("Estimate")) < 0.8
    assert M.similarity(M.normalise("Check availability"), M.normalise("Margin check")) < 0.8
    assert M.similarity(M.normalise("Concept & deck"), M.normalise("Deck concept")) >= 0.8


def test_entity_resolution_on_planted_synonyms():
    run = W.run_world(3, 4, [])
    recs, key = W.build_records(run, 4, 3)
    res = M.mine(recs)
    ev = M.er_eval(res["resolver"], key)
    assert ev["precision"] >= 0.9
    assert ev["recall"] >= 0.8


def test_world_prefix_replays_under_later_change():
    base = W.run_world(7, 3, [])
    full = W.run_world(7, 5, [(3, [{"type": "auto_approve_under", "usd": 5000}])])
    r1, _ = W.build_records(base, 3, 7)
    r2, _ = W.build_records(full, 3, 7)
    assert [r["hash"] for r in r1] == [r["hash"] for r in r2]
    assert E.summarize(full.cases, 3 * 7 * E.DAY, 5 * 7 * E.DAY)["signoffs_per_day"] < E.summarize(base.cases, 0, 3 * 7 * E.DAY)["signoffs_per_day"]
