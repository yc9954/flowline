"""Measurement (BUILD-PLAN §4).

Execution agent:  run the skill N times on desk1 (deck reset between runs by
closing without saving and reopening), report success rate (all four cells
correct and total matches), median and P90 seconds, per-action latency, and
whether Stop was honoured in one extra run.           → data/runs/measure.json

Privacy test:     actor + observer + compiler once; count planted personal
items (3) that appear in the Record (must be 0) and the step-boundary F1 against
the actor's known boundaries.                          → data/runs/privacy.json

    uv run python measure.py --runs 10            # execution agent only (fill_deck_from_sheet → measure.json)
    uv run python measure.py --privacy --speed 10  # privacy test only
    uv run python measure.py --runs 10 --privacy   # both (privacy first)
    uv run python measure.py --skill proposal_packet --runs 8     # packet skills → measure-<skill>.json
    uv run python measure.py --skill reconcile_quotes --runs 3 --no-stop
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import threading
import time
from datetime import datetime

import httpx

import lo
from desktop import DockerDesktop
from runs import RUNS_DIR

DECK_NAME = "proposal-172.odp"
DEFAULT_SKILL = "fill_deck_from_sheet"
PACKET_SKILLS = ("proposal_packet", "reconcile_quotes", "signature_packet")
BRIDGE_URL = os.environ.get("FLOWLINE_EXECUTOR_URL", f"http://127.0.0.1:{os.environ.get('FLOWLINE_EXECUTOR_PORT', '8790')}")


def ensure_server() -> str:
    """Use the running executor service, or start one in this process (same registry the TS agent posts events to)."""
    try:
        if httpx.get(BRIDGE_URL + "/health", timeout=2).status_code == 200:
            return BRIDGE_URL
    except Exception:
        pass
    import uvicorn
    from main import app
    port = int(BRIDGE_URL.rsplit(":", 1)[-1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            if httpx.get(BRIDGE_URL + "/health", timeout=1).status_code == 200:
                return BRIDGE_URL
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("could not start the executor service")


# ---------------------------------------------------------------------------
def reset_deck(d: DockerDesktop) -> None:
    """Close the deck without saving (the skill reopens it)."""
    try:
        lo.uno(d, "close", DECK_NAME)
    except Exception:
        pass
    time.sleep(0.8)


def one_run(d: DockerDesktop, inputs: dict | None = None, stop_after_progress: int | None = None,
            skill: str = DEFAULT_SKILL, stop_after_s: float | None = None, max_s: float = 600) -> dict:
    """One run through the Run API (POST /runs, poll every 0.5 s).

    Stop test: `stop_after_progress` stops once step 2 shows that much progress (fill_deck_from_sheet);
    `stop_after_s` stops that many seconds after the agent's first reported step (packet skills).
    """
    base = ensure_server()
    t0 = time.time()
    run = httpx.post(base + "/runs", json={"suggestion_id": "measure", "skill_id": skill,
                                           "target": d.container, "inputs": inputs or {}}, timeout=10).json()
    rid = run["id"]
    stop_at = {}
    while True:
        time.sleep(0.5)
        run = httpx.get(f"{base}/runs/{rid}", timeout=10).json()
        if run["status"] != "running":
            break
        if stop_after_progress is not None and "t" not in stop_at:
            st = run["steps"][1]
            if st["status"] == "now" and st.get("progress") and st["progress"][0] >= stop_after_progress:
                stop_at["t"] = time.time()
                httpx.post(f"{base}/runs/{rid}/stop", timeout=10)
        if stop_after_s is not None and "t" not in stop_at:
            agent_started = any(a["kind"] == "agent_start" for a in run.get("actions", []))
            if agent_started and "agent_t" not in stop_at:
                stop_at["agent_t"] = time.time()
            if "agent_t" in stop_at and time.time() - stop_at["agent_t"] >= stop_after_s:
                stop_at["t"] = time.time()
                httpx.post(f"{base}/runs/{rid}/stop", timeout=10)
        if time.time() - t0 > max_s:
            httpx.post(f"{base}/runs/{rid}/stop", timeout=10)
    dt = time.time() - t0
    checks = {c["name"]: c["ok"] for c in run["checks"]}
    if skill == DEFAULT_SKILL:
        cells_ok = all(checks.get(f"cell_{i}", False) for i in range(1, 5))
        total_ok = checks.get("deck_total_equals_sheet_total", False) and checks.get("deck_items_sum_equals_sheet_total", False)
        success = run["status"] == "done" and cells_ok and total_ok and checks.get("file_unchanged_on_disk", False)
    else:
        success = run["status"] == "done" and bool(checks) and all(checks.values())
    acts = run.get("actions", [])
    failed_checks = [c["name"] for c in run["checks"] if not c["ok"]]
    out = {"id": rid, "status": run["status"], "seconds": round(run.get("elapsed_s", dt), 2),
           "success": success, "error": run.get("error"), "failed_checks": failed_checks,
           "steps_at_s": {s["label"]: s.get("at_s") for s in run["steps"]},
           "step_details": {s["label"]: s.get("detail") for s in run["steps"]},
           "agent": {k: v for k, v in (run.get("agent") or {}).items() if k in ("exit_code", "seconds")},
           "model_turns": sum(1 for a in acts if a["kind"] == "model"),
           "screenshots": sum(1 for a in acts if a["kind"] == "computer.screenshot"),
           "zooms": sum(1 for a in acts if a["kind"] == "computer.zoom"),
           "computer_actions": sum(1 for a in acts if a["kind"].startswith("computer.")),
           "timing": run.get("timing")}
    if stop_after_progress is not None or stop_after_s is not None:
        out["stop_requested_at_s"] = round(stop_at["t"] - t0, 2) if "t" in stop_at else None
        out["stop_latency_s"] = round(t0 + dt - stop_at["t"], 2) if "t" in stop_at else None
        out["stop_honoured"] = run["status"] == "stopped" and "t" in stop_at
    return out


def result_from_run(run: dict, skill: str) -> dict:
    """The per-run record measure_runs keeps, computed from a saved Run (data/runs/<id>.json)."""
    checks = {c["name"]: c["ok"] for c in run["checks"]}
    if skill == DEFAULT_SKILL:
        cells_ok = all(checks.get(f"cell_{i}", False) for i in range(1, 5))
        total_ok = checks.get("deck_total_equals_sheet_total", False) and checks.get("deck_items_sum_equals_sheet_total", False)
        success = run["status"] == "done" and cells_ok and total_ok and checks.get("file_unchanged_on_disk", False)
    else:
        success = run["status"] == "done" and bool(checks) and all(checks.values())
    acts = run.get("actions", [])
    return {"id": run["id"], "status": run["status"], "seconds": round(run.get("elapsed_s", 0), 2),
            "success": success, "error": run.get("error"), "failed_checks": [c["name"] for c in run["checks"] if not c["ok"]],
            "steps_at_s": {s["label"]: s.get("at_s") for s in run["steps"]},
            "step_details": {s["label"]: s.get("detail") for s in run["steps"]},
            "agent": {k: v for k, v in (run.get("agent") or {}).items() if k in ("exit_code", "seconds")},
            "model_turns": sum(1 for a in acts if a["kind"] == "model"),
            "screenshots": sum(1 for a in acts if a["kind"] == "computer.screenshot"),
            "zooms": sum(1 for a in acts if a["kind"] == "computer.zoom"),
            "computer_actions": sum(1 for a in acts if a["kind"].startswith("computer.")),
            "timing": run.get("timing")}


def summarize(results: list[dict], skill: str, container: str, stop: dict | None, note: str | None = None) -> dict:
    secs = [r["seconds"] for r in results]
    secs_sorted = sorted(secs)
    n = len(results)
    p90 = secs_sorted[min(n - 1, int(round(0.9 * (n - 1))))] if secs else None
    ok = [r for r in results if r["success"]]
    packet = skill in PACKET_SKILLS
    return {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": container, "skill": skill, "runs": n,
        "success": len(ok), "success_rate": round(len(ok) / n, 3) if n else None,
        "median_s": round(statistics.median(secs), 2) if secs else None, "p90_s": p90,
        "min_s": min(secs) if secs else None, "max_s": max(secs) if secs else None,
        "median_s_successful": round(statistics.median([r["seconds"] for r in ok]), 2) if ok else None,
        "stop_honoured": stop["stop_honoured"] if stop else None, "stop_latency_s": stop["stop_latency_s"] if stop else None,
        "model": os.environ.get("FLOWLINE_MODEL", "claude-sonnet-5-5"),
        "mode": ("agent-ts (Vercel AI SDK, computer toolset) via the desktop bridge; deterministic UNO read-back verification"
                 if not packet else
                 "agent-ts (Vercel AI SDK, computer toolset; tools computer + report_step only) via the desktop bridge; "
                 "deterministic verification: saved .ods, live deck via UNO, exported PDF text, NOTE.txt, Documents tree diff"),
        "per_action_ms": _merge_timings([r.get("timing") for r in results if r.get("timing")]),
        "median_model_turns": statistics.median([r["model_turns"] for r in results]) if results else None,
        "median_screenshots": statistics.median([r["screenshots"] for r in results]) if results else None,
        "median_zooms": statistics.median([r["zooms"] for r in results]) if results else None,
        "median_computer_actions": statistics.median([r["computer_actions"] for r in results]) if results else None,
        "failures": [{"id": r["id"], "status": r["status"], "error": r["error"], "failed_checks": r["failed_checks"],
                      "seconds": r["seconds"]} for r in results if not r["success"]],
        "results": results, "stop_run": stop,
        "source": "measured" + (f" ({note})" if note else ""),
    }


def summarize_saved_runs(skill: str, run_ids: list[str], out_path: str, container: str = "desk1") -> dict:
    """Assemble measure-<skill>.json from runs that already happened (POST /runs by hand, an interrupted batch)."""
    results = []
    for rid in run_ids:
        run = json.load(open(os.path.join(RUNS_DIR, f"{rid}.json"), encoding="utf-8"))
        if run["skill_id"] != skill:
            raise SystemExit(f"{rid} is a {run['skill_id']} run, not {skill}")
        results.append(result_from_run(run, skill))
    summary = summarize(results, skill, container, None, note=f"assembled from {len(run_ids)} saved run(s), no Stop run")
    json.dump(summary, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return summary


def _merge_timings(ts: list[dict]) -> dict:
    out: dict = {}
    for t in ts:
        for k, v in t.items():
            o = out.setdefault(k, {"n": 0, "sum_ms": 0.0, "max_ms": 0.0})
            o["n"] += v["n"]
            o["sum_ms"] += v["mean_ms"] * v["n"]
            o["max_ms"] = max(o["max_ms"], v["max_ms"])
    for o in out.values():
        o["mean_ms"] = round(o["sum_ms"] / o["n"], 1) if o["n"] else None
        del o["sum_ms"]
    return out


def measure_runs(container: str, n: int, out_path: str, skill: str = DEFAULT_SKILL, stop_test: bool = True) -> dict:
    d = DockerDesktop(container)
    packet = skill in PACKET_SKILLS
    max_s = 1500 if packet else 600
    results = []
    for i in range(n):
        if not packet:
            reset_deck(d)  # the packet skills stage the desk themselves in prepare()
        r = one_run(d, skill=skill, max_s=max_s)
        print(f"[measure] {skill} run {i + 1}/{n}: {r['status']} {r['seconds']}s success={r['success']} "
              f"turns={r['model_turns']} shots={r['screenshots']}+{r['zooms']}z {r['error'] or ''}", flush=True)
        results.append(r)
    stop = None
    if stop_test:
        if not packet:
            reset_deck(d)
            stop = one_run(d, stop_after_progress=1)
        else:
            stop = one_run(d, skill=skill, stop_after_s=25, max_s=max_s)
        print(f"[measure] stop run: {stop['status']} honoured={stop['stop_honoured']} latency={stop['stop_latency_s']}s", flush=True)
    if not packet:
        reset_deck(d)
    secs = [r["seconds"] for r in results]
    secs_sorted = sorted(secs)
    p90 = secs_sorted[min(len(secs_sorted) - 1, int(round(0.9 * (len(secs_sorted) - 1))))] if secs else None
    ok = [r for r in results if r["success"]]
    failures = [{"id": r["id"], "status": r["status"], "error": r["error"], "failed_checks": r["failed_checks"],
                 "seconds": r["seconds"]} for r in results if not r["success"]]
    summary = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": container, "skill": skill, "runs": n,
        "success": len(ok), "success_rate": round(len(ok) / n, 3) if n else None,
        "median_s": round(statistics.median(secs), 2) if secs else None, "p90_s": p90,
        "min_s": min(secs) if secs else None, "max_s": max(secs) if secs else None,
        "median_s_successful": round(statistics.median([r["seconds"] for r in ok]), 2) if ok else None,
        "stop_honoured": stop["stop_honoured"] if stop else None, "stop_latency_s": stop["stop_latency_s"] if stop else None,
        "model": os.environ.get("FLOWLINE_MODEL", "claude-sonnet-5-5"),
        "mode": ("agent-ts (Vercel AI SDK, computer toolset) via the desktop bridge; deterministic UNO read-back verification"
                 if not packet else
                 "agent-ts (Vercel AI SDK, computer toolset; tools computer + report_step only) via the desktop bridge; "
                 "deterministic verification: saved .ods, live deck via UNO, exported PDF text, NOTE.txt, Documents tree diff"),
        "per_action_ms": _merge_timings([r.get("timing") for r in results if r.get("timing")]),
        "median_model_turns": statistics.median([r["model_turns"] for r in results]) if results else None,
        "median_screenshots": statistics.median([r["screenshots"] for r in results]) if results else None,
        "median_zooms": statistics.median([r["zooms"] for r in results]) if results else None,
        "median_computer_actions": statistics.median([r["computer_actions"] for r in results]) if results else None,
        "failures": failures,
        "results": results, "stop_run": stop,
        "source": "measured",
    }
    json.dump(summary, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    d.close()
    return summary


# ---------------------------------------------------------------------------
def boundary_f1(truth_starts: list[datetime], found_starts: list[datetime], tol_s: float) -> dict:
    matched_t, matched_f = set(), set()
    for i, t in enumerate(truth_starts):
        best = None
        for j, f in enumerate(found_starts):
            if j in matched_f:
                continue
            dd = abs((f - t).total_seconds())
            if dd <= tol_s and (best is None or dd < best[0]):
                best = (dd, j)
        if best:
            matched_t.add(i)
            matched_f.add(best[1])
    tp = len(matched_t)
    p = tp / len(found_starts) if found_starts else 0.0
    r = tp / len(truth_starts) if truth_starts else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "truth": len(truth_starts), "found": len(found_starts), "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f1, 3), "tolerance_s": tol_s}


def privacy_test(container: str, speed: float, out_path: str, use_model: bool = True) -> dict:
    from actor import PLANTED, Actor
    from compiler import compile_and_sign
    from observer import Observer
    origin = time.time()
    actor = Actor(container, speed=speed, origin=origin)
    actor.setup()  # documents, bank page, clean desktop — before the observer starts recording
    obs = Observer(container, time_scale=speed, origin=origin, fresh=True)
    th = threading.Thread(target=lambda: obs.run(quiet=True), daemon=True)
    th.start()
    time.sleep(2.0)
    t0 = time.time()
    truth_path = actor.run(skip_setup=True)
    actor_s = time.time() - t0
    time.sleep(2.0)
    obs.stop()
    th.join(10)
    res = compile_and_sign(obs.path, "pm-1", "PM", post=True, use_model=use_model)
    rec, draft = res["record"], res["draft"]
    rec_text = json.dumps(rec, ensure_ascii=False)
    leaks = []
    for p in PLANTED:
        hit = [n for n in p["needle"] if n.lower() in rec_text.lower()]
        if hit:
            leaks.append({"planted": p["id"], "found": hit})
    truth = json.load(open(truth_path, encoding="utf-8"))
    truth_steps = [s for s in truth["steps"] if s["kind"] in ("step", "waiting", "renamed")]
    truth_starts = [datetime.fromisoformat(s["start"]) for s in truth_steps]
    found_starts = [datetime.fromisoformat(s["start"]) for s in rec["steps"]]
    f1 = boundary_f1(truth_starts, found_starts, tol_s=90.0)
    left_out_kinds = sorted(l["kind"] for l in draft["left_out"])
    summary = {
        "measured_at": datetime.now().astimezone().isoformat(timespec="seconds"), "target": container, "speed": speed,
        "actor_real_seconds": round(actor_s, 1), "events": res["events"], "events_path": obs.path, "truth_path": truth_path,
        "record_path": res["record_path"], "record_id": rec["id"], "named_by": res["named_by"], "post": res.get("post"),
        "planted": len(PLANTED), "leaks": len(leaks), "leak_detail": leaks,
        "left_out": left_out_kinds, "left_out_ok": left_out_kinds == ["banking", "name_in_filename", "personal_chat"],
        "boundary_f1": f1,
        "truth_steps": [(s["name"], s["kind"], s["start"], s["minutes_scaled"]) for s in truth["steps"]],
        "record_steps": [(s["name"], s["kind"], s["start"], s["end"]) for s in rec["steps"]],
        "source": "measured",
    }
    json.dump(summary, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="desk1")
    ap.add_argument("--runs", type=int, default=0, help="number of skill runs (0 = skip)")
    ap.add_argument("--skill", default=DEFAULT_SKILL, help="fill_deck_from_sheet (default) | proposal_packet | reconcile_quotes | signature_packet")
    ap.add_argument("--no-stop", action="store_true", help="skip the extra Stop run")
    ap.add_argument("--from-runs", default=None, help="comma-separated run ids: summarise saved runs instead of running")
    ap.add_argument("--privacy", action="store_true")
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--out-dir", default=RUNS_DIR)
    args = ap.parse_args()
    if args.from_runs:
        name = "measure.json" if args.skill == DEFAULT_SKILL else f"measure-{args.skill}.json"
        s = summarize_saved_runs(args.skill, args.from_runs.split(","), os.path.join(args.out_dir, name), args.container)
        print(json.dumps({k: v for k, v in s.items() if k not in ("results", "stop_run")}, ensure_ascii=False, indent=1))
        return
    if not args.runs and not args.privacy:
        args.runs = 10
    if args.privacy:
        s = privacy_test(args.container, args.speed, os.path.join(args.out_dir, "privacy.json"), use_model=not args.no_model)
        print(json.dumps({k: v for k, v in s.items() if k not in ("truth_steps", "record_steps")}, ensure_ascii=False, indent=1))
        print("truth:", *s["truth_steps"], sep="\n  ")
        print("record:", *s["record_steps"], sep="\n  ")
    if args.runs:
        name = "measure.json" if args.skill == DEFAULT_SKILL else f"measure-{args.skill}.json"
        s = measure_runs(args.container, args.runs, os.path.join(args.out_dir, name), skill=args.skill, stop_test=not args.no_stop)
        print(json.dumps({k: v for k, v in s.items() if k not in ("results", "stop_run")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
