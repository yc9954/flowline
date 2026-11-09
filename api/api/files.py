"""Serve the per-board JSON documents the model wrote.

Lookup for board B and file <name>:
  1. data/boards/B/out/<name>.json                     (served_from "board")
  2. only for the legacy board `northwind`, and only while data/boards/northwind/ does not exist:
     data/out/<name>.json (served_from "data_out"), then fixtures/<name>.json (served_from "fixtures").
Anything else is "no data yet" — never another board's file. Files are re-read whenever their mtime
changes, so no restart is needed.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BOARD_FILES, LEGACY_BOARD, settings

NO_DATA_NEEDS = "approved records → nightly fit (POST /api/boards/{board_id}/recompute writes data/boards/{board_id}/out)"


@dataclass
class Served:
    name: str
    path: Path
    served_from: str  # "board" | "data_out" | "fixtures"
    mtime: float
    data: Any


class MissingFile(Exception):
    """No file for this board. `.needs` says what has to happen first."""

    def __init__(self, name: str, board_id: str, candidates: list[Path]):
        self.name = name
        self.board_id = board_id
        self.candidates = candidates
        self.needs = NO_DATA_NEEDS.format(board_id=board_id)
        looked = " or ".join(str(p) for p in candidates)
        super().__init__(f"no {name} for board '{board_id}' yet: expected {looked}; neither file exists")

    def detail(self) -> dict[str, str]:
        return {"detail": str(self), "state": "no_data_yet", "needs": self.needs}


class FileStore:
    def __init__(self) -> None:
        self._cache: dict[Path, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------ where

    def board_out(self, board_id: str) -> Path:
        return settings.board_out(board_id)

    def legacy_fallback(self, board_id: str) -> bool:
        """True while the legacy board has no directory of its own and still reads data/out + fixtures."""
        return board_id == LEGACY_BOARD and not settings.board_dir(board_id).is_dir()

    def candidates(self, name: str, board_id: str) -> list[tuple[Path, str]]:
        out = [(self.board_out(board_id) / f"{name}.json", "board")]
        if self.legacy_fallback(board_id):
            out.append((settings.data_out / f"{name}.json", "data_out"))
            out.append((settings.fixtures / f"{name}.json", "fixtures"))
        return out

    def locate(self, name: str, board_id: str) -> tuple[Path, str] | None:
        for path, label in self.candidates(name, board_id):
            if path.is_file():
                return path, label
        return None

    def has_data(self, board_id: str) -> bool:
        return any(self.locate(name, board_id) is not None for name in BOARD_FILES)

    # ------------------------------------------------------------ read

    def _load(self, path: Path) -> tuple[float, Any]:
        mtime = path.stat().st_mtime
        with self._lock:
            hit = self._cache.get(path)
            if hit is not None and hit[0] == mtime:
                return hit
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        with self._lock:
            self._cache[path] = (mtime, data)
        return mtime, data

    def get(self, name: str, board_id: str) -> Served:
        if name not in BOARD_FILES:
            raise KeyError(name)
        found = self.locate(name, board_id)
        if found is None:
            raise MissingFile(name, board_id, [p for p, _ in self.candidates(name, board_id)])
        path, label = found
        mtime, data = self._load(path)
        return Served(name=name, path=path, served_from=label, mtime=mtime, data=data)

    def _records_jsonl(self, board_id: str) -> Path | None:
        p = self.board_out(board_id) / "records.jsonl"
        if p.is_file():
            return p
        if self.legacy_fallback(board_id):
            p = settings.data_out / "records.jsonl"
            if p.is_file():
                return p
        return None

    def simulated_records(self, board_id: str) -> list[dict[str, Any]]:
        """Records the model wrote to <board out>/records.jsonl (one Record per line, SCHEMA §2,
        pubkey/sig empty). Re-read on mtime change. Each is stamped source="simulated"."""
        path = self._records_jsonl(board_id)
        if path is None:
            return []
        mtime = path.stat().st_mtime
        with self._lock:
            hit = self._cache.get(path)
        if hit is None or hit[0] != mtime:
            rows: list[dict[str, Any]] = []
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue  # skip a half-written line; the next mtime change re-reads
                    if isinstance(obj, dict):
                        obj["source"] = "simulated"
                        for f in ("hash", "pubkey", "sig"):
                            obj.setdefault(f, "")
                        rows.append(obj)
            with self._lock:
                self._cache[path] = (mtime, rows)
            hit = (mtime, rows)
        return [r for r in hit[1] if r.get("board_id") == board_id]

    # ------------------------------------------------------------ status

    def status(self, board_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in BOARD_FILES:
            found = self.locate(name, board_id)
            if found is None:
                out.append({"name": name, "path": None, "served_from": "missing", "source": None, "mtime": None,
                            "state": "no_data_yet"})
                continue
            path, label = found
            try:
                mtime, data = self._load(path)
                source = data.get("source") if isinstance(data, dict) else None
                err = None
            except Exception as exc:  # unreadable or invalid JSON
                mtime, source, err = path.stat().st_mtime, None, str(exc)
            row: dict[str, Any] = {
                "name": name,
                "path": str(path),
                "served_from": label,
                "source": source,
                "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            }
            if err:
                row["error"] = err
            out.append(row)
        return out


store = FileStore()
