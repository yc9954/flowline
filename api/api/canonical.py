"""SCHEMA section 12: canonical hash and Ed25519 signature of a Record.

The Mac app, the Linux compiler and this API must agree byte-for-byte, so this
module is deliberately small and has no dependencies beyond stdlib + PyNaCl.
`scripts/dev_sign.py` imports it as the reference implementation.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

SIGNATURE_FIELDS = ("hash", "pubkey", "sig")


class RecordVerifyError(ValueError):
    """Raised with a message suitable for a 400 response."""


def strip_signature_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k not in SIGNATURE_FIELDS}


def canonical_bytes(record_without_sig: dict[str, Any]) -> bytes:
    """Keys sorted recursively, separators ',' and ':', UTF-8, non-ASCII unescaped."""
    return json.dumps(
        record_without_sig, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def record_hash(record: dict[str, Any]) -> str:
    """Lowercase hex SHA-256 of the canonical JSON (signature fields removed first)."""
    return hashlib.sha256(canonical_bytes(strip_signature_fields(record))).hexdigest()


def sign_hash(hex_hash: str, signing_key: SigningKey) -> str:
    """Ed25519 signature over the UTF-8 bytes of the hex hash string, standard base64."""
    sig = signing_key.sign(hex_hash.encode("utf-8")).signature
    return base64.b64encode(sig).decode("ascii")


def pubkey_b64(signing_key: SigningKey) -> str:
    return base64.b64encode(bytes(signing_key.verify_key)).decode("ascii")


def sign_record(record: dict[str, Any], signing_key: SigningKey) -> dict[str, Any]:
    """Return a copy with hash, pubkey and sig filled in."""
    body = strip_signature_fields(record)
    h = record_hash(body)
    out = dict(body)
    out["hash"] = h
    out["pubkey"] = pubkey_b64(signing_key)
    out["sig"] = sign_hash(h, signing_key)
    return out


def _b64decode(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # binascii.Error or ValueError
        raise RecordVerifyError(f"{field} is not valid standard base64: {exc}") from exc


def verify_record(record: dict[str, Any]) -> None:
    """Raise RecordVerifyError describing the first mismatch; return None if valid."""
    for field in SIGNATURE_FIELDS:
        if field not in record:
            raise RecordVerifyError(f"missing field '{field}'")
        if not isinstance(record[field], str) or not record[field]:
            raise RecordVerifyError(f"field '{field}' must be a non-empty string")

    expected = record_hash(record)
    given = record["hash"]
    if given.lower() != given:
        raise RecordVerifyError("hash must be lowercase hex")
    if given != expected:
        raise RecordVerifyError(
            f"hash mismatch: record hashes to {expected} but carries {given}"
        )

    pub = _b64decode(record["pubkey"], "pubkey")
    if len(pub) != 32:
        raise RecordVerifyError(f"pubkey must decode to 32 bytes, got {len(pub)}")
    sig = _b64decode(record["sig"], "sig")
    if len(sig) != 64:
        raise RecordVerifyError(f"sig must decode to 64 bytes, got {len(sig)}")

    try:
        VerifyKey(pub).verify(given.encode("utf-8"), sig)
    except BadSignatureError as exc:
        raise RecordVerifyError("signature does not verify over the hash") from exc
