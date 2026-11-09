#!/usr/bin/env python3
"""Reference implementation of SCHEMA.md §12 canonical hash. Usage:
   hash_check.py record.json     -> prints canonical JSON hash (without hash/pubkey/sig)
   hash_check.py --fixture       -> prints the hash of the fixed record used by CanonicalTests.swift"""
import hashlib, json, sys

def canonical_hash(obj):
    obj = {k: v for k, v in obj.items() if k not in ("hash", "pubkey", "sig")}
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest(), s

FIXTURE = {
    "id": "1106-0412", "board_id": "northwind", "person_id": "pm-1", "role": "PM", "date": "2026-11-06",
    "covers": {"start": "2026-11-06T09:02:00+09:00", "end": "2026-11-06T15:18:00+09:00"},
    "steps": [
        {"idx": 1, "start": "2026-11-06T09:02:00+09:00", "end": "2026-11-06T09:20:00+09:00",
         "name": "Read the client brief for #167", "kind": "hands_on", "case_id": "proposal #167",
         "tools": ["mail", "docs"], "handoff_from": "Sales"},
        {"idx": 2, "start": "2026-11-06T10:52:00+09:00", "end": "2026-11-06T13:02:00+09:00",
         "name": "Waited for approval", "kind": "waiting", "case_id": "proposal #167", "tools": [],
         "handoff_to": "Director", "waiting_on": "Director"},
        {"idx": 3, "start": "2026-11-06T13:02:00+09:00", "end": "2026-11-06T13:24:00+09:00",
         "name": "Copied figures from sheet into deck — “Investment” → déck", "kind": "hands_on",
         "case_id": "proposal #167", "tools": ["sheets", "slides"], "repeats": 3},
    ],
    "kept_private": 3, "hands_on_min": 40, "waiting_min": 130, "approved_at": "2026-11-06T18:04:31+09:00",
}

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fixture":
        h, s = canonical_hash(FIXTURE)
        print(h)
        if "-v" in sys.argv:
            print(s)
    else:
        with open(sys.argv[1], encoding="utf-8") as f:
            h, s = canonical_hash(json.load(f))
        print(h)
