"""Durable lifecycle for the host-owned, headless job engine."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import uuid
from collections.abc import Iterable
from contextlib import closing, contextmanager
from types import MappingProxyType


DEFAULT_LIMITS = MappingProxyType(
    dict(max_model_calls=18, max_tool_calls=25, max_elapsed_seconds=120, max_attempts=4)
)
_LIMIT_CEILINGS = dict(
    max_model_calls=10_000, max_tool_calls=10_000, max_elapsed_seconds=86_400, max_attempts=100
)
_BUDGET = (
    ("model_left", "max_model_calls", "model_calls"),
    ("tool_left", "max_tool_calls", "tool_calls"),
    ("seconds_left", "max_elapsed_seconds", "elapsed_seconds"),
)
_WAITING = {"waiting_clarification", "waiting_approval"}
_OUTCOMES = _WAITING | {"verified", "failed", "blocked", "cancelled", "timed_out", "interrupted"}
_RETRYABLE = {"failed", "blocked", "interrupted"}
_GIT_ID = re.compile(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})")
_FAILURE_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY NOT NULL,
        project_id TEXT NOT NULL,
        base_revision TEXT NOT NULL,
        prompt TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
            'queued', 'running', 'waiting_clarification', 'waiting_approval',
            'cancelling', 'verified', 'failed', 'blocked', 'cancelled',
            'timed_out', 'rejected', 'interrupted'
        )),
        attempt_id TEXT UNIQUE,
        slot INTEGER UNIQUE CHECK (slot IN (1, 2)),
        checkpoint TEXT,
        decision_request TEXT,
        decision TEXT,
        limits TEXT NOT NULL,
        failure_code TEXT,
        result TEXT,
        model_left INTEGER NOT NULL CHECK (model_left >= 0),
        tool_left INTEGER NOT NULL CHECK (tool_left >= 0),
        seconds_left REAL NOT NULL CHECK (seconds_left >= 0),
        attempts_left INTEGER NOT NULL CHECK (attempts_left >= 0),
        attempt_accounted INTEGER NOT NULL DEFAULT 0 CHECK (attempt_accounted IN (0, 1)),
        UNIQUE (project_id, idempotency_key),
        CHECK (slot IS NULL OR (
            attempt_id IS NOT NULL AND status IN ('running', 'cancelling', 'interrupted')
        )),
        CHECK (status NOT IN ('running', 'cancelling') OR slot IS NOT NULL),
        CHECK ((status = 'verified') = (result IS NOT NULL))
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS one_active_attempt_per_project
        ON jobs (project_id) WHERE slot IS NOT NULL""",
    """CREATE TABLE IF NOT EXISTS job_events (
        seq INTEGER PRIMARY KEY,
        job_id TEXT NOT NULL REFERENCES jobs (job_id),
        status TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS events_for_job ON job_events (job_id, seq)",
    """CREATE TABLE IF NOT EXISTS job_decisions (
        job_id TEXT NOT NULL REFERENCES jobs (job_id),
        decision_id TEXT NOT NULL,
        decision TEXT,
        PRIMARY KEY (job_id, decision_id)
    )""",
)


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    return value


def _object(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _encode(value: dict) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid JSON document") from exc


def _limits(overrides) -> dict:
    limits = dict(DEFAULT_LIMITS)
    if overrides is not None:
        updates = _object(overrides, "limits")
        if updates.keys() - limits.keys():
            raise ValueError("unknown job limit")
        limits.update(updates)
    for key, value in limits.items():
        allowed_types = (int, float) if key == "max_elapsed_seconds" else (int,)
        if type(value) not in allowed_types or not 0 < value <= _LIMIT_CEILINGS[key]:
            raise ValueError(f"{key} must be positive and bounded")
    if limits["max_elapsed_seconds"] == int(limits["max_elapsed_seconds"]):
        limits["max_elapsed_seconds"] = int(limits["max_elapsed_seconds"])
    return limits


def _request(value, status: str) -> dict:
    request = _object(value, "decision request")
    kind = status.removeprefix("waiting_")
    if request.get("kind") != kind:
        raise ValueError("decision request does not match the waiting state")
    decision_id = _text(request.get("decision_id"), "decision id")
    public = {"decision_id": decision_id, "kind": kind}
    if kind == "approval":
        public["plan_hash"] = _text(request.get("plan_hash"), "plan hash")
        public["plan_summary"] = _text(request.get("plan_summary"), "plan summary")
    else:
        questions = request.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError("clarification requires questions")
        ids = set()
        public["questions"] = []
        for item in questions:
            question = _object(item, "question")
            question_id = _text(question.get("question_id"), "question id")
            if question_id in ids:
                raise ValueError("duplicate clarification question id")
            ids.add(question_id)
            public["questions"].append({
                "question_id": question_id,
                "question": _text(question.get("question"), "question text"),
            })
    return public


def _decision(value) -> dict:
    decision = _object(value, "decision")
    kind = decision.get("kind")
    if kind not in ("answer", "approve", "reject"):
        raise ValueError("unsupported decision kind")
    if decision.keys() - {"decision_id", "kind", "actor_id", "answers", "plan_hash"}:
        raise ValueError("unknown decision field")
    canonical = {
        "decision_id": _text(decision.get("decision_id"), "decision id"),
        "kind": kind,
        "actor_id": _text(decision.get("actor_id"), "actor id"),
    }
    if kind == "answer":
        if decision.get("plan_hash") is not None:
            raise ValueError("answers cannot approve a plan")
        canonical["answers"] = {
            _text(key, "question id"): _text(answer, "answer")
            for key, answer in _object(decision.get("answers"), "answers").items()
        }
    else:
        if decision.get("answers") not in (None, {}):
            raise ValueError("plan decisions cannot answer clarification questions")
        canonical["plan_hash"] = _text(decision.get("plan_hash"), "plan hash")
    return canonical


def _charge(row: sqlite3.Row, usage, *, allow_unknown: bool = False) -> dict:
    if usage is None and allow_unknown:
        # A lost attempt could have used its entire allowance before losing its receipt.
        return {column: 0 for column, _, _ in _BUDGET}
    measured = _object(usage, "usage")
    remaining = {}
    for column, _, meter in _BUDGET:
        value = measured.get(meter)
        if meter == "elapsed_seconds":
            valid = type(value) is int or (type(value) is float and math.isfinite(value))
        else:
            valid = type(value) is int
        if not valid or value < 0:
            raise ValueError(f"invalid {meter} usage")
        remaining[column] = row[column] - value if value < row[column] else 0
    return remaining


def _has_budget(row) -> bool:
    return row["attempts_left"] > 0 and all(row[column] > 0 for column, _, _ in _BUDGET)


def _projection(row: sqlite3.Row, *, limits: dict | None = None) -> dict:
    job = {
        key: row[key]
        for key in ("job_id", "project_id", "base_revision", "prompt", "idempotency_key",
                    "status", "attempt_id", "failure_code")
    }
    for key in ("checkpoint", "decision_request", "decision", "result"):
        job[key] = None if row[key] is None else json.loads(row[key])
    job["limits"] = json.loads(row["limits"]) if limits is None else limits
    return job


class JobStore:
    """Use one real SQLite connection per call; writes and events commit together.

    Only the trusted host may supply stop proofs or a verified result. An
    interrupted attempt fences publication but keeps its slot until reconciled.
    """

    def __init__(self, db_path):
        path = os.fspath(db_path)
        if path in ("", ":memory:"):
            raise ValueError("JobStore requires a durable SQLite path")
        self._path = os.path.abspath(path)
        with self._connection(write=True) as db:
            for statement in _SCHEMA:
                db.execute(statement)

    @contextmanager
    def _connection(self, *, write: bool = False):
        with closing(sqlite3.connect(self._path, isolation_level=None, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            if write:
                db.execute("PRAGMA synchronous = FULL")
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    yield db
            else:
                yield db

    @staticmethod
    def _fetch(db, job_id) -> sqlite3.Row:
        if not isinstance(job_id, str):
            raise KeyError(job_id)
        row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    @staticmethod
    def _record(db, job_id, status):
        db.execute("INSERT INTO job_events (job_id, status) VALUES (?, ?)", (job_id, status))

    def _transition(self, db, job_id: str, status: str, **fields) -> sqlite3.Row:
        # Column names come only from the fixed transition code below.
        fields["status"] = status
        assignments = ", ".join(f"{key} = ?" for key in fields)
        db.execute(f"UPDATE jobs SET {assignments} WHERE job_id = ?", (*fields.values(), job_id))
        self._record(db, job_id, status)
        return self._fetch(db, job_id)

    def submit(self, spec: dict) -> dict:
        spec = _object(spec, "job spec")
        if spec.keys() - {"project_id", "base_revision", "prompt", "idempotency_key", "limits"}:
            raise ValueError("unknown job specification field")
        project_id = _text(spec.get("project_id"), "project id")
        idempotency_key = _text(spec.get("idempotency_key"), "idempotency key")
        prompt = _text(spec.get("prompt"), "prompt")
        revision = spec.get("base_revision")
        if not isinstance(revision, str) or not _GIT_ID.fullmatch(revision):
            raise ValueError("base revision must be a full Git object id")
        revision = revision.lower()
        limits = _limits(spec.get("limits"))
        with self._connection(write=True) as db:
            existing = db.execute(
                "SELECT * FROM jobs WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (prompt != existing["prompt"] or revision != existing["base_revision"]
                        or limits != json.loads(existing["limits"])):
                    raise ValueError("idempotency key already belongs to a different submission")
                return _projection(existing)
            job_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO jobs (
                    job_id, project_id, base_revision, prompt, idempotency_key, status,
                    limits, model_left, tool_left, seconds_left, attempts_left
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (job_id, project_id, revision, prompt, idempotency_key, _encode(limits),
                 *(limits[key] for _, key, _ in _BUDGET), limits["max_attempts"]),
            )
            self._record(db, job_id, "queued")
            return _projection(self._fetch(db, job_id))

    def get(self, job_id) -> dict:
        with self._connection() as db:
            return _projection(self._fetch(db, job_id))

    def events(self, job_id, after=0) -> list:
        if type(after) is not int or after < 0:
            raise ValueError("event cursor must be a nonnegative integer")
        with self._connection() as db:
            self._fetch(db, job_id)
            return [dict(row) for row in db.execute(
                "SELECT seq, status FROM job_events WHERE job_id = ? AND seq > ? ORDER BY seq",
                (job_id, min(after, 2**63 - 1)),
            )]

    def active_attempts(self) -> list[dict]:
        """Minimal host-only listing of attempts whose slots are still reserved."""
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT job_id, attempt_id, status FROM jobs WHERE slot IS NOT NULL ORDER BY slot"
            )]

    def claim(self) -> dict | None:
        """Atomically reserve a slot and return a worker payload with remaining limits."""
        with self._connection(write=True) as db:
            slots = {row["slot"] for row in db.execute("SELECT slot FROM jobs WHERE slot IS NOT NULL")}
            slot = next((candidate for candidate in (1, 2) if candidate not in slots), None)
            if slot is None:
                return None
            row = db.execute(
                """SELECT queued.* FROM jobs AS queued
                   WHERE queued.status = 'queued' AND NOT EXISTS (
                       SELECT 1 FROM jobs AS active
                       WHERE active.slot IS NOT NULL AND active.project_id = queued.project_id
                   )
                   ORDER BY queued.rowid LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            allowance = {limit: row[column] for column, limit, _ in _BUDGET}
            allowance["max_attempts"] = row["attempts_left"]
            return _projection(
                self._transition(
                    db, row["job_id"], "running", attempt_id=uuid.uuid4().hex, slot=slot,
                    attempts_left=row["attempts_left"] - 1, attempt_accounted=0,
                ), limits=allowance,
            )

    def decide(self, job_id, decision: dict) -> dict:
        with self._connection(write=True) as db:
            row = self._fetch(db, job_id)
            decision = _decision(decision)
            decision_id = decision["decision_id"]
            serialized = _encode(decision)
            prior = db.execute(
                "SELECT decision FROM job_decisions WHERE job_id = ? AND decision_id = ?",
                (job_id, decision_id),
            ).fetchone()
            if prior is not None and prior["decision"] is not None:
                if prior["decision"] != serialized:
                    raise ValueError("decision was already bound to different inputs")
                return _projection(row)
            status = row["status"]
            if prior is None or status not in _WAITING:
                raise ValueError("no matching pending decision")
            request = json.loads(row["decision_request"])
            if decision_id != request["decision_id"]:
                raise ValueError("decision id is stale")
            kind = decision["kind"]
            if status == "waiting_clarification":
                if (kind != "answer" or decision["answers"].keys()
                        != {item["question_id"] for item in request["questions"]}):
                    raise ValueError("answer must match the pending questions exactly")
            elif kind not in ("approve", "reject") or decision["plan_hash"] != request["plan_hash"]:
                raise ValueError("decision must match the pending plan exactly")
            db.execute(
                "UPDATE job_decisions SET decision = ? WHERE job_id = ? AND decision_id = ?",
                (serialized, job_id, decision_id),
            )
            if kind == "reject":
                return _projection(self._transition(db, job_id, "rejected", decision=serialized))
            return _projection(self._transition(
                db, job_id, "queued", decision=serialized, attempt_id=None,
            ))

    def cancel(self, job_id) -> dict:
        with self._connection(write=True) as db:
            row = self._fetch(db, job_id)
            status = row["status"]
            if status in ("cancelling", "cancelled"):
                return _projection(row)
            if status not in _WAITING | {"queued", "running", "interrupted"}:
                raise ValueError("job cannot be cancelled in its current state")
            return _projection(self._transition(
                db, job_id, "cancelling" if row["slot"] is not None else "cancelled",
                failure_code=None,
            ))

    def finish(self, job_id, attempt_id, outcome: dict) -> dict:
        with self._connection(write=True) as db:
            row = self._fetch(db, job_id)
            if attempt_id is None or row["attempt_id"] != attempt_id or row["status"] not in (
                "running", "cancelling"
            ):
                raise ValueError("attempt is no longer authorized to finish")
            outcome = _object(outcome, "attempt outcome")
            status = outcome.get("status")
            if not isinstance(status, str) or status not in _OUTCOMES:
                raise ValueError("unsupported attempt outcome")
            failure_code = outcome.get("failure_code")
            if failure_code is not None and (
                not isinstance(failure_code, str) or not _FAILURE_CODE.fullmatch(failure_code)
            ):
                raise ValueError("invalid failure code")
            usage = outcome.get("usage")
            cancelling = row["status"] == "cancelling"
            if row["attempt_accounted"]:
                if not cancelling or status == "interrupted":
                    raise ValueError("attempt is already fenced pending stop")
                # The stopped receipt resolves cancellation, not a second charge.
                _charge(row, usage)
                return _projection(self._transition(
                    db, job_id, "cancelled", slot=None, failure_code=None,
                ))
            fields = _charge(row, usage, allow_unknown=status == "interrupted")
            fields["attempt_accounted"] = 1
            if status == "interrupted":
                return _projection(self._transition(
                    db, job_id, "cancelling" if cancelling else status, failure_code=failure_code, **fields,
                ))
            fields["slot"] = None
            if cancelling:
                return _projection(self._transition(
                    db, job_id, "cancelled", failure_code=None, **fields,
                ))
            if outcome.get("result") is not None and status != "verified":
                raise ValueError("only trusted verified outcomes may carry a result")
            approved = row["decision"] is not None and json.loads(row["decision"])["kind"] == "approve"
            if status == "verified":
                result = _object(outcome.get("result"), "verified result")
                if not approved or result.get("base_revision") != row["base_revision"]:
                    raise ValueError("verified result must match an approved job and base revision")
            elif status in _WAITING:
                if approved:
                    raise ValueError("an accepted plan cannot be replaced by a new decision request")
                checkpoint = _encode(_object(outcome.get("checkpoint"), "checkpoint"))
                request = _request(outcome.get("decision_request"), status)
            overspent = any(usage[meter] > row[column] for column, _, meter in _BUDGET)
            cannot_resume = status in _WAITING and not _has_budget(
                dict(fields, attempts_left=row["attempts_left"])
            )
            if status in _WAITING | {"verified"} and (overspent or cannot_resume):
                return _projection(self._transition(
                    db, job_id, "timed_out", failure_code="budget_exhausted", **fields,
                ))
            if status in _WAITING:
                if db.execute(
                    "SELECT 1 FROM job_decisions WHERE job_id = ? AND decision_id = ?",
                    (job_id, request["decision_id"]),
                ).fetchone() is not None:
                    raise ValueError("decision request id was already used for this job")
                db.execute(
                    "INSERT INTO job_decisions (job_id, decision_id) VALUES (?, ?)",
                    (job_id, request["decision_id"]),
                )
                fields.update(checkpoint=checkpoint, decision_request=_encode(request), decision=None)
                failure_code = None
            elif status == "verified":
                fields["result"] = _encode(result)
                failure_code = None
            return _projection(self._transition(db, job_id, status, failure_code=failure_code, **fields))

    def recover(self, stopped_attempt_ids: Iterable[str]) -> list[dict]:
        """Reconcile only exact attempt IDs for which the runtime proved death."""
        if not isinstance(stopped_attempt_ids, Iterable) or isinstance(stopped_attempt_ids, (str, bytes)):
            raise ValueError("stop proofs must be an iterable of attempt ids")
        stopped = {_text(attempt_id, "attempt id") for attempt_id in stopped_attempt_ids}
        recovered = []
        with self._connection(write=True) as db:
            for row in db.execute("SELECT * FROM jobs WHERE slot IS NOT NULL ORDER BY slot").fetchall():
                if row["attempt_id"] not in stopped:
                    continue
                fields = {"slot": None}
                if not row["attempt_accounted"]:
                    fields.update(_charge(row, None, allow_unknown=True))
                    fields["attempt_accounted"] = 1
                status = "cancelled" if row["status"] == "cancelling" else "interrupted"
                code = None if status == "cancelled" else row["failure_code"] or "attempt_interrupted"
                recovered.append(_projection(self._transition(
                    db, row["job_id"], status, failure_code=code, **fields,
                )))
        return recovered

    def retry(self, job_id) -> dict:
        with self._connection(write=True) as db:
            row = self._fetch(db, job_id)
            if row["status"] not in _RETRYABLE or row["slot"] is not None:
                raise ValueError("job is not retryable while active or in this state")
            if not _has_budget(row):
                raise ValueError("job has no remaining retry budget")
            return _projection(self._transition(
                db, job_id, "queued", attempt_id=None, failure_code=None,
            ))
