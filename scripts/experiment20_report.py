"""Summarize recorded Experiment 20 runs without hiding pre-existing failures."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "experiment20"


def main():
    labels = ("baseline-full", "tasneem-focused", "tasneem-full", "tasneem-focused-edge", "final-full")
    runs = {label: json.loads((OUT / "results" / (label + ".json")).read_text(encoding="utf-8")) for label in labels}
    before, after = runs["baseline-full"], runs["final-full"]

    def issues(run):
        return {kind + ":" + row["id"] for kind in ("failures", "errors") for row in run[kind]}

    old, new = issues(before), issues(after)
    summary = {
        "experiment": 20, "date": "2026-10-27", "kind": "deterministic integration comparison",
        "source_prs": {"7_includes_2": "2a8b94590734cec3375047a18e0dc71df2476f85", "3": "3d20a720302c05d527bb72a0540e726fc525c9e2", "4": "d5acac182a5f3340968c2676d70a35369d81c3c5"},
        "merge_conflicts": [], "runs": {},
        "new_failure_or_error_ids": sorted(new - old),
        "resolved_failure_or_error_ids": sorted(old - new),
        "unchanged_failure_or_error_ids": sorted(old & new),
        "baseline_passes_not_passing_after": sorted(set(before["passed"]) - set(after["passed"])),
        "additional_passing_test_ids": sorted(set(after["passed"]) - set(before["passed"])),
        "changed_source_sha256": {},
        "full_suite_green": after["successful"],
        "live_model_runs": 0,
        "limitations": ["Failure records include subtests; setup errors may prevent whole classes from running, so counts are not additive.", "Raw results/logs are local in results/ and excluded from Git.", "Edge supplement changes only the browser setting and reruns focused tests; it is separate from the matched full-suite comparison.", "No full application completion or productive Repairer recovery established."],
    }
    for label, run in runs.items():
        summary["runs"][label] = {
            **{k: run[k] for k in ("revision", "python", "platform", "packages", "elapsed_seconds", "tests_run", "successful", "missing_focused_modules")},
            "passed": len(run["passed"]), "failure_records": len(run["failures"]),
            "error_records": len(run["errors"]), "skips": len(run["skipped"]),
            "failure_ids": [x["id"] for x in run["failures"]],
            "error_ids": [x["id"] for x in run["errors"]],
            "skip_ids": [x["id"] for x in run["skipped"]],
        }
    for path in ("mini.py", "hivo/context_sufficiency.py", "hivo/host_preflight.py", "hivo/project_understanding.py", "hivo/reentry.py", "hivo/requirements.py"):
        summary["changed_source_sha256"][path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    summary["deterministic_integration_gate_passed"] = not (new - old) and not summary["baseline_passes_not_passing_after"] and runs["tasneem-focused-edge"]["successful"]
    architecture = {}
    for arm, prefix in (("baseline", "baseline-"), ("treatment", "")):
        lines = (OUT / "results" / (prefix + "architecture-self-test.log")).read_text(encoding="utf-8-sig").splitlines()
        architecture[arm] = {
            "exit_code": int((OUT / "results" / (prefix + "architecture-self-test-exit.txt")).read_text(encoding="utf-8-sig").strip()),
            "status_lines": [line.strip() for line in lines if line.endswith((" PASS", " FAIL"))],
        }
    architecture["same_status_lines"] = architecture["baseline"]["status_lines"] == architecture["treatment"]["status_lines"]
    summary["architecture_self_test"] = architecture
    summary["raw_evidence_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((OUT / "results").iterdir()) if p.is_file()
    }
    summary["deterministic_integration_gate_passed"] &= architecture["same_status_lines"]
    (OUT / "experiment20-results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("deterministic_integration_gate_passed", "new_failure_or_error_ids", "resolved_failure_or_error_ids", "baseline_passes_not_passing_after", "full_suite_green")}, indent=2))
    print("Additional passing tests:", len(summary["additional_passing_test_ids"]))


if __name__ == "__main__":
    main()
