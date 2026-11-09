"""Paths and settings. Everything is overridable by environment variable so tests
can point at temp directories without touching the other agents' files."""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: FLOWLINE_ROOT if set, else the directory that contains api/ (this file is api/api/config.py).
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("FLOWLINE_ROOT", str(_PACKAGE_ROOT))).expanduser()


def _path(env: str, default: Path) -> Path:
    return Path(os.environ.get(env, str(default))).expanduser()


class Settings:
    """Read lazily so tests that set env vars before building the app take effect."""

    @property
    def data_out(self) -> Path:
        return _path("FLOWLINE_DATA_OUT", ROOT / "data" / "out")

    @property
    def fixtures(self) -> Path:
        return _path("FLOWLINE_FIXTURES", ROOT / "fixtures")

    @property
    def db_path(self) -> Path:
        return _path("FLOWLINE_DB", ROOT / "data" / "api.sqlite")

    @property
    def flowline1_dir(self) -> Path:
        return _path("FLOWLINE_MODEL_DIR", ROOT / "flowline1")

    @property
    def board_dist(self) -> Path:
        return _path("FLOWLINE_BOARD_DIST", ROOT / "board" / "dist")

    @property
    def executor_url(self) -> str:
        return os.environ.get("FLOWLINE_EXECUTOR_URL", "http://localhost:8790").rstrip("/")

    @property
    def uv_bin(self) -> str:
        return os.environ.get("FLOWLINE_UV", os.path.expanduser("~/.local/bin/uv"))

    @property
    def cors_origins(self) -> list[str]:
        raw = os.environ.get("FLOWLINE_CORS", "http://localhost:5173,http://127.0.0.1:5173")
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()

# Names of the per-board JSON files the read endpoints serve (SCHEMA sections 3-11).
BOARD_FILES = (
    "ontology",
    "finding",
    "plans",
    "results",
    "history",
    "model",
    "expansion",
    "opening",
    "surfaces",
)
