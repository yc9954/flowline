"""Shared discrete-event machinery for the Northwind world engine and the fitted team simulator.

Both run the same proposal process script (18 steps, 7 roles) on SimPy; they differ only in the
parameters they are given (hidden truth vs. values fitted to approved records) and in whether they
emit Records. Time is in minutes since Monday 00:00 local (America/Chicago) of week 1.

Common random numbers: every case owns a fixed table of uniforms indexed by (step key, k-th use), so
two runs with the same seed and different plan rules draw identical durations and decisions wherever
the path coincides.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import simpy
from scipy.special import ndtri

TZ = ZoneInfo("America/Chicago")
DAY = 1440
WORK_START = 9 * 60
WORK_END = 18 * 60
WORK_DAY_MIN = WORK_END - WORK_START
ROLES = ["Client", "Sales", "PM", "Design", "Finance", "Director", "Legal"]

# Canonical process steps: id, display name, role, kind, tools used.
STEPS = [
    ("request_in", "Request in", "Client", "event", ["mail"]),
    ("qualify", "Qualify", "Sales", "decision", ["crm"]),
    ("discovery", "Discovery call", "Sales", "step", ["calendar", "meet"]),
    ("brief", "Write brief", "Sales", "step", ["docs"]),
    ("scope", "Scope & staffing", "PM", "step", ["docs", "sheets"]),
    ("availability", "Check availability", "PM", "step", ["calendar"]),
    ("estimate", "Estimate", "PM", "step", ["sheets"]),
    ("margin", "Margin check", "Finance", "decision", ["sheets"]),
    ("approval", "Approval", "Director", "step", ["mail", "sheets"]),
    ("cases", "Pick case studies", "Sales", "step", ["drive"]),
    ("concept", "Concept & deck", "Design", "step", ["slides"]),
    ("fill", "Fill pricing", "PM", "skill", ["sheets", "slides"]),
    ("review", "Internal review", "Director", "decision", ["slides"]),
    ("terms", "Terms / MSA", "Legal", "step", ["docs", "pdf"]),
    ("send", "Send", "Sales", "step", ["mail", "pdf"]),
    ("negotiate", "Negotiate", "Client", "decision", ["mail"]),
    ("signed", "Signed", "Client", "event", ["pdf"]),
    ("kickoff", "Kickoff hand-off", "Sales", "step", ["docs", "meet"]),
]
STEP_BY_ID = {s[0]: s for s in STEPS}
STEP_ROLE = {s[0]: s[2] for s in STEPS}
STEP_NAME = {s[0]: s[1] for s in STEPS}
STEP_KIND = {s[0]: s[3] for s in STEPS}
STEP_TOOLS = {s[0]: s[4] for s in STEPS}
SEQUENCE = [s[0] for s in STEPS]


# ----------------------------------------------------------------------------- calendar helpers
def day_of(t: float) -> int:
    return int(t // DAY)


def weekday(t: float) -> int:
    return day_of(t) % 7


def is_work_time(t: float) -> bool:
    m = t - day_of(t) * DAY
    return weekday(t) < 5 and WORK_START <= m < WORK_END


def to_work(t: float) -> float:
    """Earliest time >= t that falls inside working hours (Mon-Fri 09:00-18:00)."""
    d = day_of(t)
    m = t - d * DAY
    if d % 7 < 5:
        if WORK_START <= m < WORK_END:
            return t
        if m < WORK_START:
            return d * DAY + WORK_START
    d += 1
    while d % 7 >= 5:
        d += 1
    return d * DAY + WORK_START


def business_minutes(a: float, b: float) -> float:
    """Working minutes between a and b (b >= a)."""
    if b <= a:
        return 0.0
    total = 0.0
    t = a
    while t < b:
        d = day_of(t)
        if d % 7 < 5:
            s = max(t, d * DAY + WORK_START)
            e = min(b, d * DAY + WORK_END)
            if e > s:
                total += e - s
        t = (d + 1) * DAY
    return total


def weekday_minutes(a: float, b: float) -> float:
    """Minutes between a and b on a Mon-Fri 24 h calendar (weekends removed, nights kept)."""
    if b <= a:
        return 0.0
    total = 0.0
    t = a
    while t < b:
        d = day_of(t)
        nxt = (d + 1) * DAY
        if d % 7 < 5:
            total += min(b, nxt) - t
        t = nxt
    return total


def add_business_minutes(t: float, w: float) -> float:
    """Time at which w working minutes have elapsed after t."""
    t = to_work(t)
    while w > 1e-9:
        eod = day_of(t) * DAY + WORK_END
        chunk = min(w, eod - t)
        t += chunk
        w -= chunk
        if w > 1e-9:
            t = to_work(t)
    return t


def minutes_to_dt(t: float, origin: datetime) -> datetime:
    return origin + timedelta(minutes=float(t))


def iso(t: float, origin: datetime) -> str:
    return minutes_to_dt(t, origin).isoformat(timespec="seconds")


def dt_to_minutes(dt: datetime, origin: datetime) -> float:
    return (dt - origin).total_seconds() / 60.0


def monday_origin(date_str: str) -> datetime:
    d = datetime.fromisoformat(date_str).replace(tzinfo=TZ)
    assert d.weekday() == 0, "world must start on a Monday"
    return d


# ----------------------------------------------------------------------------- parameters
@dataclass
class Params:
    """Everything the process script needs. Durations are lognormal (mu, sigma) in minutes."""

    durations: dict[str, tuple[float, float]]
    p_qualify: float = 0.82
    p_margin_ok: float = 0.78
    p_missing_small: float = 0.02  # Approval sends back to Estimate, quotes under threshold
    p_missing_large: float = 0.40  # same, quotes at/over threshold
    p_review_fail_figures: float = 0.18  # review sends the deck back: pricing figures wrong (hand-copied)
    p_review_fail_layout: float = 0.09  # ... layout / template problems
    p_review_fail_other: float = 0.08  # ... wording and the rest
    p_revise: float = 0.30
    p_win: float = 0.41
    p_new_client: float = 0.40
    amount: tuple[float, float] = (math.log(3000.0), 0.92)  # lognormal USD
    small_threshold: float = 5000.0
    approver_hours: list[float] = field(default_factory=lambda: [18.0])  # batch sign-off times (h)
    approver_jitter_min: float = 10.0
    arrivals: list[float] = field(default_factory=lambda: [1.0, 1.0, 0.8, 0.7, 0.5])  # per weekday
    staff: dict[str, int] = field(default_factory=lambda: {"Sales": 2, "PM": 1, "Design": 2, "Finance": 1, "Director": 1, "Legal": 1})
    rework_factor: float = 0.35  # a redo takes this share of a full step
    director_blocks: list[tuple[float, float, float]] | None = None  # (hour, mu_min, sigma) busy blocks
    review_wait: tuple[float, float] | None = None  # fitted business-minute wait before review (lognormal)
    renewals_per_week: float = 0.0  # PM fills pricing for membership renewals (another process)
    skill_fill_min: float = 1.0  # agent time to fill the deck
    skill_review_min: float = 3.0  # PM checks the agent's fill
    skill_undo_p: float = 0.05  # PM undoes the fill and does it by hand
    export_pdf_min: float = 1.0  # v14: agent renames and exports the PDF for Sales

    def copy(self) -> "Params":
        import copy

        return copy.deepcopy(self)


def lognorm_params(median_min: float, sigma: float) -> tuple[float, float]:
    return (math.log(median_min), sigma)


def truth_params() -> Params:
    """Hidden truth of Northwind Fitness. Only world.py reads this; the simulator is fitted to records."""
    med = {
        "request_in": (1.0, 0.1),
        "qualify": (15.0, 0.45),
        "discovery": (45.0, 0.30),
        "brief": (180.0, 0.35),
        "scope": (72.0, 0.35),
        "availability": (20.0, 0.40),
        "estimate": (300.0, 0.35),
        "margin": (30.0, 0.40),
        "approval": (18.0, 0.30),
        "cases": (40.0, 0.40),
        "concept": (564.0, 0.35),
        "fill": (22.0, 0.30),
        "review": (60.0, 0.40),
        "terms": (120.0, 0.40),
        "send": (6.0, 0.35),
        "negotiate": (3 * DAY, 0.50),
        "signed": (5.0, 0.30),
        "kickoff": (60.0, 0.35),
    }
    return Params(
        durations={k: lognorm_params(m, s) for k, (m, s) in med.items()},
        director_blocks=[(9.5, 75.0, 0.3), (13.0, 75.0, 0.3), (15.5, 60.0, 0.3)],
        renewals_per_week=5.0,
        skill_undo_p=1 / 22,
    )


# ----------------------------------------------------------------------------- plan rules
def rules_to_params(base: Params, rules: list[dict]) -> tuple[Params, dict]:
    """Apply SCHEMA section 5 PlanRule objects. Returns (params, flags)."""
    p = base.copy()
    flags = {"auto_under": 0.0, "skill_fill": False, "template": False, "skill_pdf": False}
    for r in rules:
        t = r["type"]
        if t == "auto_approve_under":
            flags["auto_under"] = float(r["usd"])
        elif t == "approver_batches_per_day":
            n = int(r["n"])
            evening = max(base.approver_hours) if base.approver_hours else 18.0
            if n <= 1:
                p.approver_hours = [evening]
            else:
                # spread extra sign-off sessions through the working day, keep the fitted evening one
                hours = [9.0 + (evening - 9.0) * (i + 1) / n for i in range(n - 1)] + [evening]
                p.approver_hours = sorted(round(h, 2) for h in hours)
        elif t == "skill":
            if r["skill_id"] == "fill_deck_from_sheet":
                flags["skill_fill"] = True
            elif r["skill_id"] == "rename_export_pdf":
                flags["skill_pdf"] = True
        elif t == "template":
            flags["template"] = True
    return p, flags


# ----------------------------------------------------------------------------- random tables
_KEY_CACHE: dict[str, int] = {}


def _key_hash(key: str) -> int:
    h = _KEY_CACHE.get(key)
    if h is None:
        h = int(hashlib.blake2b(key.encode(), digest_size=4).hexdigest(), 16)
        _KEY_CACHE[key] = h
    return h


class CaseRandom:
    """Fixed uniforms per (key, k) for one case: identical across plans for the same seed."""

    def __init__(self, seed: int, idx: int, n_per_key: int = 12):
        self.seed, self.idx, self.n = seed, idx, n_per_key
        self._tables: dict[str, np.ndarray] = {}
        self._used: dict[str, int] = {}

    def _table(self, key: str) -> np.ndarray:
        t = self._tables.get(key)
        if t is None:
            g = np.random.default_rng([self.seed, self.idx, _key_hash(key)])
            t = g.random(self.n)
            self._tables[key] = t
        return t

    def uniform(self, key: str) -> float:
        k = self._used.get(key, 0)
        self._used[key] = k + 1
        t = self._table(key)
        if k < self.n:
            return float(t[k])
        g = np.random.default_rng([self.seed, self.idx, _key_hash(key), k])
        return float(g.random())

    def lognormal(self, key: str, mu: float, sigma: float) -> float:
        u = min(max(self.uniform(key), 1e-9), 1 - 1e-9)
        return float(math.exp(mu + sigma * ndtri(u)))

    def bernoulli(self, key: str, p: float) -> bool:
        return self.uniform(key) < p


def arrivals_for(seed: int, weeks: int, rates: list[float]) -> list[float]:
    """Poisson arrivals by weekday, uniform within working hours. Minutes from origin, sorted."""
    g = np.random.default_rng([seed, _key_hash("arrivals")])
    out = []
    for d in range(weeks * 7):
        wd = d % 7
        if wd >= 5:
            continue
        n = g.poisson(rates[wd])
        for _ in range(n):
            out.append(d * DAY + WORK_START + g.random() * WORK_DAY_MIN)
    return sorted(out)


# ----------------------------------------------------------------------------- run records
@dataclass
class StepRun:
    case: str
    case_idx: int
    step: str
    role: str
    person: str
    start: float
    end: float
    segments: list[tuple[float, float]]
    rework: bool = False
    outcome: str = ""  # e.g. "ok", "below margin", "missing figures", "changes", "revise quote"
    amount: float | None = None
    by_agent: bool = False
    pass_no: int = 1


@dataclass
class CaseResult:
    case: str
    case_idx: int
    arrival: float
    amount: float
    new_client: bool
    qualified: bool
    brief_start: float | None = None
    first_send_end: float | None = None
    signed: bool | None = None
    done: float | None = None
    auto_approved: int = 0
    fills_by_agent: int = 0
    fills_undone: int = 0
    runs: list[StepRun] = field(default_factory=list)


class Approver:
    """Batching approver: signs everything queued at fixed times of day, on working days."""

    def __init__(self, env: simpy.Environment, hours: list[float], jitter_min: float, person: simpy.PriorityResource,
                 seed: int, sign: "callable"):
        self.env, self.hours, self.jitter, self.person, self.sign = env, sorted(hours), jitter_min, person, sign
        self.queue: list = []
        self.rng = np.random.default_rng([seed, _key_hash("approver")])
        self.sessions: list[float] = []
        env.process(self.run())

    def request(self, case):
        ev = self.env.event()
        self.queue.append((case, ev))
        return ev

    def _next_session(self, now: float) -> float:
        d = day_of(now)
        for _ in range(14):
            if d % 7 < 5:
                for h in self.hours:
                    t = d * DAY + h * 60 + self.rng.normal(0, self.jitter)
                    if t > now:
                        return t
            d += 1
        return now + DAY

    def run(self):
        while True:
            t = self._next_session(self.env.now)
            yield self.env.timeout(max(0.0, t - self.env.now))
            if not self.queue:
                continue
            items, self.queue = self.queue, []
            with self.person.request(priority=0) as req:
                yield req
                self.sessions.append(self.env.now)
                for case, ev in items:
                    start = self.env.now
                    yield self.env.timeout(self.sign(case))
                    ev.succeed((start, self.env.now))


class Team:
    def __init__(self, env: simpy.Environment, staff: dict[str, int]):
        self.env = env
        self.people: dict[str, list[tuple[str, simpy.PriorityResource]]] = {}
        for role, n in staff.items():
            self.people[role] = [(f"{role.lower()}-{i + 1}", simpy.PriorityResource(env, capacity=1)) for i in range(n)]

    def pick(self, role: str, u: float) -> tuple[str, simpy.PriorityResource]:
        ppl = self.people[role]
        return ppl[min(int(u * len(ppl)), len(ppl) - 1)]

    def least_busy(self, role: str) -> tuple[str, simpy.PriorityResource]:
        return min(self.people[role], key=lambda pr: (len(pr[1].queue) + pr[1].count, pr[0]))


def do_work(env: simpy.Environment, res: simpy.PriorityResource, minutes: float, priority: int = 1,
            calendar: bool = True):
    """Hold a person's resource and work `minutes`, pausing outside working hours. Returns segments."""
    with res.request(priority=priority) as req:
        yield req
        segs = []
        remaining = minutes
        if calendar:
            t = to_work(env.now)
            if t > env.now:
                yield env.timeout(t - env.now)
        while remaining > 1e-9:
            t = env.now
            if calendar:
                eod = day_of(t) * DAY + WORK_END
                chunk = min(remaining, eod - t)
            else:
                chunk = remaining
            yield env.timeout(chunk)
            segs.append((t, env.now))
            remaining -= chunk
            if remaining > 1e-9:
                nt = to_work(env.now)
                yield env.timeout(nt - env.now)
        return segs


