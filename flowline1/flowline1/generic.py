"""Generic team simulator calibrated from mined records — no world, no process script.

Model (everything below is fitted from the approved records of one company):
  * steps: the mined nodes; hands-on minutes per step are lognormal (MLE), first pass and redo fitted apart;
    an outside party's step (client, insurer...) is a wall-clock lognormal;
  * routing: every simulated case replays one observed trace (the sequence of steps a real case took, with its
    parallel branches and send-back loops) and that case's amount, so routing/send-back probabilities and their
    correlation with amounts are the empirical ones;
  * hand-off waits: the business-minute gap between a step's end and the next step's start, sampled from the
    observed gaps per transition (pooled per target step, then globally, when a transition is rare);
  * approver batching: when the approval step's start times cluster at one time of day, it is modelled as a
    batching approver with that many sessions a day (the lever behind "signs twice a day");
  * arrivals: Poisson per weekday at the measured case-start rate; working hours from the records.
Common random numbers: every case owns keyed uniform tables (engine.CaseRandom), so two plans under the same seed
replay the same cases, amounts, durations and luck wherever their paths coincide. No capacity model: freeing one
person's hours does not shorten another person's queue here (stated in model.json limits).
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from . import engine as E
from . import miner as M

AGENT_MIN = 1.0  # agent does the step (D3 measured ~41 s per deck fill)
AGENT_REVIEW_MIN = 3.0  # the person checks the agent's work
AGENT_UNDO_P = 0.05  # the person undoes it and redoes the step by hand
APPROVAL_RE = re.compile(r"approv|sign[ -]?off|(?<!pre-)(?<!pre)authori[sz]|\bsign\b|validat|countersign", re.I)
TEMPLATE_TOOLS = {"docs", "sheets", "slides", "pdf", "forms", "drive"}  # artefacts a shared template can exist for
LAYOUT_RE = re.compile(r"layout|format|template|wrong form|missing field|incomplete form|form\b", re.I)
THRESHOLDS = [100, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000]


@dataclass
class StepModel:
    cid: int
    name: str
    role: str
    external: bool
    dur: tuple[float, float]  # lognormal (mu, sigma), minutes
    redo: tuple[float, float]
    n: int
    median_min: float


@dataclass
class Variant:
    case: str
    stages: list[list[int]]  # each stage = steps that ran in parallel (usually one)
    quals: list[list[str]]  # recorded qualifier per execution ("changes: layout", "missing figures", ...)
    amount: float | None
    completed: bool


@dataclass
class Model:
    steps: dict[int, StepModel]
    variants: list[Variant]
    waits: dict  # (from, to) | ("to", to) | "all" -> sorted array of observed business-minute gaps
    arrivals: list[float]  # cases per weekday
    staff: dict[str, int]
    cal: E.Calendar
    weeks: int
    start_cid: int | None
    end_cid: int | None
    order: dict
    approval_cid: int | None = None
    approval_role: str | None = None
    batch: dict | None = None  # {"n": sessions a day, "hours": [...], "jitter_min": ...}
    threshold_usd: float | None = None
    repeated_cid: int | None = None
    artefact_tool: str | None = None
    artefact_cids: list[int] = field(default_factory=list)
    skill_ids: dict[str, int] = field(default_factory=dict)  # skill_id -> cid
    unit: str = "case"
    report: dict = field(default_factory=dict)

    def name(self, cid: int | None) -> str:
        return self.steps[cid].name if cid is not None and cid in self.steps else ""


# ----------------------------------------------------------------------------- fitting
def _mle(values, floor_sigma=0.15, default=(math.log(30.0), 0.4)) -> tuple[float, float]:
    v = np.array([x for x in values if x > 0], float)
    if len(v) == 0:
        return default
    lv = np.log(v)
    mu = float(np.median(lv))
    sigma = float(lv.std(ddof=1)) if len(v) > 2 else 0.35
    return mu, max(min(sigma, 1.5), floor_sigma)


def _hour(t: float) -> float:
    return (t % E.DAY) / 60


def skill_id_for(name: str) -> str:
    if M.normalise(name) == M.normalise("Fill pricing") or "pricing" in name.lower() and "deck" in name.lower():
        return "fill_deck_from_sheet"
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return f"agent_{slug}"[:48]


def fit(mined: dict, cal: E.Calendar | None = None, unit: str = "case") -> Model:
    st = mined["stats"]
    cal = cal or st.get("calendar") or E.DEFAULT_CALENDAR
    by_case: dict[str, list[M.Exec]] = st["by_case"]
    order: dict = st["order"]
    execs: list[M.Exec] = mined["execs"]
    nodes = {int(n["id"][1:]): n for n in mined["ontology"]["nodes"]}
    start_cid, end_cid = st["start_cluster"], st["end_cluster"]
    weeks = max(mined["meta"]["weeks"], 1)
    report = {"steps": {}, "notes": []}

    # --- durations: first pass vs redo, per step
    full: dict[int, list[float]] = defaultdict(list)
    redo: dict[int, list[float]] = defaultdict(list)
    ext_dur: dict[int, list[float]] = defaultdict(list)
    for seq in by_case.values():
        seen: set[int] = set()
        for e in seq:
            if e.external:
                if e.end > e.start:
                    ext_dur[e.cluster].append(e.end - e.start)
                continue
            (redo if e.cluster in seen else full)[e.cluster].append(e.hands_min)
            seen.add(e.cluster)
    ratios = [np.median(redo[c]) / np.median(full[c]) for c in redo if full[c] and redo[c] and np.median(full[c]) > 0]
    redo_factor = float(np.clip(np.median(ratios), 0.1, 1.0)) if ratios else 0.5
    steps: dict[int, StepModel] = {}
    for cid, nd in nodes.items():
        ext = all(e.external for e in execs if e.cluster == cid) and any(e.external for e in execs if e.cluster == cid)
        if ext:
            d = _mle(ext_dur[cid], floor_sigma=0.3, default=(math.log(E.DAY), 0.5))
            steps[cid] = StepModel(cid, nd["name"], nd["role"], True, d, d, len(ext_dur[cid]), math.exp(d[0]))
        else:
            d = _mle(full[cid], default=(math.log(max(nd.get("median_min") or 15, 1)), 0.4))
            r = _mle(redo[cid], default=(d[0] + math.log(redo_factor), d[1])) if len(redo[cid]) >= 3 else (d[0] + math.log(redo_factor), d[1])
            steps[cid] = StepModel(cid, nd["name"], nd["role"], False, d, r, len(full[cid]), math.exp(d[0]))
        report["steps"][nd["name"]] = {"n": steps[cid].n, "median_min": round(steps[cid].median_min, 1), "sigma": round(d[1], 2), "external": steps[cid].external}
    report["redo_factor"] = round(redo_factor, 2)

    # --- variants (observed traces) and hand-off waits
    last_t = max((e.end for e in execs), default=0.0)
    variants: list[Variant] = []
    waits: dict = defaultdict(list)
    approval_cid = _approval_cid(nodes, st)
    for case, seq in by_case.items():
        stages: list[list[M.Exec]] = []
        for e in seq:
            if stages and not e.external and not stages[-1][-1].external and e.start < max(x.end for x in stages[-1]) - 1 \
                    and e.person != stages[-1][-1].person and e.cluster != stages[-1][-1].cluster:
                stages[-1].append(e)
            else:
                stages.append([e])
        completed = any(e.cluster == end_cid for e in seq) and (start_cid is None or any(e.cluster == start_cid for e in seq))
        ended = completed or (last_t - max(e.end for e in seq)) > 5 * E.DAY
        if ended:
            amount = next((e.amount for e in seq if e.amount is not None), None)
            variants.append(Variant(case, [[e.cluster for e in s] for s in stages], [[e.qualifier or "" for e in s] for s in stages], amount, completed))
        for a, b in zip(stages, stages[1:]):
            prev_end = max(x.end for x in a)
            for e in b:
                if e.external or a[-1].external:
                    gap = max(0.0, e.start - prev_end) if e.external else cal.business_minutes(prev_end, e.start)
                else:
                    gap = cal.business_minutes(prev_end, e.start)
                waits[(a[-1].cluster, e.cluster)].append(gap)
                waits[("to", e.cluster)].append(gap)
                waits["all"].append(gap)
    if not any(v.completed for v in variants):
        report["notes"].append("no completed case: the simulator has nothing to replay")
    report["variants"] = len(variants)
    report["completed_variants"] = sum(1 for v in variants if v.completed)

    # --- approver batching
    batch = None
    approval_role = None
    if approval_cid is not None:
        approval_role = nodes[approval_cid]["role"]
        appr = [e for e in execs if e.cluster == approval_cid and not e.external]
        hours = [_hour(e.start) for e in appr]
        if len(hours) >= 5 and float(np.std(hours)) < 1.0:
            per_day: dict[int, list[float]] = defaultdict(list)
            for e in appr:
                per_day[E.day_of(e.start)].append(e.start)
            sessions = []
            firsts = []
            for d, starts in per_day.items():
                starts.sort()
                k = 1 + sum(1 for x, y in zip(starts, starts[1:]) if y - x > 90)
                sessions.append(k)
                firsts.append(_hour(starts[0]))
            n = int(np.median(sessions)) if sessions else 1
            evening = float(np.median(hours))
            batch = {"n": n, "hours": [round(evening, 2)] if n <= 1 else _spread_hours(cal, evening, n),
                     "jitter_min": max(float(np.std(hours) * 60), 3.0)}
            # the wait into a batched step is produced by the schedule, not sampled
            for k in [k for k in waits if isinstance(k, tuple) and k[-1] == approval_cid]:
                del waits[k]
    waits = {k: np.sort(np.array(v, float)) for k, v in waits.items() if len(v)}
    report["approval"] = {"step": nodes[approval_cid]["name"] if approval_cid is not None else None, "role": approval_role, "batch": batch}

    # --- amounts and the auto-approve threshold
    amounts = [a for a, _ in st["approvals"]]
    threshold = pick_threshold(amounts) if approval_cid is not None else None
    if threshold:
        report["threshold_usd"] = threshold
        report["share_under_threshold"] = round(float((np.array(amounts) < threshold).mean()), 3)

    # --- arrivals per weekday (all cases, started or not completed)
    per_wd: Counter = Counter()
    for seq in by_case.values():
        per_wd[E.weekday(seq[0].start)] += 1
    arr_rates = [per_wd.get(wd, 0) / weeks for wd in range(5)]
    mean_rate = sum(arr_rates) / 5
    arr_rates = [0.5 * a + 0.5 * mean_rate for a in arr_rates]
    if sum(arr_rates) == 0:
        arr_rates = [0.2] * 5
    report["arrivals_per_weekday"] = [round(a, 2) for a in arr_rates]

    # --- the most repeated hands-on step (agent candidate) and the repeated artefact (template candidate)
    counts: Counter = Counter(e.cluster for e in execs if not e.external and e.cluster in nodes)
    main_cids = [c for c, nd in nodes.items() if nd["critical_path"] and not steps[c].external and nd["role"] not in st["external_roles"]]
    cand = [c for c in counts if c != approval_cid and not steps[c].external and steps[c].median_min <= 120
            and nodes[c]["role"] not in st["external_roles"] and c not in (start_cid, end_cid)]
    skills = [c for c in cand if nodes[c]["kind"] == "skill"]
    pool = skills or cand or [c for c in counts if not steps[c].external]
    repeated_cid = max(pool, key=lambda c: (counts[c], -steps[c].median_min)) if pool else None
    # the artefact: what the layout/format send-backs point at, else the most used tool on the main path
    loop_targets: Counter = Counter()
    for seq in by_case.values():
        for p, e in zip(seq, seq[1:]):
            if LAYOUT_RE.search(p.qualifier or "") and order.get(e.cluster, 0) < order.get(p.cluster, 0) and not e.external:
                for t in e.tools:
                    if t not in M.NON_ARTIFACT_TOOLS:
                        loop_targets[t] += 1
    tool_counts: Counter = Counter(t for e in execs if e.cluster in main_cids for t in e.tools if t in TEMPLATE_TOOLS)
    if not tool_counts:
        tool_counts = Counter(t for e in execs if e.cluster in main_cids for t in e.tools if t not in M.NON_ARTIFACT_TOOLS)
    artefact_tool = loop_targets.most_common(1)[0][0] if loop_targets else (tool_counts.most_common(1)[0][0] if tool_counts else None)
    artefact_cids = []
    if artefact_tool:
        for c in main_cids:
            tc = Counter(t for e in execs if e.cluster == c for t in e.tools if t not in M.NON_ARTIFACT_TOOLS)
            if tc and tc.most_common(1)[0][0] == artefact_tool:
                artefact_cids.append(c)
    report["repeated_step"] = nodes[repeated_cid]["name"] if repeated_cid is not None else None
    report["artefact"] = {"tool": artefact_tool, "steps": [nodes[c]["name"] for c in artefact_cids]}

    staff = Counter(mined["meta"]["roles"].values())
    model = Model(steps=steps, variants=variants, waits=waits, arrivals=arr_rates, staff=dict(staff), cal=cal, weeks=weeks,
                  start_cid=start_cid, end_cid=end_cid, order=order, approval_cid=approval_cid, approval_role=approval_role,
                  batch=batch, threshold_usd=threshold, repeated_cid=repeated_cid, artefact_tool=artefact_tool,
                  artefact_cids=artefact_cids, unit=unit, report=report)
    if repeated_cid is not None:
        model.skill_ids[skill_id_for(nodes[repeated_cid]["name"])] = repeated_cid
    report["assumptions"] = {"agent_min": AGENT_MIN, "agent_review_min": AGENT_REVIEW_MIN, "agent_undo_p": AGENT_UNDO_P,
                             "agent": "does the step in agent_min, the person reviews in agent_review_min after the usual hand-off wait; send-backs unchanged — the gain is the person's hours, not the cycle",
                             "template": "removes send-back loops whose recorded reason mentions layout, format, template or form; no other effect",
                             "auto_approve": "cases under the threshold skip the approval step and the send-backs it caused",
                             "batching": "the approver signs everything queued at the session times; intra-session order ignored",
                             "capacity": "no queueing between cases: hand-off waits are replayed as measured"}
    return model


def pick_threshold(amounts: list[float]) -> float | None:
    """A round amount under which ~65 % of the recorded amounts fall (needs 5 amounts)."""
    if len(amounts) < 5:
        return None
    arr = np.array(amounts, float)
    return float(min(THRESHOLDS, key=lambda t: abs(float((arr < t).mean()) - 0.65)))


def approval_node(nodes: list[dict], external_roles: set) -> dict | None:
    """The approval-like step with the longest wait (ontology nodes)."""
    cands = [n for n in nodes if APPROVAL_RE.search(n["name"]) and n["role"] not in external_roles]
    return max(cands, key=lambda n: (n.get("wait_before_h", 0), n["cases"])) if cands else None


def _spread_hours(cal: E.Calendar, evening: float, n: int) -> list[float]:
    start = cal.start / 60
    hours = [start + (evening - start) * (i + 1) / n for i in range(n - 1)] + [evening]
    return sorted(round(h, 2) for h in hours)


def _approval_cid(nodes: dict, st: dict) -> int | None:
    nd = approval_node(list(nodes.values()), set(st["external_roles"]))
    return int(nd["id"][1:]) if nd else None


# ----------------------------------------------------------------------------- plans
def plan_catalogue(model: Model) -> list[dict]:
    """Candidate plans generated from the mined bottleneck and the repeated work (SCHEMA §5 Plan shape)."""
    appr = model.name(model.approval_cid)
    role = model.approval_role or ""
    a_opts = [("as_is", f"{role} signs all" if appr else "Today's hand-offs", [], "keeps signing every case" if appr else "nothing to change")]
    if model.batch and model.batch["n"] == 1:
        a_opts.append(("twice_a_day", "Sign-off twice a day", [{"type": "approver_batches_per_day", "n": 2}],
                       "signs at midday and at close"))
    if model.threshold_usd and model.approval_cid is not None:
        t = int(model.threshold_usd)
        a_opts.append((f"auto_{t}", f"Auto-approve under ${t:,}", [{"type": "auto_approve_under", "usd": t}], f"signs only cases over ${t:,}"))
    d_opts = [("by_hand", "everything by hand", [], None)]
    if model.artefact_tool and model.artefact_cids:
        art = M.ARTIFACT.get(model.artefact_tool, model.artefact_tool)
        d_opts.append(("template", f"shared {art} template", [{"type": "template", "name": f"shared {art} template"}],
                       (model.steps[model.artefact_cids[0]].role, "starts from the shared template")))
    if model.repeated_cid is not None:
        x = model.steps[model.repeated_cid]
        sid = next(k for k, v in model.skill_ids.items() if v == model.repeated_cid)
        d_opts.append(("agent", f"agent does '{x.name}' ({x.role} reviews)",
                       [{"type": "skill", "skill_id": sid, "actor": x.role, "reviewer": x.role}], (x.role, "checks the agent's work, not typing")))
    plans = []
    for a_id, a_name, a_rules, a_change in a_opts:
        for d_id, d_name, d_rules, d_change in d_opts:
            who = []
            if appr:
                who.append({"role": role, "change": a_change[:40]})
            if d_change:
                who.append({"role": d_change[0], "change": d_change[1][:40]})
            elif model.repeated_cid is not None:
                who.append({"role": model.steps[model.repeated_cid].role, "change": "nothing to change"})
            plans.append({"id": f"{a_id}__{d_id}", "name": a_name, "sub": f"+ {d_name}", "rules": a_rules + d_rules,
                          "today": a_id == "as_is" and d_id == "by_hand", "who": who, "_a": a_id, "_d": d_id})
    return plans


def _flags(model: Model, rules: list[dict]) -> dict:
    f = {"auto_under": 0.0, "batches": model.batch["n"] if model.batch else 0, "skills": set(), "template": False}
    for r in rules:
        t = r["type"]
        if t == "auto_approve_under":
            f["auto_under"] = float(r["usd"])
        elif t == "approver_batches_per_day":
            f["batches"] = int(r["n"])
        elif t == "skill":
            cid = model.skill_ids.get(r["skill_id"])
            if cid is not None:
                f["skills"].add(cid)
        elif t == "template":
            f["template"] = True
    return f


def _strip_approval(stages: list[list[int]], quals: list[list[str]], approval_cid: int, order: dict):
    """Remove the approval stages and the send-back loops they caused (approval -> back jump -> ... -> approval)."""
    out_s, out_q = [], []
    i = 0
    while i < len(stages):
        s = stages[i]
        if approval_cid in s:
            nxt = stages[i + 1] if i + 1 < len(stages) else None
            if nxt and all(order.get(c, 0) < order.get(approval_cid, 0) for c in nxt):
                j = next((k for k in range(i + 1, len(stages)) if approval_cid in stages[k]), None)
                if j is not None:
                    i = j  # skip the loop body; the next approval is handled on the next iteration
                    continue
            rest = [c for c in s if c != approval_cid]
            if rest:
                out_s.append(rest)
                out_q.append([q for c, q in zip(s, quals[i]) if c != approval_cid])
            i += 1
            continue
        out_s.append(list(s))
        out_q.append(list(quals[i]))
        i += 1
    return out_s, out_q


def _strip_loops(stages, quals, cids: set[int], order: dict, reason_re):
    """Remove loops that go back into `cids` from a step whose recorded reason matches (template fixes layout send-backs)."""
    out_s, out_q = [], []
    i = 0
    while i < len(stages):
        s, q = stages[i], quals[i]
        nxt = stages[i + 1] if i + 1 < len(stages) else None
        if nxt and any(reason_re.search(x or "") for x in q) and any(c in cids for c in nxt) \
                and all(order.get(c, 0) < min(order.get(x, 0) for x in s) for c in nxt):
            j = next((k for k in range(i + 1, len(stages)) if set(stages[k]) & set(s)), None)
            if j is not None:
                out_s.append(list(s))
                out_q.append(["ok" for _ in s])
                i = j + 1
                continue
        out_s.append(list(s))
        out_q.append(list(q))
        i += 1
    return out_s, out_q


def _sample_wait(model: Model, rnd: E.CaseRandom, prev: int | None, cid: int, k: int) -> float:
    arr = model.waits.get((prev, cid)) if prev is not None else None
    if arr is None or len(arr) < 5:
        arr = model.waits.get(("to", cid))
    if arr is None or len(arr) < 5:
        arr = model.waits.get("all")
    if arr is None or len(arr) == 0:
        return 0.0
    u = rnd.uniform(f"wait:{cid}:{k}")
    return float(np.interp(u, np.linspace(0, 1, len(arr)), arr))


def _next_session(t: float, hours: list[float], jitter: float, rnd: E.CaseRandom, k: int) -> float:
    d = E.day_of(t)
    j = (rnd.uniform(f"session:{k}") - 0.5) * 2 * jitter
    for _ in range(21):
        if d % 7 < 5:
            for h in sorted(hours):
                s = d * E.DAY + h * 60 + j
                if s > t:
                    return s
        d += 1
    return t + E.DAY


def _arrivals(seed: int, weeks: int, rates: list[float], cal: E.Calendar) -> list[float]:
    g = np.random.default_rng([seed, E._key_hash("arrivals")])
    out = []
    for d in range(weeks * 7):
        wd = d % 7
        if wd >= 5:
            continue
        for _ in range(g.poisson(rates[wd])):
            out.append(d * E.DAY + cal.start + g.random() * cal.day_min)
    return sorted(out)


def simulate(model: Model, rules: list[dict], seed: int, weeks: int) -> dict:
    """Replay `weeks` of arrivals under the plan rules; KPIs over the cases that complete the measured cycle."""
    cal = model.cal
    flags = _flags(model, rules)
    hours = _spread_hours(cal, max(model.batch["hours"]), flags["batches"]) if model.batch and flags["batches"] >= 1 else None
    completed = [v for v in model.variants if v.completed]
    variants = model.variants if model.variants else []
    rows = []
    signoffs = 0
    agent_runs = 0
    undone = 0
    horizon = weeks * 7 * E.DAY
    for i, t0 in enumerate(_arrivals(seed, weeks, model.arrivals, cal)):
        rnd = E.CaseRandom(seed, i)
        if not variants:
            break
        v = variants[min(int(rnd.uniform("variant") * len(variants)), len(variants) - 1)]
        stages, quals = [list(s) for s in v.stages], [list(q) for q in v.quals]
        amount = v.amount
        if flags["auto_under"] and model.approval_cid is not None and amount is not None and amount < flags["auto_under"]:
            stages, quals = _strip_approval(stages, quals, model.approval_cid, model.order)
        if flags["template"] and model.artefact_cids:
            stages, quals = _strip_loops(stages, quals, set(model.artefact_cids), model.order, LAYOUT_RE)
        t = t0
        prev: int | None = None
        hands: list[tuple[float, float]] = []
        marks: dict[int, list[tuple[float, float]]] = defaultdict(list)
        seen: Counter = Counter()
        appr_wait = 0.0
        prev_end = t0
        for stage in stages:
            ends = []
            for cid in stage:
                step = model.steps.get(cid)
                if step is None:
                    continue
                k = seen[cid]
                seen[cid] += 1
                if step.external:
                    d = rnd.lognormal(f"dur:{cid}:{k}", *step.dur)
                    s, e = t, t + d
                    marks[cid].append((s, e))
                    ends.append(e)
                    continue
                mu, sg = step.redo if k > 0 else step.dur
                dur = rnd.lognormal(f"dur:{cid}:{k}", mu, sg)
                if cid in flags["skills"]:
                    # the agent does the step at once; the person's review still waits its usual hand-off wait
                    dur = AGENT_MIN + AGENT_REVIEW_MIN
                    agent_runs += 1
                    if rnd.bernoulli(f"undo:{cid}:{k}", AGENT_UNDO_P):
                        undone += 1
                        dur += rnd.lognormal(f"dur:{cid}:{k}", mu, sg)
                    w = 0.0 if prev is None else _sample_wait(model, rnd, prev, cid, k)
                    ready = cal.add_business_minutes(t, w) if w > 0 else t
                elif cid == model.approval_cid and hours:
                    ready = _next_session(t, hours, model.batch["jitter_min"], rnd, k)
                    signoffs += 1 if ready < horizon else 0
                    s, e = ready, ready + dur
                    hands.append((s, e))
                    marks[cid].append((s, e))
                    ends.append(e)
                    appr_wait += E.weekday_minutes(prev_end, s)
                    continue
                else:
                    if cid == model.approval_cid:
                        signoffs += 1 if t < horizon else 0
                    w = 0.0 if prev is None else _sample_wait(model, rnd, prev, cid, k)
                    ready = cal.add_business_minutes(t, w) if w > 0 else t
                segs = cal.work_segments(ready, dur)
                hands.extend(segs)
                marks[cid].append((segs[0][0], segs[-1][1]))
                ends.append(segs[-1][1])
                if prev == model.approval_cid and model.approval_cid is not None:
                    appr_wait += E.weekday_minutes(prev_end, segs[0][0])
            if ends:
                prev_end = max(ends)
                t = prev_end
                prev = stage[-1]
        lo = marks[model.start_cid][0][0] if model.start_cid in marks else None
        hi = min((e for s, e in marks.get(model.end_cid, [])), default=None) if model.end_cid is not None else None
        if lo is None or hi is None or hi <= lo:
            continue
        cyc = E.weekday_minutes(lo, hi) / 60
        work = E.union_minutes(hands, lo, hi) / 60
        rows.append({"case": v.case, "brief_start": lo, "end": hi, "cycle_h": cyc, "work_h": work, "waiting_h": cyc - work,
                     "approval_wait_h": appr_wait / 60, "amount": amount,
                     "steps": sorted((s, e, c) for c, ms in marks.items() for s, e in ms)})
    weeks_f = max(weeks, 1e-9)
    workdays = max(round(weeks * 5), 1)
    if not rows:
        return {"n": 0, "signoffs_per_day": signoffs / workdays, "completed_per_day": 0.0, "agent_runs": agent_runs, "undone": undone}
    cyc = np.array([r["cycle_h"] for r in rows])
    wait = np.array([r["waiting_h"] for r in rows])
    return {"n": len(rows), "cycle_h": float(np.median(cyc)), "cycle_mean_h": float(cyc.mean()), "cycle_p80_h": float(np.percentile(cyc, 80)),
            "work_h": float(np.median([r["work_h"] for r in rows])), "waiting_h": float(np.median(wait)),
            "waiting_share": float(wait.sum() / max(cyc.sum(), 1e-9)),
            "approval_wait_h": float(np.median([r["approval_wait_h"] for r in rows])),
            "signoffs_per_day": signoffs / workdays, "completed_per_day": len(rows) / workdays,
            "agent_runs": agent_runs, "undone": undone, "cases": rows}


def run_plans(model: Model, plans: list[dict], seeds: list[int], weeks: int) -> dict:
    per_plan = {p["id"]: [] for p in plans}
    for seed in seeds:
        for p in plans:
            per_plan[p["id"]].append(simulate(model, p["rules"], seed, weeks))
    return per_plan


def plans_page(model: Model, board_id: str, plans: list[dict], seeds: list[int], weeks: int, recomputed_at: str,
               measured_today_h: float | None = None) -> tuple[dict, dict]:
    """Same contract as simulator.plans_page. Effects are relative *means* over every replayed case (with a few dozen
    traces the median flips between the before-the-weekend and after-the-weekend modes), applied to the measured
    baseline median so the board shows one baseline everywhere; ranges are the 10th–90th percentile of per-rerun means."""
    per_plan = run_plans(model, plans, seeds, weeks)
    today = next(p for p in plans if p["today"])

    def pooled(pid, key):
        vals = [c[key] for r in per_plan[pid] if r.get("n") for c in r["cases"]]
        return float(np.mean(vals)) if vals else 0.0

    sim_today_h = pooled(today["id"], "cycle_h")
    sim_today_med = float(np.median([c["cycle_h"] for r in per_plan[today["id"]] if r.get("n") for c in r["cases"]])) if sim_today_h else 0.0
    f = (measured_today_h / sim_today_h) if measured_today_h and sim_today_h else 1.0
    today_h = sim_today_h * f
    n_seeds = len(seeds)
    rows = []
    for p in plans:
        runs = [r for r in per_plan[p["id"]] if r.get("n")]
        if not runs:
            continue
        per_seed = np.array([r["cycle_mean_h"] for r in runs])
        rows.append({"plan": p, "hours": pooled(p["id"], "cycle_h"), "work_h": pooled(p["id"], "work_h"), "waiting_h": pooled(p["id"], "waiting_h"),
                     "range": (float(np.percentile(per_seed, 10)), float(np.percentile(per_seed, 90))), "per_seed": per_seed,
                     "agent_runs": int(np.median([r["agent_runs"] for r in runs])), "undone": int(np.median([r["undone"] for r in runs]))})
    rows.sort(key=lambda r: (round(r["hours"], 3), 0 if r["plan"]["today"] else 1, r["plan"]["id"]))

    def held_n(row):
        n = 0
        for i in range(n_seeds):
            vals = {r["plan"]["id"]: r["per_seed"][i] for r in rows if len(r["per_seed"]) > i}
            if vals and min(vals, key=vals.get) == row["plan"]["id"]:
                n += 1
        return n

    # best = the lowest mean; among plans within 1 % of it (a statistical tie), the one that wins most reruns
    tied = [r for r in rows if r["hours"] <= rows[0]["hours"] * 1.01 + 1e-9]
    best = max(tied, key=lambda r: (held_n(r), -r["hours"]))
    rows.remove(best)
    rows.insert(0, best)
    held = held_n(best)
    out_plans = []
    for rank, r in enumerate(rows, 1):
        p = r["plan"]
        out_plans.append({
            "id": p["id"], "rank": rank, "name": p["name"], "sub": p["sub"],
            "hours": round(r["hours"] * f, 1), "work_h": round(r["work_h"] * f, 1), "waiting_h": round(r["waiting_h"] * f, 1),
            "vs_today": round(r["hours"] / sim_today_h - 1, 3) if sim_today_h else 0.0,
            "best": r is best, "today": p["today"],
            "held_best_n": held if r is best else held_n(r),
            "range_h": [round(r["range"][0] * f, 1), round(r["range"][1] * f, 1)],
            "who": p["who"], "rules": p["rules"],
        })
    second = (rows[1]["hours"] - best["hours"]) * f if len(rows) > 1 else 0.0
    page = {
        "source": "simulated", "board_id": board_id, "reruns": n_seeds, "weeks": weeks,
        "headline": f"{best['plan']['name']} {best['plan']['sub']}: {today_h:.0f} hours → {best['hours'] * f:.0f}."
        if not best["plan"]["today"] else f"No tested plan beats today's {today_h:.0f} hours yet.",
        "today_h": round(today_h, 1), "plans": out_plans,
        "note": (f"Every plan replays the same {model.unit}s over {weeks} weeks, {n_seeds} times with new luck; the simulator is fitted "
                 f"to this team's records (step times, hand-off waits, send-backs, arrivals). The best plan held in {held} of {n_seeds} reruns; "
                 f"the next best is {second:.1f} h slower. Effects are mean changes over every replayed {model.unit}, applied to the measured "
                 f"baseline; ranges are the 10th–90th percentile of per-rerun means. Nothing changes until you approve."),
        "recomputed_at": recomputed_at,
    }
    detail = {"per_plan": {pid: [{k: v for k, v in r.items() if k != "cases"} for r in runs] for pid, runs in per_plan.items()},
              "best_id": best["plan"]["id"], "best_rules": best["plan"]["rules"], "sim_today_h": sim_today_h, "sim_today_median_h": sim_today_med, "scale": f,
              "agent_runs": best["agent_runs"], "undone": best["undone"]}
    return page, detail
