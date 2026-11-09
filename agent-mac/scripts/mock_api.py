#!/usr/bin/env python3
"""Stub of the Flowline board API (SCHEMA.md §2, §11) for exercising agent-mac end to end.

  python3 scripts/mock_api.py [--port 8787] [--offer]

Endpoints:
  POST   /api/boards/{board}/records            verify hash (and sig if `cryptography` is installed) → 201 {id, accepted}
  DELETE /api/boards/{board}/records/{id}       withdraw → 200
  GET    /api/boards/{board}/plans              one plan
  POST   /api/boards/{board}/plans/{id}/approve approving it makes a suggestion `offered` for pm-1
  GET    /api/people/{person}/suggestions       list (empty until a plan is approved, or --offer)
  POST   /api/suggestions/{id}/respond          {answer: do_it|not_now|dont_ask}
  POST   /api/runs                              start a simulated run; steps advance every second
  GET    /api/runs/{id}                         poll
  POST   /api/runs/{id}/stop                    stop
Only the record hash is printed; keys are never involved."""
import argparse, hashlib, json, sys, time, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    import base64
    HAVE_CRYPTO = True
except Exception:
    HAVE_CRYPTO = False

records = {}
runs = {}
RUN_DELAY = 0.0
suggestion = {
    "id": "sug-1", "person_id": "pm-1", "skill_id": "fill_deck_from_sheet",
    "title": "Fill this deck's pricing from your sheet?",
    "body": "You did this 11 times last week, about 22 minutes each. I'd take under a minute, and nothing is saved until you check it.",
    "why_now": "your team approved \"Agent fills the deck, PM reviews\" on Mon 11 Nov",
    "count_last_week": 11, "minutes_each": 22, "estimate_s": 50, "plan_id": "plan-2", "status": "never",
}
plan = {"id": "plan-2", "rank": 1, "name": "Agent fills the deck, PM reviews", "sub": "Copy pricing into the proposal deck",
        "hours": 4.0, "status": "proposed", "source": "prototype"}

RUN_STEPS = [
    ("READ THE SHEET", "Four line items and the total from pricing-sheet #172"),
    ("FILL THE DECK", "Typing into slide 6, Investment"),
    ("CHECK THE TOTAL", "Deck total must equal $4,290"),
    ("LEAVE IT FOR YOU", "Nothing is saved until you keep it"),
]
STEP_SECONDS = [2, 4, 2, 1]  # how long each step takes in the simulation


