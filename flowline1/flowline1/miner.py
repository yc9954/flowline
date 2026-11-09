"""Process miner: approved Records -> Ontology (SCHEMA §3) and Finding (§4).

Entity resolution: normalise names (case, punctuation, ids, amounts, versions, filler verbs, light stemming),
a small table of confirmed synonyms, then token similarity; two names merge only when their score >= 0.8.
Mining: group hands-on steps by case, merge a step that continued across days into one execution, build the
directly-follows graph; wait = next start - previous end (Mon-Fri 24 h calendar); a back edge is an earlier
step reappearing in the same case; a step that ends outside working hours owns the overnight wait after it.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np

from . import engine as E

BOARD = "northwind"
SMALL_QUOTE_USD = 5000

STOP = {"the", "a", "an", "to", "for", "with", "of", "in", "into", "on", "and", "&", "+", "/", "proposal", "plan", "by", "from"}
FILLER = {"write", "build", "calc", "do", "prep", "prepare", "make", "draft", "run", "pick", "choose", "select", "new", "v"}
# Confirmed merges (what the product learns from people's answers at end-of-day review).
SYNONYMS = {
    "fit check": "qualify",
    "disco call": "discovery call",
    "intro call with client": "discovery call",
    "quote calc": "estimate",
    "pricing build": "estimate",
    "sign off": "approval",
    "approve quote": "approval",
    "quote approval": "approval",
    "gm check": "margin check",
    "margin review": "margin check",
    "copy figures into deck": "fill pricing",
    "handoff to delivery": "kickoff hand-off",
    "proposal deck": "concept & deck",
}
# Finding.map: the condensed main path, one row per hand-off (name, role, canonical steps folded in, main artifact)
MAP_GROUPS = [
    ("Brief", "Sales", ["Qualify", "Discovery call", "Write brief"], "docs"),
    ("Estimate", "PM", ["Scope & staffing", "Check availability", "Estimate"], "sheets"),
    ("Margin check", "Finance", ["Margin check"], "sheets"),
    ("Approval", "Director", ["Approval"], "quote"),
    ("Deck", "Design", ["Pick case studies", "Concept & deck", "Fill pricing"], "slides"),
    ("Review", "Director", ["Internal review", "Terms / MSA"], "slides"),
    ("Send", "Sales", ["Send"], "mail"),
]
REASONS = {"changes": "Review changes", "revise quote": "Revise quote", "below 25% margin": "Margin under 25%",
           "missing figures": "Missing figures", "sent back": "Sent back"}
ARTIFACT = {"quote": "quote", "docs": "brief (doc)", "sheets": "pricing sheet", "slides": "deck", "pdf": "PDF", "mail": "email",
            "calendar": "calendar", "meet": "call", "crm": "CRM", "drive": "case-study folder", "agent": "agent run"}
AGENT_TOOLS = {"sheets", "slides", "mail", "pdf", "docs", "drive"}

_amount_re = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
_id_re = re.compile(r"#\d+|\bv\d+\b|\b\d[\d,.]*\b")


def stem(tok: str) -> str:
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    for suf in ("ing", "ed", "al", "es", "s", "e"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)]
    return tok


def split_qualifier(name: str) -> tuple[str, str]:
    """'Approval $4,400 — missing figures' -> ('Approval $4,400', 'missing figures')."""
    for sep in (" — ", " – ", " - ", " ("):
        if sep in name:
            head, tail = name.split(sep, 1)
            return head.strip(), tail.strip(" )").strip()
    return name.strip(), ""


def amount_of(name: str) -> float | None:
    m = _amount_re.search(name)
    return float(m.group(1).replace(",", "")) if m else None


def normalise(name: str) -> frozenset[str]:
    head, _ = split_qualifier(name)
    s = head.lower()
    s = _amount_re.sub(" ", s)
    s = _id_re.sub(" ", s)
    s = s.replace("-", "").replace("/", " ").replace("&", " and ").replace("+", " and ")
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in SYNONYMS:
        s = SYNONYMS[s]
        s = s.replace("-", "").replace("/", " ").replace("&", " and ")
    toks = [stem(t) for t in s.split() if t not in STOP and t not in FILLER]
    toks = [t for t in toks if len(t) > 1]
    return frozenset(toks) if toks else frozenset({s.replace(" ", "")})


def _tok_eq(a: str, b: str) -> bool:
    if a == b:
        return True
    return len(min(a, b, key=len)) >= 4 and (a.startswith(b) or b.startswith(a))


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = sum(1 for x in a if any(_tok_eq(x, y) for y in b))
    union = len(a) + len(b) - inter
    jacc = inter / union if union else 0.0
    overlap = inter / min(len(a), len(b))
    return 0.4 * jacc + 0.6 * overlap


class Resolver:
    """Single-linkage clustering of raw names at similarity >= threshold."""

    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold
        self.cluster_of: dict[str, int] = {}
        self.display: dict[int, str] = {}
        self.members: dict[int, list[str]] = {}

    def fit(self, names: Counter) -> "Resolver":
        heads = {}
        for n in names:
            head, _ = split_qualifier(n)
            head = _amount_re.sub("", head).strip()
            heads.setdefault(head, 0)
            heads[head] += names[n]
        keys = list(heads)
        toks = {k: normalise(k) for k in keys}
        parent = list(range(len(keys)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if toks[keys[i]] == toks[keys[j]] or similarity(toks[keys[i]], toks[keys[j]]) >= self.threshold:
                    parent[find(i)] = find(j)
        groups: dict[int, list[str]] = defaultdict(list)
        for i, k in enumerate(keys):
            groups[find(i)].append(k)
        cid = 0
        for _, ks in sorted(groups.items(), key=lambda kv: -sum(heads[k] for k in kv[1])):
            cid += 1
            ks.sort(key=lambda k: (-heads[k], k))
            self.members[cid] = ks
            self.display[cid] = ks[0]
            for k in ks:
                self.cluster_of[k] = cid
        self._head_of = {n: _amount_re.sub("", split_qualifier(n)[0]).strip() for n in names}
        return self

    def cluster(self, raw: str) -> int:
        head = self._head_of.get(raw)
        if head is None:
            head = _amount_re.sub("", split_qualifier(raw)[0]).strip()
        c = self.cluster_of.get(head)
        if c is None:  # unseen name: nearest cluster or new
            t = normalise(head)
            best, bs = None, 0.0
            for cid, ks in self.members.items():
                s = max(similarity(t, normalise(k)) for k in ks)
                if s > bs:
                    best, bs = cid, s
            if best is not None and bs >= self.threshold:
                c = best
            else:
                c = max(self.members, default=0) + 1
                self.members[c] = [head]
                self.display[c] = head
            self.cluster_of[head] = c
        return c


def er_eval(resolver: Resolver, name_key: dict[str, str]) -> dict:
    """Pairwise precision/recall of merges against the planted answer key (hands-on proposal steps)."""
    names = [n for n in name_key]
    tp = fp = fn = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            same_truth = name_key[names[i]] == name_key[names[j]]
            same_pred = resolver.cluster(names[i]) == resolver.cluster(names[j])
            tp += same_truth and same_pred
            fp += (not same_truth) and same_pred
            fn += same_truth and (not same_pred)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": prec, "recall": rec, "tp": tp, "fp": fp, "fn": fn, "names": len(names)}


# ----------------------------------------------------------------------------- loading
class Exec:
    __slots__ = ("case", "cluster", "person", "role", "start", "end", "hands_min", "qualifier", "amount", "tools",
                 "repeats", "external", "handoff_from", "by_agent", "raw", "segs")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _parse(ts: str) -> datetime:
    """Local wall-clock time (offset dropped): the calendar is the team's working day, not UTC."""
    return datetime.fromisoformat(ts).replace(tzinfo=None)


