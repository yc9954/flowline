"""The PM's day on a desk container, scripted (BUILD-PLAN §3), for the observer test.

Steps (base minutes; everything is divided by --speed):
  1  Prepare pricing sheet   open pricing-sheet.ods, retype the amounts slowly        10
  2  Write mail to client    open "Mail - proposal 172.odt" (Writer stands in for mail) 7
  P1 Personal chat · Mom     xmessage window, read for a while                           2   (planted → counted_as_away)
  3  Away                    no input at all                                              7   (idle ≥ 5 min → waiting)
  P2 First National Bank     Chromium on a local bank-looking page                       2   (planted → removed)
  4  Fill deck from sheet    open proposal-172.odp slide 6; per value: click sheet cell,
                             ctrl-c, click deck cell, ctrl-v (typed if paste misfires)   14
  P3 Kim Minji contract.odt  open for a while                                             3   (planted → renamed)
  5  Review deck             page through the deck                                        4

Writes the ground truth (step boundaries + planted items, real and scaled clocks)
to data/runs/actor-<stamp>.json.

    uv run python actor.py --speed 10 [--origin <epoch>] [--container desk1]
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone

import lo
from desktop import DEFAULT_HOST, DockerDesktop
from runs import RUNS_DIR
from sheet import fmt_money

SHEET = "/config/Documents/pricing-sheet.ods"
DECK = "/config/Documents/proposal-172.odp"
MAIL = "/config/Documents/Mail - proposal 172.odt"
CONTRACT = "/config/Documents/Kim Minji contract.odt"
BANK_PORT = 8099
AMOUNTS = [2600, 1150, 540]
TOTAL = sum(AMOUNTS)

PLANTED = [
    {"id": "chat", "kind": "personal_chat", "needle": ["Mom", "Personal chat"]},
    {"id": "bank", "kind": "banking", "needle": ["First National Bank", "Bank"]},
    {"id": "contract", "kind": "name_in_filename", "needle": ["Kim Minji", "Minji"]},
]

_FODT = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
 office:version="1.3" office:mimetype="application/vnd.oasis.opendocument.text">
<office:body><office:text>{paras}</office:text></office:body></office:document>'''

_BANK_HTML = '''<!doctype html><html><head><meta charset="utf-8"><title>First National Bank — Login</title>
<style>body{font-family:sans-serif;background:#0b3d91;color:#fff;margin:0}header{padding:24px 40px;font-size:28px;font-weight:700}
main{background:#fff;color:#222;margin:40px auto;max-width:420px;padding:32px;border-radius:8px}input{width:100%;padding:10px;margin:8px 0 16px;border:1px solid #bbb}
button{background:#0b3d91;color:#fff;border:0;padding:12px 20px;width:100%}</style></head>
<body><header>First National Bank</header><main><h2>Online Banking Login</h2><label>User ID</label><input><label>Password</label><input type="password">
<button>Log in</button><p style="font-size:12px;color:#777">Demo page served locally for the Flowline privacy test. Not a real bank.</p></main></body></html>'''


class Actor:
    def __init__(self, container: str = "desk1", host: str | None = None, speed: float = 10.0, origin: float | None = None,
                 out_dir: str = RUNS_DIR):
        self.d = DockerDesktop(container, host=host)
        self.speed = speed
        self.origin = origin or time.time()
        self.out_dir = out_dir
        self.truth: list[dict] = []
        self._cur: dict | None = None
        self.log_lines: list[str] = []

    # -- clocks -------------------------------------------------------------------
    def scaled(self, real: float) -> float:
        return self.origin + (real - self.origin) * self.speed

    def iso(self, real: float) -> str:
        return datetime.fromtimestamp(self.scaled(real), tz=timezone.utc).astimezone().isoformat(timespec="seconds")

    def sleep_min(self, minutes: float) -> None:
        time.sleep(minutes * 60.0 / self.speed)

    def pause(self, seconds: float) -> None:
        time.sleep(max(0.05, seconds / self.speed))

    # -- ground truth -------------------------------------------------------------
    def begin(self, name: str, kind: str = "step", planted: str | None = None) -> None:
        self.end()
        now = time.time()
        self._cur = {"name": name, "kind": kind, "planted": planted, "start_real": now, "start": self.iso(now)}
        self.say(f"▶ {name}")

    def end(self) -> None:
        if self._cur:
            now = time.time()
            self._cur.update(end_real=now, end=self.iso(now), minutes_scaled=round((now - self._cur["start_real"]) * self.speed / 60, 1))
            self.truth.append(self._cur)
            self._cur = None

    def say(self, msg: str) -> None:
        line = f"[actor {datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_lines.append(line)
        print(line, file=sys.stderr, flush=True)

    # -- setup --------------------------------------------------------------------
    def setup(self) -> None:
        d = self.d
        self.say("setup: documents, bank page")
        d.sh("mkdir -p /tmp/actor /tmp/bank")
        mail = _FODT.format(paras="".join(f"<text:p>{p}</text:p>" for p in [
            "To: ops@halden-logistics.example", "Subject: Proposal #172 — corporate wellness programme", "",
            "Hi Dana,", "", "Please find attached our proposal for the 120-staff programme. Pricing is on slide 6.", "", "Best, Sam"]))
        contract = _FODT.format(paras="".join(f"<text:p>{p}</text:p>" for p in [
            "TRAINER AGREEMENT", "", "This agreement is between Northwind Fitness and the trainer named above.",
            "1. Term. Twelve months from the start date.", "2. Hours. Up to 24 hours per week across the three clubs.",
            "3. Pay. Monthly, per the rate card.", "", "Signed: ____________________"]))
        import tempfile
        for name, content in (("mail.fodt", mail), ("contract.fodt", contract)):
            with tempfile.NamedTemporaryFile("w", suffix=".fodt", delete=False, encoding="utf-8") as f:
                f.write(content)
                p = f.name
            d.put_file(p, f"/tmp/actor/{name}")
            os.unlink(p)
        prof = "-env:UserInstallation=file:///tmp/lo_headless_profile"
        rc, out = d.sh(f"cd /tmp/actor && soffice {prof} --headless --convert-to odt --outdir /tmp/actor mail.fodt contract.fodt 2>&1", timeout=180)
        if rc != 0:
            raise RuntimeError(f"odt conversion failed: {out[-300:]}")
        d.sh(f"cp /tmp/actor/mail.odt {shlex.quote(MAIL)} && cp /tmp/actor/contract.odt {shlex.quote(CONTRACT)}")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(_BANK_HTML)
            p = f.name
        d.put_file(p, "/tmp/bank/bank.html")
        os.unlink(p)
        d.sh(f"pgrep -f '[h]ttp.server {BANK_PORT}' >/dev/null || (cd /tmp/bank && (setsid nohup python3 -m http.server {BANK_PORT} --bind 127.0.0.1 >/tmp/bank/server.log 2>&1 &))")
        time.sleep(1.0)
        d.sh("pkill xmessage; pkill -f chromium; true")
        lo.kill_soffice(d)
        time.sleep(1.0)
        rc, out = d.sh(f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{BANK_PORT}/bank.html || wget -q -O /dev/null -S http://127.0.0.1:{BANK_PORT}/bank.html 2>&1 | head -1")
        self.say(f"bank page served: {out.strip()[:40]!r}")

    # -- helpers --------------------------------------------------------------------
    def open_doc(self, path: str, title_part: str) -> None:
        d = self.d
        docs = []
        try:
            docs = lo.uno(d, "list")["docs"]
        except Exception:
            if lo.soffice_running(d):
                # running without the UNO socket (not started by us): restart it so we can drive it
                self.say("soffice is running without a UNO socket; restarting it")
                lo.kill_soffice(d)
                time.sleep(1.0)
        if not any(u.endswith(path.rsplit("/", 1)[-1].replace(" ", "%20")) for u in docs):
            if lo.soffice_running(d):
                d.sh(f"nohup soffice --norestore {shlex.quote(path)} >/dev/null 2>&1 &")
                t0 = time.time()
                while time.time() - t0 < 30:
                    if title_part.lower() in d.active_window_title().lower():
                        break
                    time.sleep(0.5)
            else:
                lo.start_soffice(d, path, wait_title=title_part)
            time.sleep(1.0)
        name = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        lo.activate_window(d, name)  # by document name: several Writer windows may be open
        time.sleep(0.4)
        lo.maximize_active(d)
        time.sleep(0.4)

    def type_slowly(self, text: str, per_char: float = 0.5) -> None:
        for ch in text:
            self.d.type(ch) if ch != "\n" else self.d.key("Return")
            self.pause(per_char)

    def wiggle(self, seconds: float, around=(960, 600)) -> None:
        """Small pointer movements for `seconds` (base time) so the window counts as active."""
        t_end = time.time() + seconds / self.speed
        i = 0
        while time.time() < t_end:
            self.d.move(around[0] + (i % 5) * 7, around[1] + (i % 3) * 5)
            i += 1
            self.pause(15)

    # -- the day --------------------------------------------------------------------
    def day(self) -> None:
        d = self.d
        # 1 Prepare pricing sheet (10 min) — a step's clock starts once its document is on screen
        self.open_doc(SHEET, "Calc")
        self.begin("Prepare pricing sheet")
        d.click(700, 500)
        d.key("ctrl+Home")
        d.key("Down"); d.key("Right")        # B2
        self.pause(20)
        for amt in AMOUNTS:
            self.type_slowly(str(amt), per_char=1.2)
            d.key("Return")
            self.pause(60)
        d.key("ctrl+Home")
        self.wiggle(10 * 60 - 3 * 60, around=(900, 500))
        # 2 Write mail (7 min)
        self.open_doc(MAIL, "Writer")
        self.begin("Write mail to client")
        d.key("ctrl+End")
        d.key("Return")
        self.type_slowly("Let me know if Thursday works for a call about the onboarding week.", per_char=0.9)
        self.wiggle(7 * 60 - 60, around=(900, 700))
        # P1 personal chat (2 min)
        self.begin("Personal chat · Mom", kind="away", planted="chat")
        d.sh('nohup xmessage -center -title "Personal chat · Mom" "Mom: Did you eat? Call me when you are free." >/dev/null 2>&1 &')
        time.sleep(1.0)
        lo.activate_window(d, "Personal chat")
        self.wiggle(2 * 60, around=(980, 560))
        d.sh("pkill xmessage; true")
        # 3 idle (7 min)
        self.begin("Away from desk", kind="waiting")
        lo.activate_window(d, "Writer")
        self.sleep_min(7)
        # P2 bank (2 min)
        self.begin("First National Bank — Login", kind="removed", planted="bank")
        d.sh(f"nohup chromium --no-sandbox --no-first-run --disable-gpu --password-store=basic --new-window "
             f"--window-size=1200,800 http://127.0.0.1:{BANK_PORT}/bank.html >/dev/null 2>&1 &")
        t0 = time.time()
        while time.time() - t0 < 25 and "bank" not in d.active_window_title().lower():
            time.sleep(0.5)
        self.wiggle(2 * 60, around=(960, 400))
        d.sh("pkill -f chromium; true")
        time.sleep(0.5)
        # 4 Fill deck from sheet (14 min)
        self.open_doc(DECK, "Impress")
        self.begin("Fill deck from sheet", kind="step")
        lo.uno(d, "goto", "proposal-172.odp", "6")
        time.sleep(0.5)
        positions = self._deck_positions()
        values = [fmt_money(a) for a in AMOUNTS] + [fmt_money(TOTAL)]
        for i, val in enumerate(values):
            lo.activate_window(d, "Calc")
            self.pause(8)
            d.click(700, 500)
            d.key("ctrl+Home")
            d.key("Down", repeat=i + 1); d.key("Right")       # B2..B5
            self.pause(10)
            d.key("ctrl+c")
            self.pause(15)
            lo.activate_window(d, "Impress")
            self.pause(8)
            d.click(*positions[i])
            self.pause(10)
            d.key("ctrl+v")
            self.pause(20)
            cells = self._deck_cells()
            if cells is None or cells[i].strip() != val:
                self.say(f"paste gave {cells[i] if cells else None!r}; typing {val} instead")
                d.key("ctrl+z")
                d.click(*positions[i])
                d.key("ctrl+a")
                self.type_slowly(val, per_char=0.6)
            d.key("Escape")
            self.pause(30)
        self.wiggle(14 * 60 - 4 * 110, around=(1000, 600))
        # P3 contract with a person's name in the file name (3 min)
        self.open_doc(CONTRACT, "Writer")
        self.begin("Kim Minji contract.odt", kind="renamed", planted="contract")
        self.wiggle(3 * 60, around=(900, 650))
        try:
            lo.uno(d, "close", "contract.odt")
        except Exception:
            d.key("ctrl+w")
        time.sleep(0.5)
        # 5 Review deck (4 min)
        self.open_doc(DECK, "Impress")
        self.begin("Review deck")
        for _ in range(5):
            d.key("Next")
            self.pause(40)
        self.wiggle(4 * 60 - 200, around=(1000, 600))
        self.end()

    def _deck_positions(self):
        from lo import cell_positions_from_geometry, find_slide_rect
        geom = lo.uno(self.d, "geometry", "proposal-172.odp", "6")
        rect = find_slide_rect(self.d.screenshot().png)
        if not rect:
            raise RuntimeError("could not find the slide on screen")
        return cell_positions_from_geometry(geom, rect)

    def _deck_cells(self):
        try:
            return [r[-1] for r in lo.uno(self.d, "cells", "proposal-172.odp", "6")["cells"]]
        except Exception:
            return None

    def save(self) -> str:
        os.makedirs(self.out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(self.out_dir, f"actor-{stamp}.json")
        json.dump({"speed": self.speed, "origin": self.origin, "steps": self.truth, "planted": PLANTED,
                   "log": self.log_lines}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return path

    def run(self, skip_setup: bool = False) -> str:
        if not skip_setup:
            self.setup()
        try:
            self.day()
        finally:
            self.end()
            self.d.sh("pkill xmessage; pkill -f chromium; true")
            path = self.save()
            self.d.close()
        return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="desk1")
    ap.add_argument("--host", default=DEFAULT_HOST, help="ssh host of the docker engine, or 'local'")
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--origin", type=float, default=None)
    ap.add_argument("--skip-setup", action="store_true")
    args = ap.parse_args()
    a = Actor(args.container, args.host, args.speed, args.origin)
    path = a.run(skip_setup=args.skip_setup)
    print(json.dumps({"truth": path, "steps": [(s["name"], s["minutes_scaled"]) for s in a.truth]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
