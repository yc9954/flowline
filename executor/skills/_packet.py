"""The packet skill engine — one engine, three skill ids (SCHEMA §11 Skill):

  proposal_packet   READ THE QUOTES · UPDATE THE SHEET · FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER
  reconcile_quotes  READ THE QUOTES · UPDATE THE SHEET · HAND IT OVER
  signature_packet  FILL THE DECK · EXPORT FOR SIGNATURE · HAND IT OVER

HAND IT OVER is a real e-mail to a teammate, sent through the Roundcube inbox window
that every desk has open (MAIL.md): reconcile_quotes mails pm@ with the corrected
sheet attached; the two packet skills mail director@ (cc finance@) with the exported
PDF attached.  Verified afterwards over IMAP (mail.py): newest matching message after
the run start, attachment bytes equal the file on the desk, body names what it must.

The agent (agent-ts/run.mjs) gets two tools only, `computer` and `report_step`:
everything it learns comes from screenshots, everything it does goes through
Thunar, Atril, Calc, Impress and Mousepad like a person would.  This module does
the deterministic part around it:

  prepare   fresh vendor quotes (assets/quotes.py: randomised, exactly one differs
            from the sheet), the canonical sheet and deck restored, `For signature/`
            emptied, every document closed without saving, stale lock files removed,
            a GUI soffice with the UNO socket that *accepts* double-clicks from Thunar
            (an --invisible instance silently drops them), truth.json written; then the
            desk is dressed like a person's screen (inputs.dress): Calc with the sheet on
            the left half, Impress with the deck on the right half (slide 6), Thunar at
            Documents/Quotes bottom-left, the pinned inbox window untouched
  agent     spawned, killed on Stop; its events become RunSteps (runs.RunContext)
  verify    saved .ods vs the quotes, live deck cells via UNO (nothing saved: file
            sha unchanged, isModified), the exported PDF's text (pypdf), NOTE.txt,
            and a before/after listing of /config/Documents so nothing else changed
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

import lo
import mail
from bridge import read_target_file
from desktop import Desktop, DockerDesktop
from runs import RunContext, have_api_key
from sheet import fmt_money, parse_amount, read_sheet_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTOR_DIR = os.path.dirname(HERE)
AGENT_DIR = os.path.join(EXECUTOR_DIR, "agent-ts")
ASSETS_DIR = os.path.join(EXECUTOR_DIR, "assets")
sys.path.insert(0, ASSETS_DIR)
BRIDGE_URL = os.environ.get("FLOWLINE_EXECUTOR_URL", f"http://127.0.0.1:{os.environ.get('FLOWLINE_EXECUTOR_PORT', '8790')}")

READ_QUOTES, UPDATE_SHEET, FILL_DECK, EXPORT, HAND_OVER = (
    "READ THE QUOTES", "UPDATE THE SHEET", "FILL THE DECK", "EXPORT FOR SIGNATURE", "HAND IT OVER")
ALL_STEPS = [READ_QUOTES, UPDATE_SHEET, FILL_DECK, EXPORT, HAND_OVER]
MAIL_WINDOW_CLASS = "FlowlineMail"   # the pinned Roundcube window on every desk — never closed by prepare

# who gets the hand-off mail (MAIL.md people). The subject ends in "· <Role>" of the sending desk so that six
# desks mailing director@ in the same minute never match each other's message; the sender is checked as well.
MAIL_RECONCILE = {"to": "pm", "cc": None, "subject": "Quotes reconciled — proposal 172", "attachment": None}
MAIL_PACKET = {"to": "director", "cc": "finance", "subject": "Proposal 172 — for signature", "attachment": "proposal-172.pdf"}
DESK_LOGIN = {1: "pm", 2: "finance", 3: "sales", 4: "ops", 5: "studio", 6: "director"}
ROLE = {"pm": "PM", "finance": "Finance", "sales": "Sales", "ops": "Ops", "studio": "Studio", "director": "Director"}


def desk_login(target: str, person_id: str | None = None) -> str:
    """The mailbox a desk sends from: the run's person_id when it names a login, else by desk number."""
    if person_id:
        low = person_id.lower()
        for login in ROLE:
            if low == login or low.startswith(login + "-") or low.startswith(login + "@"):
                return login
    m = re.search(r"(\d+)", target or "")
    return DESK_LOGIN.get(int(m.group(1)) if m else 0, "pm")

