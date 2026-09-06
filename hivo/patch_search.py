"""Bounded, evidence-driven patch candidate search for HIVO CORE-5.

Search operates exclusively in disposable sandboxes.  The only API that can
write the canonical subject is :func:`apply_selected_patch_candidate`, an
explicit caller action that rechecks all anchors and existing authority.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .experiment_sandbox import ExperimentalSandbox, SandboxSecurityError, subject_tree_snapshot, canonical_subject_hash, validate_source_syntax
from .lexical_index import LexicalIndex, incremental_lexical_update
from .mutation_strategy import MutationStrategyRouter, StrategyDecision
from .patch_candidates import (
    AUTHORITY_BLOCKED, CandidateFailureEvidence, CONTRACT_CONFLICT, DETERMINISTIC_OPERATOR,
    GUARD_REGRESSION, MODEL_PROPOSED, PatchCandidate, PatchCandidateReceipt,
    PatchOperation, PROPOSED, STALE_BASE, SYNTAX_INVALID, TARGET_FAILED, V25_5_REJECTED,
    V25_6_FAILED, VERIFIED, VIABLE, generate_deterministic_candidates,
    generate_experiment_derived_candidate, normalize_model_candidates,
)
from .project_brain_refs import canonical_hash
from .repair_problem import DNT_PROTECTED, FINAL_MUTATION_AUTHORIZED, PatchSearchBudget, RepairProblem
from .repository_map import RepositoryMap, incremental_reindex


CORE5_SEARCH_SCHEMA_VERSION = "CORE-5-PATCH-SEARCH-V1"
VERIFIED_CANDIDATE = "VERIFIED_CANDIDATE"
BEST_VIABLE_CANDIDATE = "BEST_VIABLE_CANDIDATE"
APPLY_SELECTED_CANDIDATE = "APPLY_SELECTED_CANDIDATE"
NO_VIABLE_PATCH_CANDIDATE = "NO_VIABLE_PATCH_CANDIDATE"
PATCH_SEARCH_BUDGET_REACHED = "PATCH_SEARCH_BUDGET_REACHED"


def _map(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return dict(data) if isinstance(data, Mapping) else {}
        except Exception:
            return {}
    return {}


def _bool_result(value: Any, *, default: bool = False) -> tuple[bool, dict[str, Any], str]:
    if isinstance(value, bool):
        return value, {"passed": value}, ""
    if value is None:
        return default, {"status": "NOT_RUN"}, "callback returned None"
    data = _map(value)
    if data:
        if str(data.get("status", "")).upper() in {"NOT_RUN", "SKIPPED", "NOT_CONFIGURED"}:
            return default, data, ""
        if "allowed" in data:
            passed = bool(data.get("allowed"))
        else:
            passed = bool(data.get("passed", data.get("valid", data.get("success", data.get("ok", False)))))
        reason = str(data.get("reason", data.get("status", "")))
        return passed, data, reason
    return bool(value), {"value": str(value)}, ""


def _invoke(callback: Any, *args: Any, **kwargs: Any) -> Any:
    if callback is None:
        return None
    target = callback
    if not callable(target):
        for name in ("evaluate", "check", "validate", "verify", "run"):
            if hasattr(target, name):
                target = getattr(target, name)
                break
    if not callable(target):
        return None
    # Existing project callbacks have intentionally varied small signatures.
    attempts = [
        lambda: target(*args, **kwargs),
        lambda: target(*args),
        lambda: target(args[0]) if args else target(),
    ]
    last: Exception | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last = exc
            continue
    if last:
        return {"passed": False, "reason": f"callback signature rejected: {last}"}
    return None


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_target(root: Path, path: str) -> Path:
    raw = str(path or "").replace("\\", "/")
    if not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":") or ".." in raw.split("/"):
        raise ValueError("unsafe candidate path")
    target = (root / raw).resolve()
    target.relative_to(root.resolve())
    if any(item in {".git", ".agent_runs", ".agent_evidence", ".hivo", "output", "node_modules"} for item in target.relative_to(root.resolve()).parts):
        raise ValueError("candidate path is protected")
    return target


def _authority_label(problem: RepairProblem, path: str, candidate_label: str = "") -> tuple[str, str]:
    normalized = str(path).replace("\\", "/").lstrip("./")
    dnt = {str(item).replace("\\", "/").lstrip("./") for item in problem.dnt_context}
    authority = dict(problem.authority_context or {})
    for key in ("dnt", "do_not_touch", "approved_dnt"):
        raw = authority.get(key, ())
        if isinstance(raw, str):
            raw = (raw,)
        dnt.update(str(item).replace("\\", "/").lstrip("./") for item in raw or ())
    if normalized in dnt:
        return DNT_PROTECTED, "target is explicitly do-not-touch"
    approved: set[str] = set()
    for key in ("approved_mutation_scope", "mutation_scope", "authorized_paths", "approved_scope", "mutation_targets"):
        raw = authority.get(key, ())
        if isinstance(raw, Mapping):
            raw = raw.get("paths", raw.get("files", ()))
        if isinstance(raw, str):
            raw = (raw,)
        approved.update(str(item).replace("\\", "/").lstrip("./") for item in raw or ())
    # Candidate/model metadata is diagnostic input and cannot grant authority.
    if normalized in approved:
        return FINAL_MUTATION_AUTHORIZED, "target is in existing authorized mutation scope"
    return candidate_label or "DIAGNOSTIC_SUSPECT", "diagnostic suspect is not final mutation authority"


def _candidate_authority_violations(problem: RepairProblem, candidate: PatchCandidate) -> tuple[str, ...]:
    """Check every changed path; target_path alone is insufficient for multi-file patches."""
    authority = dict(problem.authority_context or {})
    explicit_scope = any(
        key in authority and bool(authority.get(key))
        for key in ("approved_mutation_scope", "mutation_scope", "authorized_paths", "approved_scope", "mutation_targets")
    )
    violations: list[str] = []
    for path in candidate.changed_paths:
        label, reason = _authority_label(problem, path, candidate.target_authority)
        if label == DNT_PROTECTED:
            violations.append(f"DNT_PROTECTED:{path}:{reason}")
        elif explicit_scope and label != FINAL_MUTATION_AUTHORIZED:
            violations.append(f"AUTHORITY_BLOCKED:{path}:{reason}")
        elif not explicit_scope and not bool(authority.get("allow_diagnostic_candidate_search", True)) and label != FINAL_MUTATION_AUTHORIZED:
            violations.append(f"AUTHORITY_BLOCKED:{path}:{reason}")
    return tuple(violations)


def _candidate_source_hash(problem: RepairProblem, root: Path) -> str:
    identity = str(problem.subject_identity or "")
    return identity if len(identity) == 64 and all(c in "0123456789abcdefABCDEF" for c in identity) else canonical_subject_hash(root)


def _apply_candidate_to_sandbox(candidate: PatchCandidate, sandbox_root: Path, canonical_root: Path) -> tuple[bool, dict[str, Any], list[str]]:
    original_hashes: dict[str, str] = {}
    syntax: dict[str, Any] = {}
    violations: list[str] = []
    changed: set[str] = set()
    diff_size = 0
    for operation in candidate.representation.operations:
        try:
            target = _safe_target(sandbox_root, operation.path)
            canonical_target = _safe_target(canonical_root, operation.path)
        except (ValueError, OSError) as exc:
            violations.append(f"PATH_UNSAFE:{operation.path}:{exc}")
            continue
        if not target.is_file() or not canonical_target.is_file():
            violations.append(f"TARGET_MISSING:{operation.path}")
            continue
        before = target.read_bytes()
        canonical_bytes = canonical_target.read_bytes()
        current_hash = _sha_bytes(canonical_bytes)
        original_hashes.setdefault(operation.path, current_hash)
        if not operation.expected_file_hash and not operation.expected_text:
            violations.append(f"ANCHOR:{operation.path}:missing current-source anchor")
            continue
        if operation.expected_file_hash and operation.expected_file_hash != current_hash:
            violations.append(f"STALE_BASE:{operation.path}")
            continue
        text = before.decode("utf-8", errors="replace")
        after, reason = operation.apply(text)
        if reason:
            violations.append(f"ANCHOR:{operation.path}:{reason}")
            continue
        if after == text:
            violations.append(f"NO_CHANGE:{operation.path}")
            continue
        target.write_bytes(after.encode("utf-8"))
        diff_size += abs(after.count("\n") - text.count("\n")) + sum(1 for left, right in zip(text.splitlines(), after.splitlines()) if left != right)
        changed.add(operation.path)
    for path in sorted(changed):
        validation = validate_source_syntax(path, (sandbox_root / path).read_text(encoding="utf-8", errors="replace"))
        syntax[path] = validation.to_dict()
        if not validation.valid:
            violations.append(f"SYNTAX_INVALID:{path}:{validation.error}")
    return not violations and bool(changed), {"changed_paths": sorted(changed), "original_hashes": original_hashes, "syntax": syntax, "diff_size": diff_size}, violations


def _candidate_score_parts(candidate: PatchCandidate, decision: StrategyDecision, receipt: PatchCandidateReceipt) -> dict[str, float]:
    parts = {
        "localization_support": float(candidate.score),
        "deterministic_provenance": 1.0 if candidate.provenance == DETERMINISTIC_OPERATOR else 0.25,
        "evidence_alignment": 0.5 * len(candidate.evidence_sources),
        "hypothesis_alignment": 0.25 * len(candidate.hypothesis_ids),
        "strategy_signal": 0.2 * len(decision.signals),
        "diff_risk": -0.15 * max(0, candidate.complexity - 1),
    }
    if receipt.status == VERIFIED:
        parts["V25_6_pass"] = 1000.0
    elif receipt.status == VIABLE:
        parts["V25_5_pass"] = 100.0
    return {key: round(value, 6) for key, value in parts.items()}


def _candidate_score(candidate: PatchCandidate, decision: StrategyDecision, receipt: PatchCandidateReceipt) -> float:
    return round(sum(_candidate_score_parts(candidate, decision, receipt).values()), 6)


def _candidate_final_state_key(candidate: PatchCandidate, root: Path) -> str:
    """Hash the resulting changed source, so textually different proposals
    that produce the same final state are suppressed."""
    rows: list[dict[str, str]] = []
    by_path: dict[str, str] = {}
    for operation in candidate.representation.operations:
        if operation.path not in by_path:
            target = _safe_target(root, operation.path)
            by_path[operation.path] = target.read_text(encoding="utf-8", errors="replace")
        updated, reason = operation.apply(by_path[operation.path])
        if reason:
            return "INVALID:" + candidate.canonical_hash
        by_path[operation.path] = updated
    for path in sorted(by_path):
        rows.append({"path": path, "sha256": hashlib.sha256(by_path[path].encode("utf-8")).hexdigest()})
    return canonical_hash({"base": canonical_subject_hash(root), "files": rows})


@dataclass(frozen=True)
class PatchSearchResult:
    problem: RepairProblem
    strategy_decisions: tuple[StrategyDecision, ...] = ()
    generated_candidates: tuple[PatchCandidate, ...] = ()
    deduplicated_candidates: tuple[PatchCandidate, ...] = ()
    receipts: tuple[PatchCandidateReceipt, ...] = ()
    ranked_viable_candidates: tuple[PatchCandidate, ...] = ()
    rejected_candidates: tuple[CandidateFailureEvidence, ...] = ()
    winner: PatchCandidate | None = None
    runner_up_or_pareto: tuple[PatchCandidate, ...] = ()
    budget_usage: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    next_action: str = NO_VIABLE_PATCH_CANDIDATE
    source_unchanged: bool = True
    canonical_before: str = ""
    canonical_after: str = ""

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE5_SEARCH_SCHEMA_VERSION,
            "problem": self.problem.to_dict(),
            "strategy_decisions": [item.to_dict() for item in self.strategy_decisions],
            "generated_candidates": [item.to_dict() for item in self.generated_candidates],
            "deduplicated_candidates": [item.to_dict() for item in self.deduplicated_candidates],
            "receipts": [item.to_dict() for item in self.receipts],
            "ranked_viable_candidates": [item.to_dict() for item in self.ranked_viable_candidates],
            "rejected_candidates": [item.to_dict() for item in self.rejected_candidates],
            "winner": self.winner.to_dict() if self.winner else None,
            "runner_up_or_pareto": [item.to_dict() for item in self.runner_up_or_pareto],
            "budget_usage": dict(self.budget_usage), "metrics": dict(self.metrics),
            "unresolved_evidence": list(self.unresolved_evidence), "next_action": self.next_action,
            "source_unchanged": self.source_unchanged, "canonical_before": self.canonical_before, "canonical_after": self.canonical_after,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


class PatchSearchEngine:
    def __init__(self, *, strategy_router: MutationStrategyRouter | None = None) -> None:
        self.strategy_router = strategy_router or MutationStrategyRouter()

    def search(
        self,
        problem: RepairProblem | Mapping[str, Any],
        project_root: str | Path | None = None,
        *,
        targeted_checker: Any = None,
        guard_checker: Any = None,
        contract_checker: Any = None,
        v25_5_gate: Any = None,
        v25_6_verifier: Any = None,
        model_provider: Any = None,
        repository_map: RepositoryMap | None = None,
        lexical_index: LexicalIndex | None = None,
    ) -> PatchSearchResult:
        current = problem if isinstance(problem, RepairProblem) else RepairProblem.from_value(problem)
        root = Path(project_root or current.project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("patch search project root must exist")
        budget = current.candidate_budget
        before = canonical_subject_hash(root)
        metrics: dict[str, int] = {
            "patch_search_sessions": 1,
            "suspects_considered": 0, "strategies_considered": 0, "candidates_generated": 0,
            "deterministic_generated": 0, "model_generated": 0, "experiment_generated": 0,
            "duplicate_candidates_suppressed": 0, "sandbox_evaluations": 0,
            "syntax_evaluations": 0, "targeted_evaluations": 0, "guard_evaluations": 0,
            "contract_evaluations": 0, "v25_5_evaluations": 0, "v25_6_evaluations": 0,
            "stale_candidates": 0, "authority_blocked": 0, "dnt_blocked": 0,
            "source_bodies_loaded": 0, "full_v25_6_shortlist": 0, "syntax_valid_candidates": 0,
            "strategy_candidates_generated": 0, "strategy_syntax_failures": 0,
            "strategy_target_failures": 0, "strategy_guard_failures": 0,
            "strategy_v25_5_failures": 0, "strategy_viable_count": 0,
            "strategies_selected": 0, "experiment_derived_candidates": 0,
            "model_candidates": 0, "authority_blocked_candidates": 0,
            "syntax_invalid_candidates": 0, "target_failed_candidates": 0,
            "guard_regression_candidates": 0, "contract_conflict_candidates": 0,
            "v25_5_rejected_candidates": 0, "v25_6_failed_candidates": 0,
            "verified_candidates": 0, "candidate_files_changed": 0,
            "search_budget_reached": 0, "candidate_sandboxes_created": 0,
            "candidate_source_bytes_materialized": 0, "targeted_tests_run": 0,
            "guard_tests_run": 0, "full_v25_6_runs": 0,
            "targeted_passes": 0, "guard_passes": 0, "v25_5_passes": 0,
        }
        records = list(current.suspect_candidates[:budget.max_suspects])
        decisions: list[StrategyDecision] = []
        generated: list[PatchCandidate] = []
        strategy_counts: dict[str, int] = {}
        for record in records:
            metrics["suspects_considered"] += 1
            decision = self.strategy_router.route(current, record)
            decisions.append(decision)
            metrics["strategies_considered"] += len(decision.strategies)
            metrics["strategies_selected"] += min(len(decision.strategies), budget.max_strategies)
            for strategy in decision.strategies[:budget.max_strategies]:
                if len(generated) >= budget.max_candidates:
                    break
                if strategy_counts.get(strategy, 0) >= budget.max_candidates_per_strategy:
                    continue
                candidates = generate_deterministic_candidates(current, root, record, strategy)
                for candidate in candidates:
                    if len(generated) >= budget.max_candidates or metrics["deterministic_generated"] >= budget.max_deterministic_candidates:
                        break
                    generated.append(candidate)
                    metrics["strategy_candidates_generated"] += 1
                    strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
                    metrics["deterministic_generated"] += 1
            if len(generated) >= budget.max_candidates:
                break
        experiment_candidate = generate_experiment_derived_candidate(current, root, records[0]) if records else None
        if experiment_candidate and len(generated) < budget.max_candidates:
            generated.append(experiment_candidate)
            metrics["experiment_generated"] += 1
            metrics["experiment_derived_candidates"] += 1
        if model_provider is not None and len(generated) < budget.max_candidates and budget.max_model_candidates:
            context = current.evidence_packet.to_dict()
            context["strategy_hints"] = [item.to_dict(include_hash=False) for item in decisions[:budget.max_strategies]]
            context["source_slices"] = list(current.metadata.get("source_slices", ()))[:budget.max_source_slices]
            context["contracts"] = list(current.contracts)[:8]
            context["failure_evidence"] = [item.to_dict() for item in current.failure_evidence][:8]
            provider_method = getattr(model_provider, "generate", None) or getattr(model_provider, "propose", None) or model_provider
            hints = tuple(item.strategies for item in decisions[:budget.max_strategies])
            try:
                proposed = provider_method(current, context, strategy_hints=hints, candidate_budget=budget)
            except TypeError:
                try:
                    proposed = provider_method(current, context, hints, budget)
                except TypeError:
                    proposed = _invoke(provider_method, current, context, limit=budget.max_model_candidates)
            if proposed is None:
                proposed = ()
            model_candidates = normalize_model_candidates(proposed if not isinstance(proposed, Mapping) else (proposed,), current)
            for candidate in model_candidates[:budget.max_model_candidates]:
                if len(generated) >= budget.max_candidates:
                    break
                generated.append(candidate)
                metrics["model_generated"] += 1
                metrics["model_candidates"] += 1
        metrics["candidates_generated"] = len(generated)
        dedup: list[PatchCandidate] = []
        seen: set[str] = set()
        for candidate in generated:
            try:
                key = _candidate_final_state_key(candidate, root)
            except (OSError, ValueError):
                key = candidate.logical_hash
            if key in seen:
                metrics["duplicate_candidates_suppressed"] += 1
                continue
            seen.add(key)
            dedup.append(candidate)
        receipts: list[PatchCandidateReceipt] = []
        rejected: list[CandidateFailureEvidence] = []
        evaluated_candidates: list[PatchCandidate] = []
        for candidate in dedup:
            metrics["sandbox_evaluations"] += 1
            metrics["candidate_sandboxes_created"] += 1
            authority_violations = _candidate_authority_violations(current, candidate)
            if authority_violations:
                status = AUTHORITY_BLOCKED
                if any(item.startswith("DNT_PROTECTED:") for item in authority_violations):
                    metrics["dnt_blocked"] += 1
                else:
                    metrics["authority_blocked"] += 1
                metrics["authority_blocked_candidates"] += 1
                receipt = PatchCandidateReceipt(candidate.candidate_id, candidate.canonical_hash, status, before, changed_paths=(), violations=authority_violations, evidence=("authority_filter",))
                receipts.append(receipt)
                rejected.append(CandidateFailureEvidence(candidate.candidate_id, status, "authority", "; ".join(authority_violations), authority_violations, before, candidate.target_path))
                continue
            if candidate.base_subject_hash and len(candidate.base_subject_hash) == 64 and candidate.base_subject_hash != before:
                metrics["stale_candidates"] += 1
                receipt = PatchCandidateReceipt(candidate.candidate_id, candidate.canonical_hash, STALE_BASE, before, violations=("candidate base subject is stale",), evidence=("base_revision",))
                receipts.append(receipt)
                rejected.append(CandidateFailureEvidence(candidate.candidate_id, STALE_BASE, "base", "candidate base subject is stale", ("STALE_BASE",), before, candidate.target_path))
                continue
            try:
                with ExperimentalSandbox(root, session_id=f"core5-{candidate.candidate_id}", authority={"allow_ephemeral_probes": True}, dnt_paths=current.dnt_context) as sandbox:
                    ok, applied, violations = _apply_candidate_to_sandbox(candidate, sandbox.sandbox_root, root)  # type: ignore[arg-type]
                    syntax = dict(applied.get("syntax", {}))
                    metrics["syntax_evaluations"] += 1
                    metrics["candidate_files_changed"] += len(applied.get("changed_paths", ()))
                    metrics["candidate_source_bytes_materialized"] += sum(
                        len((sandbox.sandbox_root / path).read_bytes())
                        for path in applied.get("changed_paths", ())
                        if (sandbox.sandbox_root / path).is_file()
                    )
                    if not ok:
                        status = SYNTAX_INVALID if any(item.startswith("SYNTAX_INVALID") for item in violations) else TARGET_FAILED
                        if status == SYNTAX_INVALID:
                            metrics["strategy_syntax_failures"] += 1
                            metrics["syntax_invalid_candidates"] += 1
                        else:
                            metrics["strategy_target_failures"] += 1
                            metrics["target_failed_candidates"] += 1
                        receipt = PatchCandidateReceipt(candidate.candidate_id, candidate.canonical_hash, status, before, canonical_subject_hash(sandbox.sandbox_root), tuple(applied.get("changed_paths", ())), syntax=syntax, violations=tuple(violations), evidence=("sandbox",), diff_size=int(applied.get("diff_size", 0)), validity="REJECTED")
                        receipts.append(receipt)
                        rejected.append(CandidateFailureEvidence(candidate.candidate_id, status, "sandbox", "; ".join(violations), tuple(violations), before, candidate.target_path))
                        continue
                    targeted_evaluated = bool(targeted_checker and metrics["targeted_evaluations"] < budget.max_targeted_check_candidates)
                    targeted = _invoke(targeted_checker, candidate, sandbox.sandbox_root, applied) if targeted_evaluated else {"status": "NOT_RUN"}
                    if targeted_evaluated:
                        metrics["targeted_evaluations"] += 1
                        metrics["targeted_tests_run"] += 1
                    elif targeted_checker:
                        targeted = {"status": "NOT_RUN", "reason": "targeted verification budget reached"}
                    target_ok, targeted_data, target_reason = _bool_result(targeted, default=True)
                    guard_evaluated = bool(guard_checker)
                    guard = _invoke(guard_checker, candidate, sandbox.sandbox_root, applied) if guard_evaluated else {"status": "NOT_RUN"}
                    if guard_evaluated:
                        metrics["guard_evaluations"] += 1
                        metrics["guard_tests_run"] += 1
                    guard_ok, guard_data, guard_reason = _bool_result(guard, default=True)
                    contract = _invoke(contract_checker, candidate, sandbox.sandbox_root, applied) if contract_checker else {"status": "NOT_RUN"}
                    if contract_checker:
                        metrics["contract_evaluations"] += 1
                    contract_ok, contract_data, contract_reason = _bool_result(contract, default=True)
                    if targeted_evaluated and target_ok:
                        metrics["targeted_passes"] += 1
                    if guard_evaluated and guard_ok:
                        metrics["guard_passes"] += 1
                    if not target_ok:
                        status, reason = TARGET_FAILED, target_reason or "targeted check failed"
                        metrics["strategy_target_failures"] += 1
                        metrics["target_failed_candidates"] += 1
                    elif not guard_ok:
                        status, reason = GUARD_REGRESSION, guard_reason or "guard check failed"
                        metrics["strategy_guard_failures"] += 1
                        metrics["guard_regression_candidates"] += 1
                    elif not contract_ok:
                        status, reason = CONTRACT_CONFLICT, contract_reason or "contract check failed"
                        metrics["contract_conflict_candidates"] += 1
                    else:
                        status, reason = PROPOSED, "targeted gates passed or were not configured"
                    v25 = {"status": "NOT_RUN"}
                    v25_ok = False
                    if status == PROPOSED and v25_5_gate is not None and metrics["v25_5_evaluations"] < budget.max_v25_5_candidates:
                        metrics["v25_5_evaluations"] += 1
                        first_path = candidate.changed_paths[0]
                        candidate_path = sandbox.sandbox_root / first_path
                        original_path = root / first_path
                        result = _invoke(v25_5_gate, first_path, candidate_path.read_text(encoding="utf-8"), original_path.read_text(encoding="utf-8"), pre_state_bytes=original_path.read_bytes(), candidate_files={p: (sandbox.sandbox_root / p).read_text(encoding="utf-8") for p in candidate.changed_paths})
                        v25_ok, v25, v25_reason = _bool_result(result)
                        if v25_ok:
                            metrics["v25_5_passes"] += 1
                        if not v25_ok:
                            status, reason = V25_5_REJECTED, v25_reason or "V25.5 gate rejected candidate"
                            metrics["strategy_v25_5_failures"] += 1
                            metrics["v25_5_rejected_candidates"] += 1
                    elif status == PROPOSED:
                        status, reason = V25_5_REJECTED, "V25.5 gate not supplied" if v25_5_gate is None else "V25.5 candidate budget reached"
                        metrics["v25_5_rejected_candidates"] += 1
                    sandbox_hash = canonical_subject_hash(sandbox.sandbox_root)
                    receipt = PatchCandidateReceipt(candidate.candidate_id, candidate.canonical_hash, status, before, sandbox_hash, tuple(applied.get("changed_paths", ())), syntax, targeted_data, guard_data, contract_data, v25, {}, (reason,) if reason else (), ("sandbox", "v25_5"), canonical_hash({"candidate": candidate.canonical_hash, "sandbox": sandbox_hash}), 0, sandbox.sandbox_identity, int(applied.get("diff_size", 0)), "PASSED_HARD_GATES" if status == PROPOSED else "REJECTED")
                    receipts.append(receipt)
                    if status in {PROPOSED, VIABLE} and v25_ok:
                        metrics["syntax_valid_candidates"] += 1
                        if metrics["syntax_valid_candidates"] <= budget.max_syntax_valid_candidates:
                            decision = next((item for item in decisions if item.candidate_id == candidate.metadata.get("source_candidate_id")), StrategyDecision(candidate.candidate_id, (candidate.strategy,)))
                            score_parts = _candidate_score_parts(candidate, decision, receipt)
                            scored_data = candidate.to_dict(include_hash=False)
                            scored_data["status"] = VIABLE
                            scored_data["score"] = sum(score_parts.values())
                            scored_data["score_contributions"] = score_parts
                            scored = PatchCandidate.from_value(scored_data)
                            evaluated_candidates.append(scored)
                            metrics["strategy_viable_count"] += 1
                        else:
                            reason = "syntax-valid candidate budget reached"
                            rejected.append(CandidateFailureEvidence(candidate.candidate_id, TARGET_FAILED, "budget", reason, (reason,), before, candidate.target_path))
                    else:
                        rejected.append(CandidateFailureEvidence(candidate.candidate_id, status, "evaluation", reason, (reason,), before, candidate.target_path))
            except (OSError, SandboxSecurityError, ValueError) as exc:
                status = TARGET_FAILED
                receipt = PatchCandidateReceipt(candidate.candidate_id, candidate.canonical_hash, status, before, violations=(str(exc),), evidence=("sandbox_exception",))
                receipts.append(receipt)
                rejected.append(CandidateFailureEvidence(candidate.candidate_id, status, "sandbox", str(exc), (str(exc),), before, candidate.target_path))
        # Full V25.6 is reserved for a bounded shortlist and only after V25.5.
        ranked = sorted(evaluated_candidates, key=lambda item: (-item.score, item.strategy, item.candidate_id))
        verified: list[PatchCandidate] = []
        if v25_6_verifier is not None:
            for candidate in ranked[:budget.max_full_v25_6_candidates]:
                metrics["full_v25_6_shortlist"] += 1
                metrics["v25_6_evaluations"] += 1
                metrics["full_v25_6_runs"] += 1
                # Full verification must observe the candidate state, never
                # the unchanged canonical subject.  Re-materialize only the
                # bounded finalist in a disposable sandbox.
                with ExperimentalSandbox(root, session_id=f"core5-v25-6-{candidate.candidate_id}") as finalist_sandbox:
                    metrics["candidate_sandboxes_created"] += 1
                    metrics["candidate_source_bytes_materialized"] += int(finalist_sandbox.sandbox_bytes_materialized)
                    finalist_ok, _, finalist_violations = _apply_candidate_to_sandbox(candidate, finalist_sandbox.sandbox_root, root)
                    if not finalist_ok:
                        result = {"passed": False, "reason": "; ".join(finalist_violations), "stage": "finalist_sandbox"}
                    else:
                        result = _invoke(v25_6_verifier, candidate, finalist_sandbox.sandbox_root)
                passed, data, reason = _bool_result(result)
                receipt_index = next((index for index, item in enumerate(receipts) if item.candidate_id == candidate.candidate_id), None)
                if passed:
                    verified_candidate = candidate.with_status(VERIFIED)
                    verified.append(verified_candidate)
                    metrics["verified_candidates"] += 1
                    if receipt_index is not None:
                        old = receipts[receipt_index]
                        receipts[receipt_index] = PatchCandidateReceipt(old.candidate_id, old.candidate_hash, VERIFIED, old.base_subject_hash, old.sandbox_subject_hash, old.changed_paths, old.syntax, old.targeted_checks, old.guard_checks, old.contract_checks, old.v25_5, data, old.violations, old.evidence + ("v25_6",), old.canonical_audit_hash, old.provider_calls, old.sandbox_identity, old.diff_size, "VERIFIED")
                else:
                    metrics["v25_6_failed_candidates"] += 1
                    rejected.append(CandidateFailureEvidence(candidate.candidate_id, V25_6_FAILED, "v25_6", reason or "V25.6 failed", (reason or "V25.6 failed",), before, candidate.target_path, details=data))
        viable = sorted(verified or ranked, key=lambda item: (-item.score, item.strategy, item.candidate_id))
        winner = viable[0] if viable else None
        if verified:
            next_action = VERIFIED_CANDIDATE
        elif winner:
            next_action = BEST_VIABLE_CANDIDATE
        elif generated:
            next_action = NO_VIABLE_PATCH_CANDIDATE
        else:
            next_action = PATCH_SEARCH_BUDGET_REACHED if len(records) >= budget.max_suspects else NO_VIABLE_PATCH_CANDIDATE
        after = canonical_subject_hash(root)
        metrics["candidates_deduplicated"] = len(dedup)
        metrics["viable_candidates"] = len(viable)
        metrics["rejected_candidates"] = len(rejected)
        metrics["repair_suspects_considered"] = metrics["suspects_considered"]
        metrics["deterministic_candidates"] = metrics["deterministic_generated"]
        metrics["candidate_files_changed"] = int(metrics["candidate_files_changed"])
        metrics["average_diff_lines"] = int(round(sum(item.diff_size for item in receipts) / max(1, len(receipts))))
        metrics["candidates_to_first_viable"] = next((index + 1 for index, item in enumerate(dedup) if item in viable), 0)
        metrics["candidates_to_verified"] = next((index + 1 for index, item in enumerate(dedup) if any(done.candidate_id == item.candidate_id for done in verified)), 0)
        metrics["syntax_valid_candidate_rate"] = int(round(100 * metrics["syntax_valid_candidates"] / max(1, len(dedup))))
        metrics["targeted_test_pass_rate"] = int(round(100 * metrics["targeted_passes"] / max(1, metrics["targeted_evaluations"])))
        metrics["guard_clean_rate"] = int(round(100 * metrics["guard_passes"] / max(1, metrics["guard_evaluations"])))
        metrics["v25_5_pass_rate"] = int(round(100 * metrics["v25_5_passes"] / max(1, metrics["v25_5_evaluations"])))
        metrics["v25_6_pass_rate"] = int(round(100 * metrics["verified_candidates"] / max(1, metrics["v25_6_evaluations"])))
        if len(generated) >= budget.max_candidates or len(dedup) >= budget.max_candidates:
            metrics["search_budget_reached"] = 1
        candidate_by_id = {item.candidate_id: item for item in generated}
        receipt_by_id = {item.candidate_id: item for item in receipts}
        enriched_rejected: list[CandidateFailureEvidence] = []
        for item in rejected:
            candidate = candidate_by_id.get(item.candidate_id)
            receipt = receipt_by_id.get(item.candidate_id)
            if candidate is None:
                enriched_rejected.append(item)
                continue
            anchors = tuple(operation.to_dict(include_hash=False) for operation in candidate.representation.operations)
            enriched_rejected.append(CandidateFailureEvidence(
                item.candidate_id, item.status, item.stage, item.reason, item.violations,
                item.subject_hash, item.target_path or candidate.target_path, item.canonical_hash_value,
                item.details, candidate.strategy, candidate.changed_paths, anchors,
                dict(receipt.syntax) if receipt else {},
            ))
        rejected = enriched_rejected
        return PatchSearchResult(
            problem=current, strategy_decisions=tuple(decisions), generated_candidates=tuple(generated), deduplicated_candidates=tuple(dedup),
            receipts=tuple(receipts), ranked_viable_candidates=tuple(viable), rejected_candidates=tuple(rejected), winner=winner,
            runner_up_or_pareto=tuple(viable[1: 1 + budget.max_pareto_alternatives]), budget_usage={"candidates": len(generated), "deterministic": metrics["deterministic_generated"], "model": metrics["model_generated"], "v25_5": metrics["v25_5_evaluations"], "v25_6": metrics["v25_6_evaluations"]},
            metrics=metrics, unresolved_evidence=tuple({"kind": "UNRESOLVED_CANDIDATE", "candidate_id": item.candidate_id, "path": item.target_path} for item in generated if item not in viable),
            next_action=next_action, source_unchanged=before == after, canonical_before=before, canonical_after=after,
        )


def search_patch_candidates(problem: RepairProblem | Mapping[str, Any], project_root: str | Path | None = None, **kwargs: Any) -> PatchSearchResult:
    return PatchSearchEngine().search(problem, project_root, **kwargs)


def apply_selected_patch_candidate(
    candidate: PatchCandidate | Mapping[str, Any], project_root: str | Path, *,
    authority: Mapping[str, Any] | None = None, dnt_paths: Iterable[str] = (),
    expected_subject_hash: str = "", expected_candidate_hash: str = "",
    current_revision_identity: str = "", v25_5_gate: Any = None, mutation_executor: Any = None,
) -> dict[str, Any]:
    """Explicit canonical application seam; search never calls this function."""
    selected = candidate if isinstance(candidate, PatchCandidate) else PatchCandidate.from_value(candidate)
    root = Path(project_root).expanduser().resolve()
    before = canonical_subject_hash(root)
    if expected_candidate_hash and expected_candidate_hash != selected.canonical_hash:
        return {"applied": False, "status": STALE_BASE, "reason": "candidate hash does not match the selected proposal"}
    if expected_subject_hash and expected_subject_hash != before:
        return {"applied": False, "status": STALE_BASE, "reason": "current subject hash differs from candidate base"}
    if selected.candidate_source_hash and len(selected.candidate_source_hash) == 64 and selected.candidate_source_hash != before:
        return {"applied": False, "status": STALE_BASE, "reason": "candidate source hash is stale"}
    if current_revision_identity and selected.base_revision_identity and current_revision_identity != selected.base_revision_identity:
        return {"applied": False, "status": STALE_BASE, "reason": "candidate revision identity is stale"}
    if selected.status not in {VIABLE, VERIFIED}:
        return {"applied": False, "status": AUTHORITY_BLOCKED, "reason": "only viable or verified candidates may be explicitly applied"}
    if v25_5_gate is None:
        return {"applied": False, "status": V25_5_REJECTED, "reason": "the real V25.5 gate is required for canonical application"}
    authority_map = dict(authority or {})
    dnt = {str(item).replace("\\", "/").lstrip("./") for item in dnt_paths}
    for key in ("dnt", "do_not_touch", "approved_dnt", "approved_do_not_touch"):
        raw = authority_map.get(key, ())
        if isinstance(raw, str):
            raw = (raw,)
        dnt.update(str(item).replace("\\", "/").lstrip("./") for item in raw or ())
    approved = set()
    for key in ("approved_mutation_scope", "mutation_scope", "authorized_paths", "approved_scope", "mutation_targets"):
        raw = authority_map.get(key, ())
        if isinstance(raw, str): raw = (raw,)
        if isinstance(raw, Mapping): raw = raw.get("paths", raw.get("files", ()))
        approved.update(str(item).replace("\\", "/").lstrip("./") for item in raw or ())
    if not approved:
        return {"applied": False, "status": AUTHORITY_BLOCKED, "reason": "existing approved mutation scope is required"}
    for operation in selected.representation.operations:
        if operation.path in dnt:
            return {"applied": False, "status": AUTHORITY_BLOCKED, "reason": f"DNT protected: {operation.path}"}
        if approved and operation.path not in approved:
            return {"applied": False, "status": AUTHORITY_BLOCKED, "reason": f"outside authorized mutation scope: {operation.path}"}
        target = _safe_target(root, operation.path)
        current = target.read_bytes().decode("utf-8", errors="replace")
        if operation.expected_file_hash and _sha_bytes(target.read_bytes()) != operation.expected_file_hash:
            return {"applied": False, "status": STALE_BASE, "reason": f"stale file anchor: {operation.path}"}
        updated, reason = operation.apply(current)
        if reason:
            return {"applied": False, "status": STALE_BASE, "reason": reason}
        syntax = validate_source_syntax(operation.path, updated)
        if not syntax.valid:
            return {"applied": False, "status": SYNTAX_INVALID, "reason": syntax.error}
        if v25_5_gate is not None:
            result = _invoke(v25_5_gate, operation.path, updated, current, pre_state_bytes=target.read_bytes())
            allowed, data, reason = _bool_result(result)
            if not allowed:
                return {"applied": False, "status": V25_5_REJECTED, "reason": reason, "v25_5": data}
    if mutation_executor is not None:
        result = _invoke(mutation_executor, selected, root)
        passed, data, reason = _bool_result(result)
        return {"applied": passed, "status": "APPLIED" if passed else TARGET_FAILED, "reason": reason, "executor": data, "before": before, "after": canonical_subject_hash(root) if passed else before}
    for operation in selected.representation.operations:
        target = _safe_target(root, operation.path)
        current = target.read_bytes().decode("utf-8", errors="replace")
        updated, _ = operation.apply(current)
        target.write_bytes(updated.encode("utf-8"))
    after = canonical_subject_hash(root)
    return {"applied": True, "status": "APPLIED", "before": before, "after": after, "changed_paths": list(selected.changed_paths), "candidate_hash": selected.canonical_hash}


def update_repository_indexes_after_application(repository_map: RepositoryMap, lexical_index: LexicalIndex | None, project_root: str | Path, *, changed_paths: Iterable[str] = (), deleted_paths: Iterable[str] = ()) -> tuple[RepositoryMap, LexicalIndex | None]:
    updated_map = incremental_reindex(repository_map, project_root, changed_paths=changed_paths, deleted_paths=deleted_paths)
    updated_index = incremental_lexical_update(lexical_index, updated_map, project_root, changed_paths=changed_paths, deleted_paths=deleted_paths) if lexical_index is not None else None
    return updated_map, updated_index


def benchmark_patch_search_scenarios(scenarios: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        result = search_patch_candidates(scenario["problem"], scenario["project_root"], **dict(scenario.get("search_kwargs", {})))
        rows.append({"name": str(scenario.get("name", "scenario")), "winner": result.winner.candidate_id if result.winner else None, "generated": len(result.generated_candidates), "viable": len(result.ranked_viable_candidates), "metrics": dict(result.metrics), "next_action": result.next_action})
    return {"benchmark_kind": "DETERMINISTIC_CORE5_PATCH_SEARCH", "scenario_count": len(rows), "provider_calls": 0, "scenarios": rows}


__all__ = [
    "CORE5_SEARCH_SCHEMA_VERSION", "VERIFIED_CANDIDATE", "BEST_VIABLE_CANDIDATE", "APPLY_SELECTED_CANDIDATE", "NO_VIABLE_PATCH_CANDIDATE", "PATCH_SEARCH_BUDGET_REACHED",
    "PatchSearchResult", "PatchSearchEngine", "search_patch_candidates", "apply_selected_patch_candidate", "update_repository_indexes_after_application", "benchmark_patch_search_scenarios",
]
