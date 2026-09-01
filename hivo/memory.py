"""Durable, bounded, disk-backed memory for the coding orchestrator.

The database is an execution ledger, not an ever-growing prompt.  Callers ask
for a small relevant projection and only verified notes or promoted facts are
eligible for that projection by default.
"""

from __future__ import annotations

import copy
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
SCHEMA_VERSION = "3"
PROMOTION_SCHEMA_VERSION = "V22.5C"
PROMOTION_CANDIDATE_TYPE = "PromotionCandidate"


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


_PROMOTION_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_transcript", "private_reasoning", "raw_worker_output", "raw_content",
    "worker_output", "model_output", "mission_compiler_output", "task_fit_output",
    "decomposer_output", "raw_model_output", "raw_model_transcript",
    "falsifier_output", "strategy_output", "strategy_text",
    "repair_output", "repair_speculation",
})


def _contains_promotion_private(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (str(key).casefold() == "raw_worker_transcript_included" and item is not False)
            or _promotion_private_key(key)
            or _contains_promotion_private(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_promotion_private(item) for item in value)
    if isinstance(value, str):
        lower = value.casefold()
        return any(marker in lower for marker in (
            "chain_of_thought", "private reasoning", "raw worker transcript",
            "worker output", "worker transcript", "worker said done", "model output", "model transcript",
            "raw model", "missioncompiler", "mission compiler output", "decomposer prose",
            "decomposer output", "decomposer response", "task-fit output", "falsifier prose",
            "falsifier output", "strategy text", "strategy output", "repair speculation",
            "repair output",
        ))
    return False


def _promotion_private_key(key: Any) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    if normalized == "raw_worker_transcript_included":
        return False
    if normalized in _PROMOTION_PRIVATE_KEYS:
        return True
    return any(marker in normalized for marker in (
        "transcript", "chain_of_thought", "private_reasoning", "raw_worker",
        "raw_model", "worker_output", "model_output", "missioncompiler",
        "mission_compiler", "decomposer", "task_fit", "falsifier", "strategy_output",
        "repair_output", "repair_speculation",
    ))


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
                CREATE TABLE IF NOT EXISTS project_brain_facts (
                    record_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    fact_hash TEXT NOT NULL,
                    semantic_hash TEXT NOT NULL,
                    conflict_key TEXT NOT NULL DEFAULT '',
                    fact_json TEXT NOT NULL,
                    durability_class TEXT NOT NULL,
                    subject_state_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    supersedes_json TEXT NOT NULL DEFAULT '[]',
                    superseded_by TEXT,
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, fact_hash)
                );
                CREATE INDEX IF NOT EXISTS project_brain_facts_project_status
                    ON project_brain_facts(project_id, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS project_brain_facts_semantic
                    ON project_brain_facts(project_id, semantic_hash, status);
                CREATE INDEX IF NOT EXISTS project_brain_facts_conflict
                    ON project_brain_facts(project_id, conflict_key, status);
                CREATE TABLE IF NOT EXISTS promotions (
                    promotion_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    promotion_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, candidate_hash)
                );
                CREATE TABLE IF NOT EXISTS task_brain_completions (
                    project_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    completion_hash TEXT NOT NULL,
                    completion_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, task_id)
                );
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

    # ------------------------------------------------------------------
    # V22 Stage 5C verified Project Brain records
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _project_id(project_id: str | None) -> str:
        normalized = str(project_id or "default").strip()
        return normalized[:180] or "default"

    @staticmethod
    def _decode_json(value: Any, fallback: Any) -> Any:
        try:
            decoded = json.loads(str(value))
        except (TypeError, ValueError):
            return copy.deepcopy(fallback) if isinstance(fallback, (dict, list)) else fallback
        return decoded

    def _records_from_connection(
        self, connection: sqlite3.Connection, project_id: str, *, include_inactive: bool = True,
    ) -> list[dict]:
        project = self._project_id(project_id)
        if include_inactive:
            rows = connection.execute(
                """SELECT * FROM project_brain_facts
                   WHERE project_id = ? ORDER BY record_id""", (project,),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT * FROM project_brain_facts
                   WHERE project_id = ? AND status = 'ACTIVE'
                   ORDER BY record_id""", (project,),
            ).fetchall()
        records: list[dict] = []
        for row in rows:
            fact = self._decode_json(row["fact_json"], {})
            if not isinstance(fact, dict):
                fact = {}
            supersedes = self._decode_json(row["supersedes_json"], [])
            if not isinstance(supersedes, list):
                supersedes = []
            provenance = self._decode_json(row["provenance_json"], {})
            if not isinstance(provenance, dict):
                provenance = {}
            records.append({
                "record_id": str(row["record_id"]),
                "project_id": str(row["project_id"]),
                "fact_hash": str(row["fact_hash"]),
                "semantic_hash": str(row["semantic_hash"]),
                "conflict_key": str(row["conflict_key"] or ""),
                "fact": fact,
                "durability_class": str(row["durability_class"]),
                "subject_state_hash": str(row["subject_state_hash"] or ""),
                "status": str(row["status"]),
                "supersedes": supersedes,
                "superseded_by": row["superseded_by"],
                "provenance": provenance,
            })
        return records

    def project_brain_snapshot(
        self, project_id: str = "default", *, include_inactive: bool = True,
    ) -> dict:
        project = self._project_id(project_id)
        with self._connection() as connection:
            records = self._records_from_connection(
                connection, project, include_inactive=include_inactive,
            )
        return {"project_id": project, "records": records}

    def project_brain_hash(
        self, project_id: str = "default", *, include_inactive: bool = True,
    ) -> str:
        return self._canonical_hash(self.project_brain_snapshot(
            project_id, include_inactive=include_inactive,
        ))

    # Read aliases make the durable boundary discoverable without exposing
    # the older free-form notes API as Project Brain state.
    verified_project_facts = project_brain_snapshot
    get_project_brain = project_brain_snapshot

    def retrieve_verified_project_facts(
        self, query: str = "", *, project_id: str = "default", max_items: int = 6,
        include_stale: bool = False,
    ) -> list[dict]:
        project = self._project_id(project_id)
        query_tokens = _tokens(query)[:12]
        with self._connection() as connection:
            rows = self._records_from_connection(
                connection, project, include_inactive=bool(include_stale),
            )
        if not include_stale:
            rows = [row for row in rows if row.get("status") == "ACTIVE"]
        for row in rows:
            searchable = _json({
                "fact": row.get("fact", {}), "conflict_key": row.get("conflict_key", ""),
            }).casefold()
            overlap = sum(1 for token in query_tokens if token in searchable)
            row["relevance"] = overlap * 5 + (1 if row.get("status") == "ACTIVE" else 0)
        rows.sort(key=lambda item: (
            int(item.get("relevance", 0)), item.get("status") == "ACTIVE", item.get("record_id", ""),
        ), reverse=True)
        return rows[: max(0, int(max_items))]

    def mark_stale_verified_facts(
        self, *, current_subject_state_hash: str | None = None,
        changed_paths: Iterable[str] | None = None, project_id: str = "default",
    ) -> dict:
        project = self._project_id(project_id)
        changed = {
            str(path or "").replace("\\", "/").lstrip("./")
            for path in (changed_paths or []) if str(path or "").strip()
        }
        marked: list[str] = []
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT record_id, subject_state_hash, fact_json
                   FROM project_brain_facts
                   WHERE project_id = ? AND status = 'ACTIVE'
                     AND durability_class = 'STATE_BOUND_VERIFIED'""", (project,),
            ).fetchall()
            for row in rows:
                fact = self._decode_json(row["fact_json"], {})
                if not isinstance(fact, dict):
                    fact = {}
                dependencies = {
                    str(path or "").replace("\\", "/").lstrip("./")
                    for path in fact.get("dependency_paths", []) or []
                }
                stale = bool(
                    current_subject_state_hash
                    and str(row["subject_state_hash"] or "") != str(current_subject_state_hash)
                )
                if changed and dependencies.intersection(changed):
                    stale = True
                if not stale:
                    continue
                connection.execute(
                    "UPDATE project_brain_facts SET status = 'STALE', updated_at = ? WHERE record_id = ?",
                    (_now(), row["record_id"]),
                )
                marked.append(str(row["record_id"]))
        return {"marked_stale": len(marked), "record_ids": marked, "model_calls": 0}

    mark_verified_facts_stale = mark_stale_verified_facts

    def get_task_brain_completion(self, project_id: str = "default", task_id: str = "") -> dict | None:
        project = self._project_id(project_id)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT completion_json FROM task_brain_completions
                   WHERE project_id = ? AND task_id = ?""", (project, str(task_id)),
            ).fetchone()
        if not row:
            return None
        value = self._decode_json(row["completion_json"], {})
        return value if isinstance(value, dict) else None

    def save_task_brain_completion(self, project_id: str, completion: dict) -> dict | None:
        if not isinstance(completion, dict) or not completion.get("task_id"):
            return None
        project = self._project_id(project_id)
        value = copy.deepcopy(completion)
        value.setdefault("completion_hash", self._canonical_hash({
            key: item for key, item in value.items() if key != "completion_hash"
        }))
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO task_brain_completions(
                       project_id, task_id, completion_hash, completion_json, created_at, updated_at
                   ) VALUES(?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, task_id) DO UPDATE SET
                       completion_hash=excluded.completion_hash,
                       completion_json=excluded.completion_json,
                       updated_at=excluded.updated_at""",
                (project, str(value["task_id"]), value["completion_hash"], _json(value), now, now),
            )
        return value

    def _candidate_hash(self, candidate: dict) -> str:
        return self._canonical_hash({
            key: item for key, item in candidate.items()
            if key not in {"candidate_hash", "candidate_id"}
        })

    def commit_verified_promotion(
        self, candidate: dict, *, task_completion: dict | None = None,
    ) -> dict:
        """Atomically deduplicate, supersede, and persist one V22 candidate."""
        if not isinstance(candidate, dict):
            return {
                "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                "model_calls": 0,
            }
        project = self._project_id(candidate.get("project_id"))
        candidate_hash = str(candidate.get("candidate_hash") or "")
        if (
            candidate.get("artifact_type") != PROMOTION_CANDIDATE_TYPE
            or candidate.get("schema_version") != PROMOTION_SCHEMA_VERSION
            or not candidate_hash
            or self._candidate_hash(candidate) != candidate_hash
            or _contains_promotion_private(candidate)
        ):
            return {
                "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                "model_calls": 0,
            }
        provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
        if (
            int(provenance.get("model_calls", 0) or 0) != 0
            or provenance.get("raw_worker_transcript_included") is not False
            or provenance.get("authority_escalation") is True
            or provenance.get("cross_project_memory") is True
        ):
            return {
                "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                "model_calls": 0,
            }
        now = _now()
        category_names = (
            "verified_facts", "verified_interfaces", "verified_preservations", "verified_prohibitions",
            "verified_tests",
        )
        with self._connection() as connection:
            before_records = self._records_from_connection(connection, project, include_inactive=True)
            before_snapshot = {"project_id": project, "records": before_records}
            before_hash = self._canonical_hash(before_snapshot)
            existing_promotion = connection.execute(
                """SELECT receipt_json FROM promotions
                   WHERE project_id = ? AND candidate_hash = ?""", (project, candidate_hash),
            ).fetchone()
            if existing_promotion:
                receipt = self._decode_json(existing_promotion["receipt_json"], {})
                if not isinstance(receipt, dict):
                    receipt = {}
                completion = None
                task_id = (task_completion or {}).get("task_id") if isinstance(task_completion, dict) else None
                if task_id:
                    row = connection.execute(
                        """SELECT completion_json FROM task_brain_completions
                           WHERE project_id = ? AND task_id = ?""", (project, str(task_id)),
                    ).fetchone()
                    if row:
                        completion = self._decode_json(row["completion_json"], {})
                    if not isinstance(completion, dict):
                        completion = {
                            "schema_version": PROMOTION_SCHEMA_VERSION,
                            "task_id": str(task_id),
                            "terminal_state": "VERIFIED_AND_PROMOTED",
                            "parent_verification_hash": receipt.get("parent_verification_hash"),
                            "promotion_hash": receipt.get("promotion_hash"),
                            "subject_state_hash": receipt.get("subject_state_hash"),
                            "artifact_refs": [
                                str(item)[:220] for item in (task_completion or {}).get("artifact_refs", []) or []
                            ][:24],
                            "project_brain_record_ids": list(
                                receipt.get("promoted_record_ids", []) or []
                            )[:256],
                        }
                        completion["completion_hash"] = self._canonical_hash(completion)
                        connection.execute(
                            """INSERT INTO task_brain_completions(
                                   project_id, task_id, completion_hash, completion_json, created_at, updated_at
                               ) VALUES(?, ?, ?, ?, ?, ?)
                               ON CONFLICT(project_id, task_id) DO UPDATE SET
                                   completion_hash=excluded.completion_hash,
                                   completion_json=excluded.completion_json,
                                   updated_at=excluded.updated_at""",
                            (project, str(task_id), completion["completion_hash"], _json(completion), now, now),
                        )
                after_hash = self._canonical_hash(before_snapshot)
                return {
                    "promotion_status": "ALREADY_PROMOTED", "status": "ALREADY_PROMOTED",
                    "no_op": True, "candidate": copy.deepcopy(candidate),
                    "promotion_receipt": receipt, "project_brain_before_hash": before_hash,
                    "project_brain_after_hash": after_hash,
                    "project_brain_records": before_records,
                    "task_brain_completion": completion, "model_calls": 0,
                }

            facts: list[dict] = []
            for category in category_names:
                values = candidate.get(category)
                if not isinstance(values, list):
                    return {
                        "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                        "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                        "model_calls": 0,
                    }
                facts.extend(item for item in values if isinstance(item, dict))
            if not facts:
                return {
                    "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                    "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                    "model_calls": 0,
                }
            for fact in facts:
                fact_hash = str(fact.get("fact_hash") or "")
                if (
                    not fact_hash
                    or fact.get("verified") is not True
                    or fact.get("approved") is not True
                    or fact.get("durability_class") not in {"DURABLE_VERIFIED", "STATE_BOUND_VERIFIED"}
                    or fact.get("subject_state_hash") != candidate.get("subject_state_hash")
                    or not isinstance(fact.get("evidence_refs"), list)
                    or not fact.get("evidence_refs")
                    or self._canonical_hash({
                    key: item for key, item in fact.items() if key != "fact_hash"
                    }) != fact_hash
                ):
                    return {
                        "promotion_status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE",
                        "status": "PROMOTION_NOT_ELIGIBLE_PROVENANCE", "no_op": True,
                        "model_calls": 0,
                    }

            existing_active = [
                item for item in before_records if item.get("status") == "ACTIVE"
            ]
            exact_by_hash = {str(item.get("fact_hash")): item for item in existing_active}
            semantic_by_hash = {str(item.get("semantic_hash")): item for item in existing_active}
            conflict_by_key = {
                str(item.get("conflict_key")): item for item in existing_active
                if str(item.get("conflict_key") or "")
            }
            authority_change = candidate.get("authority_change")
            if not isinstance(authority_change, dict):
                source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
                authority_change = source.get("authority_change") if isinstance(source.get("authority_change"), dict) else {}
            authority_change_approved = authority_change.get("approved") is True
            supersede_refs = {
                str(item) for item in (candidate.get("supersedes") or [])
            }
            if authority_change_approved:
                for key in ("previous_fact_hash", "previous_record_id"):
                    if authority_change.get(key):
                        supersede_refs.add(str(authority_change[key]))

            deduplicated_ids: list[str] = []
            superseded_ids: list[str] = []
            superseded_by_fact_hash: dict[str, str] = {}
            superseded_refs_by_fact_hash: dict[str, list[str]] = {}
            new_facts: list[tuple[dict, str]] = []
            seen_new_hashes: set[str] = set()
            seen_new_semantics: dict[str, dict] = {}
            for fact in facts:
                fact_hash = str(fact.get("fact_hash"))
                if fact_hash in seen_new_hashes:
                    deduplicated_ids.append(fact_hash)
                    continue
                seen_new_hashes.add(fact_hash)
                old_exact = exact_by_hash.get(fact_hash)
                if old_exact:
                    deduplicated_ids.append(old_exact.get("record_id"))
                    continue
                semantic_hash = str(fact.get("semantic_hash") or "")
                old_semantic = semantic_by_hash.get(semantic_hash)
                if old_semantic:
                    old_record_id = str(old_semantic.get("record_id"))
                    superseded_ids.append(old_record_id)
                    superseded_by_fact_hash[old_record_id] = fact_hash
                    superseded_refs_by_fact_hash.setdefault(fact_hash, []).extend(
                        [old_record_id, str(old_semantic.get("fact_hash") or "")]
                    )
                conflict_key = str(fact.get("conflict_key") or "")
                old_conflict = conflict_by_key.get(conflict_key) if conflict_key else None
                conflict_target = old_conflict
                if not conflict_target and conflict_key:
                    conflict_target = seen_new_semantics.get(conflict_key)
                if conflict_target and str(conflict_target.get("semantic_hash")) != semantic_hash:
                    target_id = str(conflict_target.get("record_id") or conflict_target.get("fact_hash") or "")
                    explicitly_authorized = authority_change_approved and (
                        target_id in supersede_refs
                        or str(conflict_target.get("fact_hash")) in supersede_refs
                    )
                    if not explicitly_authorized:
                        return {
                            "promotion_status": "PROMOTION_CONFLICT", "status": "PROMOTION_CONFLICT",
                            "no_op": True, "candidate": copy.deepcopy(candidate),
                            "project_brain_before_hash": before_hash,
                            "project_brain_after_hash": before_hash,
                            "conflict_record_ids": [target_id], "model_calls": 0,
                        }
                    if target_id not in superseded_ids:
                        superseded_ids.append(target_id)
                    superseded_by_fact_hash[target_id] = fact_hash
                    superseded_refs_by_fact_hash.setdefault(fact_hash, []).extend(
                        [target_id, str(conflict_target.get("fact_hash") or "")]
                    )
                if conflict_key:
                    seen_new_semantics[conflict_key] = {
                        "semantic_hash": semantic_hash,
                        "fact_hash": fact_hash,
                        "record_id": "",
                    }
                new_facts.append((fact, fact_hash))

            # Resolve the record ids before changing any row so a conflict
            # always leaves the database untouched.
            record_specs: list[tuple[dict, str, str]] = []
            for fact, fact_hash in new_facts:
                record_id = f"verified-{self._canonical_hash(project)[:10]}-{fact_hash[:24]}"
                record_specs.append((fact, fact_hash, record_id))
            record_by_fact_hash = {fact_hash: record_id for _fact, fact_hash, record_id in record_specs}
            for fact, fact_hash, record_id in record_specs:
                conflict_key = str(fact.get("conflict_key") or "")
                if conflict_key and conflict_key in seen_new_semantics:
                    seen_new_semantics[conflict_key]["record_id"] = record_id
            superseded_ids = list(dict.fromkeys(
                item for item in superseded_ids if item and item not in deduplicated_ids
            ))
            for record_id in superseded_ids:
                superseded_by = record_by_fact_hash.get(
                    superseded_by_fact_hash.get(record_id, ""),
                )
                if superseded_by is None:
                    superseded_by = record_specs[0][2] if record_specs else None
                connection.execute(
                    """UPDATE project_brain_facts
                       SET status = 'SUPERSEDED', superseded_by = ?, updated_at = ?
                       WHERE project_id = ? AND record_id = ? AND status = 'ACTIVE'""",
                    (superseded_by, now, project, record_id),
                )
            inserted_ids: list[str] = []
            for fact, fact_hash, record_id in record_specs:
                supersede_refs = [
                    str(item) for item in (fact.get("supersedes", []) or [])
                    if str(item).strip()
                ]
                supersede_refs.extend(
                    str(item) for item in (candidate.get("supersedes", []) or [])
                    if str(item).strip()
                )
                supersede_refs.extend(superseded_refs_by_fact_hash.get(fact_hash, []))
                supersede_refs = list(dict.fromkeys(supersede_refs))[:24]
                connection.execute(
                    """INSERT INTO project_brain_facts(
                           record_id, project_id, fact_hash, semantic_hash, conflict_key,
                           fact_json, durability_class, subject_state_hash, status,
                           supersedes_json, superseded_by, provenance_json, created_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, NULL, ?, ?, ?)""",
                    (
                        record_id, project, fact_hash, str(fact.get("semantic_hash") or ""),
                        str(fact.get("conflict_key") or ""), _json(fact),
                        str(fact.get("durability_class") or "STATE_BOUND_VERIFIED"),
                        str(fact.get("subject_state_hash") or candidate.get("subject_state_hash") or ""),
                        _json(supersede_refs),
                        _json(candidate.get("provenance", {})), now, now,
                    ),
                )
                inserted_ids.append(record_id)
            after_records = self._records_from_connection(connection, project, include_inactive=True)
            after_snapshot = {"project_id": project, "records": after_records}
            after_hash = self._canonical_hash(after_snapshot)
            receipt: dict[str, Any] = {
                "schema_version": PROMOTION_SCHEMA_VERSION,
                "artifact_type": "PromotionReceipt",
                "promotion_id": f"promotion-{candidate_hash[:24]}",
                "project_id": project,
                "candidate_hash": candidate_hash,
                "parent_verification_hash": (candidate.get("source") or {}).get("parent_verification_hash"),
                "subject_state_hash": candidate.get("subject_state_hash"),
                "project_brain_before_hash": before_hash,
                "project_brain_after_hash": after_hash,
                "promoted_record_ids": inserted_ids,
                "deduplicated_record_ids": deduplicated_ids,
                "superseded_record_ids": superseded_ids,
                "eligibility_status": "PROMOTION_ELIGIBLE",
                "promotion_status": "PROMOTED",
                "provenance": {
                    "source": "deterministic_verified_state_promotion",
                    "model_calls": 0, "raw_worker_transcript_included": False,
                    "authority_escalation": False, "cross_project_memory": False,
                    "strategy_learning": False, "auto_reverification": False,
                },
            }
            receipt["promotion_hash"] = self._canonical_hash(receipt)
            completion = None
            if isinstance(task_completion, dict) and task_completion.get("task_id"):
                completion = {
                    "schema_version": PROMOTION_SCHEMA_VERSION,
                    "task_id": str(task_completion["task_id"]),
                    "terminal_state": "VERIFIED_AND_PROMOTED",
                    "parent_verification_hash": receipt.get("parent_verification_hash"),
                    "promotion_hash": receipt.get("promotion_hash"),
                    "subject_state_hash": receipt.get("subject_state_hash"),
                    "artifact_refs": list(task_completion.get("artifact_refs", []) or [])[:24],
                    "project_brain_record_ids": inserted_ids[:256],
                }
                completion["completion_hash"] = self._canonical_hash(completion)
                connection.execute(
                    """INSERT INTO task_brain_completions(
                           project_id, task_id, completion_hash, completion_json, created_at, updated_at
                       ) VALUES(?, ?, ?, ?, ?, ?)
                       ON CONFLICT(project_id, task_id) DO UPDATE SET
                           completion_hash=excluded.completion_hash,
                           completion_json=excluded.completion_json,
                           updated_at=excluded.updated_at""",
                    (project, completion["task_id"], completion["completion_hash"], _json(completion), now, now),
                )
                # Keep the receipt hash independent of the pointer hash.  The
                # pointer already carries the promotion hash, and including
                # its own hash in the receipt would create a circular identity.
            connection.execute(
                """INSERT INTO promotions(
                       promotion_id, project_id, candidate_hash, promotion_hash,
                       status, receipt_json, created_at
                   ) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt["promotion_id"], project, candidate_hash,
                    receipt["promotion_hash"], "PROMOTED", _json(receipt), now,
                ),
            )
            return {
                "promotion_status": "PROMOTED", "status": "PROMOTED", "no_op": False,
                "candidate": copy.deepcopy(candidate), "promotion_receipt": receipt,
                "project_brain_before_hash": before_hash,
                "project_brain_after_hash": after_hash,
                "project_brain_records": after_records,
                "task_brain_completion": completion, "model_calls": 0,
                "promoted_record_ids": inserted_ids,
                "deduplicated_record_ids": deduplicated_ids,
                "superseded_record_ids": superseded_ids,
            }

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

    def context_for(
        self, query: str, *, max_items: int = 6, max_chars: int = 2400,
        project_id: str = "default",
    ) -> str:
        if max_chars <= 0:
            return ""
        notes = self.retrieve(query, max_items=max_items, verified_only=True)
        facts = self.retrieve_verified_project_facts(
            query, project_id=project_id, max_items=max_items,
        )
        if not notes and not facts:
            return ""
        heading = "VERIFIED LONG-TERM PROJECT MEMORY (relevant excerpts only):\n"
        output = heading
        # Project Brain facts are structured and bounded.  Only the fact
        # projection is rendered; timestamps and persistence internals never
        # enter a Worker prompt.
        for record in facts:
            fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
            line = "- [verified_project_fact] " + _json({
                "record_id": record.get("record_id"),
                "category": fact.get("category"),
                "field": fact.get("field"),
                "fact": fact.get("fact"),
                "authority": fact.get("authority"),
                "durability_class": record.get("durability_class"),
                "subject_state_hash": record.get("subject_state_hash"),
            }) + "\n"
            if len(output) + len(line) > max_chars:
                remaining = max_chars - len(output)
                if remaining > 20:
                    output += line[:remaining]
                break
            output += line
        for note in notes:
            line = f"- [{note['kind']}/{note['scope']}] {note['content']}\n"
            if len(output) + len(line) > max_chars:
                remaining = max_chars - len(output)
                if remaining > 20:
                    output += line[:remaining]
                break
            output += line
        return output[:max_chars].rstrip()
