"""Offline Experiment 20 input checks and portable execution provenance."""
import hashlib
import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "d15b6068f78dd5b9e46daacd81f5543af5c2cf89"
TREATMENT = "a91062551c9b346a35eb4abb5f18a6f64f95a72b"


def tree(revision):
    rows = subprocess.check_output(
        ["git", "ls-tree", "-r", revision, "--", "mini.py", "hivo", "tests", "requirements.txt"],
        cwd=ROOT, text=True, encoding="utf-8").splitlines()
    return {path: head.split()[2] for row in rows for head, path in [row.split("\t", 1)]
            if path.endswith(".py") or path in ("requirements.txt", "tests/fixtures/experiment20_scope.json")}


def capture():
    """Reject tracked runtime/test drift before executing either comparison arm.

    Both arms use inherited dependencies from the treatment checkout. Verify
    that those files also belong to the baseline; only mini.py and the new
    scope module/test/fixture are intentional differences. This is not a
    hermetic environment or a claim about unselected test suites.
    """
    expected, baseline = tree(TREATMENT), tree(BASELINE)
    differences = {"mini.py", "hivo/verification_scope.py", "tests/test_experiment20_child_scope.py",
                   "tests/fixtures/experiment20_scope.json"}
    hashes = {}
    for name, oid in expected.items():
        data = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != oid:
            raise RuntimeError("Pinned runtime/test input drift: " + name)
        if name not in differences and baseline.get(name) != oid:
            raise RuntimeError("Uncontrolled inherited dependency: " + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    versions = {}
    for name in ("rich", "prompt_toolkit", "playwright"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return {
        "baseline": BASELINE, "treatment": TREATMENT,
        "python": platform.python_version(), "implementation": platform.python_implementation(),
        "platform": platform.system(), "machine": platform.machine(),
        "packages": versions, "input_sha256_lf_normalized": hashes,
        "runner_sha256_lf_normalized": {
            p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted((ROOT / "scripts").glob("experiment20_*.py"))},
        "inherited_runtime_and_test_inputs_match_baseline": True,
        "protocol_sha256_lf_normalized": hashlib.sha256(
            (ROOT / "reports/experiment20/protocol.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "provider_calls_blocked": ["mini.ask_ollama", "mini.structured_model_call"],
        "boundary": "offline controlled inputs; not a hermetic sandbox or live E2E",
        "command": [Path(sys.argv[0]).name] + [
            "<fresh-output-directory>" if i and sys.argv[i - 1] == "--output-dir" else arg
            for i, arg in enumerate(sys.argv[1:], start=1)]}
