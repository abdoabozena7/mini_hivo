"""One headless Mini Hivo attempt on a trusted runtime's disposable staging area.

The store is the source of operator decisions, and the runtime is the isolation
boundary. Neither a model reply nor this process can publish a verified patch.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import unicodedata
import uuid
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from threading import Lock

import mini

from hivo.http_client import HttpTransportError, JsonResponse
from hivo.integration_gate import canonical_hash, fingerprint_dependency_paths
from hivo.job_result import snapshot_digest
from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy
from hivo.run_budget import RunBudget, RunBudgetExceeded


_BASE_URL = "http://127.0.0.1:11434"
_PROVIDER_ROUTES = {("get", "/api/tags"), ("post", "/api/show"), ("post", "/api/chat")}
_FRAME_LIMIT = 3 * 1024 * 1024
_PROVIDER_LIMIT = 512 * 1024
_BUDGET_KEYS = ("max_model_calls", "max_tool_calls", "max_elapsed_seconds")
_IDENTITY_KEYS = ("job_id", "project_id", "base_revision")
_RUNTIME_NAMES = frozenset({
    ".hivo", ".agent_backups", ".agent_evidence", ".agent_runs",
    ".agent_memory.json", ".agent_experiment.jsonl", ".mini_hivo", ".git",
})
_ENGINE_LOCK = Lock()


class _Blocked(ValueError):
    """A safe, externally reportable decision or authority failure."""


def _require(condition, code):
    if not condition:
        raise _Blocked(code)


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _display(text, limit):
    # Keep host/absolute paths and terminal control characters out of requests.
    text = re.sub(r"(?<![\w./-])(?:[A-Za-z]:[\\/]|\\\\|/)[^\s\"'`]+", "[path]", str(text))
    return " ".join("".join(
        char for char in text if char.isspace() or unicodedata.category(char)[0] != "C"
    ).split())[:limit]


def _run_binding(job):
    return {
        **{key: job[key] for key in _IDENTITY_KEYS},
        "prompt_sha256": hashlib.sha256(job["prompt"].encode("utf-8")).hexdigest(),
    }


def _wait(job, base_sha256, kind, public, authority, *, allowed_paths=None):
    request = {"decision_id": uuid.uuid4().hex, "kind": kind, **public}
    checkpoint = {
        "schema": 1, **_run_binding(job), "paused_attempt_id": job["attempt_id"],
        "base_sha256": base_sha256, "request": request, "authority": authority,
    }
    if allowed_paths is not None:
        checkpoint["allowed_paths"] = allowed_paths
    checkpoint["checkpoint_sha256"] = _hash(checkpoint)
    return _outcome(f"waiting_{kind}", checkpoint=checkpoint, decision_request=request)


def _decision(job, base_sha256):
    checkpoint, request, decision = (job.get(key) for key in ("checkpoint", "decision_request", "decision"))
    if checkpoint is None and request is None and decision is None:
        return None
    _require(all(isinstance(value, dict) for value in (checkpoint, request, decision)), "DECISION_REQUIRED")
    _require(checkpoint.get("schema") == 1
             and isinstance(checkpoint.get("paused_attempt_id"), str)
             and checkpoint["paused_attempt_id"] != job["attempt_id"]
             and all(checkpoint.get(key) == value for key, value in _run_binding(job).items())
             and checkpoint.get("checkpoint_sha256") == _hash({
                 key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"
             }), "STALE_CHECKPOINT")
    _require(checkpoint.get("base_sha256") == base_sha256, "BASE_CHANGED")
    _require(request == checkpoint.get("request")
             and isinstance(request.get("decision_id"), str) and request["decision_id"]
             and decision.get("decision_id") == request["decision_id"]
             and isinstance(decision.get("actor_id"), str) and decision["actor_id"].strip(),
             "STALE_DECISION")
    if request.get("kind") == "approval":
        _require(decision.get("kind") == "approve"
                 and not decision.get("answers")
                 and isinstance(request.get("plan_hash"), str)
                 and decision.get("plan_hash") == request["plan_hash"], "STALE_APPROVAL")
    else:
        _require(request.get("kind") == "clarification" and decision.get("kind") == "answer"
                 and decision.get("plan_hash") is None, "STALE_DECISION")
        questions, answers = request.get("questions"), decision.get("answers")
        _require(isinstance(questions, list) and questions and isinstance(answers, dict)
                 and set(answers) == {question["question_id"] for question in questions}
                 and all(isinstance(answer, str) and answer.strip() and len(answer) <= 700
                         and "\0" not in answer for answer in answers.values()),
                 "INVALID_CLARIFICATION_ANSWERS")
    return checkpoint


def _clarification(job, base_sha256, phase, pending, questions, contract, reconnaissance=None):
    public = [{"question_id": item["question_id"], "question": _display(item["question"], 700)}
              for item in pending]
    _require(public and all(item["question"] for item in public)
             and len({item["question_id"] for item in public}) == len(public), "CLARIFICATION_INVALID")
    return _wait(job, base_sha256, "clarification", {"questions": public}, {
        "phase": phase, "questions": questions, "contract": contract, "reconnaissance": reconnaissance,
    })


def _resolve_clarification(job, checkpoint):
    authority = checkpoint["authority"]
    questions, source = authority["questions"], authority["contract"]
    request, decision = job["decision_request"], job["decision"]
    answers = decision["answers"]
    expected = [{"question_id": item["question_id"], "question": _display(item["question"], 700)}
                for item in questions if item.get("blocking")]
    _require(expected == request["questions"] and source.get("original_goal") == job["prompt"],
             "STALE_CLARIFICATION")

    def select(question, **_):
        answer = answers.get(question["question_id"])
        if answer is None:
            return None
        options = question.get("options", [])[:mini.REQUIREMENT_MAX_CLARIFICATION_OPTIONS]
        return options.index(answer) if answer in options else len(options)

    other_answers = iter(answers[item["question_id"]] for item in questions
                         if item["question_id"] in answers
                         and answers[item["question_id"]] not in
                         item.get("options", [])[:mini.REQUIREMENT_MAX_CLARIFICATION_OPTIONS])
    mini.RUN["clarification_answers"] = source.get("clarification_answers", [])
    resolution = mini.resolve_clarification_questions(
        {"questions": questions}, interactive=True, terminal_available=True,
        selector=select, answer_reader=lambda _: next(other_answers),
    )
    _require(resolution["status"] == "ready"
             and {item["question_id"] for item in resolution["answers"]} == set(answers),
             "STALE_CLARIFICATION")
    for item in resolution["answers"]:
        # Native presentation compacts answers; keep the exact operator text in
        # the source/decision record even when the search ledger normalizes it.
        item["answer"] = answers[item["question_id"]]
        item["authority_decision_id"] = request["decision_id"]
    goal = job["prompt"]
    if authority["phase"] == "repository":
        contract = mini._contract_with_repository_decisions(goal, source, {"questions": questions}, resolution)
        return contract, authority["reconnaissance"]
    _require(authority["phase"] == "source", "STALE_CLARIFICATION")
    confirmed, derived = resolution["answers"], resolution["derived"]
    ledger = mini._ledger_with_confirmed_answers(source["source_requirement_ledger"], confirmed)
    contract = mini.normalize_goal_contract(
        goal, mini._deterministic_contract_from_ledger(goal, ledger, derived),
        source_ledger=ledger, confirmed=confirmed, derived=derived,
        clarification_questions=questions, clarification_answers=confirmed,
        interaction_style=source["interaction_style"],
    )
    contract["source_contract"] = mini.source_contract_from_ledger(
        goal, ledger, confirmed=confirmed, derived=derived, questions=questions,
        answers=confirmed, interaction_style=source["interaction_style"],
    )
    return contract, None


def _restore_context(contract, authority=None):
    mini.RUN.update({
        "project_mode": mini.EXISTING_PROJECT, "impact_planning_required": True,
        "source_requirement_ledger": mini.freeze(contract["source_requirement_ledger"]),
        "clarification_answers": contract.get("clarification_answers", []),
    })
    if authority is not None:
        mini.RUN.update(authority["context"])


def _resume_repository_context(job, contract, reconnaissance, repository, questions):
    """Continue Stage 2 after its stored, read-only reconnaissance and questions."""
    mini.RUN["repository_evidence"] = reconnaissance["evidence"]
    mini.RUN["repository_reconnaissance"] = reconnaissance
    summary = mini.stage2.bounded_repository_summary(reconnaissance, mini.EXISTING_PROJECT)
    specification = mini.expand_project_specification(job["prompt"], contract, repository_summary=summary)
    brain = mini.prepare_project_brain(
        job["prompt"], contract, repository, specification=specification,
        repository_evidence=reconnaissance["evidence"],
    )
    task_brain = mini.create_task_brain(
        "ROOT", job["prompt"], contract, brain, mini.EXISTING_PROJECT,
        repository_evidence=reconnaissance["evidence"], open_questions=questions,
    )
    return {
        "status": "ready", "project_mode": mini.EXISTING_PROJECT,
        "contract": contract, "task_brain": task_brain, "reconnaissance": reconnaissance,
    }


def _exact_scope(contracts, workspace):
    paths = set()
    for contract in contracts:
        _require(not (contract.get("target_new_surface_proposal_ids")
                      and contract.get("approved_new_surface_parent_scopes")),
                 "UNSUPPORTED_APPROVAL_SCOPE")
        for path in contract.get("allowed_mutation_paths", []):
            _require(isinstance(path, str) and path
                     and not re.search(r'[\\:*?<>|"\x00-\x1f]', path), "UNSUPPORTED_APPROVAL_SCOPE")
            parts = path.split("/")
            _require(not any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts)
                     and parts[0].casefold() not in _RUNTIME_NAMES
                     and not any(part.casefold() == ".git" for part in parts)
                     and not (workspace / path).is_dir(), "UNSUPPORTED_APPROVAL_SCOPE")
            paths.add(path)
    _require(paths and len(paths) == len({path.casefold() for path in paths}), "UNSUPPORTED_APPROVAL_SCOPE")
    return sorted(paths)


def _approval_scope(plan, contract, workspace):
    """Validate Stage 3 and compile the authority shape without granting it."""
    requirements = mini._active_stage3_requirements(contract)
    evidence = mini.RUN["repository_evidence"]
    registry = mini.RUN["canonical_surface_registry"]
    goal = mini._stage4_authoritative_goal(contract, plan)
    _require(all(mini.stage2.validate_repository_evidence(item, workspace) for item in evidence),
             "STALE_REPOSITORY_EVIDENCE")
    gate = mini.stage3.validate_change_plan(
        plan, requirements, evidence, mini.EXISTING_PROJECT,
        surface_registry=registry, authoritative_task_goal=goal,
    )
    _require(gate.get("valid") is True and plan.get("plan_hash") == mini.stage3.plan_content_hash(plan),
             "APPROVED_PLAN_STALE")
    snapshot = mini.stage4.create_plan_contractability_snapshot(
        plan, authoritative_task_goal=goal, requirements=requirements,
        repository_evidence=evidence, canonical_surface_registry=registry,
    )
    compiled = mini.stage4.compile_execution_contracts(snapshot, contractability_only=True)
    return _exact_scope(compiled["contracts"], workspace)


def _plan(job, workspace, base_sha256, checkpoint):
    goal = job["prompt"]
    reconnaissance = None
    if checkpoint is None:
        contract = mini.get_goal_contract(goal, interactive=False, terminal_available=False)
        if mini._contract_needs_clarification(contract):
            return _unchanged(workspace, base_sha256, _clarification(
                job, base_sha256, "source", contract["unanswered_questions"],
                contract["questions"], contract,
            ))
    else:
        contract, reconnaissance = _resolve_clarification(job, checkpoint)
    _restore_context(contract)
    repository = mini.inspect_repository(workspace)
    if reconnaissance is None:
        understanding = mini.prepare_stage2_context(
            goal, contract, repo_snapshot=repository, interactive=False, terminal_available=False,
        )
    else:
        understanding = _resume_repository_context(
            job, contract, reconnaissance, repository, checkpoint["authority"]["questions"],
        )
    if understanding.get("status") == "clarification_required":
        return _unchanged(workspace, base_sha256, _clarification(
            job, base_sha256, "repository", mini.RUN["unanswered_clarification_questions"],
            understanding["clarification_questions"], understanding["contract"], understanding["reconnaissance"],
        ))
    if understanding.get("status") != "ready":
        return _outcome("failed", "PROJECT_UNDERSTANDING_FAILED")
    _require(understanding.get("project_mode") == mini.EXISTING_PROJECT, "EXISTING_PROJECT_REQUIRED")
    contract = understanding["contract"]
    mini.begin_durable_run(contract)
    planning = mini.prepare_stage3_context(understanding, contract, interactive=False, terminal_available=False)
    _require(planning.get("status") == "plan_approval_required"
             and planning.get("read_only") is True
             and planning.get("plan_gate", {}).get("valid") is True,
             "CHANGE_PLAN_UNAVAILABLE")
    plan = planning["plan"]
    paths = _approval_scope(plan, contract, workspace)
    context = {key: mini.RUN[key] for key in (
        "project_brain", "task_brain", "repository_evidence", "canonical_surface_registry",
    )}
    summary = (
        "Approved scope if accepted: " + ", ".join(paths) + ". "
        + _display(mini.format_plan_approval_summary(plan), 3500)
    )
    return _unchanged(workspace, base_sha256, _wait(
        job, base_sha256, "approval", {"plan_hash": plan["plan_hash"], "plan_summary": summary},
        {"plan": plan, "contract": contract, "context": context}, allowed_paths=paths,
    ))


def _unchanged(workspace, expected, outcome):
    _require(snapshot_digest(workspace) == expected, "PREAPPROVAL_WORKSPACE_CHANGED")
    return outcome


def _root_is_current(result, plan_hash, snapshot_hash, workspace):
    receipt = result.get("parent_verification_receipt")
    task = mini.TASKS.get("ROOT", {})
    subject = receipt.get("subject_state") if isinstance(receipt, dict) else None
    return (
        result.get("status") == "done"
        and result.get("plan_hash") == plan_hash
        and result.get("approved_plan_snapshot_hash") == snapshot_hash
        and result.get("integration_result") == mini.PARENT_VERIFIED
        and result.get("parent_verified") is True
        and mini.RUN.get("root_verified") is True
        and task.get("verification_status") == "passed"
        and isinstance(receipt, dict) and receipt == task.get("parent_verification_receipt")
        and receipt.get("parent_id") == "ROOT" and receipt.get("verified") is True
        and receipt.get("plan_hash") == plan_hash
        and receipt.get("receipt_status") == mini.PARENT_VERIFIED
        and isinstance(receipt.get("receipt_hash"), str)
        and receipt["receipt_hash"] == canonical_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
        and bool(result.get("integration_evidence"))
        and bool(mini.RUN.get("parent_verification_runs"))
        and isinstance(subject, dict) and bool(subject.get("paths"))
        and subject == fingerprint_dependency_paths(workspace, [item["path"] for item in subject["paths"]])
    )


def _execute(job, workspace, checkpoint):
    authority = checkpoint["authority"]
    plan, contract = authority["plan"], authority["contract"]
    plan_hash = job["decision"]["plan_hash"]
    _require(plan.get("plan_hash") == plan_hash and contract.get("original_goal") == job["prompt"],
             "APPROVED_PLAN_STALE")
    _restore_context(contract, authority)
    paths = _approval_scope(plan, contract, workspace)
    _require(paths == checkpoint["allowed_paths"], "APPROVED_PLAN_STALE")
    approval = mini._plan_approval_record(plan, "APPROVED", "HEADLESS_OPERATOR_DECISION")
    mini.RUN.update(approved_change_plan=plan, plan_approval=approval)
    mini.begin_durable_run(contract)
    compilation = mini.compile_approved_plan_execution_contracts(contract=contract, plan=plan, approval=approval)
    _require(compilation.get("status") == "ready"
             and _exact_scope(compilation["contracts"], workspace) == paths,
             "EXECUTION_AUTHORITY_INVALID")
    _require(snapshot_digest(workspace) == checkpoint["base_sha256"], "BASE_CHANGED")
    mini.RUN.update(stage5b_enabled=True, child_receipt_policy="atomic_verified", integration_target_policy="resolved")
    execution_contract = {
        **contract, "plan_hash": plan_hash,
        "integration_verification": plan.get("integration_verification", []),
    }
    result, _ = mini.execute_approved_plan_graph(
        execution_contract, mini.load_memory(), repo_snapshot=mini.inspect_repository(workspace),
    )
    final_sha256 = snapshot_digest(workspace)
    if not _root_is_current(result, plan_hash, compilation["snapshot"]["snapshot_hash"], workspace):
        return _outcome("failed", "ROOT_VERIFICATION_FAILED")
    if final_sha256 == checkpoint["base_sha256"]:
        return _outcome("failed", "NO_CANDIDATE_CHANGE")
    return _outcome("candidate", evidence={
        "job_id": job["job_id"], "attempt_id": job["attempt_id"], "root_verified": True,
        "base_revision": job["base_revision"], "plan_hash": plan_hash,
        "allowed_paths": paths, "workspace_sha256": final_sha256,
    })


def _outcome(status, failure_code=None, *, checkpoint=None, decision_request=None, evidence=None):
    return {
        "status": status, "failure_code": failure_code, "checkpoint": checkpoint,
        "decision_request": decision_request, "evidence": evidence,
        "usage": {"model_calls": 0, "tool_calls": 0, "elapsed_seconds": 0.0},
    }


@contextmanager
def _engine(workspace, budget, transport):
    # Mini Hivo's CLI engine owns process-global run state. The production
    # runtime uses one process per attempt; also serialize in-process test use.
    keys = (
        "RUN", "TASKS", "ROLE_STATUS", "DASHBOARD", "RUN_STARTED", "RUN_ID", "WORKSPACE",
        "ACTIVE_TRANSACTION", "LAST_COMMITTED_TRANSACTION", "ACTIVE_CONTRACT", "ACTIVE_TOOL_CONTRACT",
        "ACTIVE_CONTEXT_SUFFICIENCY_GATE", "ACTIVE_PROJECT_WORLD_MODEL", "ACTIVE_IMPACT_CONTRACT",
        "ACTIVE_IMPACT_REQUIRED", "PREFLIGHT_CONFLICT_STATE", "HOST_PREFLIGHT_RESULT", "MEMORY_STORE",
        "ACTIVE_RUN_BUDGET", "MODEL_POLICY", "MODEL", "MODEL_CAPABILITIES", "MODEL_TASK_CAPACITY",
        "ROUTER_MODEL", "FALLBACK_MODEL", "VISION_MODEL", "VISION_ENABLED_FOR_RUN", "VISION_ERROR",
        "FORCE_CPU_FOR_RUN", "OLLAMA_BASE_URL", "OLLAMA_URL", "http_get_json", "http_post_json",
    )

    observed = {"requests": 0, "http_success": False}

    def provider(op, url, timeout, payload=None):
        path = url.removeprefix(_BASE_URL)
        if (op, path) not in _PROVIDER_ROUTES or url != _BASE_URL + path:
            raise HttpTransportError("provider route denied")
        if op == "post" and (not isinstance(payload, dict) or payload.get("model") != GEMMA_MODEL):
            raise HttpTransportError("provider model denied")
        observed["requests"] += 1
        response = transport(op, path, timeout=timeout, payload=payload)
        if not isinstance(response, JsonResponse):
            raise HttpTransportError("invalid provider reply")
        observed["http_success"] |= response.status_code == 200
        return response

    with _ENGINE_LOCK:
        previous = {key: getattr(mini, key) for key in keys}
        try:
            mini.WORKSPACE, mini.MEMORY_STORE = workspace, None
            mini.HOST_PREFLIGHT_RESULT = None
            mini.ACTIVE_RUN_BUDGET = budget
            mini.MODEL_POLICY = SingleModelPolicy(GEMMA_MODEL)
            mini.MODEL = mini.ROUTER_MODEL = GEMMA_MODEL
            mini.VISION_MODEL = mini.FALLBACK_MODEL = ""
            mini.MODEL_CAPABILITIES = set()
            mini.MODEL_TASK_CAPACITY = 2  # Audited Gemma E4B profile.
            mini.OLLAMA_BASE_URL, mini.OLLAMA_URL = _BASE_URL, _BASE_URL + "/api/chat"
            mini.http_get_json = lambda url, *, timeout: provider("get", url, timeout)
            mini.http_post_json = lambda url, *, timeout, payload: provider("post", url, timeout, payload)
            mini.reset_run("recursive")
            mini.RUN["planning_route"] = "current_recursive"
            yield observed
        finally:
            try:
                if mini.ACTIVE_TRANSACTION is not None and mini.ACTIVE_TRANSACTION is not previous["ACTIVE_TRANSACTION"]:
                    mini.rollback_transaction()
            finally:
                for key, value in previous.items():
                    setattr(mini, key, value)


def run_attempt(job: dict, workspace: Path, *, transport=None) -> dict:
    """Run a claimed job in freshly staged scratch; never use direct HTTP.

    `transport(op, path, *, timeout, payload)` returns an HTTP `JsonResponse`
    or raises `HttpTransportError`. Only the runtime or an offline test supplies it.
    """
    budget = None
    try:
        _require(isinstance(job, dict) and job.get("status") == "running"
                 and all(isinstance(job.get(key), str) and job[key].strip()
                         for key in (*_IDENTITY_KEYS, "attempt_id", "prompt"))
                 and re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", job["base_revision"]), "INVALID_JOB")
        limits = job.get("limits")
        _require(isinstance(limits, dict) and all(limits.get(key) is not None for key in _BUDGET_KEYS), "INVALID_LIMITS")
        budget = RunBudget(**{key: limits[key] for key in _BUDGET_KEYS})
        _require(callable(transport), "PROVIDER_BRIDGE_REQUIRED")
        workspace = Path(workspace)
        _require(workspace.is_absolute() and workspace.is_dir() and not workspace.is_symlink(),
                 "INVALID_WORKSPACE")
        _require(not any(path.name.casefold() in _RUNTIME_NAMES for path in workspace.iterdir()),
                 "WORKSPACE_NOT_PRISTINE")
        base_sha256 = snapshot_digest(workspace)
        workspace = workspace.resolve(strict=True)
        checkpoint = _decision(job, base_sha256)
        with _engine(workspace, budget, transport) as observed:
            try:
                mini._check_run_deadline()
                if checkpoint is not None and checkpoint["request"]["kind"] == "approval":
                    outcome = _execute(job, workspace, checkpoint)
                else:
                    outcome = _plan(job, workspace, base_sha256, checkpoint)
                mini._check_run_deadline()
            except mini.ProviderError:
                outcome = _outcome("failed", "PROVIDER_FAILURE")
            except mini.stage4.ExecutionContractError:
                outcome = _outcome("blocked", "EXECUTION_AUTHORITY_INVALID")
            except mini.TaskBrainValidationError:
                outcome = _outcome("failed", "PROJECT_UNDERSTANDING_FAILED")
            except _Blocked:
                if not observed["requests"] or observed["http_success"]:
                    raise
                outcome = _outcome("failed", "PROVIDER_FAILURE")
            if (outcome["status"] in {"failed", "blocked"}
                    and observed["requests"] and not observed["http_success"]):
                outcome = _outcome("failed", "PROVIDER_FAILURE")
    except RunBudgetExceeded as exc:
        outcome = _outcome("timed_out" if exc.resource == "elapsed" else "failed",
                           "RUN_BUDGET_" + exc.resource.upper() + "_EXHAUSTED")
    except _Blocked as exc:
        outcome = _outcome("blocked", str(exc))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"[job worker] rejected attempt: {type(exc).__name__}", file=sys.stderr)
        outcome = _outcome("blocked", "WORKER_INPUT_OR_SNAPSHOT_INVALID")
    if budget is not None:
        summary = budget.snapshot()
        outcome["usage"] = {key: summary[key] for key in outcome["usage"]}
    return outcome


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _read_frame(stream, limit=_FRAME_LIMIT):
    raw = stream.readline(limit + 1)
    if not raw.endswith(b"\n") or len(raw) > limit:
        raise ValueError("missing or oversized worker frame")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    if not isinstance(value, dict):
        raise ValueError("worker frame is not an object")
    return value


def _send_frame(stream, frame, limit=_FRAME_LIMIT):
    data = (_canonical(frame) + "\n").encode("ascii")
    if len(data) > limit:
        raise ValueError("oversized worker frame")
    stream.write(data)
    stream.flush()


def _serve(stdin, stdout):
    def transport(op, path, *, timeout, payload):
        try:
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("invalid provider timeout")
            _send_frame(stdout, {"kind": "provider", "op": op, "path": path, "timeout": timeout,
                                 "payload": payload}, _PROVIDER_LIMIT)
            reply = _read_frame(stdin, _PROVIDER_LIMIT)
            if reply.get("kind") != "provider_result":
                raise ValueError("expected provider result")
            if "error" in reply:
                raise HttpTransportError("host provider request failed")
            code, text = reply.get("status_code"), reply.get("text")
            if type(code) is not int or not 100 <= code <= 599 or not isinstance(text, str):
                raise ValueError("invalid provider result")
            return JsonResponse(code, text)
        except (ValueError, OSError) as exc:
            raise HttpTransportError("provider bridge unavailable") from exc

    try:
        request = _read_frame(stdin)
        if request.get("kind") != "start" or not isinstance(request.get("workspace"), str):
            raise ValueError("expected start frame")
    except (ValueError, OSError):
        outcome = _outcome("blocked", "INVALID_WORKER_REQUEST")
    else:
        with redirect_stdout(sys.stderr):
            outcome = run_attempt(request.get("job"), Path(request["workspace"]), transport=transport)
    try:
        _send_frame(stdout, {"kind": "outcome", "outcome": outcome})
    except ValueError:
        _send_frame(stdout, {"kind": "outcome", "outcome": {
            **_outcome("blocked", "WORKER_OUTCOME_TOO_LARGE"), "usage": outcome["usage"],
        }})


def _main():
    if sys.platform == "linux":
        # Generated subprocesses share the worker UID in the container.
        # Prevent reopening the bridge descriptors through /proc or ptrace.
        import ctypes
        if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            _send_frame(sys.stdout.buffer, {
                "kind": "outcome", "outcome": _outcome("blocked", "PROVIDER_BRIDGE_UNPROTECTED"),
            })
            return
    with os.fdopen(os.dup(0), "rb") as stdin, os.fdopen(os.dup(1), "wb") as stdout, \
            open(os.devnull, "rb") as empty_input:
        # Only the synchronous controller retains the non-inheritable bridge.
        os.dup2(empty_input.fileno(), 0)
        os.dup2(2, 1)
        _serve(stdin, stdout)


if __name__ == "__main__":
    _main()
