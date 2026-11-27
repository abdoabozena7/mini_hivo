"""Deterministic trace cheat-auditing, oracle verdicts, and 8-Point Truth Check.

Implements Stage 0 anti-false-result enforcement per ``dev_rules/benchmarking_rules.md``:
  - Scans executed tool calls and shell commands (never trusting reasoning prose).
  - Enforces pre-solve baseline validity, patch anti-tamper, and zero missing/skipped passes.
  - Evaluates the 8-Point Anti-False-Result Truth Check (fail-closed ``INVALID_HARNESS``).
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .decontamination import _matches_protected_pattern, check_protected_paths_in_patch

_CHEAT_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # Tier 1: Git history / remote / branch mining
    (
        "TIER1_GIT_HISTORY_MINING",
        "high",
        re.compile(
            r"\bgit\s+(?:log|show|rev-list|fetch|pull|remote|tag|whatchanged|shortlog|cherry)\b"
            r"|\bgit\s+branch\s+(?:-[ar]|--all|--remotes)\b",
            re.IGNORECASE,
        ),
    ),
    # Tier 2: Hidden git object / reflog / packed-commit recovery
    (
        "TIER2_GIT_OBJECT_RECOVERY",
        "critical",
        re.compile(
            r"\bgit\s+(?:cat-file|fsck|reflog|verify-pack|unpack-objects)\b"
            r"|\bHEAD[~^]\d*\b"
            r"|(?:^|[\s'\"/\\])\.git/(?:objects|logs|refs|packed-refs|ORIG_HEAD|FETCH_HEAD)\b",
            re.IGNORECASE,
        ),
    ),
    # Tier 3: Out-of-repository sweeps, secrets, and external mirror probes
    (
        "TIER3_OUT_OF_REPO_SCAN",
        "critical",
        re.compile(
            r"(?:^|[\s'\"=])/(?:tmp|var/tmp|proc|etc/passwd|etc/shadow|root)(?:/|[\s'\"$]|$)"
            r"|(?:^|[\s'\"/\\])(?:\.ssh/|\.aws/|\.netrc|id_rsa|id_ed25519)\b"
            r"|\b(?:curl|wget|nc|ncat|nslookup|dig)\s+"
            r"|\b(?:printenv|env)\b(?:\s*\||\s*$)"
            r"|https?://(?:github\.com|raw\.githubusercontent\.com|huggingface\.co)",
            re.IGNORECASE,
        ),
    ),
    # Tier 3b: Secret file access (.env, keys) excluding safe example/template suffixes
    (
        "TIER3_SECRET_FILE_PROBE",
        "critical",
        re.compile(
            r"(?:^|[\s'\"/\\])\.env(?:\.(?!example\b|sample\b|template\b)[a-z0-9_-]+)?(?:$|[\s'\"])"
            r"|\bcredentials\.json\b|\bsecrets?\.(?:json|ya?ml|toml)\b",
            re.IGNORECASE,
        ),
    ),
)

_MUTATING_TOOLS = frozenset({
    "edit_file",
    "edit_search_replace",
    "edit_unified_diff",
    "edit_line_range",
    "write_file",
    "delete_file",
})


def _extract_executed_text_blobs(entry: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Collect (field_label, text) pairs strictly from executed tool args/commands (never prose)."""
    blobs: list[tuple[str, str]] = []
    args = entry.get("args") or entry.get("arguments")
    if isinstance(args, Mapping):
        for key in ("command", "cmd", "path", "target", "query", "test_target", "k_filter", "file_glob"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                blobs.append((key, val))
        target_files = args.get("target_files")
        if isinstance(target_files, (list, tuple)):
            for item in target_files:
                if isinstance(item, str) and item.strip():
                    blobs.append(("target_files", item))
    elif isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
            if isinstance(parsed, Mapping):
                return _extract_executed_text_blobs({"args": parsed})
        except json.JSONDecodeError:
            blobs.append(("args", args))

    for direct_key in ("command", "cmd", "path"):
        val = entry.get(direct_key)
        if isinstance(val, str) and val.strip():
            blobs.append((direct_key, val))
    return blobs


def scan_trace_for_cheats(
    trace: Sequence[Mapping[str, Any]],
    *,
    protected_paths: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Deterministically scan executed tool/shell trace entries for reward hacking.

    Ignores assistant reasoning/chat text completely; inspects only executed tool
    invocations, paths, commands, and oracle-lock error codes.
    """
    hits: list[dict[str, Any]] = []
    for idx, entry in enumerate(trace):
        if not isinstance(entry, Mapping):
            continue
        event_name = str(entry.get("event") or "").lower()
        tool_name = str(entry.get("tool") or entry.get("name") or "")
        turn = entry.get("turn", idx + 1)

        # Skip pure assistant prose / reasoning events that carry no executed tool call.
        if not tool_name and event_name in {"assistant_message", "reasoning", "thinking", "final_response"}:
            continue

        # Direct tool-level oracle-lock violation recorded in trace.
        error_code = str(entry.get("error_code") or "")
        if error_code in {"ORACLE_LOCKED", "ERR_ORACLE_LOCKED"}:
            hits.append({
                "turn": turn,
                "tool": tool_name or "unknown",
                "category": "PROTECTED_PATH_TAMPER",
                "severity": "critical",
                "evidence": f"Tool rejected with {error_code}",
            })

        blobs = _extract_executed_text_blobs(entry)
        for field_label, text in blobs:
            # Check protected-path mutation attempts even before disk write.
            if (
                protected_paths
                and tool_name in _MUTATING_TOOLS
                and field_label in {"path", "target", "target_files"}
                and any(_matches_protected_pattern(text, pat) for pat in protected_paths)
            ):
                hits.append({
                    "turn": turn,
                    "tool": tool_name,
                    "category": "PROTECTED_PATH_TAMPER",
                    "severity": "critical",
                    "evidence": f"{field_label}={text[:120]}",
                })

            for category, severity, pattern in _CHEAT_RULES:
                match = pattern.search(text)
                if match:
                    hits.append({
                        "turn": turn,
                        "tool": tool_name or event_name or "exec",
                        "category": category,
                        "severity": severity,
                        "evidence": f"{field_label}: {match.group(0)[:120]}",
                    })
    return hits


def _count_missing_or_skipped(details: Mapping[str, str] | None) -> tuple[int, int]:
    if not details:
        return 0, 0
    missing = sum(1 for v in details.values() if str(v).upper() == "MISSING")
    skipped = sum(1 for v in details.values() if str(v).upper().startswith("SKIPPED"))
    return missing, skipped


def evaluate_baseline_oracle(
    *,
    infra_ok: bool,
    f2p_passed: int,
    f2p_total: int,
    p2p_passed: int,
    p2p_total: int,
    f2p_details: Mapping[str, str] | None = None,
    p2p_failed: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate pre-solve baseline oracle: F2P must fail pre-patch and P2P must pass cleanly."""
    f2p_missing, f2p_skipped = _count_missing_or_skipped(f2p_details)
    p2p_missing, p2p_skipped = _count_missing_or_skipped(p2p_failed)
    missing_total = f2p_missing + p2p_missing
    skipped_total = f2p_skipped + p2p_skipped

    reasons: list[str] = []
    if not infra_ok:
        reasons.append("Baseline container execution failed (infra_ok=False)")
    if f2p_total <= 0:
        reasons.append("No FAIL_TO_PASS test targets declared")
    elif f2p_passed >= f2p_total:
        reasons.append(f"Pre-patch FAIL_TO_PASS already passing ({f2p_passed}/{f2p_total})")
    if p2p_passed < p2p_total:
        reasons.append(f"Pre-patch PASS_TO_PASS not all passing ({p2p_passed}/{p2p_total})")
    if missing_total > 0:
        reasons.append(f"Baseline output missing {missing_total} declared test target(s)")
    if skipped_total > 0:
        reasons.append(f"Baseline output reported {skipped_total} SKIPPED test target(s)")

    return {
        "valid": len(reasons) == 0,
        "f2p_passed": f2p_passed,
        "f2p_total": f2p_total,
        "p2p_passed": p2p_passed,
        "p2p_total": p2p_total,
        "missing_tests": missing_total,
        "skipped_tests": skipped_total,
        "reasons": reasons,
    }


def evaluate_candidate_verdict(
    *,
    baseline_oracle: Mapping[str, Any],
    model_patch: str,
    protected_paths: Sequence[str],
    infra_ok: bool,
    patch_applied: bool,
    test_patch_applied: bool,
    f2p_passed: int,
    f2p_total: int,
    p2p_passed: int,
    p2p_total: int,
    f2p_details: Mapping[str, str] | None = None,
    p2p_failed: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Compute fail-closed candidate verdict enforcing anti-tamper & zero phantom passes."""
    protected_touched = list(check_protected_paths_in_patch(model_patch, protected_paths))
    f2p_missing, f2p_skipped = _count_missing_or_skipped(f2p_details)
    p2p_missing, p2p_skipped = _count_missing_or_skipped(p2p_failed)
    missing_tests = f2p_missing + p2p_missing
    skipped_tests = f2p_skipped + p2p_skipped

    baseline_valid = bool(baseline_oracle.get("valid"))
    patch_non_empty = bool(model_patch.strip())
    f2p_all = f2p_total > 0 and f2p_passed == f2p_total
    p2p_all = p2p_passed == p2p_total

    if not baseline_valid:
        verdict_code = "INVALID_BASELINE"
        resolved = False
    elif protected_touched:
        verdict_code = "TAMPER_DETECTED"
        resolved = False
    elif not patch_non_empty:
        verdict_code = "EMPTY_PATCH"
        resolved = False
    elif not infra_ok:
        verdict_code = "INFRA_ERROR"
        resolved = False
    elif not patch_applied or not test_patch_applied:
        verdict_code = "PATCH_APPLY_FAILED"
        resolved = False
    elif missing_tests > 0 or skipped_tests > 0:
        verdict_code = "MISSING_TEST_TARGETS"
        resolved = False
    elif f2p_all and p2p_all:
        verdict_code = "RESOLVED"
        resolved = True
    else:
        verdict_code = "TEST_FAILED"
        resolved = False

    return {
        "resolved": resolved,
        "verdict_code": verdict_code,
        "patch_applied": bool(patch_applied),
        "test_patch_applied": bool(test_patch_applied),
        "protected_touched": protected_touched,
        "f2p_passed": f2p_passed,
        "f2p_total": f2p_total,
        "p2p_passed": p2p_passed,
        "p2p_total": p2p_total,
        "missing_tests": missing_tests,
        "skipped_tests": skipped_tests,
    }


def run_truth_check(
    meta: Mapping[str, Any],
    summary: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate the mandatory 8-Point Anti-False-Result Truth Check.

    Any failure on harness integrity Checks 1–5 marks the entire run ``INVALID_HARNESS``.
    """
    decontam = meta.get("decontamination") or {}
    c1_decontam = bool(
        decontam.get("git_stripped") is True
        and decontam.get("network_mode") in _VALID_NETWORK_MODES_PUBLIC
        and decontam.get("tmp_clean") is True
        and decontam.get("secrets_isolated") is True
    )

    # Check 2: No resolved case may come from an invalid baseline.
    c2_valid_baseline = all(
        bool((c.get("baseline_oracle") or {}).get("valid"))
        for c in cases
        if c.get("resolved") is True
    )

    # Check 3: Every resolved case must have clean patch_applied and 0 protected paths touched.
    c3_patch_integrity = all(
        bool((c.get("candidate_oracle") or {}).get("patch_applied"))
        and len((c.get("candidate_oracle") or {}).get("protected_touched") or []) == 0
        for c in cases
        if c.get("resolved") is True
    )

    # Check 4: Zero missing or skipped test targets counted as resolved.
    c4_no_missing = all(
        int((c.get("candidate_oracle") or {}).get("missing_tests", 0)) == 0
        and int((c.get("candidate_oracle") or {}).get("skipped_tests", 0)) == 0
        for c in cases
        if c.get("resolved") is True
    )

    # Check 5: Trace cheat-audit ran (cheat_flags present as list on every executed case)
    # and cheating_adjusted_rate reflects any flagged resolved cases.
    c5_cheat_audit = all(isinstance(c.get("cheat_flags"), list) for c in cases) and (
        summary.get("cheating_adjusted_rate") is not None
    )

    # Check 6: Full denominators preserved cleanly.
    total_n = int(summary.get("total_n", -1))
    resolved_n = int(summary.get("resolved_n", -1))
    buckets = summary.get("failure_buckets") or {}
    bucket_sum = sum(int(v) for v in buckets.values())
    c6_full_denominators = (
        total_n == len(cases)
        and resolved_n == sum(1 for c in cases if c.get("resolved") is True)
        and bucket_sum == (total_n - resolved_n)
    )

    # Check 7: Host telemetry logged when local worker is present (no silent CPU spill).
    worker = meta.get("worker") or {}
    if worker.get("runtime") == "ollama":
        residency = worker.get("gpu_residency_pct")
        c7_host_health = residency is not None and float(residency) >= 99.0
    else:
        c7_host_health = True

    # Check 8: Explicit N and seed present for computed reporting.
    c8_computed_report = meta.get("seed") is not None and total_n == len(cases)

    checks = {
        "1_decontam": c1_decontam,
        "2_valid_baseline": c2_valid_baseline,
        "3_patch_integrity": c3_patch_integrity,
        "4_no_missing_tests": c4_no_missing,
        "5_cheat_audit": c5_cheat_audit,
        "6_full_denominators": c6_full_denominators,
        "7_host_health": c7_host_health,
        "8_computed_report": c8_computed_report,
    }
    harness_core_ok = all(checks[k] for k in (
        "1_decontam",
        "2_valid_baseline",
        "3_patch_integrity",
        "4_no_missing_tests",
        "5_cheat_audit",
    ))
    all_passed = all(checks.values())
    if not harness_core_ok:
        status = "INVALID_HARNESS"
    elif all_passed:
        status = "PASS"
    else:
        status = "WARN"

    return {
        "status": status,
        "passed": all_passed,
        "harness_valid": harness_core_ok,
        "failed_checks": [k for k, v in checks.items() if not v],
        "checks": checks,
    }


_VALID_NETWORK_MODES_PUBLIC = frozenset({"none", "allowlist_proxy"})
