"""Skill `fill_deck_from_sheet` v1 — the four steps the run shows:

  1 READ THE SHEET    the agent calls read_sheet (pandas/odfpy on the file, never the GUI)
  2 FILL THE DECK     on the open Impress deck the agent clicks each empty amount cell and types
  3 CHECK THE TOTAL   the agent reads the live table back (read_deck_cells, UNO, nothing saved)
  4 LEAVE IT FOR YOU  nothing is saved

The agent loop is `agent-ts/run.mjs` (Vercel AI SDK, Claude computer toolset).  This
module does what must be deterministic around it: open the deck on the right slide,
spawn the agent, kill it on Stop (its events are mapped to RunSteps by
runs.RunContext.apply_event), and verify afterwards — cells vs sheet, sum, file hash
unchanged, document left modified — so the Run's checks never depend on what the
model claims.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time

import lo
from bridge import read_target_file
from desktop import Desktop, DockerDesktop
from runs import RunContext, have_api_key
from sheet import fmt_money, parse_amount, read_sheet_bytes

SKILL = {
    "id": "fill_deck_from_sheet",
    "version": 1,
    "actor": "PM",
    "reviewer": "PM",
    "steps": ["READ THE SHEET", "FILL THE DECK", "CHECK THE TOTAL", "LEAVE IT FOR YOU"],
    "inputs": {"sheet": "/config/Documents/pricing-sheet.ods", "deck": "/config/Documents/proposal-172.odp", "slide": 6},
    "saves": False,
}

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.join(os.path.dirname(HERE), "agent-ts")
BRIDGE_URL = os.environ.get("FLOWLINE_EXECUTOR_URL", f"http://127.0.0.1:{os.environ.get('FLOWLINE_EXECUTOR_PORT', '8790')}")


class SkillError(Exception):
    pass


def title(inputs: dict | None = None) -> str:
    """Run title for the agent panel, e.g. "Filling proposal #172 pricing from your sheet"."""
    deck = (inputs or {}).get("deck") or SKILL["inputs"]["deck"]
    m = re.search(r"(\d{2,5})", deck.rsplit("/", 1)[-1])
    return f"Filling proposal #{m.group(1)} pricing from your sheet" if m else "Filling the deck's pricing from your sheet"


def _file_sha(desktop: Desktop, path: str) -> str:
    if isinstance(desktop, DockerDesktop):
        rc, out = desktop.sh(f"sha256sum {path} | cut -d' ' -f1")
        return out.strip()
    return hashlib.sha256(open(os.path.expanduser(path), "rb").read()).hexdigest()


def _save_png(d: str, name: str, png: bytes) -> str:
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(png)
    return p


def ensure_deck_open(desktop: DockerDesktop, ctx: RunContext, deck_path: str, slide_n: int) -> None:
    deck_name = deck_path.rsplit("/", 1)[-1]
    t = time.perf_counter()
    open_docs: list[str] = []
    alive = False
    try:
        open_docs = lo.uno(desktop, "list")["docs"]
        alive = True
    except Exception:
        if lo.soffice_running(desktop):  # running without our UNO socket: restart it so we can read the deck back
            lo.kill_soffice(desktop)
            time.sleep(1.0)
    if not any(u.endswith(deck_name) for u in open_docs):
        if alive:
            lo.open_document(desktop, deck_path)  # the warm (invisible) instance shows it in a normal window
        else:
            lo.start_soffice(desktop, deck_path, wait_title="Impress")
        for _ in range(40):
            if "impress" in desktop.active_window_title().lower():
                break
            time.sleep(0.5)
        time.sleep(0.5)
    lo.activate_window(desktop, deck_name)
    time.sleep(0.3)
    lo.maximize_active(desktop)
    time.sleep(0.5)
    lo.uno(desktop, "goto", deck_name, str(slide_n))
    time.sleep(0.6)
    ctx.log("open_deck", f"{deck_name} slide {slide_n}", time.perf_counter() - t, step=2)


def run(ctx: RunContext, desktop: Desktop, inputs: dict) -> None:
    inputs = {**SKILL["inputs"], **(inputs or {})}
    sheet_path, deck_path, slide_n = inputs["sheet"], inputs["deck"], int(inputs["slide"])
    deck_name = deck_path.rsplit("/", 1)[-1]
    is_docker = isinstance(desktop, DockerDesktop)
    shots_dir = os.path.join(ctx.runs_dir, ctx.run.id)
    if not ctx.run.steps:  # main.start_run has already set the steps (and step 1 "now")
        ctx.set_steps(SKILL["steps"])
    if not have_api_key():
        ctx.finish("failed", error="needs ANTHROPIC_API_KEY: the agent loop (agent-ts) cannot run without it")
        return

    try:
        # --- prepare: the sheet for verification, the deck open on the slide -------------
        sheet = read_sheet_bytes(read_target_file(desktop, sheet_path))
        ctx.fill_total = len(sheet.items) + 1
        ctx.check("sheet_total_equals_sum", sheet.consistent(), f"sum {sheet.sum_items} vs total {sheet.total}")
        want_amounts = [a for _, a in sheet.items] + [sheet.total]
        labels = [l for l, _ in sheet.items] + ["Total"]
        sha_before = _file_sha(desktop, deck_path)
        if is_docker:
            ensure_deck_open(desktop, ctx, deck_path, slide_n)
            before = lo.uno(desktop, "cells", deck_name, str(slide_n))["cells"]
            ctx.check("amount_cells_empty_before", not any(r[-1].strip() for r in before), json.dumps([r[-1] for r in before]))
        if ctx.stop_requested():
            raise StopIteration

        # --- the agent ----------------------------------------------------------------------
        cmd = [os.environ.get("FLOWLINE_NODE", "node"), os.path.join(AGENT_DIR, "run.mjs"), "--run-id", ctx.run.id,
               "--target", ctx.run.target, "--skill", SKILL["id"], "--inputs", json.dumps(inputs), "--bridge", BRIDGE_URL,
               "--max-steps", str(inputs.get("max_steps", 25))]
        t0 = time.perf_counter()
        ctx.log("agent_start", "node agent-ts/run.mjs", step=1)
        proc = subprocess.Popen(cmd, cwd=AGENT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stopped = False
        while proc.poll() is None:
            if ctx.stop_requested():
                stopped = True
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            time.sleep(0.2)
        out, err = proc.communicate(timeout=10)
        agent_s = time.perf_counter() - t0
        ctx.log("agent_exit", f"exit={proc.returncode} stderr={err.strip()[-300:]}", agent_s)
        ctx.run.agent = {"exit_code": proc.returncode, "seconds": round(agent_s, 2), "stdout": out[-2000:], "stderr": err[-2000:]}
        if stopped:
            raise StopIteration

        # --- verify (deterministic, independent of the model's claims) ------------------------
        if ctx.run.steps[2].status != "done":
            ctx.start_step(3, f"Deck total must equal {fmt_money(sheet.total)}")
        if not is_docker:
            raise SkillError("cannot verify the deck on this target (needs the LibreOffice UNO bridge)")
        cells = [r[-1] for r in lo.uno(desktop, "cells", deck_name, str(slide_n))["cells"]]
        ctx.log("read_back", f"uno: {cells}", step=3)
        amounts = [parse_amount(c) for c in cells]
        ok_cells = [a == b for a, b in zip(amounts, want_amounts)] + [False] * max(0, len(want_amounts) - len(amounts))
        for i, (lbl, want) in enumerate(zip(labels, want_amounts)):
            got = cells[i] if i < len(cells) else None
            ctx.check(f"cell_{i + 1}", ok_cells[i], f"{lbl}: deck says {got!r}, sheet says {fmt_money(want)}")
        items_sum = sum(a or 0 for a in amounts[:-1])
        deck_total = amounts[-1] if amounts else None
        ctx.check("deck_items_sum_equals_sheet_total", items_sum == sheet.total, f"{items_sum} vs {sheet.total}")
        ctx.check("deck_total_equals_sheet_total", deck_total == sheet.total, f"{deck_total} vs {sheet.total}")
        all_ok = all(ok_cells) and items_sum == sheet.total
        ctx.done_step(3, f"Deck total {fmt_money(deck_total or 0)} {'equals' if all_ok else 'does not equal'} the sheet total {fmt_money(sheet.total)}")

        if ctx.run.steps[3].status != "done":
            ctx.start_step(4, "Nothing is saved until you keep it")
        sha_after = _file_sha(desktop, deck_path)
        ctx.check("file_unchanged_on_disk", sha_after == sha_before, f"sha256 {sha_before[:12]} → {sha_after[:12]}")
        st = lo.uno(desktop, "status", deck_name)
        ctx.check("document_left_modified_unsaved", bool(st.get("modified")), json.dumps(st))
        shot = desktop.screenshot()
        ctx.run.final_screenshot = _save_png(shots_dir, "final.png", shot.png)
        ctx.check("agent_finished", proc.returncode == 0, f"exit code {proc.returncode}")
        if inputs.get("leave_open"):
            ctx.done_step(4, "Left open and unsaved for you to check")
        else:
            # default: close the deck without saving so the desktop is clean for the next run (inputs.leave_open keeps it)
            lo.uno(desktop, "close", deck_name)
            ctx.log("close_deck", "closed without saving", step=4)
            ctx.done_step(4, "Nothing saved; the deck was closed unchanged")
        if not all_ok:
            raise SkillError(f"deck cells {cells} do not match the sheet")
        if sha_after != sha_before:
            raise SkillError("the deck file changed on disk — something saved it")
        if proc.returncode != 0:
            raise SkillError("agent exited with code %d (%s)" % (proc.returncode, "step limit" if proc.returncode == 2 else "error"))
        ctx.finish("done")
    except StopIteration:
        try:
            desktop.key("Escape")
            shot = desktop.screenshot()
            ctx.run.final_screenshot = _save_png(shots_dir, "final.png", shot.png)
        except Exception:
            pass
        ctx.finish("stopped")
    except Exception as e:  # noqa: BLE001
        try:
            shot = desktop.screenshot()
            ctx.run.final_screenshot = _save_png(shots_dir, "final.png", shot.png)
        except Exception:
            pass
        ctx.finish("failed", error=f"{type(e).__name__}: {e}")