# ----------------------------------------------------------------------------- the process
class ProcessRun:
    """One simulation run of the proposal process under a rule schedule.

    rule_schedule: list of (t_from_minutes, rules) sorted by time; rules active for a decision are those of
    the latest entry with t_from <= now. Pass [(0, rules)] for a single plan.
    """

    def __init__(self, params: Params, seed: int, weeks: int, rule_schedule: list[tuple[float, list[dict]]],
                 drain_days: int = 21):
        self.base = params
        self.seed = seed
        self.weeks = weeks
        self.schedule = sorted(rule_schedule, key=lambda x: x[0])
        self.drain_days = drain_days
        self.env = simpy.Environment()
        self.team = Team(self.env, params.staff)
        self.cases: list[CaseResult] = []
        self.extra_runs: list[StepRun] = []  # renewals etc.
        self._prepared = {t: rules_to_params(params, rules) for t, rules in self.schedule}
        self.director = self.team.people["Director"][0][1]
        # one approver whose hours follow the active rules
        self.approver = Approver(self.env, self.active(0)[0].approver_hours, params.approver_jitter_min,
                                 self.director, seed, self._sign_minutes)
        self._sign_case: dict[str, CaseRandom] = {}

    # --- rules
    def active(self, t: float) -> tuple[Params, dict]:
        cur = self._prepared[self.schedule[0][0]]
        for t0, _ in self.schedule:
            if t0 <= t:
                cur = self._prepared[t0]
        return cur

    def _sign_minutes(self, case: CaseResult) -> float:
        mu, s = self.base.durations["approval"]
        return self._sign_case[case.case].lognormal("dur:approval", mu, s)

    # --- helpers
    def _dur(self, rnd: CaseRandom, step: str, rework: bool = False, p: Params | None = None) -> float:
        p = p or self.base
        mu, s = p.durations[step]
        d = rnd.lognormal(f"dur:{step}", mu, s)
        return d * p.rework_factor if rework else d

    def _step(self, case: CaseResult, rnd: CaseRandom, step: str, person: tuple[str, simpy.PriorityResource],
              minutes: float, rework=False, outcome="", amount=None, by_agent=False, pass_no=1, calendar=True,
              priority=1):
        segs = yield self.env.process(do_work(self.env, person[1], minutes, priority=priority, calendar=calendar))
        run = StepRun(case.case, case.case_idx, step, STEP_ROLE[step], person[0], segs[0][0], segs[-1][1], segs,
                      rework=rework, outcome=outcome, amount=amount, by_agent=by_agent, pass_no=pass_no)
        case.runs.append(run)
        return run

    # --- schedule switching
    def _rule_switcher(self):
        for t0, _ in self.schedule[1:]:
            yield self.env.timeout(max(0.0, t0 - self.env.now))
            p, _ = self.active(self.env.now)
            self.approver.hours = sorted(p.approver_hours)

    def _director_blocks(self):
        blocks = self.base.director_blocks
        if not blocks:
            return
        g = np.random.default_rng([self.seed, _key_hash("director_blocks")])
        total_days = self.weeks * 7 + self.drain_days
        for d in range(total_days):
            if d % 7 >= 5:
                continue
            for hour, mu, sig in blocks:
                t = d * DAY + hour * 60 + g.normal(0, 15)
                yield self.env.timeout(max(0.0, t - self.env.now))
                length = float(np.exp(np.log(mu) + sig * g.standard_normal()))
                self.env.process(do_work(self.env, self.director, length, priority=1))
            yield self.env.timeout(max(0.0, (d + 1) * DAY - self.env.now))

    def _renewals(self):
        rate = self.base.renewals_per_week
        if rate <= 0:
            return
        g = np.random.default_rng([self.seed, _key_hash("renewals")])
        pm = self.team.people["PM"][0]
        n = 0
        for d in range(self.weeks * 7):
            if d % 7 >= 5:
                continue
            k = g.poisson(rate / 5)
            times = sorted(d * DAY + WORK_START + g.random(k) * WORK_DAY_MIN)
            for t in times:
                yield self.env.timeout(max(0.0, t - self.env.now))
                n += 1
                case = CaseResult(f"renewal #{300 + n}", -n, t, 0.0, False, True)
                rnd = CaseRandom(self.seed, 10_000 + n)
                p, flags = self.active(self.env.now)
                self.env.process(self._renewal(case, rnd, pm, p, flags))

    def _renewal(self, case, rnd, pm, p, flags):
        if flags["skill_fill"]:
            run = yield self.env.process(self._step(case, rnd, "fill", pm, p.skill_review_min, by_agent=True))
        else:
            run = yield self.env.process(self._step(case, rnd, "fill", pm, self._dur(rnd, "fill", p=p)))
        self.extra_runs.append(run)

    # --- the case script
    def _case(self, case: CaseResult, rnd: CaseRandom):
        env, team, base = self.env, self.team, self.base
        self._sign_case[case.case] = rnd
        sales = team.pick("Sales", rnd.uniform("owner"))
        pm = team.people["PM"][0]
        finance = team.people["Finance"][0]
        director = team.people["Director"][0]
        legal = team.people["Legal"][0]

        yield env.process(self._step(case, rnd, "request_in", sales, self._dur(rnd, "request_in"), amount=None, priority=0))
        q = yield env.process(self._step(case, rnd, "qualify", sales, self._dur(rnd, "qualify")))
        if not rnd.bernoulli("dec:qualify", base.p_qualify):
            q.outcome = "declined"
            case.qualified = False
            case.done = env.now
            return
        q.outcome = "fit"
        yield env.process(self._step(case, rnd, "discovery", sales, self._dur(rnd, "discovery")))
        b = yield env.process(self._step(case, rnd, "brief", sales, self._dur(rnd, "brief")))
        case.brief_start = b.start

        # Scope & staffing || Check availability (both PM; parallel branches, one person)
        p1 = env.process(self._step(case, rnd, "scope", pm, self._dur(rnd, "scope")))
        p2 = env.process(self._step(case, rnd, "availability", pm, self._dur(rnd, "availability")))
        yield p1 & p2

        pass_no = 0
        first_send_done = False
        deck_done = False
        while True:  # estimate -> margin -> approval -> deck -> review -> terms -> send, with loops
            pass_no += 1
            rework = pass_no > 1
            yield env.process(self._step(case, rnd, "estimate", pm, self._dur(rnd, "estimate", rework), rework=rework, pass_no=pass_no))
            # margin check loop
            while True:
                ok = rnd.bernoulli("dec:margin", base.p_margin_ok)
                yield env.process(self._step(case, rnd, "margin", finance, self._dur(rnd, "margin"), outcome="ok" if ok else "below 25% margin", pass_no=pass_no))
                if ok:
                    break
                yield env.process(self._step(case, rnd, "estimate", pm, self._dur(rnd, "estimate", True), rework=True, pass_no=pass_no))
            # approval (batched) or auto-approve rule
            p, flags = self.active(env.now)
            if flags["auto_under"] and case.amount < flags["auto_under"]:
                case.auto_approved += 1
                sent_back = False
            else:
                ev = self.approver.request(case)
                start, end = yield ev
                small = case.amount < base.small_threshold
                sent_back = rnd.bernoulli("dec:approval", base.p_missing_small if small else base.p_missing_large)
                run = StepRun(case.case, case.case_idx, "approval", "Director", director[0], start, end, [(start, end)],
                              outcome="missing figures" if sent_back else "approved", amount=case.amount, pass_no=pass_no)
                case.runs.append(run)
            if sent_back:
                continue  # back to Estimate

            # Concept & deck (Design) || Pick case studies (Sales)
            deck_pass = 0
            while True:
                deck_pass += 1
                p, flags = self.active(env.now)
                redo = deck_done or deck_pass > 1
                dmin = self._dur(rnd, "concept", redo)
                design = team.least_busy("Design")
                d1 = env.process(self._step(case, rnd, "concept", design, dmin, rework=redo, pass_no=pass_no))
                if not deck_done:
                    deck_done = True
                    d2 = env.process(self._step(case, rnd, "cases", sales, self._dur(rnd, "cases")))
                    yield d1 & d2
                else:
                    yield d1
                # Fill pricing (PM) — by hand, or by the agent with PM review
                p, flags = self.active(env.now)
                fill_by_agent = False
                if flags["skill_fill"]:
                    yield env.process(self._step(case, rnd, "fill", pm, p.skill_fill_min + p.skill_review_min, by_agent=True, pass_no=pass_no))
                    case.fills_by_agent += 1
                    fill_by_agent = True
                    if rnd.bernoulli("dec:undo", p.skill_undo_p):
                        case.fills_undone += 1
                        fill_by_agent = False
                        yield env.process(self._step(case, rnd, "fill", pm, self._dur(rnd, "fill"), rework=True, outcome="undone, redone by hand", pass_no=pass_no))
                else:
                    yield env.process(self._step(case, rnd, "fill", pm, self._dur(rnd, "fill"), pass_no=pass_no))
                # Internal review (Director). Fitted sims model the Director's other load as a wait.
                if base.review_wait is not None:
                    w = rnd.lognormal("wait:review", *base.review_wait)
                    yield env.timeout(max(0.0, add_business_minutes(env.now, w) - env.now))
                u = rnd.uniform("dec:review")
                p_fig = 0.0 if fill_by_agent else base.p_review_fail_figures
                p_lay = 0.0 if flags["template"] else base.p_review_fail_layout
                if u < p_fig:
                    outcome = "changes: figures"
                elif u < base.p_review_fail_figures + p_lay:
                    outcome = "changes: layout"
                elif u < base.p_review_fail_figures + base.p_review_fail_layout + base.p_review_fail_other:
                    outcome = "changes: wording"
                else:
                    outcome = "ok"
                yield env.process(self._step(case, rnd, "review", director, self._dur(rnd, "review"), outcome=outcome, pass_no=pass_no))
                if outcome == "ok":
                    break
            if case.new_client and not first_send_done:
                yield env.process(self._step(case, rnd, "terms", legal, self._dur(rnd, "terms")))
            p, flags = self.active(env.now)
            send_min = self._dur(rnd, "send")
            if flags["skill_pdf"]:
                send_min = min(send_min, p.export_pdf_min) + 0.5
            s = yield env.process(self._step(case, rnd, "send", sales, send_min, pass_no=pass_no, by_agent=flags["skill_pdf"]))
            if not first_send_done:
                case.first_send_end = s.end
                first_send_done = True
            # Client negotiates (wall clock, not calendar-bound)
            revise = rnd.bernoulli("dec:revise", base.p_revise)
            n_start = env.now
            yield env.timeout(self._dur(rnd, "negotiate"))
            case.runs.append(StepRun(case.case, case.case_idx, "negotiate", "Client", "client", n_start, env.now, [(n_start, env.now)],
                                     outcome="revise quote" if revise else "accepted terms", pass_no=pass_no))
            if revise and pass_no < 3:
                continue
            break
        won = rnd.bernoulli("dec:win", base.p_win)
        case.signed = won
        if won:
            yield env.process(self._step(case, rnd, "signed", sales, self._dur(rnd, "signed"), outcome="won"))
            yield env.process(self._step(case, rnd, "kickoff", sales, self._dur(rnd, "kickoff")))
        else:
            case.runs.append(StepRun(case.case, case.case_idx, "negotiate", "Client", "client", env.now, env.now, [(env.now, env.now)], outcome="lost"))
        case.done = env.now

    def _arrivals(self):
        times = arrivals_for(self.seed, self.weeks, self.base.arrivals)
        for i, t in enumerate(times):
            yield self.env.timeout(max(0.0, t - self.env.now))
            rnd = CaseRandom(self.seed, i)
            amount = rnd.lognormal("amount", *self.base.amount)
            new_client = rnd.bernoulli("new_client", self.base.p_new_client)
            case = CaseResult(f"proposal #{160 + i}", i, t, round(amount, -1), new_client, True)
            self.cases.append(case)
            self.env.process(self._case(case, rnd))

    def run(self) -> "ProcessRun":
        self.env.process(self._arrivals())
        self.env.process(self._renewals())
        self.env.process(self._director_blocks())
        if len(self.schedule) > 1:
            self.env.process(self._rule_switcher())
        self.env.run(until=(self.weeks * 7 + self.drain_days) * DAY)
        return self


