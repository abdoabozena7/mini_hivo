"""Private terminal history, not execution authority or a replay queue."""

from __future__ import annotations

import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4


MAX_NAME_LENGTH = 80
MAX_HISTORY_LIMIT = 100
_FINISHED_STATUSES = frozenset({"completed", "failed", "cancelled", "blocked"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Session name must be text.")
    value = value.strip()
    if not value or len(value) > MAX_NAME_LENGTH or not value.isprintable():
        raise ValueError(
            f"Session name must contain 1-{MAX_NAME_LENGTH} readable characters."
        )
    return value


def _require_directory(path: Path) -> None:
    if not stat.S_ISDIR(path.stat().st_mode):
        raise NotADirectoryError(f"Workspace is not a directory: {path}")


@dataclass(frozen=True)
class Session:
    id: str
    name: str
    workspace: Path
    created_at: str
    updated_at: str
    last_active_at: str


@dataclass(frozen=True)
class Turn:
    id: str
    session_id: str
    prompt: str
    status: str
    summary: str
    log_path: Path
    run_id: str
    started_at: str
    finished_at: str | None


class SessionStore:
    """SQLite catalogue with explicit, transactionally recorded turn endings."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.db_path = self.state_dir / "sessions.sqlite3"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_recency
                    ON sessions(last_active_at DESC, created_at DESC, id);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    CHECK (
                        (status = 'running' AND finished_at IS NULL)
                        OR (status <> 'running' AND finished_at IS NOT NULL)
                    )
                );
                CREATE INDEX IF NOT EXISTS turns_history
                    ON turns(session_id, started_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
        except BaseException:
            connection.close()
            raise
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _session(connection: sqlite3.Connection, session_id: str) -> Session:
        row = connection.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown session: {session_id}")
        return Session(
            id=row["id"],
            name=row["name"],
            workspace=Path(row["workspace"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_active_at=row["last_active_at"],
        )

    @staticmethod
    def _turn(row: sqlite3.Row) -> Turn:
        return Turn(
            id=row["id"],
            session_id=row["session_id"],
            prompt=row["prompt"],
            status=row["status"],
            summary=row["summary"],
            log_path=Path(row["log_path"]),
            run_id=row["run_id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def create(self, workspace: Path, name: str | None = None) -> Session:
        workspace = Path(workspace).expanduser().resolve(strict=True)
        _require_directory(workspace)
        name = _name(
            name if name is not None else (workspace.name or "Session")[:MAX_NAME_LENGTH]
        )
        session_id = uuid4().hex
        now = _now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions "
                "(id, name, workspace, created_at, updated_at, last_active_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, name, str(workspace), now, now, now),
            )
            return self._session(connection, session_id)

    def list(self) -> list[Session]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM sessions "
                "ORDER BY last_active_at DESC, created_at DESC, id"
            ).fetchall()
            return [self._session(connection, row["id"]) for row in rows]

    def get(self, session_id: str) -> Session:
        with self._connection() as connection:
            return self._session(connection, session_id)

    def resolve(self, reference: str) -> Session:
        if not isinstance(reference, str):
            raise ValueError("Session reference must be text.")
        reference = reference.strip()
        sessions = self.list()
        for session in sessions:
            if session.id == reference:
                return session
        matches = [
            session for session in sessions
            if reference and (
                session.name.casefold() == reference.casefold()
                or session.id.startswith(reference)
            )
        ]
        if not matches:
            raise KeyError(f"Unknown session: {reference}")
        if len(matches) != 1:
            raise ValueError(f"Ambiguous session reference: {reference}")
        return matches[0]

    def select(self, session_id: str) -> Session:
        with self._connection() as connection:
            session = self._session(connection, session_id)
            _require_directory(session.workspace)
            now = _now()
            connection.execute(
                "UPDATE sessions SET last_active_at = ?, updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            return self._session(connection, session_id)

    def rename(self, session_id: str, name: str) -> Session:
        name = _name(name)
        with self._connection() as connection:
            self._session(connection, session_id)
            connection.execute(
                "UPDATE sessions SET name = ?, updated_at = ? WHERE id = ?",
                (name, _now(), session_id),
            )
            return self._session(connection, session_id)

    def start_turn(self, session_id: str, prompt: str) -> Turn:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A turn needs a nonempty text prompt.")
        log_created = False
        log_path = None
        try:
            with self._connection() as connection:
                session = self._session(connection, session_id)
                turn_id = uuid4().hex
                log_path = self.state_dir / "logs" / session.id / f"{turn_id}.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("x", encoding="utf-8"):
                    pass
                log_created = True
                now = _now()
                connection.execute(
                    "INSERT INTO turns "
                    "(id, session_id, prompt, status, log_path, started_at) "
                    "VALUES (?, ?, ?, 'running', ?, ?)",
                    (turn_id, session_id, prompt, str(log_path), now),
                )
                connection.execute(
                    "UPDATE sessions SET last_active_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, session_id),
                )
                row = connection.execute(
                    "SELECT * FROM turns WHERE id = ?", (turn_id,)
                ).fetchone()
                turn = self._turn(row)
            return turn
        except BaseException:
            if log_created and log_path is not None:
                log_path.unlink(missing_ok=True)
            raise

    def finish_turn(
        self, turn_id: str, *, status: str, summary: str, run_id: str = ""
    ) -> Turn:
        if not isinstance(status, str) or status not in _FINISHED_STATUSES:
            raise ValueError("Turn status must be completed, failed, cancelled or blocked.")
        if not isinstance(summary, str) or not isinstance(run_id, str):
            raise ValueError("Turn summary and run ID must be text.")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM turns WHERE id = ?", (turn_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown turn: {turn_id}")
            if row["status"] != "running" or row["finished_at"] is not None:
                raise ValueError(f"Turn is already finished: {turn_id}")
            now = _now()
            updated = connection.execute(
                "UPDATE turns SET status = ?, summary = ?, run_id = ?, finished_at = ? "
                "WHERE id = ? AND status = 'running' AND finished_at IS NULL",
                (status, summary, run_id, now, turn_id),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Turn is already finished: {turn_id}")
            connection.execute(
                "UPDATE sessions SET last_active_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["session_id"]),
            )
            return self._turn(
                connection.execute(
                    "SELECT * FROM turns WHERE id = ?", (turn_id,)
                ).fetchone()
            )

    def history(self, session_id: str, limit: int = 20) -> list[Turn]:
        if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise ValueError(f"History limit must be an integer from 1 to {MAX_HISTORY_LIMIT}.")
        with self._connection() as connection:
            self._session(connection, session_id)
            rows = connection.execute(
                "SELECT * FROM turns WHERE session_id = ? "
                "ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [self._turn(row) for row in reversed(rows)]
