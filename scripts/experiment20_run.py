"""Record deterministic Experiment 20 checks; no live model calls are requested."""
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

FOCUSED = [
    "test_authority_drift", "test_host_preflight", "test_model_transport_timeout",
    "test_verified_state_reentry", "test_browser_implicit_favicon",
    "test_experiment18a_schema_feedback", "test_greenfield_context_progress",
    "test_ingestion_integration", "test_repair_impact_anchor", "test_cloud_model",
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
    args = parser.parse_args()
    out = ROOT / "reports" / "experiment20" / "results"
    out.mkdir(parents=True, exist_ok=True)
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
        suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py")
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
    }
    (out / (args.label + ".json")).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if k not in ("passed", "failures", "errors", "skipped")}, indent=2))
    print(f"Passed={len(result.passed_ids)} failures={len(result.failures)} errors={len(result.errors)} skipped={len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
