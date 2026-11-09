"""SCHEMA §12: canonical JSON → sha256 → Ed25519 over the hex string."""
import base64
import hashlib
import json

from nacl.signing import SigningKey

from compiler import canonical_json, record_hash, sign_record, verify_record

FIXED = {
    "id": "1106-0412", "board_id": "northwind", "person_id": "pm-1", "role": "PM", "date": "2026-11-06",
    "covers": {"start": "2026-11-06T09:00:00+09:00", "end": "2026-11-06T10:30:00+09:00"},
    "steps": [{"idx": 1, "start": "2026-11-06T09:00:00+09:00", "end": "2026-11-06T09:40:00+09:00",
               "name": "Prepare pricing sheet", "kind": "hands_on", "case_id": "proposal #172", "tools": ["sheets"]},
              {"idx": 2, "start": "2026-11-06T09:40:00+09:00", "end": "2026-11-06T10:30:00+09:00",
               "name": "Fill proposal deck — café", "kind": "hands_on", "tools": ["slides"], "repeats": 11}],
    "kept_private": 2, "hands_on_min": 90, "waiting_min": 0, "approved_at": "2026-11-06T18:02:00+09:00",
}
# Computed once from the canonical form below; any change to the canonicalisation breaks this.
FIXED_CANONICAL = ('{"approved_at":"2026-11-06T18:02:00+09:00","board_id":"northwind","covers":{"end":"2026-11-06T10:30:00+09:00",'
                   '"start":"2026-11-06T09:00:00+09:00"},"date":"2026-11-06","hands_on_min":90,"id":"1106-0412","kept_private":2,'
                   '"person_id":"pm-1","role":"PM","steps":[{"case_id":"proposal #172","end":"2026-11-06T09:40:00+09:00","idx":1,'
                   '"kind":"hands_on","name":"Prepare pricing sheet","start":"2026-11-06T09:00:00+09:00","tools":["sheets"]},'
                   '{"end":"2026-11-06T10:30:00+09:00","idx":2,"kind":"hands_on","name":"Fill proposal deck — café","repeats":11,'
                   '"start":"2026-11-06T09:40:00+09:00","tools":["slides"]}],"waiting_min":0}')
FIXED_SHA256 = hashlib.sha256(FIXED_CANONICAL.encode("utf-8")).hexdigest()


def test_canonical_json_is_sorted_compact_utf8():
    c = canonical_json(FIXED)
    assert c.decode("utf-8") == FIXED_CANONICAL
    assert "é" in c.decode("utf-8")  # ensure_ascii=False
    assert ": " not in c.decode("utf-8") and ", " not in c.decode("utf-8")


def test_fixed_record_fixed_hash():
    assert record_hash(FIXED) == FIXED_SHA256
    # hash ignores hash/pubkey/sig fields
    assert record_hash({**FIXED, "hash": "x", "pubkey": "y", "sig": "z"}) == FIXED_SHA256


def test_integers_without_point():
    assert canonical_json({"a": 19.0, "b": 2}) == b'{"a":19.0,"b":2}'  # python shortest round-trip keeps 19.0 for floats
    assert canonical_json({"a": 19}) == b'{"a":19}'


def test_sign_and_verify_roundtrip():
    sk = SigningKey(b"\x01" * 32)
    rec = sign_record(FIXED, sk)
    assert rec["hash"] == FIXED_SHA256
    assert base64.b64decode(rec["pubkey"]) == bytes(sk.verify_key)
    # sig is over the UTF-8 bytes of the hex hash string
    assert base64.b64decode(rec["sig"]) == sk.sign(FIXED_SHA256.encode("utf-8")).signature
    assert verify_record(rec)
    bad = dict(rec)
    bad["hands_on_min"] = 91
    assert not verify_record(bad)
    assert json.loads(json.dumps(rec)) == rec