# ----------------------------------------------------------------------------- measurement
def union_minutes(intervals: list[tuple[float, float]], lo: float, hi: float) -> float:
    segs = sorted((max(a, lo), min(b, hi)) for a, b in intervals if min(b, hi) > max(a, lo))
    total, cur_a, cur_b = 0.0, None, None
    for a, b in segs:
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total


def case_kpis(case: CaseResult) -> dict | None:
    """Cycle (brief start -> first send end, wall-clock hours), hands-on union, waiting, approval wait."""
    if case.brief_start is None or case.first_send_end is None:
        return None
    lo, hi = case.brief_start, case.first_send_end
    hands = [(s, e) for r in case.runs if r.role != "Client" for (s, e) in r.segments]
    work = union_minutes(hands, lo, hi)
    cycle = weekday_minutes(lo, hi)
    # approval wait: from the end of the last step before Approval to the start of the step after it
    appr_wait = 0.0
    runs = sorted((r for r in case.runs if r.role != "Client" and r.start < hi), key=lambda r: r.start)
    for i, r in enumerate(runs):
        if r.step == "approval":
            prev_end = max((x.end for x in runs[:i]), default=r.start)
            nxt = next((x.start for x in runs[i + 1:] if x.step in ("concept", "estimate")), r.end)
            appr_wait += weekday_minutes(prev_end, r.start) + weekday_minutes(r.end, nxt)
    return {"cycle_h": cycle / 60, "work_h": work / 60, "waiting_h": (cycle - work) / 60,
            "approval_wait_h": appr_wait / 60, "passes": max((r.pass_no for r in runs), default=1)}


