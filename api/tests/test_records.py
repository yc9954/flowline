from __future__ import annotations

import base64
import json

from nacl.signing import SigningKey

from api.canonical import canonical_bytes, record_hash, sign_record, verify_record
from tests.conftest import BOARD, make_record


def test_canonical_json_matches_schema_rules():
    obj = {"b": 1, "a": {"z": "é", "y": [1, 2.5]}, "c": 19.0}
    assert canonical_bytes(obj) == '{"a":{"y":[1,2.5],"z":"é"},"b":1,"c":19.0}'.encode("utf-8")


def test_hash_ignores_signature_fields(signing_key: SigningKey):
    rec = make_record()
    signed = sign_record(rec, signing_key)
    assert record_hash(signed) == record_hash(rec) == signed["hash"]
    verify_record(signed)  # does not raise


def test_signed_record_accepted(client, signed_record):
    r = client.post(f"/api/boards/{BOARD}/records", json=signed_record)
    assert r.status_code == 201, r.text
    assert r.json() == {"id": "1106-0412", "accepted": True}

    listed = client.get(f"/api/boards/{BOARD}/records").json()
    assert [x["id"] for x in listed] == ["1106-0412"]
    assert listed[0]["sig"] == signed_record["sig"]

    status = client.get(f"/api/boards/{BOARD}/status").json()
    assert status["records"] == 1


def test_tampered_body_rejected(client, signed_record):
    bad = dict(signed_record)
    bad["hands_on_min"] = 999  # change a value after signing
    r = client.post(f"/api/boards/{BOARD}/records", json=bad)
    assert r.status_code == 400
    assert "hash mismatch" in r.json()["detail"]


def test_tampered_signature_rejected(client, signed_record):
    bad = dict(signed_record)
    other = SigningKey.generate()
    bad["sig"] = base64.b64encode(other.sign(bad["hash"].encode()).signature).decode()
    r = client.post(f"/api/boards/{BOARD}/records", json=bad)
    assert r.status_code == 400
    assert "signature does not verify" in r.json()["detail"]


def test_recomputed_hash_with_wrong_key_rejected(client, signed_record):
    # Attacker rewrites hash+sig consistently but with a different key than claimed pubkey.
    bad = dict(signed_record)
    bad["hands_on_min"] = 5
    other = SigningKey.generate()
    bad["hash"] = record_hash(bad)
    bad["sig"] = base64.b64encode(other.sign(bad["hash"].encode()).signature).decode()
    r = client.post(f"/api/boards/{BOARD}/records", json=bad)
    assert r.status_code == 400


def test_missing_fields_and_bad_base64_rejected(client, signed_record):
    missing = {k: v for k, v in signed_record.items() if k != "sig"}
    r = client.post(f"/api/boards/{BOARD}/records", json=missing)
    assert r.status_code == 400 and "missing field 'sig'" in r.json()["detail"]

    bad = dict(signed_record, pubkey="not base64!!")
    r = client.post(f"/api/boards/{BOARD}/records", json=bad)
    assert r.status_code == 400 and "base64" in r.json()["detail"]


def test_board_mismatch_rejected(client, signing_key):
    rec = sign_record(make_record(board_id="other"), signing_key)
    r = client.post(f"/api/boards/{BOARD}/records", json=rec)
    assert r.status_code == 400 and "board_id" in r.json()["detail"]


def test_withdraw(client, signed_record):
    client.post(f"/api/boards/{BOARD}/records", json=signed_record)
    r = client.delete(f"/api/boards/{BOARD}/records/1106-0412")
    assert r.status_code == 200 and r.json()["withdrawn"] is True
    assert client.get(f"/api/boards/{BOARD}/records").json() == []
    assert len(client.get(f"/api/boards/{BOARD}/records?withdrawn=1").json()) == 1
    assert client.get(f"/api/boards/{BOARD}/status").json()["records"] == 0

    # Unknown id -> 404
    assert client.delete(f"/api/boards/{BOARD}/records/nope").status_code == 404

    # Re-posting the identical record after withdrawal re-activates it.
    r = client.post(f"/api/boards/{BOARD}/records", json=signed_record)
    assert r.status_code == 201
    assert len(client.get(f"/api/boards/{BOARD}/records").json()) == 1


def test_duplicate_id_different_content_conflicts(client, signing_key):
    a = sign_record(make_record(), signing_key)
    b = sign_record(make_record(hands_on_min=41), signing_key)
    assert client.post(f"/api/boards/{BOARD}/records", json=a).status_code == 201
    assert client.post(f"/api/boards/{BOARD}/records", json=b).status_code == 409


def test_extra_fields_pass_through_and_hash(client, signing_key):
    rec = make_record(mood="fine", steps=[dict(make_record()["steps"][0], note="new field")])
    signed = sign_record(rec, signing_key)
    r = client.post(f"/api/boards/{BOARD}/records", json=signed)
    assert r.status_code == 201, r.text
    got = client.get(f"/api/boards/{BOARD}/records/1106-0412").json()
    assert got["mood"] == "fine" and got["steps"][0]["note"] == "new field"


def test_dev_sign_script_round_trips(client, tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "dev_sign.py"
    rec_path = tmp_path / "rec.json"
    rec_path.write_text(json.dumps(make_record()))
    key_path = tmp_path / "dev_key"

    out = subprocess.run(
        [sys.executable, str(script), str(rec_path), "--key", str(key_path), "--compact"],
        capture_output=True, text=True, check=True,
    )
    assert key_path.exists() and (key_path.stat().st_mode & 0o777) == 0o600
    signed = json.loads(out.stdout)
    assert set(signed) >= {"hash", "pubkey", "sig"}

    r = client.post(f"/api/boards/{BOARD}/records", json=signed)
    assert r.status_code == 201, r.text

    # --verify agrees, and a second run reuses the same key.
    signed_path = tmp_path / "signed.json"
    signed_path.write_text(out.stdout)
    v = subprocess.run([sys.executable, str(script), "--verify", str(signed_path), "--key", str(key_path)],
                       capture_output=True, text=True)
    assert v.returncode == 0, v.stderr
    pk = subprocess.run([sys.executable, str(script), "--pubkey", "--key", str(key_path)],
                        capture_output=True, text=True, check=True)
    assert pk.stdout.strip() == signed["pubkey"]