DOCS = "/config/Documents"
DEFAULT_INPUTS = {
    "proposal": 172,     # 171 Harbor Ridge Clinic · 172 Halden Logistics (the original) · 173 Kickoff Coaching (assets/make_assets.VARIANTS)
    "sheet": None,       # default: Documents/pricing-sheet.ods for 172, pricing-sheet-<n>.ods otherwise
    "deck": None,        # default: Documents/proposal-<n>.odp
    "slide": 6,
    "quotes_dir": f"{DOCS}/Quotes",
    "out_dir": f"{DOCS}/For signature",
    "dress": True,       # open Calc (left), Impress (right, slide 6), Thunar (Quotes) before the agent starts
    "max_steps": 90,
    # "seed": 7            fixes the quotes (which vendor differs, by how much) for a demo take
    # "leave_open": True   (default) leave Calc/Impress/Thunar/the inbox as the agent left them
}
MAX_STEP_TIMEOUT_S = 1200


def make_skill(skill_id: str, steps: list[str], version: int = 1) -> dict:
    return {"id": skill_id, "version": version, "actor": "PM", "reviewer": "PM", "steps": steps,
            "inputs": dict(DEFAULT_INPUTS), "saves": UPDATE_SHEET in steps or EXPORT in steps,
            "tools": ["computer", "report_step"]}


def resolve_inputs(inputs: dict | None, skill_inputs: dict | None = None) -> dict:
    """Defaults + the proposal variant's file names (inputs.sheet/deck given explicitly win)."""
    from make_assets import variant
    merged = {**DEFAULT_INPUTS, **(skill_inputs or {}), **(inputs or {})}
    v = variant(merged.get("proposal") or 172)
    merged["proposal"] = v["n"]
    merged["sheet"] = merged.get("sheet") or f"{DOCS}/{v['sheet']}"
    merged["deck"] = merged.get("deck") or f"{DOCS}/{v['deck']}"
    merged["client"] = v["client"]
    return merged


def make_title(skill_id: str, inputs: dict | None = None) -> str:
    try:
        deck = resolve_inputs(inputs)["deck"]
    except Exception:
        deck = (inputs or {}).get("deck") or f"{DOCS}/proposal-172.odp"
    m = re.search(r"(\d{2,5})", deck.rsplit("/", 1)[-1])
    n = f"#{m.group(1)}" if m else ""
    return {
        "proposal_packet": f"Preparing proposal {n} for signature from the vendor quotes",
        "reconcile_quotes": f"Checking the pricing sheet for proposal {n} against the vendor quotes",
        "signature_packet": f"Filling proposal {n} and exporting it for signature",
    }.get(skill_id, f"Running {skill_id}").replace("  ", " ")


class SkillError(Exception):
    pass


# ---------------------------------------------------------------------------
# pure helpers (unit-tested in tests/test_packet.py)
# ---------------------------------------------------------------------------
def money_pattern(n: int) -> re.Pattern:
    """$2,860 · 2,860 · 2860 · $ 2 860 — the amount, however the app rendered it."""
    digits = str(n)
    grouped = f"{n:,}"
    alts = [re.escape(grouped), re.escape(digits), re.escape(grouped.replace(",", " "))]
    return re.compile(r"(?<![\d.])\$?\s?(?:%s)(?!\d|,\d)" % "|".join(alts))


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def pdf_has_amounts(text: str, amounts: list[int]) -> tuple[bool, str]:
    missing = [fmt_money(a) for a in amounts if not money_pattern(a).search(text)]
    return (not missing), ("all amounts present" if not missing else "missing " + ", ".join(missing))


def note_ok(text: str, vendor: str | None, total: int) -> tuple[bool, str]:
    lines = [l for l in text.splitlines() if l.strip()]
    has_total = bool(money_pattern(total).search(text))
    has_vendor = True
    if vendor:  # the full name, or its distinctive first word ("MoveWell", "Kickoff", "Downtown")
        first = vendor.split()[0].lower()
        has_vendor = vendor.lower() in text.lower() or (len(first) >= 4 and first in text.lower())
    ok = bool(lines) and has_total and has_vendor
    return ok, f"{len(lines)} line(s); total {fmt_money(total)} {'named' if has_total else 'MISSING'}" + \
        (f"; vendor {vendor!r} {'named' if has_vendor else 'MISSING'}" if vendor else "")


def parse_tree(listing: str) -> dict[str, str]:
    """`sha256sum` output → {relative path: sha}."""
    out = {}
    for line in listing.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        sha, _, path = line.partition("  ")
        path = path.strip()
        if path.startswith("./"):
            path = path[2:]
        if sha and path:
            out[path] = sha.strip("\\ ")
    return out


