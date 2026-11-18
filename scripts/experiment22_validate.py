"""Run Experiment 22 verification-integrity and child-scope regressions."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    ("test_experiment20_child_scope.py", 38),
    ("test_experiment17_field_scoped_profile.py", 5),
    ("test_verified_child_integration.py", 22),
    ("test_experiment9_integration_targets.py", 12),
    ("test_verification_outcome_integrity.py", 31),
    ("test_evidence_policy.py", 9),
    ("test_verification_applicability.py", 15),
    ("test_experiment11_evidence_compatibility.py", 10),
    ("test_experiment13_monotonic.py", 9),
    ("test_experiment18a_schema_feedback.py", 9),
    ("test_context_sufficiency_gate.py", 9),
    ("test_greenfield_context_progress.py", 9),
    ("test_repair_impact_anchor.py", 3),
]
SOURCE_FILES = (
    "hivo/evidence.py",
    "hivo/verification_routing.py",
    "hivo/verification_scope.py",
    "mini.py",
    "tests/test_verification_outcome_integrity.py",
    "tests/test_experiment20_child_scope.py",
)


def _sha256(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _provenance():
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8"
    ).strip()
    versions = {}
    for package in ("rich", "prompt_toolkit", "playwright"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return {
        "revision": revision,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": versions,
        "source_sha256_lf_normalized": {
            name: _sha256(ROOT / name) for name in SOURCE_FILES
        },
        "provider_calls_blocked": ["mini.ask_ollama", "mini.structured_model_call"],
        "boundary": "selected offline regressions; no live provider or application E2E claim",
    }


def _run_suite(pattern, expected, temporary):
    bootstrap = (
        "import sys,runpy;from unittest.mock import patch;import mini;sys.argv="
        + repr(["unittest", "discover", "-s", "tests", "-p", pattern, "-v"])
        + ";a=patch.object(mini,'ask_ollama',side_effect=AssertionError('Live model call forbidden'));"
        "b=patch.object(mini,'structured_model_call',side_effect=AssertionError('Live provider forbidden'));"
        "a.start();b.start();runpy.run_module('unittest',run_name='__main__')"
    )
    env = dict(
        os.environ,
        TEMP=str(temporary),
        TMP=str(temporary),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONIOENCODING="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", bootstrap],
        cwd=ROOT,
        env=env,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    counts = re.findall(r"Ran (\d+) tests?", completed.stdout)
    summaries = re.findall(r"^OK.*$|^FAILED.*$", completed.stdout, re.M)
    actual = int(counts[-1]) if counts else None
    row = {
        "suite": pattern,
        "expected_methods": expected,
        "observed_methods": actual,
        "exit_code": completed.returncode,
        "summary": summaries,
        "passed": completed.returncode == 0 and actual == expected and summaries == ["OK"],
    }
    return row, completed.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    temporary = args.output_dir.resolve() / "tmp"
    temporary.mkdir()
    (args.output_dir / "provenance.json").write_text(
        json.dumps(_provenance(), indent=2) + "\n", encoding="utf-8"
    )
    rows = []
    for pattern, expected in SUITES:
        row, output = _run_suite(pattern, expected, temporary)
        (args.output_dir / (pattern + ".log")).write_text(output, encoding="utf-8")
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = {
        "experiment": 22,
        "suite_count": len(rows),
        "expected_methods": sum(expected for _name, expected in SUITES),
        "observed_methods": sum(row["observed_methods"] or 0 for row in rows),
        "passed": all(row["passed"] for row in rows),
        "suites": rows,
    }
    (args.output_dir / "results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
