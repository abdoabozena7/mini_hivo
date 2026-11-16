import argparse
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument("workspace", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
workspace = args.workspace.resolve()
source = workspace / "numbers_api.py"
tests = workspace / "test_numbers_api.py"
expected_tests_hash = "3f56c6f0c400b32dc52fb5a3d9488c0f6823c9fd5674268a3466eb9634873b2a"
spec = importlib.util.spec_from_file_location("independent_clamp_candidate", source)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load the produced module: {source}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cases = [
    (-5, 0, 10, 0),
    (15, 0, 10, 10),
    (3, 0, 10, 3),
    (0, 0, 10, 0),
    (10, 0, 10, 10),
    (-1, -5, -2, -2),
    (-9, -5, -2, -5),
    (2.5, 1.0, 2.0, 2.0),
]
observations = []
for value, lower, upper, expected in cases:
    actual = module.clamp_number(value, lower, upper)
    observations.append({
        "input": [value, lower, upper],
        "expected": expected,
        "actual": actual,
        "passed": actual == expected,
    })
unit = subprocess.run(
    [sys.executable, "-X", "utf8", "-m", "unittest", "test_numbers_api.py", "-q"],
    cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30,
)
test_hash = hashlib.sha256(tests.read_bytes()).hexdigest()
signature_preserved = list(inspect.signature(module.clamp_number).parameters) == [
    "value", "lower", "upper",
]
passed = (
    all(item["passed"] for item in observations)
    and unit.returncode == 0
    and test_hash == expected_tests_hash
    and signature_preserved
)
report = {
    "passed": passed,
    "workspace": str(workspace),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "protected_tests_sha256_before": expected_tests_hash,
    "protected_tests_sha256_after": test_hash,
    "protected_tests_unchanged": test_hash == expected_tests_hash,
    "signature_preserved": signature_preserved,
    "independent_cases": observations,
    "unittest": {
        "exit_code": unit.returncode,
        "stdout": unit.stdout,
        "stderr": unit.stderr,
    },
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
sys.exit(0 if passed else 1)
