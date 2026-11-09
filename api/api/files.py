"""Serve the per-board JSON documents the model (data/out) or the board prototype
(fixtures) wrote. Priority: data/out/<name>.json, then fixtures/<name>.json, else 404.
Files are re-read whenever their mtime changes, so no restart is needed."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import BOARD_FILES, settings


@dataclass
class Served:
    name: str
    path: Path
    served_from: str  # "data_out" | "fixtures"
    mtime: float
    data: Any


class MissingFile(Exception):
    def __init__(self, name: str, candidates: list[Path]):
        self.name = name
        self.candidates = candidates
        super().__init__(
            f"no data for '{name}': expected {candidates[0]} (model output) or {candidates[1]} (fixture); "
            f"neither file exists yet"
        )


class FileStore:
    def __init__(self) -> None:
        self._cache: dict[Path, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def candidates(self, name: str) -> list[Path]:
        return [settings.data_out / f"{name}.json", settings.fixtures / f"{name}.json"]

    def locate(self, name: str) -> tuple[Path, str] | None:
        for path, label in zip(self.candidates(name), ("data_out", "fixtures")):
            if path.is_file():
                return path, label
        return None

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

    def get(self, name: str) -> Served:
        if name not in BOARD_FILES:
            raise KeyError(name)
        found = self.locate(name)
        if found is None:
            raise MissingFile(name, self.candidates(name))
        path, label = found
        mtime, data = self._load(path)
        return Served(name=name, path=path, served_from=label, mtime=mtime, data=data)

    def simulated_records(self, board_id: str) -> list[dict[str, Any]]:
        """Records the model wrote to data/out/records.jsonl (one Record per line, SCHEMA §2,
        pubkey/sig empty). Re-read on mtime change. Each is stamped source="simulated"."""
        path = settings.data_out / "records.jsonl"
        if not path.is_file():
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

    def status(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in BOARD_FILES:
            found = self.locate(name)
            if found is None:
                out.append({"name": name, "path": None, "served_from": "missing", "source": None, "mtime": None})
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