def tree_changes(before: dict[str, str], after: dict[str, str], allowed: set[str]) -> list[str]:
    """Paths that changed/appeared/disappeared and are not expected to. Lock files are ignored."""
    def ignored(p: str) -> bool:
        base = p.rsplit("/", 1)[-1]
        return base.startswith(".~lock.") or base.startswith(".goutputstream")
    bad = []
    for p in sorted(set(before) | set(after)):
        if ignored(p) or p in allowed:
            continue
        if before.get(p) != after.get(p):
            kind = "added" if p not in before else "removed" if p not in after else "changed"
            bad.append(f"{kind} {p}")
    return bad


def pick_quotes(skill_steps: list[str]) -> bool:
    return READ_QUOTES in skill_steps


# ---------------------------------------------------------------------------
# desktop helpers (desk containers)
# ---------------------------------------------------------------------------
def _sha(desktop: Desktop, path: str) -> str:
    if isinstance(desktop, DockerDesktop):
        rc, out = desktop.sh(f"sha256sum {_q(path)} 2>/dev/null | cut -d' ' -f1")
        return out.strip()
    return hashlib.sha256(open(os.path.expanduser(path), "rb").read()).hexdigest()


def _q(s: str) -> str:
    import shlex
    return shlex.quote(s)


def _exists(desktop: DockerDesktop, path: str) -> bool:
    rc, out = desktop.sh(f"test -f {_q(path)} && echo yes || echo no")
    return out.strip() == "yes"


def snapshot_tree(desktop: DockerDesktop, root: str = DOCS) -> dict[str, str]:
    rc, out = desktop.sh(f"cd {_q(root)} && find . -type f -print0 | sort -z | xargs -0 sha256sum 2>/dev/null")
    return parse_tree(out)


def ensure_gui_soffice(desktop: DockerDesktop, sheet_path: str, timeout: float = 45) -> dict:
    """A GUI soffice with the UNO socket that will open documents double-clicked in Thunar.

    An instance started with --invisible (lo.warm) accepts the IPC request from
    `libreoffice --calc file` and shows nothing, so such an instance is replaced.
    Recipe: start visibly (Start Center) and let dress() open the documents into it;
    without dress the Start Center stays on screen (it accepts double-clicks too).
    """
    t0 = time.time()
    rc, inv = desktop.sh("pgrep -f 'soffice.bin.*--invisible' >/dev/null && echo yes || echo no")
    alive = lo.uno_alive(desktop)
    restarted = False
    if inv.strip() == "yes" or (lo.soffice_running(desktop) and not alive):
        lo.kill_soffice(desktop)
        time.sleep(1.0)
        alive = False
    if not alive:
        accept = f'--accept="socket,host=127.0.0.1,port={lo.UNO_PORT};urp;StarOffice.ServiceManager"'
        desktop.sh(f"nohup soffice --norestore --nologo --nofirststartwizard {accept} >/dev/null 2>&1 &")
        lo.install(desktop)
        while time.time() - t0 < timeout:
            if lo.uno_alive(desktop):
                break
            time.sleep(0.7)
        restarted = True
    try:
        lo.uno(desktop, "closeall")
    except Exception:
        pass
    if restarted:  # let the Start Center window map: the first UNO `open` then replaces that frame
        for _ in range(25):
            rc, sc = desktop.sh("wmctrl -l -x | grep -c libreoffice-startcenter")
            if sc.strip() not in ("", "0"):
                break
            time.sleep(0.4)
    # NOTE: do not close the last frame through UNO to get rid of the Start Center — a freshly started
    # instance terminates when its last frame closes (seen on desk4/desk5); dress() replaces it instead.
    return {"restarted": restarted, "seconds": round(time.time() - t0, 2)}


def close_other_windows(desktop: DockerDesktop) -> None:
    """Thunar, Atril, Mousepad, app finder — whatever the last run left open.
    The pinned Roundcube window (WM_CLASS FlowlineMail) is never touched."""
    desktop.sh("pkill -x atril; pkill -x mousepad; pkill -x xfce4-appfinder; "
               "wmctrl -l -x | awk '$3 ~ /[Tt]hunar/ && $3 !~ /" + MAIL_WINDOW_CLASS + "/ {print $1}' | xargs -r -n1 wmctrl -ic; true")
    time.sleep(0.5)


def _place(desktop: DockerDesktop, title_sub: str, x: int, y: int, w: int, h: int, tries: int = 20) -> bool:
    """Un-maximise and move/resize the first window whose title contains `title_sub`."""
    for _ in range(tries):
        rc, out = desktop.sh(f"wmctrl -l | grep -F {_q(title_sub)} | head -1 | cut -d' ' -f1")
        wid = out.strip()
        if wid:
            desktop.sh(f"wmctrl -i -r {wid} -b remove,maximized_vert,maximized_horz; wmctrl -i -r {wid} -e 0,{x},{y},{w},{h}")
            return True
        time.sleep(0.4)
    return False


