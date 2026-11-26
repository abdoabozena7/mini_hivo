"""Deterministic KPI math, 6-bucket failure triage, and canonical 3-key results builder.

Implements ``pass^k``, latency percentiles, cache hit rates, cost per resolved task,
6-stage harness funnel metrics, and strict sanity-bound assertions for Mini Hivo.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .audit import run_truth_check

FAILURE_BUCKET_KEYS: tuple[str, ...] = (
    "1_infra_quota_baseline",
    "2_tool_protocol_anchor",
    "3_localization",
    "4_worker_edit_fidelity",
    "5_verification_turn_budget",
    "6_reasoning_ceiling",
)


def _assert_unit_interval(name: str, value: float | None) -> None:
    if value is None:
        return
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"Metric {name!r} produced non-finite value: {value}")
    if value < -1e-9 or value > 1.0 + 1e-9:
        raise ValueError(f"Metric {name!r} out of [0, 1] bounds: {value}")


def compute_pass_hat_k(
    task_trial_outcomes: Sequence[Sequence[bool]],
    k: int,
) -> float:
    """Compute Sierra / Anthropic ``pass^k = E_task[ C(c, k) / C(n, k) ]``.

    Raises ``ValueError`` if ``k < 1``, ``task_trial_outcomes`` is empty, or any
    task has fewer than ``k`` trials.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if not task_trial_outcomes:
        raise ValueError("task_trial_outcomes must be non-empty")

    total = 0.0
    for idx, outcomes in enumerate(task_trial_outcomes):
        n = len(outcomes)
        if n < k:
            raise ValueError(f"Task {idx} has {n} trials, which is fewer than k={k}")
        c = sum(1 for passed in outcomes if bool(passed))
        denom = math.comb(n, k)
        total += (math.comb(c, k) / denom) if c >= k else 0.0

    val = total / len(task_trial_outcomes)
    _assert_unit_interval(f"pass^{k}", val)
    return round(val, 6)