def canonical_hash(rec):
    body = {k: v for k, v in rec.items() if k not in ("hash", "pubkey", "sig")}
    s = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def run_view(r):
    elapsed = time.time() - r["started"]
    if r["stopped_at"] is not None:
        elapsed = r["stopped_at"] - r["started"]
    steps, t, status = [], 0.0, "done"
    for i, (label, detail) in enumerate(RUN_STEPS):
        dur = STEP_SECONDS[i]
        if elapsed >= t + dur:
            steps.append({"n": i + 1, "label": label, "detail": detail, "status": "done", "at_s": int(t + dur)})
        elif elapsed >= t:
            frac = (elapsed - t) / dur
            progress = [int(frac * 4), 4] if i == 1 else None
            step = {"n": i + 1, "label": label, "detail": detail, "status": "now"}
            if progress:
                step["progress"] = progress
            steps.append(step)
            status = "running"
        else:
            steps.append({"n": i + 1, "label": label, "detail": detail, "status": "pending"})
            status = "running"
        t += dur
    if r["stopped_at"] is not None:
        status = "stopped"
    checks = [{"name": "total matches", "ok": True, "detail": "$4,290"}] if status == "done" else []
    return {"id": r["id"], "skill_id": r["skill_id"], "target": r["target"], "status": status,
            "started_at": r["started_at"], "elapsed_s": int(elapsed), "steps": steps, "checks": checks}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))

    def send(self, code, obj=None):
        data = json.dumps(obj if obj is not None else {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        p = self.path.split("?")[0].strip("/").split("/")
        if p[:2] == ["api", "people"] and len(p) == 4 and p[3] == "suggestions":
            items = [suggestion] if suggestion["person_id"] == p[2] and suggestion["status"] != "never" else []
            return self.send(200, items)
        if p[:2] == ["api", "runs"] and len(p) == 3:
            r = runs.get(p[2])
            return self.send(200, run_view(r)) if r else self.send(404, {"error": "no such run"})
        if p[:2] == ["api", "boards"] and len(p) == 4 and p[3] == "plans":
            return self.send(200, {"board_id": p[2], "reruns": 20, "weeks": 6, "headline": "One plan", "today_h": 19.0,
                                   "plans": [plan], "note": "prototype", "source": "prototype"})
        if p[:2] == ["api", "boards"] and len(p) == 4 and p[3] == "records":
            return self.send(200, list(records.values()))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        p = self.path.strip("/").split("/")
        if p[:2] == ["api", "boards"] and len(p) == 4 and p[3] == "records":
            rec = self.body()
            h = canonical_hash(rec)
            if h != rec.get("hash"):
                print(f"REJECT record {rec.get('id')}: hash mismatch\n  got      {rec.get('hash')}\n  expected {h}")
                return self.send(400, {"accepted": False, "error": "hash mismatch", "expected": h})
            sig_note = "sig not checked (pip install cryptography to verify)"
            if HAVE_CRYPTO:
                try:
                    Ed25519PublicKey.from_public_bytes(base64.b64decode(rec["pubkey"])).verify(base64.b64decode(rec["sig"]), h.encode())
                    sig_note = "sig OK"
                except Exception as e:
                    print(f"REJECT record {rec.get('id')}: bad signature ({e})")
                    return self.send(400, {"accepted": False, "error": "bad signature"})
            records[rec["id"]] = rec
            print(f"ACCEPT record {rec['id']} board={rec['board_id']} person={rec['person_id']} steps={len(rec['steps'])} "
                  f"hands_on={rec['hands_on_min']} waiting={rec['waiting_min']} kept_private={rec['kept_private']}\n  hash {h}  ({sig_note})")
            return self.send(201, {"id": rec["id"], "accepted": True})
        if p[:2] == ["api", "boards"] and len(p) == 6 and p[3] == "plans" and p[5] == "approve":
            plan["status"] = "approved"
            suggestion["status"] = "offered"
            print("plan approved → suggestion offered")
            return self.send(200, {"ok": True, "plan_id": p[4]})
        if p[:2] == ["api", "suggestions"] and len(p) == 4 and p[3] == "respond":
            ans = self.body().get("answer")
            suggestion["status"] = {"do_it": "accepted", "not_now": "declined", "dont_ask": "never"}.get(ans, suggestion["status"])
            print(f"suggestion {p[2]} → {ans}")
            return self.send(200, {"ok": True, "status": suggestion["status"]})
        if p == ["api", "runs"]:
            b = self.body()
            if RUN_DELAY:
                time.sleep(RUN_DELAY)  # simulate the executor opening the deck before answering
            rid = "run-" + uuid.uuid4().hex[:6]
            runs[rid] = {"id": rid, "skill_id": b.get("skill_id", "fill_deck_from_sheet"), "target": b.get("target", "mac"),
                         "started": time.time(), "started_at": datetime.now(timezone.utc).isoformat(), "stopped_at": None}
            print(f"run {rid} started for suggestion {b.get('suggestion_id')}")
            return self.send(201, run_view(runs[rid]))
        if p[:2] == ["api", "runs"] and len(p) == 4 and p[3] == "stop":
            r = runs.get(p[2])
            if not r:
                return self.send(404, {"error": "no such run"})
            r["stopped_at"] = time.time()
            print(f"run {p[2]} stopped")
            return self.send(200, run_view(r))
        self.send(404, {"error": "not found"})

    def do_DELETE(self):
        p = self.path.strip("/").split("/")
        if p[:2] == ["api", "boards"] and len(p) == 5 and p[3] == "records":
            if p[4] in records:
                del records[p[4]]
                print(f"WITHDRAW record {p[4]}")
                return self.send(200, {"id": p[4], "withdrawn": True})
            return self.send(404, {"error": "no such record"})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--offer", action="store_true", help="offer the suggestion immediately (skip plan approval)")
    ap.add_argument("--run-delay", type=float, default=0.0, help="seconds to wait before answering POST /api/runs")
    a = ap.parse_args()
    RUN_DELAY = a.run_delay
    if a.offer:
        suggestion["status"] = "offered"
    print(f"mock board API on http://localhost:{a.port}  (ed25519 verify: {'on' if HAVE_CRYPTO else 'off'})")
    print("approve the plan to offer a suggestion:  curl -X POST localhost:%d/api/boards/northwind/plans/plan-2/approve" % a.port)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