def dress(desktop: DockerDesktop, inputs: dict, steps: list[str]) -> dict:
    """A person's working screen: sheet in Calc on the left half, deck in Impress on the right half on the
    slide, Thunar at the Quotes folder bottom-left; the inbox window stays where it is."""
    W, H = desktop.size()
    top, half, h = 30, W // 2, H - 100   # wmctrl geometry excludes the frame; leave room for it
    sheet, deck = inputs["sheet"], inputs["deck"]
    lo.uno(desktop, "open", sheet)
    _place(desktop, sheet.rsplit("/", 1)[-1], 0, top, half - 10, h)
    lo.uno(desktop, "open", deck)
    _place(desktop, deck.rsplit("/", 1)[-1], half, top, half - 10, h)
    time.sleep(0.5)
    lo.uno(desktop, "goto", deck.rsplit("/", 1)[-1], str(inputs["slide"]))
    # the Start Center frame stays (closing it quits LibreOffice, documents or not); minimise it out of the way
    desktop.sh("for w in $(xdotool search --classname libreoffice-startcenter); do xdotool windowminimize $w; done; true")
    desktop.sh(f"nohup thunar {_q(inputs['quotes_dir'])} >/dev/null 2>&1 &")
    _place(desktop, "Quotes", 40, H - 520, 760, 440)
    # front: what the first step needs
    lo.activate_window(desktop, "Quotes" if READ_QUOTES in steps else sheet.rsplit("/", 1)[-1])
    time.sleep(0.4)
    return {"sheet": "left half", "deck": f"right half, slide {inputs['slide']}", "thunar": "Quotes, bottom-left", "inbox": "untouched"}


