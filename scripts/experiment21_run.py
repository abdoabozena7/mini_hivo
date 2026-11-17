"""Record deterministic Experiment 21 checks; no live model calls are requested."""
import argparse
import contextlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BLOCKED_CONNECTIONS = []


def offline_guard(event, args):
    if event == "socket.connect":
        address = args[1]
        if isinstance(address, tuple) and (address[0] not in ("127.0.0.1", "::1", "localhost") or address[1] == 11434):
            BLOCKED_CONNECTIONS.append(str(address))
            raise OSError("Experiment 21 blocks external network and live Ollama calls")


sys.addaudithook(offline_guard)

FOCUSED = [
    "test_authority_drift", "test_host_preflight", "test_model_transport_timeout",
    "test_verified_state_reentry", "test_browser_implicit_favicon",
    "test_experiment18a_schema_feedback", "test_greenfield_context_progress",
    "test_ingestion_integration", "test_repair_impact_anchor", "test_cloud_model",
    "test_greenfield_impact_lifecycle", "test_level1_native_verification",
    "test_literal_parser_regression", "test_pre_mutation_impact", "test_verification_applicability",
]


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed_ids = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed_ids.append(test.id())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--focused", action="store_true")
    parser.add_argument("--pattern", default="test_*.py")
    args = parser.parse_args()
    out = ROOT / "reports" / "experiment21" / "results"
    out.mkdir(parents=True, exist_ok=True)
    if any((out / (args.label + suffix)).exists() for suffix in (".log", ".json")):
        parser.error("Choose a fresh label; existing experiment evidence cannot be overwritten")
    loader = unittest.TestLoader()
    missing = []
    if args.focused:
        suite = unittest.TestSuite()
        for name in FOCUSED:
            if not (ROOT / "tests" / (name + ".py")).exists():
                missing.append(name)
                continue
            suite.addTests(loader.discover(str(ROOT / "tests"), pattern=name + ".py"))
    else:
        suite = loader.discover(str(ROOT / "tests"), pattern=args.pattern)
    # This historical prompt test may invoke a live provider. Exclude it
    # identically in both arms instead of silently exercising an online model.
    def guard_suite(items):
        for test in items:
            if isinstance(test, unittest.TestSuite):
                guard_suite(test)
            elif test.id().endswith("RequirementClarificationTests.test_root_brain_prompt_compacts_large_source_side_channel_without_dropping_ids"):
                name = test._testMethodName
                setattr(type(test), name, unittest.skip("Excluded: historical test may call live provider")(getattr(type(test), name)))
    guard_suite(suite)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    started = time.time()
    with (out / (args.label + ".log")).open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=RecordedResult).run(suite)
    packages = {}
    for name in ("rich", "prompt_toolkit", "playwright"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    data = {
        "label": args.label, "revision": revision, "python": platform.python_version(),
        "platform": platform.platform(), "packages": packages,
        "elapsed_seconds": round(time.time() - started, 3), "tests_run": result.testsRun,
        "passed": result.passed_ids,
        "failures": [{"id": t.id(), "traceback": tb} for t, tb in result.failures],
        "errors": [{"id": t.id(), "traceback": tb} for t, tb in result.errors],
        "skipped": [{"id": t.id(), "reason": reason} for t, reason in result.skipped],
        "expected_failures": [t.id() for t, _ in result.expectedFailures],
        "unexpected_successes": [t.id() for t in result.unexpectedSuccesses],
        "missing_focused_modules": missing, "successful": result.wasSuccessful(),
        "scope": "deterministic tests; no live E2E success claim",
        "blocked_connections": BLOCKED_CONNECTIONS,
        "browser_executable": __import__("os").environ.get("HIVO_TEST_BROWSER_EXECUTABLE"),
        "working_diff_sha256": __import__("hashlib").sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
    }
    (out / (args.label + ".json")).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if k not in ("passed", "failures", "errors", "skipped")}, indent=2))
    print(f"Passed={len(result.passed_ids)} failures={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