def summarize(cases: list[CaseResult], t_lo: float, t_hi: float, runs_extra: list[StepRun] | None = None) -> dict:
    """KPIs over cases whose brief started in [t_lo, t_hi)."""
    sel = [c for c in cases if c.brief_start is not None and t_lo <= c.brief_start < t_hi]
    ks = [k for k in (case_kpis(c) for c in sel) if k]
    weeks = max((t_hi - t_lo) / (7 * DAY), 1e-9)
    workdays = max(round(weeks * 5), 1)
    signoffs = sum(1 for c in cases for r in c.runs if r.step == "approval" and t_lo <= r.start < t_hi)
    sends = sum(1 for c in cases for r in c.runs if r.step == "send" and t_lo <= r.start < t_hi)
    fills = [r for c in cases for r in c.runs if r.step == "fill" and t_lo <= r.start < t_hi]
    fills += [r for r in (runs_extra or []) if r.step == "fill" and t_lo <= r.start < t_hi]
    agent_fills = sum(1 for r in fills if r.by_agent)
    undone = sum(1 for r in fills if r.outcome.startswith("undone"))
    if not ks:
        return {"n": 0}
    cyc = np.array([k["cycle_h"] for k in ks])
    work = np.array([k["work_h"] for k in ks])
    wait = np.array([k["waiting_h"] for k in ks])
    return {
        "n": len(ks),
        "cycle_h": float(np.median(cyc)),
        "cycle_mean_h": float(cyc.mean()),
        "cycle_p80_h": float(np.percentile(cyc, 80)),
        "work_h": float(np.median(work)),
        "waiting_h": float(np.median(wait)),
        "waiting_share": float(wait.sum() / max(cyc.sum(), 1e-9)),
        "approval_wait_h": float(np.median([k["approval_wait_h"] for k in ks])),
        "approval_wait_signed_h": float(np.median([k["approval_wait_h"] for k in ks if k["approval_wait_h"] > 0])) if any(k["approval_wait_h"] > 0 for k in ks) else 0.0,
        "signed_cases": sum(1 for k in ks if k["approval_wait_h"] > 0),
        "signoffs_per_day": signoffs / workdays,
        "sends_per_day": sends / workdays,
        "fills_per_week": len(fills) / weeks,
        "agent_fills": agent_fills,
        "fills_undone": undone,
        "cases": [{"case": c.case, "brief_start": c.brief_start, **k} for c, k in zip(sel, (case_kpis(c) for c in sel)) if k],
    }