def compute_percentile(values: Sequence[float], p: float) -> float | None:
    """Return linear-interpolated percentile ``p`` (0..100) or ``None`` if empty."""
    if not (0.0 <= p <= 100.0):
        raise ValueError(f"Percentile p must be in [0, 100], got {p}")
    clean = [float(v) for v in values if v is not None]
    for v in clean:
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Non-finite latency value encountered: {v}")
    if not clean:
        return None
    clean.sort()
    if len(clean) == 1:
        return round(clean[0], 2)
    rank = (p / 100.0) * (len(clean) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    frac = rank - lo
    interp = clean[lo] + frac * (clean[hi] - clean[lo])
    return round(interp, 2)


def classify_failure_bucket(case: Mapping[str, Any]) -> str | None:
    """Assign a non-passing case deterministically to one of the 6 canonical failure buckets."""
    if case.get("resolved") is True:
        return None

    explicit = case.get("failure_bucket")
    if isinstance(explicit, str) and explicit in FAILURE_BUCKET_KEYS:
        return explicit

    baseline = case.get("baseline_oracle") or {}
    cand = case.get("candidate_oracle") or {}
    funnel = case.get("funnel") or {}
    status = str(case.get("agent_status") or case.get("status") or "").lower()
    verdict = str(cand.get("verdict_code") or "").upper()
    err = str(case.get("agent_error") or case.get("error") or "").lower()

    # Bucket 1: Infra, Quota, or Invalid Baseline (never tune prompts for this)
    if (
        baseline.get("valid") is False
        or verdict in {"INVALID_BASELINE", "INFRA_ERROR"}
        or status in {"invalid_baseline", "docker_pull_failed", "provider_error", "quota_blocked", "infra_error"}
        or any(tok in err for tok in ("429", "413", "rate limit", "quota", "docker", "conda", "connection"))
    ):
        return "1_infra_quota_baseline"

    # Bucket 2: Tool / Protocol / Anchor Friction
    tool_schema_errors = int(funnel.get("tool_schema_errors", 0))
    dispatches = int(funnel.get("dispatches", 0))
    if tool_schema_errors >= 2 and dispatches == 0:
        return "2_tool_protocol_anchor"

    # Bucket 3: Localization Failure
    if funnel.get("localized") is False or (dispatches == 0 and verdict == "EMPTY_PATCH"):
        return "3_localization"

    # Bucket 4: Worker Edit Fidelity (localized, dispatched, yet rollback/empty/bad patch)
    rollbacks = int(funnel.get("rollbacks", 0))
    if verdict in {"EMPTY_PATCH", "PATCH_APPLY_FAILED", "TAMPER_DETECTED"} or (
        rollbacks > 0 and cand.get("patch_applied") is False
    ):
        return "4_worker_edit_fidelity"

    # Bucket 5: Verification / Turn-Budget Exhaustion
    if status in {"max_turns", "timeout", "elapsed_exceeded", "budget_exceeded"} or any(
        tok in err for tok in ("max_turns", "max_orchestrator_turns", "timed out", "elapsed")
    ):
        return "5_verification_turn_budget"

    # Bucket 6: True Reasoning / Architecture Ceiling
    return "6_reasoning_ceiling"


def build_benchmark_results(
    meta: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    pass_k: int = 1,
) -> dict[str, Any]:
    """Aggregate per-case outcomes into Mini Hivo's canonical 3-key ``results.json`` envelope.

    Enforces strict sanity-bound assertions (conserved denominators, rates in ``[0, 1]``,
    ``cheating_adjusted_rate <= valid_resolve_rate``, zero NaNs) and attaches the
    programmatic 8-Point Anti-False-Result Truth Check to ``meta.truth_check``.
    """
    normalized_cases: list[dict[str, Any]] = []
    buckets: dict[str, int] = {k: 0 for k in FAILURE_BUCKET_KEYS}

    total_n = len(cases)
    invalid_baseline_n = 0
    infra_or_quota_blocked_n = 0
    resolved_n = 0
    clean_resolved_n = 0

    total_usd = 0.0
    orch_in_total = 0
    orch_cached_total = 0
    latencies: list[float] = []

    trial_matrix: list[list[bool]] = []
    localized_flags: list[bool] = []
    total_dispatches = 0
    total_rollbacks = 0
    total_tool_calls = 0
    total_schema_errors = 0

    for raw in cases:
        case = dict(raw)
        is_resolved = bool(case.get("resolved"))
        baseline = case.get("baseline_oracle") or {}
        cheat_flags = case.get("cheat_flags")
        if cheat_flags is None:
            cheat_flags = []
            case["cheat_flags"] = cheat_flags

        bucket = classify_failure_bucket(case)
        case["failure_bucket"] = bucket
        if not is_resolved and bucket is not None:
            buckets[bucket] += 1

        if baseline.get("valid") is False:
            invalid_baseline_n += 1
        elif not is_resolved and bucket == "1_infra_quota_baseline":
            infra_or_quota_blocked_n += 1

        if is_resolved:
            resolved_n += 1
            if len(cheat_flags) == 0:
                clean_resolved_n += 1

        trials = case.get("trial_outcomes")
        if isinstance(trials, Sequence) and not isinstance(trials, (str, bytes)) and len(trials) > 0:
            trial_matrix.append([bool(t) for t in trials])
        else:
            trial_matrix.append([is_resolved])
            case["trial_outcomes"] = [is_resolved]

        usd = float(case.get("usd") or 0.0)
        if math.isnan(usd) or math.isinf(usd) or usd < 0.0:
            raise ValueError(f"Invalid case USD spend for {case.get('task_id')}: {usd}")
        total_usd += usd

        tokens = case.get("tokens") or {}
        orch_in_total += int(tokens.get("orch_in") or 0)
        orch_cached_total += int(tokens.get("orch_cached_in") or 0)

        lat = case.get("latency_ms")
        if lat is not None:
            latencies.append(float(lat))

        funnel = case.get("funnel") or {}
        if "localized" in funnel and funnel["localized"] is not None:
            localized_flags.append(bool(funnel["localized"]))
        total_dispatches += int(funnel.get("dispatches") or 0)
        total_rollbacks += int(funnel.get("rollbacks") or 0)
        total_tool_calls += int(funnel.get("tool_calls") or 0)
        total_schema_errors += int(funnel.get("tool_schema_errors") or 0)

        normalized_cases.append(case)

    valid_non_blocked_n = max(0, total_n - invalid_baseline_n - infra_or_quota_blocked_n)
    raw_resolve_rate = round(resolved_n / total_n, 4) if total_n > 0 else 0.0
    valid_resolve_rate = round(resolved_n / valid_non_blocked_n, 4) if valid_non_blocked_n > 0 else 0.0
    cheating_adjusted_rate = round(clean_resolved_n / valid_non_blocked_n, 4) if valid_non_blocked_n > 0 else 0.0

    # Compute pass^k across eligible trial sets if non-empty.
    if trial_matrix and all(len(t) >= pass_k for t in trial_matrix):
        pass_hat_val: float | None = compute_pass_hat_k(trial_matrix, pass_k)
        n_trials_min = min(len(t) for t in trial_matrix)
    else:
        pass_hat_val = None
        n_trials_min = min((len(t) for t in trial_matrix), default=0)

    cache_hit_rate = (
        round(min(orch_cached_total, orch_in_total) / orch_in_total, 4)
        if orch_in_total > 0
        else None
    )
    usd_per_resolved = round(total_usd / resolved_n, 4) if resolved_n > 0 else None

    tool_schema_validity_rate = (
        round(max(0, total_tool_calls - total_schema_errors) / total_tool_calls, 4)
        if total_tool_calls > 0
        else None
    )
    localization_recall_rate = (
        round(sum(1 for x in localized_flags if x) / len(localized_flags), 4)
        if localized_flags
        else None
    )
    worker_rollback_rate = (
        round(min(total_rollbacks, total_dispatches) / total_dispatches, 4)
        if total_dispatches > 0
        else None
    )
    worker_edit_fidelity_rate = (
        round(max(0, total_dispatches - total_rollbacks) / total_dispatches, 4)
        if total_dispatches > 0
        else None
    )

    # Sanity-bound assertions
    for name, val in (
        ("raw_resolve_rate", raw_resolve_rate),
        ("valid_resolve_rate", valid_resolve_rate),
        ("cheating_adjusted_rate", cheating_adjusted_rate),
        ("pass_hat_k", pass_hat_val),
        ("cache_hit_rate", cache_hit_rate),
        ("tool_schema_validity_rate", tool_schema_validity_rate),
        ("localization_recall_rate", localization_recall_rate),
        ("worker_rollback_rate", worker_rollback_rate),
        ("worker_edit_fidelity_rate", worker_edit_fidelity_rate),
    ):
        _assert_unit_interval(name, val)

    if cheating_adjusted_rate > valid_resolve_rate + 1e-9:
        raise ValueError("Sanity violation: cheating_adjusted_rate exceeded valid_resolve_rate")
    if sum(buckets.values()) != (total_n - resolved_n):
        raise ValueError(
            f"Sanity violation: failure bucket sum ({sum(buckets.values())}) != failed count ({total_n - resolved_n})"
        )

    summary: dict[str, Any] = {
        "total_n": total_n,
        "invalid_baseline_n": invalid_baseline_n,
        "infra_or_quota_blocked_n": infra_or_quota_blocked_n,
        "valid_non_blocked_n": valid_non_blocked_n,
        "resolved_n": resolved_n,
        "clean_resolved_n": clean_resolved_n,
        "raw_resolve_rate": raw_resolve_rate,
        "valid_resolve_rate": valid_resolve_rate,
        "cheating_adjusted_rate": cheating_adjusted_rate,
        "pass_hat_k": {"k": pass_k, "n_trials": n_trials_min, "value": pass_hat_val},
        "total_usd": round(total_usd, 4),
        "usd_per_resolved": usd_per_resolved,
        "cache_hit_rate": cache_hit_rate,
        "latency_p50_ms": compute_percentile(latencies, 50.0),
        "latency_p95_ms": compute_percentile(latencies, 95.0),
        "funnel": {
            "tool_schema_validity_rate": tool_schema_validity_rate,
            "localization_recall_rate": localization_recall_rate,
            "worker_edit_fidelity_rate": worker_edit_fidelity_rate,
            "worker_rollback_rate": worker_rollback_rate,
        },
        "failure_buckets": buckets,
    }

    meta_out = dict(meta)
    meta_out["truth_check"] = run_truth_check(meta_out, summary, normalized_cases)

    return {
        "meta": meta_out,
        "summary": summary,
        "cases": normalized_cases,
    }
