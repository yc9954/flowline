"""Run the model build (`uv run python -m flowline1 build --out <data/out>`) as a
background subprocess, one at a time, and expose its state for /status."""

from __future__ import annotations

import os
import subprocess
import threading
from collections import deque
from typing import Any

from .config import settings
from .db import now_iso


class Recompute:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state: dict[str, Any] = {
            "state": "idle",
            "started_at": None,
            "finished_at": None,
            "returncode": None,
            "command": None,
            "tail": None,
        }

    def available(self) -> tuple[bool, str]:
        d = settings.flowline1_dir
        if not d.is_dir():
            return False, f"model directory {d} does not exist yet; flowline1 is being built in parallel"
        if not (d / "pyproject.toml").is_file() and not (d / "flowline1").is_dir():
            return False, f"{d} exists but has no pyproject.toml or flowline1/ package yet; nothing to run"
        return True, ""

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Return False if a build is already running."""
        with self._lock:
            if self.running():
                return False
            cmd = [settings.uv_bin, "run", "python", "-m", "flowline1", "build", "--out", str(settings.data_out)]
            self.state.update(
                state="running",
                started_at=now_iso(),
                finished_at=None,
                returncode=None,
                command=" ".join(cmd),
                tail=None,
            )
            self._thread = threading.Thread(target=self._run, args=(cmd,), daemon=True)
            self._thread.start()
            return True

    def _run(self, cmd: list[str]) -> None:
        tail: deque[str] = deque(maxlen=40)
        try:
            settings.data_out.mkdir(parents=True, exist_ok=True)
            # Drop our own venv from the child's environment so `uv run` in flowline1/
            # uses that project's environment, not api/.venv.
            env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
            proc = subprocess.Popen(
                cmd,
                cwd=str(settings.flowline1_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                tail.append(line.rstrip("\n"))
            rc = proc.wait()
            self.state.update(
                state="done" if rc == 0 else "failed",
                finished_at=now_iso(),
                returncode=rc,
                tail="\n".join(tail),
            )
        except Exception as exc:
            tail.append(f"launcher error: {exc}")
            self.state.update(state="failed", finished_at=now_iso(), returncode=-1, tail="\n".join(tail))


recompute = Recompute()
