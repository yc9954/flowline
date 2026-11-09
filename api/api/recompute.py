"""Nightly fit as a background job, one per board at a time.

POST /api/boards/{id}/recompute exports the board's approved, non-withdrawn records to
data/boards/{id}/records.ndjson and runs `flowline1 fit` on them as a subprocess (never on the
server thread). The command is FLOWLINE_FIT_CMD, a template with the placeholders
{records} {out} {industry} {board_id}; the default is

    <uv> run --directory <flowline1 dir> python -m flowline1 fit --records {records} --out {out} --industry {industry}

Until `flowline1 fit` exists (track G3) the job simply ends `failed` with the command's stderr.
Jobs live in memory: a restart forgets finished jobs, and a running one dies with the process.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .config import settings
from .db import new_id, now_iso

TAIL_LINES = 40


def _tail(text: str) -> str:
    return "\n".join(deque(text.splitlines(), maxlen=TAIL_LINES))


def _uv() -> str:
    uv = settings.uv_bin
    if os.path.isfile(uv):
        return uv
    return shutil.which("uv") or uv


def build_command(board_id: str, records: Path, out: Path, industry: str | None) -> list[str]:
    template = settings.fit_cmd
    if template is None:
        cmd = [_uv(), "run", "--directory", str(settings.flowline1_dir), "python", "-m", "flowline1", "fit",
               "--records", str(records), "--out", str(out)]
        if industry:
            cmd += ["--industry", industry]
        return cmd
    if not industry:
        template = template.replace("--industry {industry}", "").replace("--industry={industry}", "")
    # Quote the substituted paths so a space in a path survives shlex.
    filled = template.format(
        records=shlex.quote(str(records)),
        out=shlex.quote(str(out)),
        industry=shlex.quote(industry or ""),
        board_id=shlex.quote(board_id),
    )
    return shlex.split(filled)


class Recompute:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}

    # ------------------------------------------------------------ queries

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def latest(self, board_id: str) -> dict[str, Any]:
        """State for /status: the board's newest job, or idle."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j["board_id"] == board_id]
        if not jobs:
            return {"state": "idle", "job_id": None, "started_at": None, "finished_at": None,
                    "returncode": None, "command": None, "tail": None}
        return dict(max(jobs, key=lambda j: j["started_at"]))

    def running(self, board_id: str) -> dict[str, Any] | None:
        with self._lock:
            for j in self._jobs.values():
                if j["board_id"] == board_id and j["state"] == "running":
                    return dict(j)
        return None

    def reset(self) -> None:  # tests
        with self._lock:
            self._jobs.clear()
            self._threads.clear()

    # ------------------------------------------------------------ start

    def start(self, board_id: str, records: Path, out: Path, *, industry: str | None, records_exported: int) -> dict[str, Any] | None:
        """Launch the fit; None if one is already running for this board."""
        with self._lock:
            if any(j["board_id"] == board_id and j["state"] == "running" for j in self._jobs.values()):
                return None
            cmd = build_command(board_id, records, out, industry)
            job: dict[str, Any] = {
                "job_id": new_id("fit"),
                "board_id": board_id,
                "state": "running",
                "started_at": now_iso(),
                "finished_at": None,
                "returncode": None,
                "command": " ".join(shlex.quote(c) for c in cmd),
                "records": str(records),
                "records_exported": records_exported,
                "out": str(out),
                "industry": industry,
                "tail": None,
                "stderr": None,
            }
            self._jobs[job["job_id"]] = job
            t = threading.Thread(target=self._run, args=(job["job_id"], cmd, out), daemon=True, name=job["job_id"])
            self._threads[job["job_id"]] = t
            t.start()
            return dict(job)

    def _finish(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is not None:
                j.update(fields, finished_at=now_iso())

    def _run(self, job_id: str, cmd: list[str], out: Path) -> None:
        try:
            out.mkdir(parents=True, exist_ok=True)
            # Drop our own venv so `uv run` in flowline1/ uses that project's environment, not api/.venv.
            env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
            proc = subprocess.Popen(cmd, cwd=str(settings.flowline1_dir if settings.flowline1_dir.is_dir() else Path.cwd()),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            stdout, stderr = proc.communicate()
            rc = proc.returncode
            self._finish(job_id, state="done" if rc == 0 else "failed", returncode=rc,
                         tail=_tail(stdout + ("\n" + stderr if stderr else "")), stderr=_tail(stderr))
        except Exception as exc:  # command not found, bad cwd, ...
            msg = f"launcher error: {type(exc).__name__}: {exc}"
            self._finish(job_id, state="failed", returncode=-1, tail=msg, stderr=msg)

    def wait(self, job_id: str, timeout: float | None = None) -> None:  # tests
        t = self._threads.get(job_id)
        if t is not None:
            t.join(timeout)


recompute = Recompute()
