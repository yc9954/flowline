"""Events → DraftDay → auto-approved, signed Record (SCHEMA §1, §2, §12).

Segmentation: a new segment at every app / title switch and whenever idle ≥ 5 min
(the idle stretch becomes a "waiting" segment); fragments < 2 min are merged into
the previous segment.  Private events (chat → counted_as_away, banking → removed)
never become steps; they are listed in `left_out`.  Names in file hints are
already masked by the observer; a step whose file hint was masked is reported as
`name_in_filename` / `renamed`.

Step names come from the Claude Messages API (model FLOWLINE_MODEL) given only
masked titles; without ANTHROPIC_API_KEY a rule-based namer is used.

The approved Record is canonicalised, hashed (sha256 hex) and signed (Ed25519,
key at ~/.flowline/key, 0600), saved to data/runs/record-<id>.json and POSTed
to the board API (http://localhost:8787/api/boards/northwind/records).

    uv run python compiler.py --events data/runs/observer/desk1/2026-11-09.jsonl --person pm-1 --role PM
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

IDLE_SPLIT_S = 5 * 60
MERGE_UNDER_S = 2 * 60
API_URL = os.environ.get("FLOWLINE_API", "http://localhost:8787")
from runs import RUNS_DIR  # noqa: E402  (FLOWLINE_ROOT / package-relative)
KEY_PATH = os.path.expanduser(os.environ.get("FLOWLINE_KEY", "~/.flowline/key"))

TOOL_OF_APP = {"calc": "sheets", "impress": "slides", "writer": "docs", "browser": "browser", "libreoffice": "docs",
               "desktop": "desktop", "xmessage": "chat"}


# ---------------------------------------------------------------------------
# events → segments
# ---------------------------------------------------------------------------
@dataclass
class Segment:
    start: datetime
    end: datetime
    app: str
    title_hash: str
    title_masked: str
    file_hint: Optional[str]
    kind: str = "hands_on"          # hands_on | waiting | away | removed
    private: Optional[str] = None   # personal_chat | banking
    n: int = 0
    titles: set = field(default_factory=set)

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def load_events(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    out.sort(key=lambda e: e["ts"])
    return out


def segment(events: list[dict], idle_split_s: float = IDLE_SPLIT_S, merge_under_s: float = MERGE_UNDER_S) -> list[Segment]:
    segs: list[Segment] = []
    if not events:
        return segs
    # sample spacing: use the median gap as "one tick" so the last event covers a tick
    gaps = sorted((parse_ts(b["ts"]) - parse_ts(a["ts"])).total_seconds() for a, b in zip(events, events[1:]))
    tick = gaps[len(gaps) // 2] if gaps else 1.0
    tick = max(0.5, min(tick, 60.0))
    cur: Optional[Segment] = None
    first_ts = parse_ts(events[0]["ts"])
    for e in events:
        ts = parse_ts(e["ts"])
        private = e.get("private")
        idle = float(e.get("idle_s", 0))
        if private:
            kind = "away" if private == "personal_chat" else "removed"
            key = ("private", private)
        elif idle >= idle_split_s:
            kind = "waiting"
            key = ("idle",)
        else:
            kind = "hands_on"
            key = (e.get("app"), e.get("title_hash"))
        if cur is not None and cur_key == key:
            cur.end = ts + timedelta(seconds=tick)
            cur.n += 1
            if kind == "hands_on" and e.get("title_masked"):
                cur.titles.add(e["title_masked"])
            continue
        if kind == "waiting":
            # the idle stretch began `idle` seconds ago: carve it out of the previous segment
            start = max(ts - timedelta(seconds=idle), first_ts)  # never before the log begins
            if cur is not None and cur.end > start:
                cur.end = max(cur.start, start)
        else:
            start = ts
        cur = Segment(start=start, end=ts + timedelta(seconds=tick), app=e.get("app", "unknown"),
                      title_hash=e.get("title_hash", ""), title_masked=e.get("title_masked", ""),
                      file_hint=e.get("file_hint"), kind=kind, private=private, n=1,
                      titles={e["title_masked"]} if e.get("title_masked") else set())
        cur_key = key
        segs.append(cur)
    # merge fragments shorter than merge_under_s into the previous segment (never merge private ones away)
    merged: list[Segment] = []
    for s in segs:
        if merged and s.kind == "hands_on" and s.seconds < merge_under_s and merged[-1].kind == "hands_on":
            prev = merged[-1]
            prev.end = s.end
            prev.n += s.n
            prev.titles |= s.titles
            continue
        if merged and s.kind == "hands_on" and merged[-1].kind == "hands_on" and merged[-1].seconds < merge_under_s:
            # previous was the fragment: absorb it into this one
            prev = merged.pop()
            s.start = prev.start
            s.n += prev.n
            s.titles |= prev.titles
        merged.append(s)
    # a tiny "waiting"/private fragment (a flicker) is dropped into its neighbour
    out: list[Segment] = []
    for s in merged:
        if s.kind in ("waiting",) and s.seconds < 30 and out:
            out[-1].end = s.end
            continue
        if s.kind == "hands_on" and s.seconds < 15:
            # a sliver left after carving out an idle stretch (or a flicker next to a private window)
            if out and out[-1].kind == "hands_on":
                out[-1].end = s.end
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------
_CASE_RE = re.compile(r"(proposal|quote|deal|case|invoice|contract|order)[\s_-]*#?\s*(\d{2,5})", re.IGNORECASE)


def case_id_of(text: str) -> Optional[str]:
    m = _CASE_RE.search(text or "")
    if m:
        return f"{m.group(1).lower()} #{m.group(2)}"
    return None


def rule_name(seg: Segment) -> str:
    t = (seg.title_masked or "").lower()
    fh = (seg.file_hint or "").lower()
    app = seg.app
    if seg.kind == "waiting":
        return "Away from desk"
    if "pricing" in fh or ("pricing" in t and app == "calc"):
        return "Prepare pricing sheet"
    if app == "calc":
        return "Work in spreadsheet"
    if app == "impress":
        return "Fill proposal deck" if "proposal" in fh or "proposal" in t else "Edit slide deck"
    if app == "writer":
        if "mail" in fh or "mail" in t:
            return "Write mail to client"
        if "contract" in fh or "contract" in t:
            return "Review contract"
        return "Write document"
    if app == "browser":
        return "Browse the web"
    if app == "desktop":
        return "Switch between apps"
    return f"Work in {app}"


def llm_names(segs: list[Segment], model: str) -> Optional[list[str]]:
    """Ask Claude for short step names from masked titles only. None on any failure."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        rows = [{"idx": i, "app": s.app, "minutes": round(s.seconds / 60, 1), "kind": s.kind,
                 "titles": sorted(s.titles)[:5], "file_hint": s.file_hint} for i, s in enumerate(segs)]
        prompt = ("These are the work segments of one person's day, derived from masked window titles "
                  "(personal names are already replaced by [name]). Give each a short step name (2-5 words, "
                  "verb first, e.g. 'Prepare pricing sheet', 'Fill proposal deck'). 'waiting' segments are "
                  "'Away from desk'. Return JSON only: {\"names\": [\"...\", ...]} with one name per segment in order.\n\n"
                  + json.dumps(rows, ensure_ascii=False))
        resp = client.messages.create(model=model, max_tokens=2000, messages=[{"role": "user", "content": prompt}],
                                      output_config={"format": {"type": "json_schema", "schema": {
                                          "type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                                          "required": ["names"], "additionalProperties": False}}})
        text = "".join(b.text for b in resp.content if b.type == "text")
        names = json.loads(text)["names"]
        if len(names) != len(segs):
            return None
        return [n.strip()[:60] for n in names]
    except Exception as e:  # noqa: BLE001
        print(f"[compiler] model naming failed, using rules: {type(e).__name__}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# DraftDay / Record
# ---------------------------------------------------------------------------
def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def compile_draft(events: list[dict], person_id: str, role: str, board_id: str = "northwind",
                  model: str | None = None, use_model: bool = True) -> dict:
    segs = segment(events)
    steps_segs = [s for s in segs if s.kind in ("hands_on", "waiting")]
    names = llm_names(steps_segs, model or os.environ.get("FLOWLINE_MODEL", "claude-sonnet-5-5")) if use_model else None
    if names is None:
        names = [rule_name(s) for s in steps_segs]
    steps = []
    left_out = []
    for i, (s, name) in enumerate(zip(steps_segs, names)):
        case_id = case_id_of((s.file_hint or "") + " " + (s.title_masked or ""))
        step = {"idx": len(steps) + 1, "start": iso(s.start), "end": iso(s.end), "name": name,
                "kind": "waiting" if s.kind == "waiting" else "hands_on",
                "tools": sorted({TOOL_OF_APP.get(s.app, s.app)}) if s.kind == "hands_on" else [],
                "share": True}
        if case_id:
            step["case_id"] = case_id
        if s.file_hint and "[name]" in s.file_hint:
            left_out.append({"kind": "name_in_filename", "label": s.file_hint, "action": "renamed"})
        steps.append(step)
    for s in segs:
        if s.kind == "away":
            left_out.append({"kind": "personal_chat", "label": "Personal chat", "minutes": int(round(s.seconds / 60)),
                             "action": "counted_as_away"})
        elif s.kind == "removed":
            left_out.append({"kind": "banking", "label": "Banking", "minutes": int(round(s.seconds / 60)),
                             "action": "removed"})
    date = steps[0]["start"][:10] if steps else datetime.now().strftime("%Y-%m-%d")
    hands_on = sum((parse_ts(s["end"]) - parse_ts(s["start"])).total_seconds() for s in steps if s["kind"] == "hands_on") / 60
    waiting = sum((parse_ts(s["end"]) - parse_ts(s["start"])).total_seconds() for s in steps if s["kind"] == "waiting") / 60
    summary = (f"{len(steps)} steps, {hands_on:.0f} min hands-on and {waiting:.0f} min waiting; "
               f"{len(left_out)} item{'s' if len(left_out) != 1 else ''} kept private.")
    return {"person_id": person_id, "role": role, "date": date, "board_id": board_id,
            "steps": steps, "left_out": left_out, "summary": summary}


def approve(draft: dict, approved_at: str | None = None) -> dict:
    """Auto-approve policy: share every step with share=true; left_out stays on the device."""
    steps = []
    for s in draft["steps"]:
        if not s.get("share", True):
            continue
        rs = {k: v for k, v in s.items() if k != "share"}
        rs["idx"] = len(steps) + 1
        steps.append(rs)
    hands_on = sum((parse_ts(s["end"]) - parse_ts(s["start"])).total_seconds() for s in steps if s["kind"] == "hands_on")
    waiting = sum((parse_ts(s["end"]) - parse_ts(s["start"])).total_seconds() for s in steps if s["kind"] == "waiting")
    date = draft["date"]
    pid4 = hashlib.sha256(draft["person_id"].encode()).hexdigest()[:4]
    rec = {"id": f"{date[5:7]}{date[8:10]}-{pid4}", "board_id": draft["board_id"], "person_id": draft["person_id"],
           "role": draft["role"], "date": date,
           "covers": {"start": steps[0]["start"] if steps else f"{date}T00:00:00", "end": steps[-1]["end"] if steps else f"{date}T00:00:00"},
           "steps": steps, "kept_private": len(draft["left_out"]),
           "hands_on_min": int(round(hands_on / 60)), "waiting_min": int(round(waiting / 60)),
           "approved_at": approved_at or datetime.now().astimezone().isoformat(timespec="seconds")}
    return rec


# ---------------------------------------------------------------------------
# canonical hash + signature (SCHEMA §12)
# ---------------------------------------------------------------------------
def canonical_json(obj: dict) -> bytes:
    body = {k: v for k, v in obj.items() if k not in ("hash", "pubkey", "sig")}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def record_hash(obj: dict) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def load_or_create_key(path: str = KEY_PATH):
    from nacl.signing import SigningKey
    if os.path.exists(path):
        seed = base64.b64decode(open(path, "r", encoding="utf-8").read().strip())
        return SigningKey(seed)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sk = SigningKey.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(base64.b64encode(bytes(sk)).decode())
    os.chmod(path, 0o600)
    return sk


def sign_record(rec: dict, signing_key=None) -> dict:
    sk = signing_key or load_or_create_key()
    h = record_hash(rec)
    sig = sk.sign(h.encode("utf-8")).signature
    out = dict(rec)
    out["hash"] = h
    out["pubkey"] = base64.b64encode(bytes(sk.verify_key)).decode()
    out["sig"] = base64.b64encode(sig).decode()
    return out


def verify_record(rec: dict) -> bool:
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey
    if record_hash(rec) != rec.get("hash"):
        return False
    try:
        VerifyKey(base64.b64decode(rec["pubkey"])).verify(rec["hash"].encode("utf-8"), base64.b64decode(rec["sig"]))
        return True
    except (BadSignatureError, KeyError, ValueError):
        return False


def post_record(rec: dict, api: str = API_URL, timeout: float = 5.0) -> dict:
    import httpx
    url = f"{api}/api/boards/{rec['board_id']}/records"
    try:
        r = httpx.post(url, json=rec, timeout=timeout)
        return {"posted": r.status_code in (200, 201), "status": r.status_code, "body": r.text[:300]}
    except Exception as e:  # noqa: BLE001
        return {"posted": False, "error": f"{type(e).__name__}: {e}"}


def compile_and_sign(events_path: str, person_id: str, role: str, board_id: str = "northwind", post: bool = True,
                     use_model: bool = True, out_dir: str = RUNS_DIR) -> dict:
    events = load_events(events_path)
    draft = compile_draft(events, person_id, role, board_id, use_model=use_model)
    rec = sign_record(approve(draft))
    os.makedirs(out_dir, exist_ok=True)
    draft_path = os.path.join(out_dir, f"draft-{rec['id']}.json")
    rec_path = os.path.join(out_dir, f"record-{rec['id']}.json")
    json.dump(draft, open(draft_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(rec, open(rec_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    result = {"draft": draft, "record": rec, "draft_path": draft_path, "record_path": rec_path,
              "events": len(events), "named_by": "model" if use_model and _named_by_model(draft) else "rules"}
    if post:
        result["post"] = post_record(rec)
    return result


def _named_by_model(draft: dict) -> bool:
    # heuristic for the report only: rule names are from a fixed set
    fixed = {"Away from desk", "Prepare pricing sheet", "Work in spreadsheet", "Fill proposal deck", "Edit slide deck",
             "Write mail to client", "Review contract", "Write document", "Browse the web", "Switch between apps"}
    return any(s["name"] not in fixed and not s["name"].startswith("Work in ") for s in draft["steps"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--person", default="pm-1")
    ap.add_argument("--role", default="PM")
    ap.add_argument("--board", default="northwind")
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--no-model", action="store_true")
    args = ap.parse_args()
    r = compile_and_sign(args.events, args.person, args.role, args.board, post=not args.no_post, use_model=not args.no_model)
    print(json.dumps({k: v for k, v in r.items() if k != "draft"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
