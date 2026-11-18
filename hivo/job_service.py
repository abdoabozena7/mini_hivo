"""Version 1 of the internal callable Mini Hivo job API."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from .job_runtime import DockerJobRuntime
    from .job_store import JobStore


JOB_API_VERSION = 1
JobStatus = Literal[
    "queued", "running", "waiting_clarification", "waiting_approval",
    "cancelling", "interrupted", "verified", "failed", "blocked",
    "cancelled", "timed_out", "rejected",
]


class JobLimits(TypedDict):
    max_model_calls: int
    max_tool_calls: int
    max_elapsed_seconds: int | float
    max_attempts: int


class Question(TypedDict):
    question_id: str
    question: str


class ClarificationRequest(TypedDict):
    decision_id: str
    kind: Literal["clarification"]
    questions: list[Question]


class ApprovalRequest(TypedDict):
    decision_id: str
    kind: Literal["approval"]
    plan_summary: str
    plan_hash: str


class JobView(TypedDict):
    job_id: str
    project_id: str
    base_revision: str
    status: JobStatus
    limits: JobLimits
    decision_request: ClarificationRequest | ApprovalRequest | None
    failure_code: str | None


class JobEvent(TypedDict):
    seq: int
    status: JobStatus


class BehaviorCheck(TypedDict):
    check_id: str
    passed: bool


class JobResult(TypedDict):
    diff: str
    base_revision: str
    changed_paths: list[str]
    patch_sha256: str
    workspace_sha256: str
    checks: list[BehaviorCheck]


_REVISION = re.compile(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})")
_FAILURE_CODE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_WAITING = {"waiting_clarification", "waiting_approval"}
_RUNTIME_STATES = _WAITING | {"failed", "blocked", "cancelled", "timed_out", "interrupted"}
_NO_USAGE = {"model_calls": 0, "tool_calls": 0, "elapsed_seconds": 0}


def _failure_code(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _FAILURE_CODE.fullmatch(value):
        return value
    return "invalid_failure_code"


def _decision_request(job: dict[str, Any]) -> ClarificationRequest | ApprovalRequest | None:
    request = job.get("decision_request")
    if not isinstance(request, dict):
        return None
    if job["status"] == "waiting_clarification" and request["kind"] == "clarification":
        return {
            "decision_id": request["decision_id"],
            "kind": "clarification",
            "questions": [
                {"question_id": question["question_id"], "question": question["question"]}
                for question in request["questions"]
            ],
        }
    if job["status"] == "waiting_approval" and request["kind"] == "approval":
        return {
            "decision_id": request["decision_id"],
            "kind": "approval",
            "plan_summary": request["plan_summary"],
            "plan_hash": request["plan_hash"],
        }
    return None


def _view(job: dict[str, Any]) -> JobView:
    limits = job["limits"]
    return {
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "base_revision": job["base_revision"],
        "status": job["status"],
        "limits": {
            "max_model_calls": limits["max_model_calls"],
            "max_tool_calls": limits["max_tool_calls"],
            "max_elapsed_seconds": limits["max_elapsed_seconds"],
            "max_attempts": limits["max_attempts"],
        },
        "decision_request": _decision_request(job),
        "failure_code": _failure_code(job.get("failure_code")),
    }


def _result(value: dict[str, Any]) -> JobResult:
    return {
        "diff": value["diff"],
        "base_revision": value["base_revision"],
        "changed_paths": list(value["changed_paths"]),
        "patch_sha256": value["patch_sha256"],
        "workspace_sha256": value["workspace_sha256"],
        "checks": [
            {"check_id": check["check_id"], "passed": check["passed"]} for check in value["checks"]
        ],
    }


def _verify_candidate(job, base_dir, work_dir, outcome, checker):
    from .job_result import verify_candidate

    return verify_candidate(job, base_dir, work_dir, outcome, checker)


def _required_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


class JobService:
    """Host-composed API; the caller authenticates actor identities.

    The registry, store, runtime and checker are host-owned. Each project ID
    must name a distinct canonical repository path. A checker that executes
    candidate code must use the runtime's isolated ``check`` method.
    """

    api_version = JOB_API_VERSION

    def __init__(
        self,
        store: JobStore,
        runtime: DockerJobRuntime,
        projects: Mapping[str, Path],
        checker: Callable[[dict[str, Any], Path], list[BehaviorCheck]],
        *,
        authorize_decision: Callable[[str, str], bool],
    ) -> None:
        if not callable(checker) or not callable(authorize_decision):
            raise TypeError("checker and authorize_decision must be callable")
        self._store = store
        self._runtime = runtime
        self._projects: dict[str, Path] = {}
        registered_paths: set[Path] = set()
        registered_identities: set[tuple[int, int]] = set()
        for project_id, path in projects.items():
            canonical = Path(path).resolve(strict=False)
            # Verbatim Windows paths can keep distinct spellings after resolve().
            identity = None
            try:
                info = canonical.stat()
            except FileNotFoundError:
                pass
            else:
                if info.st_ino:
                    identity = (info.st_dev, info.st_ino)
            if canonical in registered_paths or (
                identity is not None and identity in registered_identities
            ):
                raise ValueError("project registry contains a duplicate repository path")
            registered_paths.add(canonical)
            if identity is not None:
                registered_identities.add(identity)
            self._projects[project_id] = canonical
        self._checker = checker
        self._authorize_decision = authorize_decision
        self._dispatch_lock = Lock()
        self._dispatching: set[str] = set()

    def submit(
        self,
        project_id: str,
        *,
        base_revision: str,
        prompt: str,
        idempotency_key: str,
        limits: Mapping[str, int | float] | None = None,
    ) -> JobView:
        if not isinstance(project_id, str) or project_id not in self._projects:
            raise KeyError("project is not registered")
        if not isinstance(base_revision, str) or not _REVISION.fullmatch(base_revision):
            raise ValueError("base_revision must be a full Git object ID")
        _required_text(prompt, "prompt")
        _required_text(idempotency_key, "idempotency_key")
        if limits is not None and not isinstance(limits, Mapping):
            raise ValueError("limits must be a mapping")
        return _view(self._store.submit({
            "project_id": project_id,
            "base_revision": base_revision,
            "prompt": prompt,
            "idempotency_key": idempotency_key,
            "limits": dict(limits) if limits is not None else {},
        }))

    def status(self, job_id: str) -> JobView:
        return _view(self._store.get(job_id))

    def events(self, job_id: str, after: int = 0) -> list[JobEvent]:
        if type(after) is not int or after < 0:
            raise ValueError("after must be a nonnegative event sequence")
        return [
            {"seq": event["seq"], "status": event["status"]}
            for event in self._store.events(job_id, after=after)
        ]

    def _authorize(self, job_id: str, actor_id: str) -> None:
        job = self._store.get(job_id)
        try:
            if isinstance(actor_id, str) and actor_id.strip():
                if self._authorize_decision(job["project_id"], actor_id) is True:
                    return
        except Exception:
            raise PermissionError("actor not authorized for this project") from None
        raise PermissionError("actor not authorized for this project")

    def answer(
        self, job_id: str, *, decision_id: str, answers: Mapping[str, str], actor_id: str
    ) -> JobView:
        self._authorize(job_id, actor_id)
        _required_text(decision_id, "decision_id")
        if not isinstance(answers, Mapping) or not answers:
            raise ValueError("answers must be a nonempty question-to-answer mapping")
        answers = dict(answers)
        for question_id, answer in answers.items():
            _required_text(question_id, "question_id")
            _required_text(answer, "answer")
            if "\0" in answer or len(answer) > 700:
                raise ValueError("answer must be at most 700 characters with no NUL")
        return _view(self._store.decide(job_id, {
            "decision_id": decision_id,
            "kind": "answer",
            "actor_id": actor_id,
            "answers": answers,
        }))

    def _plan_decision(
        self, job_id: str, decision_id: str, plan_hash: str, actor_id: str, kind: str
    ) -> JobView:
        self._authorize(job_id, actor_id)
        _required_text(decision_id, "decision_id")
        _required_text(plan_hash, "plan_hash")
        return _view(self._store.decide(job_id, {
            "decision_id": decision_id,
            "kind": kind,
            "actor_id": actor_id,
            "answers": {},
            "plan_hash": plan_hash,
        }))

    def approve(self, job_id: str, *, decision_id: str, plan_hash: str, actor_id: str) -> JobView:
        return self._plan_decision(job_id, decision_id, plan_hash, actor_id, "approve")

    def reject(self, job_id: str, *, decision_id: str, plan_hash: str, actor_id: str) -> JobView:
        return self._plan_decision(job_id, decision_id, plan_hash, actor_id, "reject")

    def cancel(self, job_id: str) -> JobView:
        job = self._store.cancel(job_id)
        if job["status"] != "cancelling":
            return _view(job)
        attempt_id = job["attempt_id"]
        try:
            stopped = self._runtime.cancel(attempt_id) is True
        except Exception:
            stopped = False
        if stopped:
            with self._dispatch_lock:
                # The local dispatcher can still be draining finalization.
                if attempt_id not in self._dispatching:
                    self._store.recover([attempt_id])
        return self.status(job_id)

    def result(self, job_id: str) -> JobResult | None:
        job = self._store.get(job_id)
        if job["status"] != "verified" or job.get("result") is None:
            return None
        return _result(job["result"])

    def retry(self, job_id: str) -> JobView:
        return _view(self._store.retry(job_id))

    def recover(self) -> list[JobView]:
        """Settle only externally confirmed stops, never a dispatch we still own."""
        with self._dispatch_lock:
            attempts = [
                row["attempt_id"] for row in self._store.active_attempts()
                if row["attempt_id"] not in self._dispatching
            ]
        confirmed = []
        for attempt_id in attempts:
            try:
                if self._runtime.stopped(attempt_id) is True:
                    confirmed.append(attempt_id)
            except Exception:
                continue
        return [_view(job) for job in self._store.recover(confirmed)]

    def _finish(self, job_id: str, attempt_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._store.finish(job_id, attempt_id, outcome)
        except ValueError:
            current = self._store.get(job_id)
            if current["attempt_id"] != attempt_id or current["status"] not in {"running", "cancelling"}:
                return current
            if outcome["status"] == "interrupted":
                raise
            # A malformed report cannot release a slot or manufacture a budget refund.
            return self._finish(job_id, attempt_id, {
                "status": "interrupted", "failure_code": "invalid_runtime_outcome",
            })

    def _run_claimed(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id, attempt_id = job["job_id"], job["attempt_id"]
        current = self._store.get(job_id)
        if current["attempt_id"] != attempt_id:
            return current
        if current["status"] == "cancelling":
            return self._finish(job_id, attempt_id, {
                "status": "cancelled", "usage": dict(_NO_USAGE),
            })
        if current["status"] != "running":
            return current
        repository = self._projects.get(job["project_id"])
        if repository is None:
            return self._finish(job_id, attempt_id, {
                "status": "blocked", "failure_code": "project_not_registered", "usage": dict(_NO_USAGE),
            })

        receipt: JobResult | None = None
        finalized = False

        def still_running() -> bool:
            active = self._store.get(job_id)
            return active["status"] == "running" and active["attempt_id"] == attempt_id

        def finalize(base_dir: Path, work_dir: Path, candidate: dict[str, Any]) -> JobResult:
            nonlocal receipt, finalized
            try:
                if finalized:
                    raise ValueError
                finalized = True
                if (
                    (job.get("decision") or {}).get("kind") != "approve"
                    or candidate.get("status") != "candidate"
                    or not still_running()
                ):
                    raise ValueError
                receipt = _result(_verify_candidate(job, base_dir, work_dir, candidate, self._checker))
                if not still_running():
                    raise ValueError
                return deepcopy(receipt)
            except Exception:
                receipt = None
                raise ValueError("candidate verification failed") from None

        try:
            report = self._runtime.run(deepcopy(job), repository, finalize)
        except Exception:
            return self._finish(job_id, attempt_id, {
                "status": "interrupted", "failure_code": "runtime_error",
            })

        status = report.get("status") if isinstance(report, dict) else None
        if not isinstance(status, str) or status not in _RUNTIME_STATES | {"verified", "candidate"}:
            return self._finish(job_id, attempt_id, {
                "status": "interrupted", "failure_code": "invalid_runtime_outcome",
            })
        outcome = {
            "status": status,
            "usage": report.get("usage"),
            "failure_code": _failure_code(report.get("failure_code")),
        }
        if status == "verified" and receipt is not None and report.get("result") == receipt:
            outcome["result"] = receipt
        elif status in {"verified", "candidate"}:
            outcome.update(status="failed", failure_code="candidate_verification_failed")
        elif status in _WAITING:
            outcome.update(checkpoint=report.get("checkpoint"), decision_request=report.get("decision_request"))
        return self._finish(job_id, attempt_id, outcome)

    def run_next(self) -> JobView | None:
        """Dispatch one atomic claim without serializing independent attempts."""
        with self._dispatch_lock:
            job = self._store.claim()
            if job is None:
                return None
            attempt_id = job["attempt_id"]
            self._dispatching.add(attempt_id)
        try:
            return _view(self._run_claimed(job))
        finally:
            with self._dispatch_lock:
                self._dispatching.remove(attempt_id)
