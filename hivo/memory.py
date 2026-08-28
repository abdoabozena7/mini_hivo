"""Durable, bounded, disk-backed memory for the coding orchestrator.

The database is an execution ledger, not an ever-growing prompt.  Callers ask
for a small relevant projection and only verified notes are eligible for that
projection by default.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MEMORY_DIRECTORY = ".hivo"
MEMORY_DATABASE = "memory.sqlite3"
LEGACY_MEMORY_FILE = ".agent_memory.json"
SCHEMA_VERSION = "2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in re.findall(r"[\w.-]{2,}", str(text).casefold(), flags=re.UNICODE):
        if token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


class MemoryStore:
    """SQLite-backed project memory with bounded relevance retrieval."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).expanduser().resolve()
        self.db_path = self.workspace / MEMORY_DIRECTORY / MEMORY_DATABASE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._recover_interrupted_artifacts()
        self._migrate_legacy_once()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    contract_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    parent_id TEXT,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    stage_index INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, task_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    verified INTEGER NOT NULL DEFAULT 0,
                    run_id TEXT,
                    task_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS notes_verified_scope
                    ON notes(verified, scope, updated_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    run_id TEXT,
                    task_id TEXT,
                    role TEXT,
                    tool TEXT,
                    target TEXT,
                    status TEXT NOT NULL,
                    content TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS events_run_task
                    ON events(run_id, task_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS artifacts (
                    path TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    first_run_id TEXT,
                    last_run_id TEXT,
                    verified INTEGER NOT NULL DEFAULT 0,
                    content_sha256 TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_owner_verified
                    ON artifacts(owner, verified, updated_at DESC);
                """
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SCHEMA_VERSION,),
            )

    def _artifact_path(self, path: str | Path) -> str | None:
        try:
            raw = Path(str(path))
            target = raw if raw.is_absolute() else self.workspace / raw
            return target.resolve().relative_to(self.workspace).as_posix()
        except (OSError, ValueError):
            return None

    def _artifact_hash(self, relative_path: str) -> str | None:
        target = self.workspace / relative_path
        try:
            if not target.is_file():
                return None
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            return None

    def _recover_interrupted_artifacts(self) -> None:
        """Backfill files written by a process that stopped before finalization."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT e.target, e.run_id, MIN(e.created_at) AS first_at,
                          MAX(e.created_at) AS last_at
                   FROM events e
                   JOIN runs r ON r.run_id = e.run_id
                   WHERE e.tool = 'write_file' AND e.status = 'succeeded'
                     AND e.target IS NOT NULL AND e.target != ''
                     AND r.status = 'running'
                   GROUP BY e.target, e.run_id"""
            ).fetchall()
            for row in rows:
                relative = self._artifact_path(str(row["target"]))
                digest = self._artifact_hash(relative) if relative else None
                if not relative or not digest:
                    continue
                connection.execute(
                    """INSERT OR IGNORE INTO artifacts(
                           path, owner, first_run_id, last_run_id, verified,
                           content_sha256, created_at, updated_at
                       ) VALUES(?, 'model', ?, ?, 0, ?, ?, ?)""",
                    (
                        relative, row["run_id"], row["run_id"], digest,
                        row["first_at"] or _now(), row["last_at"] or _now(),
                    ),
                )

    def mark_model_artifact(self, path: str | Path, run_id: str | None = None) -> bool:
        """Record a successful model-authored full write and its exact bytes."""
        relative = self._artifact_path(path)
        digest = self._artifact_hash(relative) if relative else None
        if not relative or not digest:
            return False
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO artifacts(
                       path, owner, first_run_id, last_run_id, verified,
                       content_sha256, created_at, updated_at
                   ) VALUES(?, 'model', ?, ?, 0, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                     owner='model',
                     last_run_id=excluded.last_run_id,
                     verified=0,
                     content_sha256=excluded.content_sha256,
                     updated_at=excluded.updated_at""",
                (relative, run_id, run_id, digest, now, now),
            )
        return True

    def is_unverified_model_artifact(self, path: str | Path) -> bool:
        """Allow resumption only while the on-disk bytes still match the model write."""
        relative = self._artifact_path(path)
        if not relative:
            return False
        with self._connection() as connection:
            row = connection.execute(
                """SELECT content_sha256 FROM artifacts
                   WHERE path = ? AND owner = 'model' AND verified = 0""",
                (relative,),
            ).fetchone()
        if not row:
            return False
        digest = self._artifact_hash(relative)
        return bool(digest and digest == str(row["content_sha256"]))

    def unverified_model_artifacts(self, limit: int = 20) -> list[str]:
        """Return only model drafts whose current bytes still match the ledger."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT path, content_sha256 FROM artifacts
                   WHERE owner = 'model' AND verified = 0
                   ORDER BY updated_at DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        result: list[str] = []
        for row in rows:
            relative = str(row["path"])
            digest = self._artifact_hash(relative)
            if digest and digest == str(row["content_sha256"]):
                result.append(relative)
        return result

    def refresh_unverified_model_artifact(
        self, path: str | Path, run_id: str | None = None,
    ) -> bool:
        """Refresh bytes after a focused Builder edit without claiming user files."""
        relative = self._artifact_path(path)
        digest = self._artifact_hash(relative) if relative else None
        if not relative or not digest:
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE artifacts SET content_sha256 = ?,
                       last_run_id = COALESCE(?, last_run_id), updated_at = ?
                   WHERE path = ? AND owner = 'model' AND verified = 0""",
                (digest, run_id, _now(), relative),
            )
        return cursor.rowcount > 0

    def mark_artifacts_verified(
        self, paths: Iterable[str | Path], run_id: str | None = None,
    ) -> int:
        normalized = [self._artifact_path(path) for path in paths]
        normalized = [path for path in normalized if path]
        if not normalized:
            return 0
        with self._connection() as connection:
            changed = 0
            for path in dict.fromkeys(normalized):
                cursor = connection.execute(
                    """UPDATE artifacts SET verified = 1,
                           last_run_id = COALESCE(?, last_run_id), updated_at = ?
                       WHERE path = ? AND owner = 'model'""",
                    (run_id, _now(), path),
                )
                changed += max(0, cursor.rowcount)
        return changed

    def reconcile_rolled_back_artifact(self, path: str | Path, *, existed: bool) -> None:
        """Keep ownership aligned with bytes restored by a normal rollback."""
        relative = self._artifact_path(path)
        if not relative:
            return
        with self._connection() as connection:
            row = connection.execute(
                "SELECT verified FROM artifacts WHERE path = ? AND owner = 'model'",
                (relative,),
            ).fetchone()
            if not row or bool(row["verified"]):
                return
            if not existed:
                connection.execute(
                    "DELETE FROM artifacts WHERE path = ? AND verified = 0",
                    (relative,),
                )
                return
            digest = self._artifact_hash(relative)
            if digest:
                connection.execute(
                    "UPDATE artifacts SET content_sha256 = ?, updated_at = ? WHERE path = ?",
                    (digest, _now(), relative),
                )

    def _metadata(self, key: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _set_metadata(self, key: str, value: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def _migrate_legacy_once(self) -> None:
        if self._metadata("legacy_json_imported") == "1":
            return
        legacy_path = self.workspace / LEGACY_MEMORY_FILE
        if legacy_path.exists():
            try:
                payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                payload = {}
            operations = payload.get("operations", []) if isinstance(payload, dict) else []
            if isinstance(operations, list):
                for operation in operations:
                    if not isinstance(operation, dict):
                        continue
                    args = operation.get("args") if isinstance(operation.get("args"), dict) else {}
                    self.record_event(
                        run_id="legacy",
                        task_id=None,
                        role="legacy",
                        tool=str(operation.get("tool") or "unknown"),
                        target=str(args.get("path") or args.get("command") or ""),
                        status="imported",
                        content=str(operation.get("result") or "")[:4000],
                        details={"time": operation.get("time"), "args": args},
                    )
        self._set_metadata("legacy_json_imported", "1")

    def begin_run(self, run_id: str, goal: str, contract: dict | None = None) -> None:
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO runs(run_id, goal, contract_json, status, started_at, finished_at)
                   VALUES(?, ?, ?, 'running', ?, NULL)
                   ON CONFLICT(run_id) DO UPDATE SET
                     goal=excluded.goal,
                     contract_json=excluded.contract_json,
                     status='running',
                     finished_at=NULL""",
                (run_id, str(goal), _json(contract or {}), now),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
                (str(status), _now(), run_id),
            )

    def upsert_task(
        self,
        run_id: str,
        task_id: str,
        goal: str,
        status: str,
        *,
        summary: str = "",
        parent_id: str | None = None,
        stage_index: int | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO tasks(run_id, task_id, parent_id, goal, status, summary, stage_index, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, task_id) DO UPDATE SET
                     parent_id=excluded.parent_id,
                     goal=excluded.goal,
                     status=excluded.status,
                     summary=excluded.summary,
                     stage_index=excluded.stage_index,
                     updated_at=excluded.updated_at""",
                (run_id, task_id, parent_id, str(goal), str(status), str(summary), stage_index, _now()),
            )

    def latest_resumable_run(self, *, exclude_run_id: str | None = None) -> dict | None:
        with self._connection() as connection:
            if exclude_run_id:
                run = connection.execute(
                    """SELECT * FROM runs
                       WHERE status = 'running' AND run_id <> ?
                       ORDER BY started_at DESC LIMIT 1""",
                    (exclude_run_id,),
                ).fetchone()
            else:
                run = connection.execute(
                    "SELECT * FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            if not run:
                return None
            tasks = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY COALESCE(stage_index, 999999), task_id",
                (run["run_id"],),
            ).fetchall()
        result = dict(run)
        try:
            result["contract"] = json.loads(result.pop("contract_json"))
        except (ValueError, TypeError):
            result["contract"] = {}
            result.pop("contract_json", None)
        result["tasks"] = [dict(row) for row in tasks]
        return result

    def resumable_context(
        self,
        query: str,
        *,
        max_chars: int = 900,
        snapshot: dict | None = None,
    ) -> str:
        """Return a labeled unfinished ledger only when it is likely relevant."""
        if max_chars <= 0:
            return ""
        snapshot = snapshot or self.latest_resumable_run()
        if not snapshot:
            return ""
        query_tokens = set(_tokens(query))
        goal_tokens = set(_tokens(snapshot.get("goal", "")))
        resume_markers = {"continue", "resume", "unfinished", "كمل", "اكمل", "تابع", "استكمل"}
        if not (query_tokens & goal_tokens or query_tokens & resume_markers):
            return ""
        task_projection = [
            {
                "task_id": task["task_id"],
                "status": task["status"],
                "goal": task["goal"][:300],
                "summary": task["summary"][:300],
            }
            for task in snapshot.get("tasks", [])[-8:]
        ]
        text = (
            "UNFINISHED DISK LEDGER (not proof of completion; inspect files before continuing):\n"
            f"run={snapshot['run_id']} goal={snapshot['goal']}\n"
            f"tasks={_json(task_projection)}"
        )
        return text[:max_chars]

    def add_note(
        self,
        content: str,
        *,
        kind: str = "lesson",
        scope: str = "project",
        verified: bool = False,
        importance: float = 0.5,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        normalized = " ".join(str(content).split()).strip()
        if not normalized:
            return
        normalized = normalized[:8000]
        fingerprint = hashlib.sha256(
            f"{kind}\0{scope}\0{normalized}".encode("utf-8", errors="replace")
        ).hexdigest()
        now = _now()
        bounded_importance = max(0.0, min(1.0, float(importance)))
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO notes(
                       fingerprint, kind, scope, content, importance, verified,
                       run_id, task_id, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                     importance=MAX(notes.importance, excluded.importance),
                     verified=MAX(notes.verified, excluded.verified),
                     run_id=COALESCE(excluded.run_id, notes.run_id),
                     task_id=COALESCE(excluded.task_id, notes.task_id),
                     updated_at=excluded.updated_at""",
                (
                    fingerprint, str(kind), str(scope), normalized, bounded_importance,
                    1 if verified else 0, run_id, task_id, now, now,
                ),
            )

    def record_event(
        self,
        *,
        run_id: str | None,
        task_id: str | None,
        role: str | None,
        tool: str | None,
        target: str | None,
        status: str,
        content: str,
        details: dict | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO events(
                       created_at, run_id, task_id, role, tool, target, status, content, details_json
                   ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    _now(), run_id, task_id, role, tool, target, str(status),
                    str(content)[:4000], _json(details or {}),
                ),
            )

    def event_count(self) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"])

    def recent_files(self, limit: int = 10) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT target, MAX(id) AS newest
                   FROM events
                   WHERE target IS NOT NULL AND target != ''
                     AND tool IN (
                       'read_file', 'read_file_range', 'write_file', 'edit_file', 'edit_file_range',
                       'run_file', 'verify_web_app'
                     )
                   GROUP BY target ORDER BY newest DESC LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        return [str(row["target"]) for row in rows]

    def retrieve(
        self,
        query: str,
        *,
        max_items: int = 6,
        verified_only: bool = True,
        kinds: Iterable[str] | None = None,
    ) -> list[dict]:
        query_tokens = _tokens(query)[:12]
        clauses = ["verified = 1"] if verified_only else ["1 = 1"]
        params: list[Any] = []
        kind_values = [str(kind) for kind in kinds or []]
        if kind_values:
            clauses.append("kind IN (" + ",".join("?" for _ in kind_values) + ")")
            params.extend(kind_values)
        if query_tokens:
            clauses.append("(" + " OR ".join(
                "LOWER(content || ' ' || scope || ' ' || kind) LIKE ?" for _ in query_tokens
            ) + ")")
            params.extend(f"%{token}%" for token in query_tokens)
        sql = (
            "SELECT * FROM notes WHERE " + " AND ".join(clauses)
            + " ORDER BY importance DESC, updated_at DESC LIMIT 80"
        )
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(sql, params).fetchall()]

        query_set = set(query_tokens)
        for row in rows:
            note_tokens = set(_tokens(f"{row['content']} {row['scope']} {row['kind']}"))
            overlap = len(query_set & note_tokens)
            partial = sum(
                1 for token in query_set
                if any(token in candidate or candidate in token for candidate in note_tokens)
            )
            row["relevance"] = overlap * 5 + partial + float(row["importance"])
            row["verified"] = bool(row["verified"])
        rows.sort(key=lambda row: (row["relevance"], row["importance"], row["updated_at"]), reverse=True)
        return rows[:max(0, int(max_items))]

    def context_for(self, query: str, *, max_items: int = 6, max_chars: int = 2400) -> str:
        if max_chars <= 0:
            return ""
        notes = self.retrieve(query, max_items=max_items, verified_only=True)
        if not notes:
            return ""
        heading = "VERIFIED LONG-TERM PROJECT MEMORY (relevant excerpts only):\n"
        output = heading
        for note in notes:
            line = f"- [{note['kind']}/{note['scope']}] {note['content']}\n"
            if len(output) + len(line) > max_chars:
                remaining = max_chars - len(output)
                if remaining > 20:
                    output += line[:remaining]
                break
            output += line
        return output[:max_chars].rstrip()
