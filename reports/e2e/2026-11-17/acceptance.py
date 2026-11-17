import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


parser = argparse.ArgumentParser()
parser.add_argument("case", choices=("greeting", "multiply", "hello"))
parser.add_argument("workspace", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
workspace = args.workspace.resolve()
checks = []


def command(label, argv, expected=None, *, reject=False):
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", *argv], cwd=workspace,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    passed = (
        completed.returncode != 0 if reject else
        completed.returncode == 0 and completed.stdout == expected
    )
    checks.append({
        "case": label, "argv": argv, "expected_stdout": expected,
        "expected_nonzero": reject, "exit_code": completed.returncode,
        "stdout": completed.stdout, "stderr": completed.stderr, "passed": passed,
    })


if args.case == "greeting":
    for label, names, expected in (
        ("cli-default", [], "Hello, World!\n"),
        ("cli-named", ["Ada"], "Hello, Ada!\n"),
        ("cli-another-name", ["Bob"], "Hello, Bob!\n"),
    ):
        command(label, ["greet.py", *names], expected)
    probe = (
        "import json; from greet import greet; "
        "print(json.dumps([greet(), greet('Ada'), greet('Bob')]))"
    )
    command(
        "function-results-without-newline", ["-c", probe],
        json.dumps(["Hello, World!", "Hello, Ada!", "Hello, Bob!"]) + "\n",
    )
    unit = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "unittest", "test_greet.py", "-q"],
        cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    checks.append({
        "case": "generated-unit-tests", "exit_code": unit.returncode,
        "stdout": unit.stdout, "stderr": unit.stderr,
        "passed": unit.returncode == 0 and "Ran 0 tests" not in unit.stderr,
    })
elif args.case == "multiply":
    for inputs, expected in (
        (["6", "7"], "42\n"), (["-3", "5"], "-15\n"),
        (["-3", "-7"], "21\n"), (["0", "999"], "0\n"),
        (["123456789", "9"], "1111111101\n"),
    ):
        command("valid:" + ",".join(inputs), ["multiply.py", *inputs], expected)
    for inputs in ([], ["6"], ["6", "invalid"], ["invalid", "7"], ["6", "7", "8"]):
        command("rejected:" + ",".join(inputs), ["multiply.py", *inputs], reject=True)
else:
    command("exact-console-output", ["hello.py"], "MERGE_OK\n")

files = {}
for path in sorted(workspace.rglob("*")):
    if path.is_file() and path.suffix == ".py" and "__pycache__" not in path.parts:
        files[path.relative_to(workspace).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
report = {
    "case": args.case, "workspace": str(workspace),
    "passed": bool(checks) and all(check["passed"] for check in checks),
    "checks": checks, "product_files_sha256": files,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
sys.exit(0 if report["passed"] else 1)
