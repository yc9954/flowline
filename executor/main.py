"""Executor service (SCHEMA §11) on port 8790.

Run API
  POST /runs {suggestion_id, skill_id, target: "mac"|"desk1"|…|"desk6", person_id?, inputs} → Run (201)
                           409 when that target already has a running run (one run per desk)
                           unknown skill → Run with status "failed" and the check skill_available=false (201, no crash)
  GET  /runs/{id}          poll (500 ms); ?compact=1 for the fleet shape
  GET  /runs/active        running runs (compact: `actions` is the tool-call count, `recent_actions` the tail)
  POST /runs/{id}/stop     stop flag; the agent child process is killed, the run ends "stopped"
  POST /runs/{id}/events   step events from the TS agent (agent-ts/run.mjs)
  GET  /runs · GET /skills · GET /health

Desktop bridge (used by the TS agent and the board, one Desktop + persistent helper per target)
  GET  /desk/{target}/view                 display + model-view size
  GET  /desk/{target}/frame.jpg?w=960      live JPEG of the desk (≈400 ms cache per target, Cache-Control: no-store)
  POST /desk/{target}/action               computer-toolset action → {ok, result} or {ok, image (b64 PNG), path}
  POST /desk/{target}/run {cmd}            shell on the target → {exit, output}
  POST /desk/{target}/warm                 start the invisible GUI soffice with the UNO socket
  GET  /desk/{target}/sheet?path=          .ods → items/total
  GET  /desk/{target}/deck_cells?deck=&slide=   live Impress table (UNO, nothing saved)

Targets: `mac` (this machine) or `desk<N>` → docker container `desk<N>` on FLOWLINE_DESK_HOST. Runs on different
targets execute concurrently (one thread each, per-target lock around desktop actions); all desks are warmed at
startup without blocking it (FLOWLINE_WARM_TARGETS=desk1,…; default: every running desk<N> container).

Each run executes in a background thread: the skill module prepares the desktop, spawns `node agent-ts/run.mjs`
(Vercel AI SDK loop), maps its events onto the RunSteps, verifies the result deterministically and saves
data/runs/<id>.json.

    uv run uvicorn main:app --port 8790
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import threading
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

import skills
from bridge import DesktopPool, Target, deck_cells, frame_jpeg, perform, sheet_json, warm
from desktop import DEFAULT_HOST, SSH_OPTS, docker_binary
from runs import RUNS_DIR, Run, RunContext, compact_run, have_api_key, new_run_id

app = FastAPI(title="Flowline executor", version="0.3.0")
pool = DesktopPool()
_runs: dict[str, RunContext] = {}
_lock = threading.Lock()
DEFAULT_MODEL = os.environ.get("FLOWLINE_MODEL", "claude-sonnet-5-5")
TARGET_RE = re.compile(r"^(mac|desk\d{1,3})$")


class RunRequest(BaseModel):
    suggestion_id: Optional[str] = None
    skill_id: str = "fill_deck_from_sheet"
    target: str = "desk1"
    person_id: Optional[str] = None
    inputs: dict[str, Any] = {}


def _check_target(target: str) -> str:
    if not TARGET_RE.match(target or ""):
        raise HTTPException(400, f"bad target {target!r}: use mac or desk<N>")
    return target


def _get_target(name: str) -> Target:
    try:
        return pool.get(_check_target(name))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001  (container missing, ssh down, …)
        raise HTTPException(503, f"desk {name} is not reachable: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- runs
def _execute(ctx: RunContext, skill_mod, target: str, inputs: dict) -> None:
    t: Target | None = None
    try:
        t = pool.get(target)
        with _lock:
            t.run_id = ctx.run.id
        mark = len(t.desktop.timings)
        skill_mod.run(ctx, t.desktop, inputs)
        ctx.run.timing = _timing_since(t.desktop, mark)
        ctx.save()
    except Exception as e:  # noqa: BLE001
        ctx.finish("failed", error=f"{type(e).__name__}: {e}")
    finally:
        if ctx.run.status == "running":  # a skill that returned without finishing
            ctx.finish("failed", error="skill returned without finishing the run")
        with _lock:
            if t is not None and t.run_id == ctx.run.id:
                t.run_id = None


def _timing_since(desktop, mark: int) -> dict:
    saved = desktop.timings
    desktop.timings = saved[mark:]
    try:
        return desktop.timing_summary()
    finally:
        desktop.timings = saved


def _active_on(target: str) -> RunContext | None:
    for ctx in _runs.values():
        if ctx.run.target == target and ctx.run.status == "running":
            return ctx
    return None


def start_run(req: RunRequest) -> RunContext:
    target = _check_target(req.target)
    try:
        skill_mod = skills.load(req.skill_id)
    except ModuleNotFoundError:
        skill_mod = None
    run = Run(id=new_run_id(), skill_id=req.skill_id, target=target, suggestion_id=req.suggestion_id,
              person_id=req.person_id, inputs=req.inputs, model=DEFAULT_MODEL if have_api_key() else None)
    ctx = RunContext(run)
    if skill_mod is None:
        # a skill the executor does not ship (yet): a clear failed run, not a crash or a 404 the board cannot show
        known = sorted(_skill_ids())
        ctx.set_steps(["SKILL MISSING"])
        ctx.start_step(1, f"{req.skill_id} is not installed on the executor")
        ctx.check("skill_available", False, f"no skills/{req.skill_id}.py; have {', '.join(known)}")
        ctx.finish("failed", error=f"unknown skill {req.skill_id}")
        with _lock:
            _runs[run.id] = ctx
        return ctx
    run.title = skill_mod.title(req.inputs) if hasattr(skill_mod, "title") else skill_mod.SKILL.get("title")
    with _lock:
        busy = _active_on(target)
        if busy is not None:
            raise HTTPException(409, {"detail": f"{target} is busy with run {busy.run.id}", "run_id": busy.run.id, "target": target})
        ctx.set_steps(skill_mod.SKILL["steps"])
        ctx.start_step(1, "Starting")  # answer at once: everything slow (desktop, soffice, agent) happens in the thread
        ctx.check("skill_available", True, f"{req.skill_id} v{skill_mod.SKILL.get('version', 1)}")
        _runs[run.id] = ctx
    threading.Thread(target=_execute, args=(ctx, skill_mod, target, req.inputs), daemon=True, name=run.id).start()
    return ctx


@app.post("/runs", status_code=201)
def post_run(req: RunRequest):
    return start_run(req).snapshot()


@app.get("/runs/active")
def active_runs():
    with _lock:
        active = [ctx for ctx in _runs.values() if ctx.run.status == "running"]
    return {"runs": [ctx.compact() for ctx in sorted(active, key=lambda c: c.run.started_at)],
            "targets": {ctx.run.target: ctx.run.id for ctx in active}}


@app.get("/runs/{run_id}")
def get_run(run_id: str, compact: bool = False):
    ctx = _runs.get(run_id)
    if ctx is not None:
        return ctx.compact() if compact else ctx.snapshot()
    p = os.path.join(RUNS_DIR, f"{run_id}.json")
    if os.path.exists(p):
        data = json.load(open(p, encoding="utf-8"))
        return compact_run(data) if compact else data
    raise HTTPException(404, "no such run")


@app.post("/runs/{run_id}/stop")
def stop_run(run_id: str):
    ctx = _runs.get(run_id)
    if ctx is None:
        raise HTTPException(404, "no such run (or already finished)")
    ctx.request_stop()
    return {"id": run_id, "stop_requested": True, "status": ctx.run.status}


@app.post("/runs/{run_id}/events")
def post_event(run_id: str, ev: dict):
    ctx = _runs.get(run_id)
    if ctx is None:
        raise HTTPException(404, "no such run")
    ctx.apply_event(ev)
    return {"ok": True, "stop": ctx.stop_requested()}


@app.get("/runs")
def list_runs():
    ids = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(RUNS_DIR, "run-*.json")))
    return {"runs": ids, "active": [k for k, v in _runs.items() if v.run.status == "running"]}


def _skill_ids() -> list[str]:
    out = []
    for p in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "*.py")):
        name = os.path.basename(p)[:-3]
        if not name.startswith("_"):
            out.append(name)
    return out


@app.get("/skills")
def list_skills():
    out = []
    for name in sorted(_skill_ids()):
        try:
            out.append(skills.load(name).SKILL)
        except Exception as e:  # noqa: BLE001  a half-written skill must not take the listing down
            out.append({"id": name, "error": f"{type(e).__name__}: {e}"})
    return out


@app.get("/health")
def health():
    with _lock:
        active = sorted(ctx.run.target for ctx in _runs.values() if ctx.run.status == "running")
    return {"ok": True, "model": DEFAULT_MODEL, "api_key": have_api_key(), "agent": "agent-ts (Vercel AI SDK)",
            "desk_host": DEFAULT_HOST, "targets": sorted(pool._targets), "active_targets": active}


# ---------------------------------------------------------------- desktop bridge
@app.post("/desk/{target}/warm")
def desk_warm(target: str):
    """Start a GUI soffice with the UNO socket on the target (invisible until a document opens)."""
    return {"target": target, **warm(_get_target(target))}


def discover_desks() -> list[str]:
    """desk<N> containers running on the desk host (ssh when it is not local)."""
    local = DEFAULT_HOST in ("", "local", "localhost")
    inner = [docker_binary() if local else "/opt/homebrew/bin/docker", "ps", "--format", "{{.Names}}"]
    argv = inner if local else ["ssh", *SSH_OPTS, DEFAULT_HOST, " ".join(inner)]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return []
    names = [n for n in out.split() if re.fullmatch(r"desk\d+", n)]
    return sorted(names, key=lambda n: int(n[4:]))


WARM_TARGETS = [t for t in os.environ.get("FLOWLINE_WARM_TARGETS", "").split(",") if t and t != "mac"]


@app.on_event("startup")
def _warm_on_startup():
    def one(name: str):
        try:
            print(f"[executor] warm {name}: {warm(pool.get(name))}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[executor] warm {name} failed: {type(e).__name__}: {e}", flush=True)

    def go():
        names = WARM_TARGETS or discover_desks() or ["desk1"]
        print(f"[executor] warming {names} on {DEFAULT_HOST}", flush=True)
        for n in names:  # one thread per desk: six soffice starts in parallel, none blocking the service
            threading.Thread(target=one, args=(n,), daemon=True, name=f"warm-{n}").start()
    threading.Thread(target=go, daemon=True, name="warm").start()


@app.get("/desk/{target}/view")
def desk_view(target: str):
    t = _get_target(target)
    return {"target": target, "display_w": t.view.display_w, "display_h": t.view.display_h,
            "view_w": t.view.view_w, "view_h": t.view.view_h, "factor": t.view.factor}


@app.get("/desk/{target}/frame.jpg")
def desk_frame(target: str, w: int = 960):
    t = _get_target(target)
    try:
        jpeg, age = frame_jpeg(t, w)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"no frame from {target}: {type(e).__name__}: {e}")
    return Response(jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Frame-Age": f"{age:.3f}", "X-Target": target})


@app.post("/desk/{target}/action")
def desk_action(target: str, body: dict):
    t = _get_target(target)
    run_id = body.pop("run_id", None)
    if run_id and run_id in _runs and _runs[run_id].stop_requested():
        return {"ok": False, "error": "run stopped by the user"}
    return perform(t, body, run_id)


class RunCmd(BaseModel):
    cmd: str
    timeout: float = 60


@app.post("/desk/{target}/run")
def desk_run(target: str, body: RunCmd):
    t = _get_target(target)
    with t.lock:
        rc, out = t.desktop.run(body.cmd, timeout=min(body.timeout, 300))
    return {"exit": rc, "output": out[-20000:]}


@app.get("/desk/{target}/sheet")
def desk_sheet(target: str, path: str):
    try:
        return sheet_json(_get_target(target), path)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{type(e).__name__}: {e}")


@app.get("/desk/{target}/deck_cells")
def desk_deck_cells(target: str, deck: str, slide: int):
    try:
        return deck_cells(_get_target(target), deck, slide)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FLOWLINE_EXECUTOR_PORT", "8790")))
