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
        """Legacy single-company output (data/out). Only the legacy board (northwind) falls back to it."""
        return _path("FLOWLINE_DATA_OUT", ROOT / "data" / "out")

    @property
    def boards_dir(self) -> Path:
        """Per-board data root: data/boards/{board_id}/out/*.json."""
        return _path("FLOWLINE_BOARDS_DIR", ROOT / "data" / "boards")

    def board_dir(self, board_id: str) -> Path:
        return self.boards_dir / board_id

    def board_out(self, board_id: str) -> Path:
        return self.board_dir(board_id) / "out"

    @property
    def people_json(self) -> Path:
        """Legacy people file, migrated into the DB on first start (board northwind)."""
        return _path("FLOWLINE_PEOPLE", ROOT / "data" / "people.json")

    @property
    def fixtures(self) -> Path:
        return _path("FLOWLINE_FIXTURES", ROOT / "fixtures")

    @property
    def fit_cmd(self) -> str | None:
        """Template for the nightly fit (placeholders {records} {out} {industry} {board_id}); None = built-in default."""
        v = os.environ.get("FLOWLINE_FIT_CMD", "").strip()
        return v or None

    @property
    def public_url(self) -> str | None:
        """Where devices reach this API (api_base_hint on invite claim); None = the request's own base URL."""
        v = os.environ.get("FLOWLINE_PUBLIC_URL", "").strip()
        return v.rstrip("/") or None

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

# The one board that existed before boards lived in the DB. Its files may still sit in data/out and
# fixtures/, and data/people.json is migrated into it on first start.
LEGACY_BOARD = "northwind"
LEGACY_BOARD_META = {
    "name": "Northwind Fitness",
    "industry_naics": "713940",
    "mail_domain": "northwind.local",
    "timezone": "America/Chicago",
    # The demo desks' webmail window (executor/MAIL.md); passed to the executor in the board block.
    "mail_window_title": "Northwind Mail :: Inbox",
}
# data/people.json carried no addresses; these are the demo mailboxes (executor/MAIL.md): login ↔ person id.
LEGACY_EMAIL_LOGINS = {"pm-1": "pm", "fin-1": "finance", "sales-1": "sales", "ops-1": "ops", "studio-1": "studio", "asst-1": "director"}

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
