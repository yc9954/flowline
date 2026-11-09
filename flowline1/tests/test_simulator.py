import numpy as np

from flowline1 import engine as E
from flowline1 import simulator as S
from flowline1 import world as W


def _params():
    p = W.truth_params()
    p.director_blocks = None
    p.review_wait = (np.log(20.0), 0.5)
    return p


def test_deterministic_for_seed():
    p = _params()
    a = S.simulate(p, [], 11, 3)
    b = S.simulate(p, [], 11, 3)
    assert a["cycle_h"] == b["cycle_h"] and a["n"] == b["n"] and a["waiting_h"] == b["waiting_h"]
    c = S.simulate(p, [], 12, 3)
    assert c["cycle_h"] != a["cycle_h"] or c["n"] != a["n"]


def test_common_random_numbers_share_arrivals():
    p = _params()
    a = S.simulate(p, [], 5, 3)
    b = S.simulate(p, [{"type": "auto_approve_under", "usd": 5000}], 5, 3)
    assert a["n"] == b["n"]
    assert [c["case"] for c in a["cases"]] == [c["case"] for c in b["cases"]]


def test_plan_ordering_on_waiting_hours():
    p = _params()
    seeds = range(12)

    def med(rules, key):
        return float(np.median([S.simulate(p, rules, s, 6)[key] for s in seeds]))

    auto = [{"type": "auto_approve_under", "usd": 5000}]
    twice = [{"type": "approver_batches_per_day", "n": 2}]
    all_ = [{"type": "approver_batches_per_day", "n": 1}]
    # the wait around the signature: auto-approve < twice a day < once a day
    assert med(auto, "approval_wait_h") < med(twice, "approval_wait_h") < med(all_, "approval_wait_h")
    # and both plans cut total waiting hours against today
    assert med(auto, "waiting_h") < med(all_, "waiting_h")
    assert med(twice, "waiting_h") < med(all_, "waiting_h")


def test_rules_to_params():
    p = _params()
    q, flags = E.rules_to_params(p, [{"type": "approver_batches_per_day", "n": 2}, {"type": "skill", "skill_id": "fill_deck_from_sheet", "actor": "PM", "reviewer": "PM"}])
    assert len(q.approver_hours) == 2 and flags["skill_fill"] and not flags["template"]
    assert q.approver_hours[-1] == p.approver_hours[-1]
