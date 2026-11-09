#!/usr/bin/env python3
"""Reference signer for Flowline Records (SCHEMA section 12).

    uv run python scripts/dev_sign.py record.json            # prints the signed record
    uv run python scripts/dev_sign.py record.json --key path  # use another key file
    uv run python scripts/dev_sign.py --verify signed.json    # check hash + sig
    cat record.json | uv run python scripts/dev_sign.py -     # read from stdin
    uv run python scripts/dev_sign.py --pubkey                # print this machine's dev pubkey

The key file (default ~/.flowline/dev_key, mode 0600) holds the 32-byte Ed25519 seed
as base64. It is created on first use. The record's existing hash/pubkey/sig fields,
if any, are discarded and recomputed.

This is the implementation the agent-mac, flowline1 and executor components test
against; `api/canonical.py` is the single source of truth and this script only wraps it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

# Allow running from the api/ project root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nacl.signing import SigningKey  # noqa: E402

from api.canonical import RecordVerifyError, pubkey_b64, sign_record, verify_record  # noqa: E402

DEFAULT_KEY = Path(os.environ.get("FLOWLINE_DEV_KEY", "~/.flowline/dev_key")).expanduser()


def load_or_create_key(path: Path) -> SigningKey:
    if path.is_file():
        seed = base64.b64decode(path.read_text().strip())
        if len(seed) != 32:
            raise SystemExit(f"{path}: expected a base64 32-byte seed, got {len(seed)} bytes")
        return SigningKey(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = SigningKey.generate()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(base64.b64encode(bytes(key)).decode("ascii") + "\n")
    os.chmod(path, 0o600)
    print(f"created new device key at {path}", file=sys.stderr)
    return key


def read_json(src: str) -> dict:
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise SystemExit("record must be a JSON object")
    return obj


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", nargs="?", help="path to Record JSON (without hash/pubkey/sig), or - for stdin")
    ap.add_argument("--key", default=str(DEFAULT_KEY), help="Ed25519 seed file (default ~/.flowline/dev_key)")
    ap.add_argument("--verify", action="store_true", help="verify an already-signed record instead of signing")
    ap.add_argument("--pubkey", action="store_true", help="print the base64 public key of the key file and exit")
    ap.add_argument("--compact", action="store_true", help="print the signed record on one line")
    args = ap.parse_args(argv)

    key_path = Path(args.key).expanduser()

    if args.pubkey:
        print(pubkey_b64(load_or_create_key(key_path)))
        return 0

    if not args.record:
        ap.error("record path (or -) is required")

    record = read_json(args.record)

    if args.verify:
        try:
            verify_record(record)
        except RecordVerifyError as exc:
            print(f"INVALID: {exc}", file=sys.stderr)
            return 1
        print(f"OK hash={record['hash']} pubkey={record['pubkey']}")
        return 0

    signed = sign_record(record, load_or_create_key(key_path))
    if args.compact:
        print(json.dumps(signed, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(signed, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
