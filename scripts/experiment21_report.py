"""Build a portable comparison; retain raw logs separately without rewriting them."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "experiment21"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    labels = ["baseline-full-unrestricted", "parser-before", "parser-after",
              "combined-focused", "combined-full", "combined-focused-edge"]
    runs = {label: read(OUT / "results" / (label + ".json")) for label in labels}
    before, after = runs[labels[0]], runs["combined-full"]

    def issues(run):
        return {kind + ":" + row["id"] for kind in ("failures", "errors") for row in run[kind]}

    old, new = issues(before), issues(after)
    data = {
        "experiment": 21, "date": "2026-11-08", "baseline_revision": before["revision"],
        "pr5": "cca388daa3537030abdb7b6cf175d847f23b99ec",
        "pr6_includes_pr5": "9957271c8e66d10bdfa5b408c74d26fcd7b78be2",
        "implementation_revision": "cc8706ef871c933ffe5ee55a4b9768ac7932112c",
        "scope": "Controlled functional and regression; no fresh live-model outcome",
        "merge_resolution": "mini.py: retain Tasneem's two context-progress variables and Rodina's context_start_retries",
        "new_failures_or_errors": sorted(new - old),
        "resolved_failures_or_errors": sorted(old - new),
        "unchanged_failures_or_errors": sorted(old & new),
        "previous_passes_not_passing": sorted(set(before["passed"]) - set(after["passed"])),
        "additional_passing_tests": sorted(set(after["passed"]) - set(before["passed"])),
        "runs": {}, "functional": {}, "source_sha256": {},
        "counting_note": "Subtest failure records and setup errors are not additive with tests_run; focused and full runs overlap.",
        "interrupted_attempt": "baseline-full.log: restricted process run interrupted at browser startup; no completed result, superseded by baseline-full-unrestricted",
    }
    for label, run in runs.items():
        data["runs"][label] = {
            **{k: run[k] for k in ("revision", "python", "platform", "packages", "elapsed_seconds", "tests_run", "successful", "missing_focused_modules", "working_diff_sha256")},
            "passed_count": len(run["passed"]), "failure_records": len(run["failures"]),
            "error_records": len(run["errors"]), "skip_count": len(run["skipped"]),
            "failure_ids": [row["id"] for row in run["failures"]],
            "error_ids": [row["id"] for row in run["errors"]],
            "skip_ids": [row["id"] for row in run["skipped"]],
            "blocked_connection_count": len(run["blocked_connections"]),
        }
    for case in ("original", "compact", "period"):
        result = read(ROOT / "output" / "experiment21" / ("functional-" + case) / "result.json")
        data["functional"][case] = {k: result[k] for k in (
            "request", "verification_class", "real_model_calls", "status", "root_verified",
            "file_exists", "actual_hex", "expected_hex", "exact_bytes", "actual_sha256",
            "expected_sha256", "falsifier_native_readbacks")}
    for path in ("mini.py", "hivo/requirements.py", "hivo/pre_mutation_impact.py", "hivo/verification_routing.py",
                 "AGENTS.md", "tests/test_literal_parser_regression.py", "scripts/experiment21_run.py",
                 "scripts/experiment21_functional.py", "scripts/level1_native_verification_replay.py"):
        data["source_sha256"][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    data["raw_evidence_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((OUT / "results").iterdir()) if p.is_file()}
    data["deterministic_integration_passed"] = (
        not data["new_failures_or_errors"] and not data["previous_passes_not_passing"]
        and runs["parser-after"]["successful"] and runs["combined-focused-edge"]["successful"]
        and all(row["root_verified"] and row["exact_bytes"] for row in data["functional"].values()))
    (OUT / "experiment21-results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    prs = read(ROOT / "output" / "experiment21" / "pr-snapshot.json")
    snapshot = [{"number": p["number"], "title": p["title"], "author": p["user"]["login"],
                 "state": p["state"], "draft": p["draft"], "updated_at": p["updated_at"],
                 "head": p["head"]["sha"], "url": p["html_url"]} for p in prs]
    (OUT / "pr-status-2026-11-08.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: data[k] for k in ("deterministic_integration_passed", "new_failures_or_errors", "previous_passes_not_passing")}, indent=2))
    print("Additional passing tests:", len(data["additional_passing_tests"]))


if __name__ == "__main__":
    main()
