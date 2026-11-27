"""Unified offline verification and PR gate runner for Mini Hivo.

Shared by developers, coding agents (AGENTS.md / CLAUDE.md), and GitHub Actions
CI so local checks and PR checks stay 100% identical and strictly offline (zero
LLM API calls, zero accidental runs of legacy live-provider tests).

Usage:
    python scripts/check.py                  # All active v2 offline tests + worklog check
    python scripts/check.py --tools          # hivo/tools offline tests only
    python scripts/check.py --orchestration  # hivo/providers + hivo/hybrid tests only
    python scripts/check.py --worklogs       # worklog/check tests + INDEX.md --check
    python scripts/check.py --ci-diff BASE   # Enforce PR Hard Rule Lock + tests-touched gates
"""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent

LOCKED_RULE_FILES = frozenset({"AGENTS.md", "CLAUDE.md"})


def _normalize_rel(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")


def is_locked_rule_path(rel_path: str) -> bool:
    """Return True if *rel_path* is protected by the Hard Rule Lock."""
    norm = _normalize_rel(rel_path)
    if not norm:
        return False
    p = PurePosixPath(norm)
    if norm in LOCKED_RULE_FILES:
        return True
    if p.name == "AGENTS.md":
        return True
    if len(p.parts) >= 2 and p.parts[0] == "dev_rules" and p.suffix == ".md":
        return True
    return False


def is_governed_code_path(rel_path: str) -> bool:
    """Return True if *rel_path* is runtime/script Python code requiring tests."""
    norm = _normalize_rel(rel_path)
    if not norm:
        return False
    p = PurePosixPath(norm)
    if p.suffix != ".py":
        return False
    return len(p.parts) >= 2 and p.parts[0] in {"hivo", "scripts"}


def is_test_path(rel_path: str) -> bool:
    """Return True if *rel_path* is a test file under tests/."""
    norm = _normalize_rel(rel_path)
    if not norm:
        return False
    p = PurePosixPath(norm)
    return len(p.parts) >= 2 and p.parts[0] == "tests" and p.suffix == ".py"


def evaluate_pr_diff_gates(
    changed_files: list[str],
    *,
    allow_rule_edits: bool = False,
    allow_no_tests: bool = False,
) -> list[str]:
    """Check PR-level Hard Rule Lock and code-requires-tests gates.

    Returns a list of human-readable error strings (empty list = PASS).
    """
    errors: list[str] = []
    normalized = [_normalize_rel(f) for f in changed_files if f.strip()]

    locked_touched = sorted(f for f in normalized if is_locked_rule_path(f))
    if locked_touched and not allow_rule_edits:
        joined = ", ".join(locked_touched)
        errors.append(
            f"Hard Rule Lock violation: PR modifies read-only rule file(s): {joined}. "
            "Revert rule edits and emit a Proposed Rule Update (NOT APPLIED) in your worklog REPORT.md "
            "(or have a maintainer apply the 'rule-approved' PR label on a dedicated rule-review PR)."
        )

    code_touched = sorted(f for f in normalized if is_governed_code_path(f))
    tests_touched = sorted(f for f in normalized if is_test_path(f))
    if code_touched and not tests_touched and not allow_no_tests:
        joined = ", ".join(code_touched)
        errors.append(
            f"Missing tests for code change: PR modifies {joined} without updating any test under tests/. "
            "Add/update offline unit or regression tests (including at least one negative/boundary case), "
            "or ask a maintainer to apply the 'no-tests-needed' label if purely non-functional."
        )

    return errors


def discover_v2_test_modules(
    repo_root: Path,
    *,
    tools: bool = False,
    orchestration: bool = False,
    worklogs: bool = False,
) -> list[str]:
    """Return sorted unittest dotted module names for the requested offline scopes."""
    run_all = not (tools or orchestration or worklogs)
    tests_dir = repo_root / "tests"
    patterns: list[str] = []
    if run_all or tools:
        patterns.append("test_tools_*.py")
    if run_all or orchestration:
        patterns.extend(["test_providers*.py", "test_hybrid_*.py"])
    if run_all or worklogs:
        patterns.extend(["test_worklog_index.py", "test_check_runner.py"])

    seen: set[str] = set()
    modules: list[str] = []
    for pattern in patterns:
        for path in sorted(tests_dir.glob(pattern)):
            if path.is_file():
                mod = f"tests.{path.stem}"
                if mod not in seen:
                    seen.add(mod)
                    modules.append(mod)
    return modules


def _run_cmd(cmd: list[str], cwd: Path) -> int:
    print(f"[RUN] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd))
    return proc.returncode


def _git_changed_files(repo_root: Path, base_ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed against '{base_ref}': {proc.stderr.strip()}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mini Hivo offline verification suites and PR gates.")
    parser.add_argument("--tools", action="store_true", help="Run hivo/tools offline tests.")
    parser.add_argument("--orchestration", action="store_true", help="Run hivo/providers & hivo/hybrid offline tests.")
    parser.add_argument("--worklogs", action="store_true", help="Run worklog/check tests and INDEX.md --check.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose unittest output.")
    parser.add_argument(
        "--ci-diff",
        metavar="BASE_REF",
        help="Validate changed files in BASE_REF...HEAD against Hard Rule Lock and code-requires-tests gates.",
    )
    parser.add_argument(
        "--allow-rule-edits",
        action="store_true",
        help="Permit rule-file edits in --ci-diff mode (used by CI when PR has 'rule-approved' label).",
    )
    parser.add_argument(
        "--allow-no-tests",
        action="store_true",
        help="Permit code changes without tests in --ci-diff mode (used by CI when PR has 'no-tests-needed' label).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Override repository root directory (primarily for testing).",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.ci_diff:
        try:
            changed = _git_changed_files(repo_root, args.ci_diff)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        gate_errors = evaluate_pr_diff_gates(
            changed,
            allow_rule_edits=args.allow_rule_edits,
            allow_no_tests=args.allow_no_tests,
        )
        if gate_errors:
            for err in gate_errors:
                print(f"[FAIL] {err}", file=sys.stderr)
            return 1
        print(f"[OK] PR diff gates passed across {len(changed)} changed file(s) vs. {args.ci_diff}.")
        return 0

    run_all = not (args.tools or args.orchestration or args.worklogs)
    modules = discover_v2_test_modules(
        repo_root,
        tools=args.tools,
        orchestration=args.orchestration,
        worklogs=args.worklogs,
    )
    if not modules:
        print("[ERROR] No matching offline test modules discovered.", file=sys.stderr)
        return 1

    unittest_cmd = [sys.executable, "-m", "unittest"]
    if args.verbose:
        unittest_cmd.append("-v")
    unittest_cmd.extend(modules)
    rc = _run_cmd(unittest_cmd, cwd=repo_root)
    if rc != 0:
        return rc

    if run_all or args.worklogs:
        rc = _run_cmd([sys.executable, "scripts/update_worklog_index.py", "--check"], cwd=repo_root)
        if rc != 0:
            return rc

    print("[OK] All selected Mini Hivo offline checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
