"""Run / RunStep state (SCHEMA §11) with a JSON file per run under data/runs."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# Repo root: env FLOWLINE_ROOT, else the parent of this package (…/flowline/executor → …/flowline).
ROOT = os.environ.get("FLOWLINE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.environ.get("FLOWLINE_RUNS_DIR", os.path.join(ROOT, "data", "runs"))


def have_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class RunStep(BaseModel):
    n: int
    label: str
    detail: str = ""
    status: str = "pending"  # done | now | pending
    progress: Optional[tuple[int, int]] = None
    at_s: Optional[float] = None


class Check(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class Action(BaseModel):
    """One agent/desktop action, for the audit trail (not in SCHEMA; extra field)."""
    at: str
    at_s: float
    kind: str           # screenshot | left_click | type | key | run | read_sheet | model | ...
    detail: str = ""
    seconds: float = 0.0
    step: Optional[int] = None


class Run(BaseModel):
    id: str
    skill_id: str
    target: str
    status: str = "running"  # running | done | stopped | failed
    started_at: str = Field(default_factory=now_iso)
    elapsed_s: float = 0.0
    steps: list[RunStep] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    # extras beyond SCHEMA §11
    title: Optional[str] = None            # "Filling proposal #172 pricing from your sheet"
    suggestion_id: Optional[str] = None
    person_id: Optional[str] = None        # who this run works for (fleet: people.json)
    board: Optional[dict[str, Any]] = None # {id, name, mail_domain, mail_window_title?, people:[{id, role, email}]} from the API (board.py)
    last_action: Optional[str] = None      # "left_click 812,440" · "type \"$2,600\"" · "screenshot" (from the agent's tool_call events)
    action_count: int = 0                  # agent tool calls so far (the fleet shows it as `actions`)
    inputs: dict[str, Any] = Field(default_factory=dict)
    model: Optional[str] = None
    actions: list[Action] = Field(default_factory=list)
    final_screenshot: Optional[str] = None
    agent: dict[str, Any] = Field(default_factory=dict)   # agent-ts exit code, seconds, stdout/stderr tails
    error: Optional[str] = None
    finished_at: Optional[str] = None
    timing: dict[str, Any] = Field(default_factory=dict)


def describe_action(name: str, action: str | None, raw_input: Any) -> str:
    """Short human line for one tool call: `left_click 812,440`, `type "$2,600"`, `key Escape`, `screenshot`, `read_sheet`."""
    inp: dict = {}
    if isinstance(raw_input, dict):
        inp = raw_input
    elif isinstance(raw_input, str) and raw_input.startswith("{"):
        try:
            inp = json.loads(raw_input)
        except ValueError:
            inp = {}
    if name == "computer":
        a = action or inp.get("action") or "computer"
        c = inp.get("coordinate")
        if a == "type":
            return f'type {json.dumps(str(inp.get("text", "")))[:60]}'
        if a in ("key", "hold_key"):
            return f'{a} {inp.get("text", "")}'
        if a == "scroll" and c:
            return f'scroll {inp.get("scroll_direction", "down")} {int(c[0])},{int(c[1])}'
        if a == "left_click_drag" and inp.get("start_coordinate") and c:
            s0 = inp["start_coordinate"]
            return f"drag {int(s0[0])},{int(s0[1])} → {int(c[0])},{int(c[1])}"
        if c and isinstance(c, (list, tuple)) and len(c) == 2:
            return f"{a} {int(c[0])},{int(c[1])}"
        if a == "zoom" and inp.get("region"):
            return f'zoom {",".join(str(int(v)) for v in inp["region"])}'
        return a
    if name == "bash":
        return f'bash {str(inp.get("command", ""))[:60]}'
    if name == "read_sheet":
        return f'read_sheet {str(inp.get("path", "")).rsplit("/", 1)[-1]}'.strip()
    if name == "read_deck_cells":
        return f'read_deck_cells slide {inp.get("slide", "")}'.strip()
    return name


def new_run_id() -> str:
    return datetime.now().strftime("run-%Y%m%d-%H%M%S-") + secrets.token_hex(2)


class RunContext:
    """Mutable run with a stop flag, step helpers and persistence."""

    def __init__(self, run: Run, runs_dir: str = RUNS_DIR):
        self.run = run
        self.runs_dir = runs_dir
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._t0 = time.time()
        self.fill_total = 4          # cells to fill, for inferred progress
        self._typed = 0
        os.makedirs(runs_dir, exist_ok=True)

    # -- time ------------------------------------------------------------------
    @property
    def elapsed(self) -> float:
        return round(time.time() - self._t0, 3)

    @property
    def path(self) -> str:
        return os.path.join(self.runs_dir, f"{self.run.id}.json")

    def stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def request_stop(self) -> None:
        self.stop_event.set()

    # -- steps --------------------------------------------------------------------
    def set_steps(self, labels: list[str]) -> None:
        with self.lock:
            self.run.steps = [RunStep(n=i + 1, label=l) for i, l in enumerate(labels)]
            self.save()

    def start_step(self, n: int, detail: str = "") -> None:
        with self.lock:
            for s in self.run.steps:
                if s.n < n and s.status != "done":
                    s.status = "done"
                if s.n == n:
                    s.status = "now"
                    s.detail = detail or s.detail
                    s.at_s = self.elapsed
            self.save()

    def step_detail(self, n: int, detail: str) -> None:
        with self.lock:
            self.run.steps[n - 1].detail = detail
            self.save()

    def progress(self, n: int, done: int, total: int) -> None:
        with self.lock:
            self.run.steps[n - 1].progress = (done, total)
            self.save()

    def done_step(self, n: int, detail: str | None = None) -> None:
        with self.lock:
            s = self.run.steps[n - 1]
            s.status = "done"
            if detail is not None:
                s.detail = detail
            s.at_s = s.at_s if s.at_s is not None else self.elapsed
            self.save()

    # -- actions / checks ---------------------------------------------------------
    def log(self, kind: str, detail: str = "", seconds: float = 0.0, step: int | None = None) -> None:
        with self.lock:
            cur = next((s.n for s in self.run.steps if s.status == "now"), None)
            self.run.actions.append(Action(at=now_iso(), at_s=self.elapsed, kind=kind, detail=detail[:500],
                                           seconds=round(seconds, 3), step=step if step is not None else cur))
            if len(self.run.actions) % 5 == 0:
                self.save()

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        with self.lock:
            self.run.checks.append(Check(name=name, ok=bool(ok), detail=detail[:500]))
            self.save()
        return ok

    # -- events from the agent (agent-ts/run.mjs) ---------------------------------
    STEP_OF_TOOL = {"read_sheet": 1, "computer": 2, "bash": None, "read_deck_cells": 3}

    def apply_event(self, ev: dict) -> None:
        """Map one agent event onto RunSteps and the action log.

        `step` events are explicit (report_step tool); tool calls also move the
        steps forward when the agent forgets to report (read_sheet → 1, first
        computer action → 2 with [typed, total] progress, read_deck_cells → 3).
        """
        kind = ev.get("type", "event")
        with self.lock:
            now_step = next((s.n for s in self.run.steps if s.status == "now"), 0)
            if kind == "step":
                n = int(ev.get("step", 0) or 0)
                if 1 <= n <= len(self.run.steps):
                    if ev.get("status") == "done":
                        if self.run.steps[n - 1].status != "done":
                            if self.run.steps[n - 1].at_s is None:
                                self.start_step(n, ev.get("detail", ""))
                            self.done_step(n, ev.get("detail") or None)
                    else:
                        if self.run.steps[n - 1].status == "pending":
                            self.start_step(n, ev.get("detail", ""))
                        elif ev.get("detail"):
                            self.run.steps[n - 1].detail = ev["detail"]
                    p = ev.get("progress")
                    if p and len(p) == 2:
                        self.run.steps[n - 1].progress = (int(p[0]), int(p[1]))
                self.log("step", f"{ev.get('step')} {ev.get('status')} {ev.get('detail', '')}", step=n or None)
            elif kind == "tool_call":
                name = ev.get("name", "tool")
                action = ev.get("action")
                self.run.last_action = describe_action(name, action, ev.get("input"))
                self.run.action_count += 1
                # inferred step changes are for the 4-step deck skill; other skills report their steps themselves
                target_step = self.STEP_OF_TOOL.get(name) if len(self.run.steps) == 4 else None
                if target_step and target_step > now_step and self.run.steps[target_step - 1].status == "pending":
                    self.start_step(target_step, {1: "Reading the sheet", 2: "Filling the deck", 3: "Checking the total"}[target_step])
                    now_step = target_step
                if name == "computer" and action == "type" and now_step == 2:
                    self._typed += 1
                    st = self.run.steps[1]
                    if st.progress is None or st.progress[0] < min(self._typed, self.fill_total):
                        st.progress = (min(self._typed, self.fill_total), self.fill_total)
                label = f"{name}.{action}" if action else name
                detail = ev.get("input", "")
                if ev.get("error"):
                    detail += f" → error: {ev['error']}"
                elif ev.get("output"):
                    detail += f" → {ev['output']}"
                if ev.get("screenshot"):
                    detail += f" [{os.path.basename(ev['screenshot'])}]"
                self.log(label, detail, float(ev.get("seconds") or 0), step=now_step or None)
            elif kind == "model":
                self.log("model", f"finish={ev.get('finish')} tools={ev.get('tool_calls')} in={ev.get('input_tokens')} "
                                  f"out={ev.get('output_tokens')} {ev.get('text', '')[:160]}", step=now_step or None)
            elif kind == "done":
                self.log("agent_done", f"{ev.get('status')} steps={ev.get('steps')} {ev.get('text', '')[:300]}", float(ev.get("seconds") or 0))
            elif kind == "error":
                self.log("agent_error", str(ev.get("error", ""))[:400], float(ev.get("seconds") or 0))
            else:
                self.log(kind, json.dumps(ev)[:300])
            self.save()

    # -- finish -------------------------------------------------------------------
    def finish(self, status: str, error: str | None = None, timing: dict | None = None) -> None:
        with self.lock:
            self.run.status = status
            self.run.error = error
            self.run.finished_at = now_iso()
            if timing:
                self.run.timing = timing
            for s in self.run.steps:
                if s.status == "now":
                    s.status = "done" if status == "done" else s.status
            self.save()

    def save(self) -> None:
        with self.lock:
            self.run.elapsed_s = self.elapsed
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.run.model_dump(), f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)

    def snapshot(self) -> dict:
        with self.lock:
            self.run.elapsed_s = self.elapsed
            return self.run.model_dump()

    def compact(self) -> dict:
        """Run for the fleet: `actions` is the tool-call count (not the audit list) and the last few actions ride along."""
        with self.lock:
            self.run.elapsed_s = self.elapsed
            return compact_run(self.run.model_dump())


def compact_run(full: dict, recent: int = 12) -> dict:
    """Same transformation for a saved run file: drop the action list, keep its size and tail."""
    acts = full.get("actions") or []
    if isinstance(acts, list):
        tail = [{"at": a.get("at"), "at_s": a.get("at_s"), "kind": a.get("kind"),
                 "text": _action_text(a), **_action_xy(a)} for a in acts[-recent:] if isinstance(a, dict)]
        n = sum(1 for a in acts if isinstance(a, dict) and str(a.get("kind", "")).startswith(("computer.", "read_", "bash")))
        pointer = next(({**_action_xy(a), "at_s": a.get("at_s"), "kind": a.get("kind")} for a in reversed(acts)
                        if isinstance(a, dict) and _action_xy(a)), None)
        full = dict(full, actions=max(n, int(full.get("action_count") or 0)), recent_actions=tail, pointer=pointer)
        if not full.get("last_action"):
            last = next((a for a in reversed(acts) if isinstance(a, dict) and str(a.get("kind", "")).startswith(("computer.", "read_", "bash"))), None)
            if last:
                full["last_action"] = _action_text(last)
    full.pop("agent", None)
    full.pop("inputs", None)
    return full


def _action_xy(a: dict) -> dict:
    """{x, y} in the agent's screenshot space (≤1280×720; the bridge scales to the desk) for pointer actions."""
    kind = str(a.get("kind", ""))
    if not kind.startswith("computer."):
        return {}
    raw = str(a.get("detail", "")).split(" → ", 1)[0].split(" [", 1)[0]
    try:
        inp = json.loads(raw) if raw.startswith("{") else {}
    except ValueError:
        return {}
    c = inp.get("coordinate") or (inp.get("start_coordinate") if kind.endswith("drag") else None)
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            return {"x": int(float(c[0])), "y": int(float(c[1]))}
        except (TypeError, ValueError):
            return {}
    return {}


def _action_text(a: dict) -> str:
    kind = str(a.get("kind", ""))
    detail = str(a.get("detail", ""))
    if kind.startswith("computer."):
        return describe_action("computer", kind.split(".", 1)[1], detail.split(" → ", 1)[0].split(" [", 1)[0])
    if kind in ("read_sheet", "read_deck_cells", "bash"):
        return describe_action(kind, None, detail.split(" → ", 1)[0])
    if kind == "step":
        return f"step {detail[:80]}"
    return f"{kind} {detail[:80]}".strip()
