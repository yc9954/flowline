"""Pydantic models for every shape in SCHEMA.md sections 2-11.

All models use ``extra="allow"`` so new optional fields other components add pass
through untouched. Fields the schema marks optional (``?``) default to None.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal[
    "Client", "Sales", "PM", "Design", "Finance", "Director", "Legal",
    "Trainer", "BranchMgr", "Ops", "CEO",
]
Source = Literal["measured", "simulated", "prototype"]


class Shape(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- 2. Record


class RecordStep(Shape):
    idx: int
    start: str
    end: str
    name: str
    kind: Literal["hands_on", "waiting"]
    case_id: str | None = None
    tools: list[str] = Field(default_factory=list)
    handoff_from: Role | None = None
    handoff_to: Role | None = None
    waiting_on: Role | None = None
    repeats: int | None = None


class Covers(Shape):
    start: str
    end: str


class RecordBody(Shape):
    """Everything that is hashed (the Record without hash/pubkey/sig)."""

    id: str
    board_id: str
    person_id: str
    role: Role
    date: str
    covers: Covers
    steps: list[RecordStep]
    kept_private: int
    hands_on_min: int
    waiting_min: int
    approved_at: str


class Record(RecordBody):
    hash: str
    pubkey: str
    sig: str


class RecordAccepted(Shape):
    id: str
    accepted: bool = True


# ---------------------------------------------------------------- 3. Ontology


class OntologyRole(Shape):
    role: Role
    steps: int
    external: bool | None = None


class Node(Shape):
    id: str
    name: str
    kind: Literal["event", "step", "decision", "skill"]
    role: Role
    aliases: list[str] = Field(default_factory=list)
    median_min: float | None = None
    cases: int
    wait_before_h: float | None = None
    share_of_cycle: float | None = None
    critical_path: bool
    bottleneck: bool | None = None
    sub: str | None = None
    rule: str | None = None


class Edge(Shape):
    from_: str = Field(alias="from")
    to: str
    kind: Literal["then", "back", "parallel"]
    share: float | None = None
    wait_h: float | None = None
    label: str | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True, serialize_by_alias=True)


class OntologyCounts(Shape):
    roles: int
    steps: int
    cases: int
    files: int
    rules: int
    skills: int
    customers: int
    zip_areas: int
    branches: int


class Ontology(Shape):
    board_id: str
    version: int
    recomputed_at: str
    records_used: int
    roles: list[OntologyRole]
    nodes: list[Node]
    edges: list[Edge]
    counts: OntologyCounts
    headline: str
    source: Source | None = None


# ---------------------------------------------------------------- 4. Finding


class FindingKpis(Shape):
    cycle_time_h: float
    waiting_share: float
    small_quotes_share: float
    small_quotes_unchanged: float
    repeated_by_hand_h_per_wk: float


class MapStep(Shape):
    role: Role
    name: str
    hands_on_h: float
    artifact: str
    wait_after_h: float | None = None
    longest_wait: bool | None = None
    selected: bool | None = None


class ToScale(Shape):
    hands_on_h: float
    waiting_h: float


class SentBack(Shape):
    reason: str
    by: Role | None = None
    back_to: str
    cost: str
    share: float


class Repeated(Shape):
    task: str
    who: Role
    count_per_wk: float
    minutes: int
    agent_can_do: bool


class Finding(Shape):
    board_id: str
    process: str
    records: int
    people: int
    weeks: int
    headline: str
    sub: str
    kpis: FindingKpis
    map: list[MapStep]
    to_scale: ToScale
    sent_back: list[SentBack]
    repeated: list[Repeated]
    source: Source | None = None


# ---------------------------------------------------------------- 5. Plans


class PlanWho(Shape):
    role: Role
    change: str


class PlanRuleAutoApprove(Shape):
    type: Literal["auto_approve_under"]
    usd: int


class PlanRuleBatches(Shape):
    type: Literal["approver_batches_per_day"]
    n: int


class PlanRuleSkill(Shape):
    type: Literal["skill"]
    skill_id: str
    actor: Role
    reviewer: Role | None = None


class PlanRuleTemplate(Shape):
    type: Literal["template"]
    name: str


PlanRule = PlanRuleAutoApprove | PlanRuleBatches | PlanRuleSkill | PlanRuleTemplate


class Plan(Shape):
    id: str
    rank: int
    name: str
    sub: str
    hours: float
    work_h: float
    waiting_h: float
    vs_today: float
    best: bool
    today: bool
    held_best_n: int
    range_h: tuple[float, float]
    who: list[PlanWho]
    rules: list[PlanRule]


class PlansPage(Shape):
    board_id: str
    reruns: int
    weeks: int
    headline: str
    today_h: float
    plans: list[Plan]
    note: str
    source: Source | None = None


class PlanApproval(Shape):
    board_id: str
    plan_id: str
    plan_name: str
    approved_at: str
    approved_by: str | None = None
    suggestions_created: list[str] = Field(default_factory=list)


class ApproveRequest(Shape):
    approved_by: str | None = None


# ---------------------------------------------------------------- 6. Results


class Predicted(Shape):
    mid: float
    lo: float
    hi: float


class SeriesPoint(Shape):
    week: int
    value: float
    after: bool


class ResultKpi(Shape):
    label: str
    before: str
    after: str
    sub: str


class ResultWho(Shape):
    role: Role
    what: str
    before: str
    after: str


class NextConstraint(Shape):
    headline: str
    sub: str
    ready: bool


class Results(Shape):
    board_id: str
    headline: str
    sub: str
    records: int
    people: int
    weeks: int
    change: str
    predicted: Predicted
    measured: float
    series: list[SeriesPoint]
    kpis: list[ResultKpi]
    who: list[ResultWho]
    next_constraint: NextConstraint
    source: Source | None = None


# ---------------------------------------------------------------- 7. History


class LoopStep(Shape):
    n: int
    name: Literal["Record", "Map", "Find", "Test", "Approve", "Ask & do", "Measure"]
    at: str | None = None
    status: Literal["done", "now", "pending"]
    note: str


class Version(Shape):
    v: int
    when: str
    title: str
    found: str
    status: Literal["live", "needs_yes", "baseline"]
    delta_h: float
    predicted_delta_h: float | None = None


class Learned(Shape):
    finding: str
    action: str


class History(Shape):
    board_id: str
    headline: str
    loop: list[LoopStep]
    next_run_at: str
    versions: list[Version]
    learned: list[Learned]
    source: Source | None = None


# ---------------------------------------------------------------- 8. Model check


class ModelComponent(Shape):
    n: str
    name: str
    what: str
    size: str


class SimCheck(Shape):
    measure: str
    predicted: float
    lo: float
    hi: float
    actual: float
    unit: Literal["h", "%", "/day"]
    in_range: bool


class DemandRow(Shape):
    industry: str
    naics: str
    lift: float
    population_lift: float
    ci: tuple[float, float]
    verdict: Literal["better", "tie"]


class D1(Shape):
    dataset: str = "BPI Challenge 2020 Domestic Declarations"
    fit_year: int = 2017
    test_year: int = 2018
    median_error: float
    p80_error: float
    cases: int
    events: int
    amount_attr: bool


class Limit(Shape):
    title: str
    tag: str
    why: str


class ModelCheck(Shape):
    board_id: str
    calibrated_at: str
    records: int
    components: list[ModelComponent]
    sim_checks: list[SimCheck]
    demand: list[DemandRow]
    d1: D1
    limits: list[Limit]
    source: Source | None = None


# ---------------------------------------------------------------- 9. Expansion


class Industry(Shape):
    naics: str
    name: str


class ExpansionOpening(Shape):
    date: str
    was: str
    blockers_cleared: int


class Zip(Shape):
    zip: str
    name: str
    why: list[str]
    predicted: float
    happened: float
    rank: int
    pick: bool
    lat: float
    lon: float


class BacktestIndustry(Shape):
    naics: str
    name: str
    lift: float
    population_lift: float
    ci: tuple[float, float]
    verdict: Literal["better", "tie"]


class Pooled(Shape):
    lift: float
    population_lift: float


class Backtest(Shape):
    frozen_at: int = 2020
    scored_on: int = 2023
    n_zips: int
    lift: float
    ci: tuple[float, float]
    by_industry: list[BacktestIndustry]
    pooled: Pooled


class Expansion(Shape):
    board_id: str
    city: str
    industries: list[Industry]
    industry: str
    headline: str
    sub: str
    zips_considered: int
    branches: int
    records: int
    rank_of: int
    opening: ExpansionOpening
    zips: list[Zip]
    backtest: Backtest
    source: str


# ---------------------------------------------------------------- 10. Opening


class Workstream(Shape):
    name: str
    owner: Role
    agent: bool
    start: str
    end: str
    status: Literal["done", "on_track", "waiting", "todo"]
    saved_d: float | None = None
    due: str | None = None
    progress: tuple[int, int] | None = None


class Blocker(Shape):
    id: str
    title: str
    status: Literal["cleared", "waiting_on_you", "in_progress"]
    saved_d: float | None = None
    due: str | None = None
    was: str
    agent: str
    decided_by: Role
    surface: Literal["inbox", "notch", "weekly_digest"]


class Opening(Shape):
    board_id: str
    branch: int
    zip: str
    name: str
    playbook_from: str
    steps: int
    headline: str
    opens: str
    was: str
    today: str
    workstreams: list[Workstream]
    blockers: list[Blocker]
    source: Source | None = None


# ---------------------------------------------------------------- 11. Suggestions, runs, surfaces

SuggestionStatus = Literal["offered", "accepted", "declined", "never", "done"]


class AcceptRate(Shape):
    """Beta-Bernoulli tally per (person, skill). mean = (alpha) / (alpha + beta)."""

    alpha: float
    beta: float
    accepted: int
    declined: int
    mean: float


class Suggestion(Shape):
    id: str
    person_id: str
    skill_id: str
    title: str
    body: str
    why_now: str
    count_last_week: int
    minutes_each: int
    estimate_s: int
    plan_id: str
    status: SuggestionStatus
    accept_rate: AcceptRate | None = None
    created_at: str | None = None
    responded_at: str | None = None
    run_id: str | None = None
    pre_approved: bool | None = None  # SCHEMA §11: accepted on the person's standing yes (fleet fan-out), not a live answer


class RespondRequest(Shape):
    answer: Literal["do_it", "not_now", "dont_ask"]


class RunStep(Shape):
    n: int
    label: str
    detail: str
    status: Literal["done", "now", "pending"]
    progress: tuple[int, int] | None = None
    at_s: float | None = None


class RunCheck(Shape):
    name: str
    ok: bool
    detail: str


class Run(Shape):
    id: str
    skill_id: str
    target: str
    status: Literal["running", "done", "stopped", "failed"]
    started_at: str
    elapsed_s: float
    steps: list[RunStep] = Field(default_factory=list)
    checks: list[RunCheck] = Field(default_factory=list)
    person_id: str | None = None
    last_action: str | None = None


class BoardBlock(Shape):
    """Board config the API attaches to every executor run request (SCHEMA §11 `board`)."""

    id: str
    name: str
    mail_domain: str | None = None
    mail_window_title: str | None = None  # only when the board has a known webmail window title (legacy demo)
    people: list[dict[str, Any]] = Field(default_factory=list)  # [{id, role, email, name}]


class RunRequest(Shape):
    suggestion_id: str
    skill_id: str
    target: str = "mac"  # "mac" | "desk1" … "desk6"
    person_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    board: BoardBlock | None = None  # filled by the API from the suggestion's board; callers may omit it


class SkillInputs(Shape):
    sheet: str
    deck: str
    slide: int


class Skill(Shape):
    id: str
    version: int
    actor: Role
    reviewer: Role | None = None
    steps: list[str]
    inputs: SkillInputs
    saves: bool = False


class FinanceInboxItem(Shape):
    title: str
    sub: str
    actions: list[str]


class BranchMgrBlocker(Shape):
    title: str
    actions: list[str]


class ExpansionLead(Shape):
    zip: str
    rank: int


class TrainerRecord(Shape):
    steps: int
    left_out: int


class Surfaces(Shape):
    ceo_line: str
    finance_inbox: list[FinanceInboxItem]
    branch_mgr_blocker: BranchMgrBlocker
    expansion_lead: list[ExpansionLead]
    trainer_record: TrainerRecord
    source: Source | None = None


# ---------------------------------------------------------------- Boards & people (DB)


class Board(Shape):
    id: str
    name: str
    industry_naics: str | None = None
    mail_domain: str | None = None
    timezone: str = "UTC"
    created_at: str | None = None


class BoardCreate(Shape):
    id: str | None = None  # slugified from name when absent
    name: str
    industry_naics: str | None = None
    mail_domain: str | None = None
    timezone: str | None = None


class BoardPatch(Shape):
    name: str | None = None
    industry_naics: str | None = None
    mail_domain: str | None = None
    timezone: str | None = None


class BoardSummary(Board):
    people: int
    records: int
    has_data: bool


class BoardDetail(BoardSummary):
    data_dir: str
    legacy_fallback: bool = False


class Person(Shape):
    board_id: str
    id: str
    name: str
    role: str
    email: str | None = None
    target: str = "mac"  # "mac" | "desk1" … "deskN"
    skill_id: str | None = None
    pre_approved: bool = False
    inputs: dict[str, Any] = Field(default_factory=dict)
    invite_code: str | None = None
    invite_status: Literal["not_invited", "invited", "joined"] = "not_invited"
    invited_at: str | None = None  # when the current code was issued
    claimed_at: str | None = None  # when a device claimed it (joined_at is the same value)
    joined_at: str | None = None
    claimed_device: str | None = None
    created_at: str | None = None


class PersonInvite(Person):
    api_url: str  # what the person types into the Mac app next to the code


class PersonCreate(Shape):
    id: str | None = None  # slugified from name when absent
    name: str
    role: str
    email: str | None = None
    target: str | None = None
    skill_id: str | None = None
    pre_approved: bool = False
    inputs: dict[str, Any] = Field(default_factory=dict)


class PersonPatch(Shape):
    name: str | None = None
    role: str | None = None
    email: str | None = None
    target: str | None = None
    skill_id: str | None = None
    pre_approved: bool | None = None
    inputs: dict[str, Any] | None = None


class ClaimRequest(Shape):
    device: str | None = None


class ClaimResponse(Shape):
    board_id: str
    board_name: str
    person_id: str
    name: str
    role: str
    api_base_hint: str
    target: str | None = None
    skill_id: str | None = None


class NoData(Shape):
    """404 body when a board has no data file yet (never another board's data)."""

    detail: str
    state: Literal["no_data_yet"] = "no_data_yet"
    needs: str


class NoSuchBoard(Shape):
    """404 body when the board id is not in the DB."""

    detail: str
    state: Literal["no_such_board"] = "no_such_board"


# ---------------------------------------------------------------- API-only shapes


class FileStatus(Shape):
    name: str
    path: str | None
    served_from: Literal["board", "data_out", "fixtures", "missing"]
    source: str | None = None
    mtime: str | None = None
    state: Literal["no_data_yet"] | None = None


class RecomputeJob(Shape):
    job_id: str | None = None
    board_id: str | None = None
    state: Literal["idle", "running", "done", "failed"]
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    command: str | None = None
    records: str | None = None
    records_exported: int | None = None
    out: str | None = None
    industry: str | None = None
    tail: str | None = None
    stderr: str | None = None


RecomputeStatus = RecomputeJob


class BoardStatus(Shape):
    board_id: str
    board: Board | None = None
    data_dir: str  # the board's own directory (data/boards/{id}/out)
    legacy_fallback: bool  # True while northwind still reads data/out + fixtures
    data_out: str  # legacy single-company dir (only consulted when legacy_fallback)
    fixtures: str
    files: list[FileStatus]
    people: int
    records: int
    has_data: bool
    recompute: RecomputeJob
    executor_url: str
    board_dist_served: bool


class Message(Shape):
    detail: str


# Map of file name -> model so the status endpoint can report which shape a file has.
BOARD_FILE_MODELS: dict[str, type[Shape]] = {
    "ontology": Ontology,
    "finding": Finding,
    "plans": PlansPage,
    "results": Results,
    "history": History,
    "model": ModelCheck,
    "expansion": Expansion,
    "opening": Opening,
    "surfaces": Surfaces,
}
