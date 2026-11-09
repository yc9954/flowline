"""SQLite storage (stdlib sqlite3). One connection per call; WAL mode; created on startup.

Tables: records, suggestions, plan_approvals, runs_cache, plus accept_tally for the
Beta-Bernoulli acceptance rate per (person, skill).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    board_id    TEXT NOT NULL,
    id          TEXT NOT NULL,
    person_id   TEXT NOT NULL,
    role        TEXT NOT NULL,
    date        TEXT NOT NULL,
    hash        TEXT NOT NULL,
    pubkey      TEXT NOT NULL,
    body        TEXT NOT NULL,            -- full signed record as JSON
    received_at TEXT NOT NULL,
    withdrawn_at TEXT,
    PRIMARY KEY (board_id, id)
);
CREATE INDEX IF NOT EXISTS records_person ON records(board_id, person_id);

CREATE TABLE IF NOT EXISTS suggestions (
    id              TEXT PRIMARY KEY,
    person_id       TEXT NOT NULL,
    skill_id        TEXT NOT NULL,
    plan_id         TEXT NOT NULL,
    board_id        TEXT NOT NULL,
    status          TEXT NOT NULL,        -- offered|accepted|declined|never|done
    body            TEXT NOT NULL,        -- Suggestion JSON (minus accept_rate)
    created_at      TEXT NOT NULL,
    responded_at    TEXT,
    run_id          TEXT
);
CREATE INDEX IF NOT EXISTS suggestions_person ON suggestions(person_id, status);

CREATE TABLE IF NOT EXISTS plan_approvals (
    id          TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL,
    plan_id     TEXT NOT NULL,
    plan_name   TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    approved_by TEXT,
    plan        TEXT NOT NULL,            -- Plan JSON snapshot at approval time
    suggestion_ids TEXT NOT NULL          -- JSON list
);

CREATE TABLE IF NOT EXISTS runs_cache (
    id            TEXT PRIMARY KEY,
    suggestion_id TEXT,
    skill_id      TEXT,
    status        TEXT,
    body          TEXT NOT NULL,          -- last Run JSON seen from the executor
    updated_at    TEXT NOT NULL
);

-- Beta-Bernoulli acceptance tally per (person, skill). Prior Beta(1,1).
CREATE TABLE IF NOT EXISTS accept_tally (
    person_id TEXT NOT NULL,
    skill_id  TEXT NOT NULL,
    accepted  INTEGER NOT NULL DEFAULT 0,
    declined  INTEGER NOT NULL DEFAULT 0,
    never     INTEGER NOT NULL DEFAULT 0, -- 1 once the person said dont_ask
    PRIMARY KEY (person_id, skill_id)
);
"""

PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    # -------------------------------------------------------------- plumbing

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # -------------------------------------------------------------- records

    def insert_record(self, board_id: str, record: dict[str, Any]) -> bool:
        """Insert; return False if a record with this id already exists for the board
        (unless the existing one is withdrawn and identical, in which case it is re-activated)."""
        with self.connect() as con:
            existing = con.execute(
                "SELECT hash, withdrawn_at FROM records WHERE board_id=? AND id=?",
                (board_id, record["id"]),
            ).fetchone()
            if existing is not None:
                if existing["withdrawn_at"] is not None and existing["hash"] == record["hash"]:
                    con.execute(
                        "UPDATE records SET withdrawn_at=NULL, received_at=? WHERE board_id=? AND id=?",
                        (now_iso(), board_id, record["id"]),
                    )
                    return True
                return False
            con.execute(
                """INSERT INTO records (board_id, id, person_id, role, date, hash, pubkey, body, received_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    board_id,
                    record["id"],
                    record["person_id"],
                    record["role"],
                    record["date"],
                    record["hash"],
                    record["pubkey"],
                    json.dumps(record, ensure_ascii=False),
                    now_iso(),
                ),
            )
            return True

    def list_records(
        self, board_id: str, *, person_id: str | None = None, include_withdrawn: bool = False
    ) -> list[dict[str, Any]]:
        sql = "SELECT body, withdrawn_at, received_at FROM records WHERE board_id=?"
        args: list[Any] = [board_id]
        if person_id:
            sql += " AND person_id=?"
            args.append(person_id)
        if not include_withdrawn:
            sql += " AND withdrawn_at IS NULL"
        sql += " ORDER BY date, id"
        with self.connect() as con:
            rows = con.execute(sql, args).fetchall()
        out = []
        for r in rows:
            body = json.loads(r["body"])
            if include_withdrawn:
                body["_withdrawn_at"] = r["withdrawn_at"]
            out.append(body)
        return out

    def get_record(self, board_id: str, rid: str) -> dict[str, Any] | None:
        with self.connect() as con:
            r = con.execute(
                "SELECT body, withdrawn_at FROM records WHERE board_id=? AND id=?", (board_id, rid)
            ).fetchone()
        if r is None:
            return None
        body = json.loads(r["body"])
        body["_withdrawn_at"] = r["withdrawn_at"]
        return body

    def withdraw_record(self, board_id: str, rid: str) -> bool:
        with self.connect() as con:
            cur = con.execute(
                "UPDATE records SET withdrawn_at=? WHERE board_id=? AND id=? AND withdrawn_at IS NULL",
                (now_iso(), board_id, rid),
            )
            return cur.rowcount > 0

    def count_records(self, board_id: str) -> int:
        with self.connect() as con:
            return con.execute(
                "SELECT COUNT(*) FROM records WHERE board_id=? AND withdrawn_at IS NULL", (board_id,)
            ).fetchone()[0]

    # -------------------------------------------------------------- plan approvals

    def insert_approval(
        self,
        board_id: str,
        plan: dict[str, Any],
        approved_by: str | None,
        suggestion_ids: list[str],
    ) -> dict[str, Any]:
        row = {
            "id": new_id("appr"),
            "board_id": board_id,
            "plan_id": plan["id"],
            "plan_name": plan.get("name", plan["id"]),
            "approved_at": now_iso(),
            "approved_by": approved_by,
            "suggestions_created": suggestion_ids,
        }
        with self.connect() as con:
            con.execute(
                """INSERT INTO plan_approvals (id, board_id, plan_id, plan_name, approved_at, approved_by, plan, suggestion_ids)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    row["id"],
                    board_id,
                    row["plan_id"],
                    row["plan_name"],
                    row["approved_at"],
                    approved_by,
                    json.dumps(plan, ensure_ascii=False),
                    json.dumps(suggestion_ids),
                ),
            )
        return row

    def list_approvals(self, board_id: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM plan_approvals WHERE board_id=? ORDER BY approved_at", (board_id,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "board_id": r["board_id"],
                "plan_id": r["plan_id"],
                "plan_name": r["plan_name"],
                "approved_at": r["approved_at"],
                "approved_by": r["approved_by"],
                "suggestions_created": json.loads(r["suggestion_ids"]),
            }
            for r in rows
        ]

    # -------------------------------------------------------------- suggestions

    def insert_suggestion(self, board_id: str, s: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO suggestions (id, person_id, skill_id, plan_id, board_id, status, body, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    s["id"],
                    s["person_id"],
                    s["skill_id"],
                    s["plan_id"],
                    board_id,
                    s["status"],
                    json.dumps(s, ensure_ascii=False),
                    s.get("created_at") or now_iso(),
                ),
            )

    def _row_to_suggestion(self, r: sqlite3.Row) -> dict[str, Any]:
        s = json.loads(r["body"])
        s["status"] = r["status"]
        s["created_at"] = r["created_at"]
        s["responded_at"] = r["responded_at"]
        s["run_id"] = r["run_id"]
        s["accept_rate"] = self.accept_rate(r["person_id"], r["skill_id"])
        return s

    def list_suggestions(self, person_id: str, *, all_statuses: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM suggestions WHERE person_id=?"
        args: list[Any] = [person_id]
        if not all_statuses:
            sql += " AND status='offered'"
        sql += " ORDER BY created_at DESC"
        with self.connect() as con:
            rows = con.execute(sql, args).fetchall()
        return [self._row_to_suggestion(r) for r in rows]

    def get_suggestion(self, sid: str) -> dict[str, Any] | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM suggestions WHERE id=?", (sid,)).fetchone()
        return None if r is None else self._row_to_suggestion(r)

    def set_suggestion_status(self, sid: str, status: str, *, run_id: str | None = None) -> None:
        with self.connect() as con:
            if run_id is not None:
                con.execute(
                    "UPDATE suggestions SET status=?, responded_at=?, run_id=? WHERE id=?",
                    (status, now_iso(), run_id, sid),
                )
            else:
                con.execute(
                    "UPDATE suggestions SET status=?, responded_at=? WHERE id=?",
                    (status, now_iso(), sid),
                )

    def mark_suggestion_done_by_run(self, run_id: str) -> str | None:
        with self.connect() as con:
            r = con.execute("SELECT id FROM suggestions WHERE run_id=?", (run_id,)).fetchone()
            if r is None:
                return None
            con.execute(
                "UPDATE suggestions SET status='done' WHERE id=? AND status IN ('accepted','offered')",
                (r["id"],),
            )
            return r["id"]

    def suppress_skill(self, person_id: str, skill_id: str) -> int:
        """Mark every still-offered suggestion of this skill for this person as never."""
        with self.connect() as con:
            cur = con.execute(
                "UPDATE suggestions SET status='never', responded_at=? WHERE person_id=? AND skill_id=? AND status='offered'",
                (now_iso(), person_id, skill_id),
            )
            return cur.rowcount

    # -------------------------------------------------------------- acceptance tally

    def _tally_row(self, con: sqlite3.Connection, person_id: str, skill_id: str) -> sqlite3.Row | None:
        return con.execute(
            "SELECT accepted, declined, never FROM accept_tally WHERE person_id=? AND skill_id=?",
            (person_id, skill_id),
        ).fetchone()

    def is_suppressed(self, person_id: str, skill_id: str) -> bool:
        with self.connect() as con:
            r = self._tally_row(con, person_id, skill_id)
        return bool(r and r["never"])

    def tally(self, person_id: str, skill_id: str, *, accepted: int = 0, declined: int = 0, never: bool = False) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO accept_tally (person_id, skill_id, accepted, declined, never)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(person_id, skill_id) DO UPDATE SET
                       accepted = accepted + excluded.accepted,
                       declined = declined + excluded.declined,
                       never    = MAX(never, excluded.never)""",
                (person_id, skill_id, accepted, declined, int(never)),
            )

    def accept_rate(self, person_id: str, skill_id: str) -> dict[str, Any]:
        with self.connect() as con:
            r = self._tally_row(con, person_id, skill_id)
        acc = r["accepted"] if r else 0
        dec = r["declined"] if r else 0
        alpha = PRIOR_ALPHA + acc
        beta = PRIOR_BETA + dec
        return {
            "alpha": alpha,
            "beta": beta,
            "accepted": acc,
            "declined": dec,
            "mean": round(alpha / (alpha + beta), 4),
            "suppressed": bool(r and r["never"]),
        }

    # -------------------------------------------------------------- runs cache

    def upsert_run(self, run: dict[str, Any], *, suggestion_id: str | None = None) -> None:
        with self.connect() as con:
            existing = con.execute("SELECT suggestion_id FROM runs_cache WHERE id=?", (run["id"],)).fetchone()
            sug = suggestion_id or (existing["suggestion_id"] if existing else None)
            con.execute(
                """INSERT INTO runs_cache (id, suggestion_id, skill_id, status, body, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                       suggestion_id=excluded.suggestion_id, skill_id=excluded.skill_id,
                       status=excluded.status, body=excluded.body, updated_at=excluded.updated_at""",
                (run["id"], sug, run.get("skill_id"), run.get("status"), json.dumps(run, ensure_ascii=False), now_iso()),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            r = con.execute("SELECT body, suggestion_id FROM runs_cache WHERE id=?", (run_id,)).fetchone()
        if r is None:
            return None
        body = json.loads(r["body"])
        body["_suggestion_id"] = r["suggestion_id"]
        return body

    # -------------------------------------------------------------- fleet

    def list_board_suggestions(self, board_id: str) -> list[dict[str, Any]]:
        """Every suggestion on the board, newest first (all statuses)."""
        with self.connect() as con:
            rows = con.execute("SELECT * FROM suggestions WHERE board_id=? ORDER BY created_at DESC", (board_id,)).fetchall()
        return [self._row_to_suggestion(r) for r in rows]

    def set_suggestion_body(self, sid: str, patch: dict[str, Any]) -> None:
        """Merge extra keys (e.g. pre_approved) into the stored Suggestion JSON."""
        with self.connect() as con:
            r = con.execute("SELECT body FROM suggestions WHERE id=?", (sid,)).fetchone()
            if r is None:
                return
            body = json.loads(r["body"])
            body.update(patch)
            con.execute("UPDATE suggestions SET body=? WHERE id=?", (json.dumps(body, ensure_ascii=False), sid))

    def clear_board_fleet(self, board_id: str) -> dict[str, int]:
        """Reset for a re-take: drop the board's suggestions and the cached runs they point at (records and approvals stay)."""
        with self.connect() as con:
            runs = con.execute(
                "DELETE FROM runs_cache WHERE suggestion_id IN (SELECT id FROM suggestions WHERE board_id=?)", (board_id,)
            ).rowcount
            sugs = con.execute("DELETE FROM suggestions WHERE board_id=?", (board_id,)).rowcount
        return {"suggestions": sugs, "runs": runs}