def _mail_body(user: str, uid: str) -> str:
    import email
    from email.policy import default as default_policy
    m = mail._imap(user)
    try:
        m.select("INBOX", readonly=True)
        typ, parts = m.uid("FETCH", str(uid).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not parts or not isinstance(parts[0], tuple):
            return ""
        msg = email.message_from_bytes(parts[0][1], policy=default_policy)
    finally:
        m.logout()
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return text


def newest_mail(user: str, subject: str, attachment: str | None, after: datetime, sender: str | None = None) -> dict | None:
    """Newest INBOX message of `user` whose subject contains `subject` (and has that attachment), dated after
    `after`, and — when `sender` is given — sent from that login's address."""
    best = None
    for d in mail.find(user, subject, with_attachment=attachment):
        if sender and mail.address(sender).lower() not in (d.get("from") or "").lower():
            continue
        try:
            dt = datetime.fromisoformat(d["date"]) if d.get("date") else None
        except ValueError:
            dt = None
        if dt is None or dt < after:
            continue
        if best is None or (d["date"], int(d["id"])) > (best["date"], int(best["id"])):
            best = d
    return best


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------
def _mail_spec(steps: list[str], inputs: dict) -> dict | None:
    if HAND_OVER not in steps:
        return None
    spec = dict(MAIL_PACKET if EXPORT in steps else MAIL_RECONCILE)
    n = int(inputs.get("proposal") or 172)
    spec["subject"] = spec["subject"].replace("172", str(n))
    if spec["attachment"]:
        deck = inputs.get("deck") or f"proposal-{n}.odp"
        spec["attachment"] = deck.rsplit("/", 1)[-1].rsplit(".", 1)[0] + ".pdf"
    spec["sender"] = inputs["sender"]
    spec["role"] = inputs["role"]
    spec["subject"] = f"{spec['subject']} · {inputs['role']}"
    return spec


def prepare(ctx: RunContext, desktop: DockerDesktop, inputs: dict, steps: list[str]) -> dict:
    """Stage the desk for one run and return the truth (also written to data/runs/<id>/truth.json)."""
    from make_assets import variant
    from quotes import make_quotes

    t = time.perf_counter()
    v = variant(inputs["proposal"])
    ITEMS = v["items"]
    sheet_asset, deck_asset = v["sheet"], v["deck"]
    for name in (sheet_asset, deck_asset):
        if not os.path.exists(os.path.join(ASSETS_DIR, name)):
            raise SkillError(f"assets/{name} missing — run `uv run python assets/make_assets.py --proposal {v['n']}`")
    sheet_path, deck_path = inputs["sheet"], inputs["deck"]
    quotes_dir, out_dir = inputs["quotes_dir"], inputs["out_dir"]
    run_dir = os.path.join(ctx.runs_dir, ctx.run.id)
    os.makedirs(run_dir, exist_ok=True)

    close_other_windows(desktop)
    so = ensure_gui_soffice(desktop, sheet_path)
    # no document may survive from an earlier run: a stale, modified sheet still open in Calc would be what
    # `uno open` hands back (same URL) and what the agent reads on screen. Close again, else restart soffice.
    for attempt in range(3):
        try:
            docs = lo.uno(desktop, "list")["docs"]
        except Exception:
            docs = ["<unreachable>"]
        rc, lo_windows = desktop.sh("wmctrl -l -x | grep -c -E 'libreoffice-(calc|impress|draw|writer)'")
        if not docs and lo_windows.strip() in ("", "0"):
            break
        so["stale"] = {"docs": docs, "windows": lo_windows.strip(), "attempt": attempt}
        if attempt == 0:
            try:
                lo.uno(desktop, "closeall")
            except Exception:
                pass
        else:
            lo.kill_soffice(desktop)
            time.sleep(1.0)
            so = {**so, **ensure_gui_soffice(desktop, sheet_path)}
        time.sleep(0.5)
    ctx.log("prepare_soffice", json.dumps(so), step=1)

    # canonical documents back in place, every run: the sheet (a reconcile run saves it) and the deck
    desktop.sh(f"mkdir -p {_q(quotes_dir)} {_q(out_dir)}; rm -f {_q(out_dir)}/* {_q(quotes_dir)}/*.pdf {_q(DOCS)}/.~lock.*#")
    desktop.put_file(os.path.join(ASSETS_DIR, sheet_asset), sheet_path)
    desktop.put_file(os.path.join(ASSETS_DIR, deck_asset), deck_path)
    for name, path in ((sheet_asset, sheet_path), (deck_asset, deck_path)):
        want_sha = hashlib.sha256(open(os.path.join(ASSETS_DIR, name), "rb").read()).hexdigest()
        if _sha(desktop, path) != want_sha:
            raise SkillError(f"could not restore {name} on the desk")
    ctx.log("prepare_files", "sheet and deck restored from assets; For signature emptied", step=1)

    sheet = read_sheet_bytes(read_target_file(desktop, sheet_path))
    if not sheet.consistent():
        raise SkillError(f"canonical sheet inconsistent: {sheet.items} total {sheet.total}")
    base_items = [(l, a) for l, a in sheet.items]
    if [l for l, _ in base_items] != [l for l, _ in ITEMS]:
        raise SkillError(f"sheet rows {base_items} do not match the quote vendors {ITEMS}")

    seed = inputs.get("seed")
    if seed is None:
        seed = int.from_bytes(os.urandom(4), "big")
    with_quotes = pick_quotes(steps)
    truth, files = make_quotes(base_items, seed=seed, all_equal=not with_quotes, proposal=v["n"])
    if with_quotes:
        for name, data in files.items():
            p = os.path.join(run_dir, name)
            open(p, "wb").write(data)
            desktop.put_file(p, f"{quotes_dir}/{name}")
    truth.update({
        "skill_id": ctx.run.skill_id, "run_id": ctx.run.id, "steps": steps, "proposal": v["n"], "client": v["client"],
        "sheet": sheet_path, "deck": deck_path, "slide": int(inputs["slide"]),
        "quotes_dir": quotes_dir if with_quotes else None, "out_dir": out_dir,
        "pdf": f"{out_dir}/{deck_path.rsplit('/', 1)[-1].rsplit('.', 1)[0]}.pdf" if EXPORT in steps else None,
        "mail": _mail_spec(steps, inputs),
    })
    if not with_quotes:  # signature_packet: the sheet is right as it is
        truth["changed"] = None
        truth["sheet_after"] = truth["sheet_before"]
        truth["total_after"] = truth["total_before"]
    truth["expected_amounts"] = [a for _, a in truth["sheet_after"]] + [truth["total_after"]]
    if inputs.get("dress", True):
        try:
            truth["dressed"] = dress(desktop, inputs, steps)
            ctx.log("prepare_dress", json.dumps(truth["dressed"]), step=1)
        except Exception as e:  # noqa: BLE001
            truth["dressed"] = None
            ctx.log("prepare_dress", f"failed: {type(e).__name__}: {e}", step=1)
    else:
        truth["dressed"] = None
    json.dump(truth, open(os.path.join(run_dir, "truth.json"), "w", encoding="utf-8"), indent=1)
    ctx.log("prepare_done", f"seed {seed}; changed {truth['changed']}; truth.json", time.perf_counter() - t, step=1)
    return truth


# ---------------------------------------------------------------------------
# RunContext: the packet skills report their own steps; runs.py's inference
# (first computer action → step 2, typed cells → progress) is for fill_deck_from_sheet.
# TODO(track B): make the inference opt-in on RunContext instead of this instance patch.
# ---------------------------------------------------------------------------
def quiet_step_inference(ctx: RunContext) -> None:
    ctx.STEP_OF_TOOL = {}
    orig = ctx.apply_event

    def apply_event(ev: dict) -> None:
        if ev.get("type") == "tool_call" and ev.get("name") == "computer" and ev.get("action") == "type":
            with ctx.lock:
                now = next((s.n for s in ctx.run.steps if s.status == "now"), None)
                detail = ev.get("input", "") + (f" → error: {ev['error']}" if ev.get("error") else "")
                ctx.log("computer.type", detail, float(ev.get("seconds") or 0), step=now)
                ctx.save()
            return
        orig(ev)

    ctx.apply_event = apply_event


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def run(ctx: RunContext, desktop: Desktop, inputs: dict, skill: dict) -> None:
    steps = skill["steps"]
    inputs = resolve_inputs(inputs, skill["inputs"])
    shots_dir = os.path.join(ctx.runs_dir, ctx.run.id)
    if not ctx.run.steps:
        ctx.set_steps(steps)
    quiet_step_inference(ctx)
    if not have_api_key():
        ctx.finish("failed", error="needs ANTHROPIC_API_KEY: the agent loop (agent-ts) cannot run without it")
        return
    if not isinstance(desktop, DockerDesktop):
        ctx.finish("failed", error="the packet skills need a desk container (Thunar, Atril, LibreOffice with UNO, Mousepad)")
        return

    def n_of(label: str) -> int:
        return steps.index(label) + 1

    inputs["sender"] = desk_login(ctx.run.target, getattr(ctx.run, "person_id", None))
    inputs["role"] = ROLE[inputs["sender"]]
    proc = None
    try:
        # --- prepare ------------------------------------------------------------------
        ctx.step_detail(1, "Staging the desk")
        truth = prepare(ctx, desktop, inputs, steps)
        deck_name = truth["deck"].rsplit("/", 1)[-1]
        deck_sha_before = _sha(desktop, truth["deck"])
        sheet_sha_before = _sha(desktop, truth["sheet"])
        tree_before = snapshot_tree(desktop)
        ctx.step_detail(1, {READ_QUOTES: "Three vendor quotes in Documents/Quotes", FILL_DECK: "From the pricing sheet as it is"}[steps[0]])
        if ctx.stop_requested():
            raise StopIteration

        # --- the agent --------------------------------------------------------------------
        cmd = [os.environ.get("FLOWLINE_NODE", "node"), os.path.join(AGENT_DIR, "run.mjs"), "--run-id", ctx.run.id,
               "--target", ctx.run.target, "--skill", skill["id"], "--inputs", json.dumps(inputs), "--bridge", BRIDGE_URL,
               "--max-steps", str(inputs.get("max_steps", DEFAULT_INPUTS["max_steps"]))]
        t0 = time.perf_counter()
        ctx.log("agent_start", "node agent-ts/run.mjs (tools: computer, report_step)", step=1)
        proc = subprocess.Popen(cmd, cwd=AGENT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stopped = False
        while proc.poll() is None:
            if ctx.stop_requested() or time.perf_counter() - t0 > MAX_STEP_TIMEOUT_S:
                stopped = ctx.stop_requested()
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

        # --- verify (deterministic, independent of what the model said) ----------------------
        problems: list[str] = []
        want = truth["expected_amounts"]
        labels = [l for l, _ in truth["sheet_after"]] + ["Total"]

        if UPDATE_SHEET in steps:
            n = n_of(UPDATE_SHEET)
            if ctx.run.steps[n - 1].status != "done":
                ctx.start_step(n, "Checking the saved sheet")
            try:
                sheet = read_sheet_bytes(read_target_file(desktop, truth["sheet"]))
                got = [a for _, a in sheet.items] + [sheet.total]
            except Exception as e:  # noqa: BLE001
                sheet, got = None, []
                ctx.check("sheet_readable", False, f"{type(e).__name__}: {e}")
            ch = truth["changed"]
            row_now = got[ch["index"]] if len(got) > ch["index"] else None
            ok_row = len(got) == len(want) and row_now == ch["to"]
            ctx.check("sheet_row_corrected", ok_row,
                      f"{ch['item']}: sheet says {row_now}, {ch['vendor']} quoted {fmt_money(ch['to'])} (was {fmt_money(ch['from'])})")
            others_ok = len(got) == len(want) and all(got[i] == want[i] for i in range(len(want) - 1) if i != ch["index"])
            ctx.check("sheet_other_rows_unchanged", others_ok, f"sheet {got[:-1]} vs {want[:-1]}")
            total_ok = bool(got) and got[-1] == want[-1] and sheet is not None and sheet.consistent()
            ctx.check("sheet_total_recomputed", total_ok, f"total {got[-1] if got else None} vs {want[-1]}")
            saved = _sha(desktop, truth["sheet"]) != sheet_sha_before
            ctx.check("sheet_saved_on_disk", saved, "sha256 changed" if saved else "file unchanged — not saved")
            if not (ok_row and others_ok and total_ok):
                problems.append("sheet not corrected to the quotes")
            _finish_step(ctx, n, ok_row and others_ok and total_ok, f"{ch['item']} → {fmt_money(ch['to'])}; total {fmt_money(want[-1])}",
                         f"Sheet does not match the quotes ({got})")

        if FILL_DECK in steps:
            n = n_of(FILL_DECK)
            if ctx.run.steps[n - 1].status != "done":
                ctx.start_step(n, "Reading the deck back")
            try:
                info = lo.uno(desktop, "cells", deck_name, str(truth["slide"]))
                cells = [r[-1] for r in info["cells"]]
                ctx.check("deck_open_in_impress", True, f"{deck_name} slide {truth['slide']}")
            except Exception as e:  # noqa: BLE001
                cells = []
                ctx.check("deck_open_in_impress", False, f"{type(e).__name__}: {str(e)[-200:]}")
            ctx.log("read_back", f"uno: {cells}", step=n)
            amounts = [parse_amount(c) for c in cells]
            ok_cells = [i < len(amounts) and amounts[i] == want[i] for i in range(len(want))]
            for i, (lbl, w) in enumerate(zip(labels, want)):
                ctx.check(f"cell_{i + 1}", ok_cells[i], f"{lbl}: deck says {cells[i] if i < len(cells) else None!r}, should be {fmt_money(w)}")
            items_sum = sum(a or 0 for a in amounts[:-1]) if amounts else None
            ctx.check("deck_items_sum_equals_total", items_sum == want[-1], f"{items_sum} vs {want[-1]}")
            sha_after = _sha(desktop, truth["deck"])
            ctx.check("deck_file_unchanged_on_disk", sha_after == deck_sha_before, f"sha256 {deck_sha_before[:12]} → {sha_after[:12]}")
            try:
                st = lo.uno(desktop, "status", deck_name)
                ctx.check("deck_left_modified_unsaved", bool(st.get("modified")), json.dumps(st))
            except Exception as e:  # noqa: BLE001
                ctx.check("deck_left_modified_unsaved", False, f"{type(e).__name__}")
            if not all(ok_cells) or items_sum != want[-1]:
                problems.append(f"deck cells {cells} do not match {want}")
            if sha_after != deck_sha_before:
                problems.append("the deck file changed on disk — something saved it")
            _finish_step(ctx, n, all(ok_cells) and items_sum == want[-1] and sha_after == deck_sha_before,
                         f"Four cells filled, total {fmt_money(want[-1])}", f"Deck cells {cells} do not match the sheet")

        if EXPORT in steps:
            n = n_of(EXPORT)
            if ctx.run.steps[n - 1].status != "done":
                ctx.start_step(n, "Checking the exported PDF")
            pdf_path = truth["pdf"]
            if _exists(desktop, pdf_path):
                data = read_target_file(desktop, pdf_path)
                ctx.check("pdf_exported", True, f"{pdf_path} ({len(data)} bytes)")
                try:
                    txt = pdf_text(data)
                    ok, detail = pdf_has_amounts(txt, want)
                except Exception as e:  # noqa: BLE001
                    ok, detail = False, f"unreadable: {type(e).__name__}: {e}"
                ctx.check("pdf_contains_amounts", ok, detail)
                if not ok:
                    problems.append("exported PDF does not show the four amounts")
            else:
                ctx.check("pdf_exported", False, f"{pdf_path} missing")
                ctx.check("pdf_contains_amounts", False, "no PDF")
                problems.append("no exported PDF")
            _finish_step(ctx, n, _exists(desktop, pdf_path) and not any("PDF" in p for p in problems),
                         f"{pdf_path.rsplit('/', 1)[-1]} in For signature", "No usable PDF was exported")

        if HAND_OVER in steps:
            n = n_of(HAND_OVER)
            if ctx.run.steps[n - 1].status != "done":
                ctx.start_step(n, "Checking the hand-off mail")
            spec = truth["mail"]
            after = datetime.fromisoformat(ctx.run.started_at) - timedelta(seconds=120)
            needle = spec["subject"].split("—")[-1].strip()          # "for signature · Ops" / "proposal 172 · Finance"
            try:
                msg = newest_mail(spec["to"], needle, spec["attachment"], after, sender=spec["sender"])
                mail_err = None
            except Exception as e:  # noqa: BLE001
                msg, mail_err = None, f"{type(e).__name__}: {e}"
            ctx.check("mail_received", msg is not None,
                      f"{spec['to']}@ got {msg['subject']!r} from {msg['from']} at {msg['date']} with {msg['attachments']}" if msg
                      else f"no mail to {spec['to']}@ from {spec['sender']}@ with {needle!r}"
                           + (f" + {spec['attachment']}" if spec["attachment"] else "") + " after run start" + (f" ({mail_err})" if mail_err else ""))
            if msg is None:
                problems.append("hand-off mail not received")
                if spec["attachment"]:
                    ctx.check("mail_attachment_matches_file", False, "no mail")
                ctx.check("mail_body_complete", False, "no mail")
            else:
                if spec["attachment"]:
                    src = truth["pdf"]
                    try:
                        att = mail.fetch_attachment(spec["to"], msg["id"], spec["attachment"])
                        att_sha = hashlib.sha256(att).hexdigest()
                    except Exception as e:  # noqa: BLE001
                        att_sha = f"unreadable: {type(e).__name__}"
                    file_sha = _sha(desktop, src)
                    same = att_sha == file_sha and bool(file_sha)
                    ctx.check("mail_attachment_matches_file", same, f"attachment sha256 {att_sha[:12]} vs {src.rsplit('/', 1)[-1]} {file_sha[:12]}")
                    if not same:
                        problems.append("mail attachment is not the file on the desk")
                body = _mail_body(spec["to"], msg["id"])
                if EXPORT in steps:
                    ok_body, detail = pdf_has_amounts(body, want)
                else:
                    vendor = truth["changed"]["vendor"] if truth.get("changed") else None
                    ok_body, detail = note_ok(body, vendor, want[-1])
                ctx.check("mail_body_complete", ok_body, "body: " + detail + f" | {body.strip()[:200]!r}")
                if not ok_body:
                    problems.append("mail body incomplete")
            if spec.get("cc"):
                try:
                    cc_msg = newest_mail(spec["cc"], needle, spec["attachment"], after, sender=spec["sender"])
                except Exception as e:  # noqa: BLE001
                    cc_msg = None
                ctx.check("mail_cc_received", cc_msg is not None, f"{spec['cc']}@ {'got' if cc_msg else 'did not get'} the copy")
                if cc_msg is None:
                    problems.append(f"no copy to {spec['cc']}@")

        # nothing else under Documents changed
        allowed = set()
        if truth.get("pdf"):
            allowed.add(os.path.relpath(truth["pdf"], DOCS))
        if UPDATE_SHEET in steps:
            allowed.add(os.path.relpath(truth["sheet"], DOCS))
        tree_after = snapshot_tree(desktop)
        bad = tree_changes(tree_before, tree_after, allowed)
        ctx.check("nothing_else_changed", not bad, "; ".join(bad)[:400] if bad else f"only {sorted(allowed)}")
        if bad:
            problems.append("unexpected file changes: " + ", ".join(bad))
        ctx.check("agent_finished", proc.returncode == 0,
                  f"exit code {proc.returncode}" + (" (step limit)" if proc.returncode == 2 else ""))
        if proc.returncode != 0:
            problems.append("agent exited with code %d (%s)" % (proc.returncode, "step limit" if proc.returncode == 2 else "error"))

        shot = desktop.screenshot()
        ctx.run.final_screenshot = _save_png(shots_dir, "final.png", shot.png)
        if HAND_OVER in steps:
            spec = truth["mail"]
            _finish_step(ctx, n_of(HAND_OVER), not problems,
                         f"Mailed {spec['to']}@" + (f" with {spec['attachment']}; the deck stays unsaved in Impress" if spec["attachment"] else " — the sheet is saved on the desk"),
                         "Needs your attention: " + (problems[0] if problems else ""))
        if not inputs.get("leave_open", True):
            try:
                lo.uno(desktop, "closeall")
            except Exception:
                pass
            close_other_windows(desktop)
        if problems:
            raise SkillError("; ".join(problems))
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
            if ctx.run.final_screenshot is None:
                shot = desktop.screenshot()
                ctx.run.final_screenshot = _save_png(shots_dir, "final.png", shot.png)
        except Exception:
            pass
        ctx.finish("failed", error=f"{type(e).__name__}: {e}")


def _finish_step(ctx: RunContext, n: int, ok: bool, ok_detail: str, bad_detail: str) -> None:
    """Mark step n done. The agent's own detail is kept when the step checks out; otherwise say what is wrong."""
    st = ctx.run.steps[n - 1]
    if ok:
        ctx.done_step(n, None if (st.status == "done" and st.detail) else ok_detail)
    else:
        ctx.done_step(n, bad_detail)


def _save_png(d: str, name: str, png: bytes) -> str:
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "wb") as f:
        f.write(png)
    return p