def load(records: list[dict]) -> tuple[list[Exec], Resolver, datetime, dict]:
    """Flatten records to merged step executions in minutes from the Monday of the first record's week."""
    first = min(_parse(r["covers"]["start"]) for r in records)
    origin = (first - timedelta(days=first.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    counts = Counter(s["name"] for r in records for s in r["steps"] if s["kind"] == "hands_on" or s.get("waiting_on") == "Client")
    res = Resolver().fit(counts)
    chunks = []
    for r in records:
        for s in r["steps"]:
            external = s["kind"] == "waiting" and s.get("waiting_on") == "Client"
            if s["kind"] != "hands_on" and not external:
                continue
            a = E.dt_to_minutes(_parse(s["start"]), origin)
            b = E.dt_to_minutes(_parse(s["end"]), origin)
            _, qual = split_qualifier(s["name"])
            chunks.append(Exec(case=s.get("case_id", ""), cluster=res.cluster(s["name"]), person=r["person_id"],
                               role="Client" if external else r["role"], start=a, end=b, hands_min=0 if external else b - a,
                               qualifier=qual, amount=amount_of(s["name"]), tools=tuple(s.get("tools", [])),
                               repeats=s.get("repeats"), external=external, handoff_from=s.get("handoff_from"),
                               by_agent="agent" in s.get("tools", []), raw=s["name"], segs=[(a, b)]))
    chunks.sort(key=lambda c: (c.case, c.start))
    merged: list[Exec] = []
    for c in chunks:
        m = None
        for cand in reversed(merged[-6:]):
            if cand.case != c.case:
                break
            if cand.cluster == c.cluster and cand.person == c.person:
                m = cand
                break
        ok = m is not None and (c.external or c.start - m.end < 20 * 60)
        if ok:
            idx = merged.index(m)
            # a sequential (non-overlapping) step in between means this is a new execution, not a continuation
            ok = all(x.start < m.end - 1 or x.external for x in merged[idx + 1:])
        if ok:
            m.end = c.end
            m.hands_min += c.hands_min
            m.qualifier = m.qualifier or c.qualifier
            m.segs.append((c.start, c.end))
        else:
            merged.append(c)
    merged.sort(key=lambda c: (c.case, c.start))
    meta = {"records": len(records), "people": len({r["person_id"] for r in records}),
            "weeks": len({_parse(r["date"] + "T00:00:00").isocalendar()[:2] for r in records}),
            "roles": {r["person_id"]: r["role"] for r in records}}
    return merged, res, origin, meta


# ----------------------------------------------------------------------------- mining
def mine(records: list[dict], process_prefix: str = "proposal") -> dict:
    execs, res, origin, meta = load(records)
    proc = [e for e in execs if e.case.startswith(process_prefix)]
    by_case: dict[str, list[Exec]] = defaultdict(list)
    for e in proc:
        by_case[e.case].append(e)
    for v in by_case.values():
        v.sort(key=lambda e: (e.start, e.end))

    node_execs: dict[int, list[Exec]] = defaultdict(list)
    for e in proc:
        node_execs[e.cluster].append(e)
    edges: dict[tuple[int, int, str], list[float]] = defaultdict(list)
    out_count: Counter = Counter()
    wait_before: dict[int, list[float]] = defaultdict(list)
    wait_after: dict[int, list[float]] = defaultdict(list)
    back_reasons: dict[tuple[int, int], Counter] = defaultdict(Counter)
    back_cost: dict[tuple[int, int], list[float]] = defaultdict(list)
    outcomes: dict[int, Counter] = defaultdict(Counter)
    positions: dict[int, list[float]] = defaultdict(list)
    cycles = []
    works = []
    approvals = []  # (amount, sent_back)
    case_rows = []
    approval_starts = []

    send_cluster = _find_cluster(res, "send")
    brief_cluster = _find_cluster(res, "write brief")
    # canonical order: median relative position of each node's first occurrence in a case
    first_pos: dict[int, list[float]] = defaultdict(list)
    for seq in by_case.values():
        seen_first: set[int] = set()
        t0 = seq[0].start
        for e in seq:
            if e.cluster not in seen_first:
                seen_first.add(e.cluster)
                first_pos[e.cluster].append(E.weekday_minutes(t0, e.start) / 60)
    order = {c: float(np.median(v)) for c, v in first_pos.items()}

    for case, seq in by_case.items():
        seen: set[int] = set()
        n = len(seq)
        # owned wait per execution: gap before it (after the predecessor's after-hours tail) + its own tail
        for i, e in enumerate(seq):
            positions[e.cluster].append(order.get(e.cluster, 0.0))
            outcomes[e.cluster][e.qualifier or "ok"] += 1
            if i == 0:
                seen.add(e.cluster)
                continue
            p = seq[i - 1]
            parallel = e.start < p.end - 1 and e.person != p.person and not e.external and not p.external
            if parallel:
                kind = "parallel"
            elif e.cluster in seen and order.get(e.cluster, 0) < order.get(p.cluster, 0):
                kind = "back"
            else:
                kind = "then"
            p_free = p.end if (E.is_work_time(p.end) or p.external) else E.to_work(p.end)
            tail = E.weekday_minutes(p.end, p_free)  # owned by p
            gap = 0.0 if parallel else E.weekday_minutes(max(p.end, p_free), e.start)  # owned by e
            if p.external:  # the client's time is the client's
                tail, gap = gap + tail, 0.0
            if not parallel:
                wait_before[e.cluster].append(gap + (0.0 if E.is_work_time(e.end) or e.external else
                                                     E.weekday_minutes(e.end, E.to_work(e.end))))
                wait_after[p.cluster].append(gap + tail)
            edges[(p.cluster, e.cluster, kind)].append(0.0 if parallel else gap + tail)
            out_count[p.cluster] += 1
            if kind == "back":
                back_reasons[(p.cluster, e.cluster)][p.qualifier or "sent back"] += 1
                again = next((x for x in seq[i:] if x.cluster == p.cluster), None)
                if again:  # added time per loop, on the 09–18 working calendar
                    back_cost[(p.cluster, e.cluster)].append(E.business_minutes(p.end, again.end) / 60)
            seen.add(e.cluster)
        for i, e in enumerate(seq):
            if e.amount is not None:
                nxt = seq[i + 1] if i + 1 < n else None
                sent_back = bool(nxt and order.get(nxt.cluster, 0) < order.get(e.cluster, 0))
                approvals.append((e.amount, sent_back))
                approval_starts.append(e.start)
        b = next((x for x in seq if x.cluster == brief_cluster), None)
        s_ = next((x for x in seq if x.cluster == send_cluster), None)
        if b and s_ and s_.end > b.start:
            cyc = E.weekday_minutes(b.start, s_.end)
            hands = [seg for x in seq if not x.external for seg in x.segs]
            work = E.union_minutes(hands, b.start, s_.end)
            cycles.append(cyc / 60)
            works.append(work / 60)
            appr_wait = 0.0
            for i, e in enumerate(seq):
                if e.amount is not None and e.start < s_.end and i > 0:
                    nxt_i = next((x for x in seq[i + 1:] if not x.external), None)
                    appr_wait += E.weekday_minutes(seq[i - 1].end, e.start) + (E.weekday_minutes(e.end, nxt_i.start) if nxt_i else 0.0)
            case_rows.append({"case": case, "brief_start": b.start, "cycle_h": cyc / 60, "work_h": work / 60,
                              "waiting_h": (cyc - work) / 60, "approval_wait_h": appr_wait / 60})

    completed = sum(1 for seq in by_case.values() if any(x.cluster == send_cluster for x in seq))
    weeks = max(meta["weeks"], 1)
    cycle_med = float(np.median(cycles)) if cycles else 0.0
    work_med = float(np.median(works)) if works else 0.0
    wait_med = float(np.median(np.array(cycles) - np.array(works))) if cycles else 0.0
    wait_share = float((np.sum(cycles) - np.sum(works)) / np.sum(cycles)) if cycles else 0.0

    # --- nodes
    nodes = []
    role_steps: Counter = Counter()
    internal_waits = {}
    for cid, ex in node_execs.items():
        roles = Counter(e.role for e in ex)
        role = roles.most_common(1)[0][0]
        durs = [e.hands_min for e in ex if not e.external]
        med = float(np.median(durs)) if durs else 0.0
        handoff_client = sum(1 for e in ex if e.handoff_from == "Client") / len(ex)
        external = all(e.external for e in ex)
        if external or (handoff_client > 0.5 and med <= 6):
            role = "Client"
        cases_n = len({e.case for e in ex})
        wb = float(np.median(wait_before[cid])) / 60 if wait_before[cid] else 0.0
        fails = sum(v for k, v in outcomes[cid].items() if k != "ok")
        has_back = any(f == cid and k == "back" and len(v) >= 2 for (f, t, k), v in edges.items())
        is_decision = has_back or fails > 0
        reps = [e.repeats for e in ex if e.repeats]
        per_week = len([e for e in execs if e.cluster == cid]) / weeks
        is_skill = bool(reps) and med <= 30 and per_week >= 5
        if role == "Client" and not external and med <= 6:
            kind = "event"
        elif is_skill:
            kind = "skill"
        elif is_decision:
            kind = "decision"
        else:
            kind = "step"
        if kind == "decision" and fails:
            ok_share = 1 - fails / len(ex)
            sub = f"ok? {ok_share:.0%} yes" if role != "Client" else f"revise? {1 - ok_share:.0%}"
        elif kind == "skill":
            sub = f"{med:.0f} m · {per_week:.0f}×/wk"
        elif kind == "event":
            sub = "email / form" if positions[cid] and np.median(positions[cid]) < 1.0 else "contract"
        elif completed and cases_n < 0.6 * completed and role != "Client":
            sub = f"{cases_n / completed:.0%} of proposals"
        elif wb >= 3:
            sub = f"waits {wb:.1f} h"
        else:
            sub = f"{med / 60:.1f} h" if med >= 90 else f"{med:.0f} m"
        rule = None
        starts = [(e.start % E.DAY) / 60 for e in ex if not e.external]
        if role != "Client" and len(starts) >= 5 and float(np.std(starts)) < 1.0 and wb >= 3:
            rule = f"{role} signs in one batch a day around {int(np.median(starts)):02d}:{int((np.median(starts) % 1) * 60):02d}"
        if role != "Client":
            internal_waits[cid] = wb
            role_steps[role] += 1
        else:
            role_steps["Client"] += 1
        nodes.append({
            "id": f"n{cid}", "name": res.display[cid], "kind": kind, "role": role,
            "aliases": [k for k in res.members[cid][1:]],
            "median_min": int(round(med)), "cases": cases_n, "wait_before_h": round(wb, 1),
            "share_of_cycle": round(med / 60 / cycle_med, 3) if cycle_med else 0.0,
            "critical_path": False, "bottleneck": False, "sub": sub,
            **({"rule": rule} if rule else {}),
            "_pos": float(np.median(positions[cid])) if positions[cid] else 1.0, "_n": len(ex),
        })
    bottleneck = max(internal_waits, key=internal_waits.get) if internal_waits else None
    # critical path: nodes in >= 50% of completed cases, by median position
    for nd in nodes:
        cid = int(nd["id"][1:])
        nd["critical_path"] = nd["cases"] >= 0.5 * max(completed, 1) and nd["kind"] != "skill" or (nd["kind"] == "skill" and nd["cases"] >= 0.5 * max(completed, 1))
        nd["bottleneck"] = cid == bottleneck
    nodes.sort(key=lambda n: n["_pos"])

    # --- edges
    edge_rows = []
    for (f, t, kind), waits in edges.items():
        share = len(waits) / max(out_count[f], 1)
        row = {"from": f"n{f}", "to": f"n{t}", "kind": kind, "share": round(share, 3),
               "wait_h": round(float(np.median(waits)) / 60, 1)}
        if kind == "back":
            reason = back_reasons[(f, t)].most_common(1)[0][0]
            row["label"] = f"{reason} · {share:.0%}"
        edge_rows.append(row)
    edge_rows.sort(key=lambda e: (-e["share"], e["from"], e["to"]))

    decisions = sum(1 for n in nodes if n["kind"] == "decision")
    backs = sum(1 for e in edge_rows if e["kind"] == "back")
    skills = sum(1 for n in nodes if n["kind"] == "skill")
    artifacts = {ARTIFACT.get(t, t) for e in proc for t in e.tools if t in ARTIFACT}
    roles = [{"role": r, "steps": c, **({"external": True} if r == "Client" else {})} for r, c in role_steps.most_common()]
    roles.sort(key=lambda r: E.ROLES.index(r["role"]) if r["role"] in E.ROLES else 99)
    name_of = {int(n["id"][1:]): n["name"] for n in nodes}
    bn_name = name_of.get(bottleneck, "")
    last = max((r["approved_at"] for r in records), key=_parse)
    customers = len({e.case for e in proc if e.external})
    ontology = {
        "source": "simulated",
        "board_id": BOARD, "version": 15, "recomputed_at": last, "records_used": len(records),
        "roles": roles,
        "nodes": [{k: v for k, v in n.items() if not k.startswith("_")} for n in nodes],
        "edges": edge_rows,
        "counts": {"roles": len(roles), "steps": len(nodes), "cases": len(by_case), "files": len(artifacts),
                   "rules": decisions + sum(1 for n in nodes if n.get("rule")), "skills": skills,
                   "customers": customers, "zip_areas": 0, "branches": 3},
        "headline": f"How a proposal really moves: {len(nodes)} steps, {len(roles)} roles, {decisions} decisions, "
                    f"{backs} ways back — learned from {len(records)} approved records, drawn by nobody.",
    }

    # --- finding
    small = [a for a, _ in approvals if a < SMALL_QUOTE_USD]
    small_unchanged = sum(1 for a, sb in approvals if a < SMALL_QUOTE_USD and not sb)
    skill_nodes = [n for n in nodes if n["kind"] == "skill"]
    fill_cid = _find_cluster(res, "Fill pricing")
    repeated = []
    rep_h = 0.0
    for n in skill_nodes:
        cid = int(n["id"][1:])
        ex_all = [e for e in execs if e.cluster == cid]
        who = Counter(e.role for e in ex_all).most_common(1)[0][0]
        cnt = len(ex_all) / weeks
        mins = n["median_min"]
        tools = {t for e in ex_all for t in e.tools}
        rep_h += cnt * mins / 60
        task = "Copy figures from sheet into deck" if cid == fill_cid else n["name"]
        repeated.append({"task": task, "who": who, "count_per_wk": round(cnt, 1), "minutes": int(mins),
                         "agent_can_do": tools - {"agent"} <= AGENT_TOOLS})

    # condensed map: one row per hand-off, "to scale, one proposal". Per completed case: each row's elapsed span
    # (its steps' work plus the nights inside them) and the idle gaps between consecutive stages, attributed to the
    # stage before the gap (the board labels a wait with the next stage's role); the overnight after a step that
    # ended outside working hours belongs to the wait *for* that step (the Director's ~18:00 signature).
    # Per-row medians are scaled so that sum(hands_on_h) + sum(wait_after_h) == kpis.cycle_time_h.
    node_by_cid = {int(n["id"][1:]): n for n in nodes}
    rows_def = []
    group_of_node: dict[int, str] = {}
    for gname, grole, members, tool in MAP_GROUPS:
        cids = [c for c in (_find_cluster(res, m) for m in members) if c is not None and c in node_by_cid]
        if not cids:
            continue
        for c in cids:
            group_of_node[c] = gname
        rows_def.append((gname, grole, tool, cids))
    row_index = {g[0]: i for i, g in enumerate(rows_def)}
    hands_rows: list[list[float]] = [[] for _ in rows_def]
    wait_rows: list[list[float]] = [[] for _ in rows_def]
    n_scaled = 0
    for case, seq in by_case.items():
        b = next((x for x in seq if x.cluster == brief_cluster), None)
        s_ = next((x for x in seq if x.cluster == send_cluster), None)
        if not (b and s_ and s_.end > b.start):
            continue
        lo, hi = b.start, s_.end
        n_scaled += 1
        span_sum = [0.0] * len(rows_def)
        wait_sum = [0.0] * len(rows_def)
        ex = [x for x in seq if not x.external and x.start < hi and x.end > lo and x.cluster in group_of_node]
        for i in range(len(rows_def)):
            spans = [(x.start, x.end) for x in ex if row_index[group_of_node[x.cluster]] == i]
            span_sum[i] = E.weekday_minutes(lo, hi) - E.weekday_minutes(lo, hi) + sum(
                E.weekday_minutes(a, b2) for a, b2 in _merge_spans([(max(a, lo), min(b2, hi)) for a, b2 in spans]))
        # idle gaps = complement of all stage spans inside [lo, hi]
        merged = _merge_spans([(max(x.start, lo), min(x.end, hi)) for x in ex])
        cur = lo
        for a, b2 in merged:
            if a > cur + 1e-6:
                last = max((x for x in ex if x.end <= cur + 1e-6), key=lambda x: x.end, default=None)
                r = row_index[group_of_node[last.cluster]] if last else 0
                tail_end = min(E.to_work(cur), a) if not E.is_work_time(cur) else cur
                wait_sum[max(r - 1, 0)] += E.weekday_minutes(cur, tail_end)  # waiting *for* the step that ended after hours
                wait_sum[r] += E.weekday_minutes(tail_end, a)
            cur = max(cur, b2)
        for i in range(len(rows_def)):
            hands_rows[i].append(span_sum[i])
            wait_rows[i].append(wait_sum[i])
    map_steps = []
    if n_scaled:
        # the typical proposal: per-row medians, scaled so the parts sum to the median cycle
        h_med = [float(np.median(v)) for v in hands_rows]
        w_med = [float(np.median(v)) for v in wait_rows]
        k = cycle_med * 60 / max(sum(h_med) + sum(w_med), 1e-9)
        for i, (gname, grole, tool, cids) in enumerate(rows_def):
            ms = {"role": grole, "name": gname, "hands_on_h": round(h_med[i] * k / 60, 1), "artifact": ARTIFACT[tool],
                  "wait_after_h": round(w_med[i] * k / 60, 1)}
            if any(node_by_cid[c]["bottleneck"] for c in cids):
                ms["selected"] = True
            map_steps.append(ms)
        # make the rounded parts sum exactly to the rounded cycle, then flag the longest wait
        longest = max(map_steps, key=lambda m: m["wait_after_h"])
        resid = round(cycle_med, 1) - round(sum(m["hands_on_h"] + m["wait_after_h"] for m in map_steps), 1)
        longest["wait_after_h"] = round(longest["wait_after_h"] + resid, 1)
        longest = max(map_steps, key=lambda m: m["wait_after_h"])
        if longest["wait_after_h"] > 0:
            longest["longest_wait"] = True
    map_hands = round(sum(m["hands_on_h"] for m in map_steps), 1)
    map_wait = round(sum(m["wait_after_h"] for m in map_steps), 1)
    sent_back = []
    for e in edge_rows:
        if e["kind"] != "back":
            continue
        f, t = int(e["from"][1:]), int(e["to"][1:])
        raw_reason = back_reasons[(f, t)].most_common(1)[0][0]
        reason = next((v for k, v in REASONS.items() if raw_reason.lower().startswith(k)), raw_reason[:1].upper() + raw_reason[1:])
        cost_h = float(np.median(back_cost[(f, t)])) if back_cost[(f, t)] else 0.0
        cost = f"+{cost_h / E.WORK_DAY_MIN * 60:.1f} days".replace(".0 days", " day" if round(cost_h / 9, 1) == 1.0 else " days") if cost_h >= 9 else f"+{cost_h:.1f} h"
        by_role = node_by_cid[f]["role"]
        sent_back.append({"reason": reason, "by": by_role, "back_to": group_of_node.get(t, name_of[t]), "cost": cost, "share": e["share"]})
    sent_back.sort(key=lambda s: -s["share"])
    bn_node = next((n for n in nodes if n["bottleneck"]), None)
    longest_row = next((m for m in map_steps if m.get("longest_wait")), None)
    bn_wait = longest_row["wait_after_h"] if longest_row else (bn_node["wait_before_h"] if bn_node else 0.0)
    if bn_node and bn_node["role"] == "Director":
        headline = f"Quotes wait {bn_wait:.0f} hours for one signature."
    elif bn_node:
        headline = f"Work waits {bn_wait:.0f} hours before {bn_node['name'].lower()}."
    else:
        headline = f"A proposal takes {cycle_med:.0f} hours."
    assert len(headline) <= 60, headline
    sub = ""
    if bn_node:
        sub = (f"The {bn_node['name'].lower()} itself takes {bn_node['median_min']} minutes. Across {completed} proposals, "
               f"nobody is working on a proposal for {wait_share:.0%} of its cycle — and the longest single wait is this signature.")
    finding = {
        "source": "simulated",
        "board_id": BOARD, "process": "client proposals", "records": len(records), "people": meta["people"], "weeks": weeks,
        "headline": headline, "sub": sub.strip(),
        "kpis": {"cycle_time_h": round(cycle_med, 1), "waiting_share": round(wait_share, 3),
                 "small_quotes_share": round(len(small) / len(approvals), 3) if approvals else 0.0,
                 "small_quotes_unchanged": round(small_unchanged / len(small), 3) if small else 0.0,
                 "repeated_by_hand_h_per_wk": round(rep_h, 1)},
        "map": map_steps,
        "to_scale": {"hands_on_h": map_hands, "waiting_h": map_wait},
        "sent_back": sent_back,
        "repeated": repeated,
    }
    stats = {"cycles": cycles, "works": works, "completed": completed, "approvals": approvals, "case_rows": case_rows,
             "approval_starts": approval_starts, "bottleneck": bn_name, "origin": origin, "cluster_display": res.display}
    return {"ontology": ontology, "finding": finding, "resolver": res, "execs": execs, "stats": stats, "meta": meta}


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _find_cluster(res: Resolver, canonical: str) -> int | None:
    t = normalise(canonical)
    best, bs = None, 0.0
    for cid, ks in res.members.items():
        s = max((1.0 if normalise(k) == t else similarity(t, normalise(k))) for k in ks)
        if s > bs:
            best, bs = cid, s
    return best if bs >= 0.8 else None


def node_for(result: dict, canonical: str) -> dict | None:
    """Map a canonical step name onto a mined node (used by the simulator to fit parameters)."""
    cid = _find_cluster(result["resolver"], canonical)
    if cid is None:
        return None
    return next((n for n in result["ontology"]["nodes"] if n["id"] == f"n{cid}"), None)
