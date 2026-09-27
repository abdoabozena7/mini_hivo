"""Summarize frozen candidate A/B verification and live controller follow-through."""

import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def direct_summary(payload):
    result = payload["result"]
    surface = result.get("verification_surface") or {}
    return {
        "policy": payload["surface_policy"],
        "source_sha256": payload["source_sha256"],
        "classification": payload["classification"],
        "passed": result.get("passed") is True,
        "surface_type": surface.get("surface_type"),
        "selected_surface": (surface.get("selected") or {}).get("name"),
        "behavior_test_executed": bool(result.get("behavior_test_executed")),
        "checks": [{"name": item.get("name"), "executed": item.get("executed"),
                    "passed": item.get("passed"),
                    "terminal_cases": [{"setup": case.get("setup"),
                                        "precondition_met": case.get("precondition_met"),
                                        "passed": case.get("passed")}
                                       for case in item.get("cases", [])]}
                   for item in result.get("interaction_checks", [])],
        "failure_codes": [item.get("code") for item in result.get("failures", [])],
    }


def live_summary(workspace):
    path = Path(workspace) / ".agent_experiment.jsonl"
    if not path.is_file():
        return None
    runs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(runs) != 1:
        raise ValueError(f"expected one live run in {path}")
    run = runs[0]
    events = run.get("experiment_events", [])
    progress = (run.get("worker_progress_runs") or [{}])[0]
    manifest_paths = run.get("candidate_patch_artifacts", []) or []
    candidate_hashes = []
    for item in manifest_paths:
        manifest = load(item)
        candidate_hashes.extend(file.get("candidate_sha256") for file in manifest.get("files", []))
    event_log = sorted((Path(workspace) / ".agent_runs").glob("*.jsonl"))
    durable_events = [json.loads(line) for file in event_log
                      for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    receipt = next((item for item in reversed(durable_events)
                    if item.get("kind") == "verified_child_receipt_created"), {})
    readiness = next((item for item in reversed(durable_events)
                      if item.get("kind") == "integration_readiness_checked"), {})
    final_source = Path(workspace) / "index.html"
    return {
        "source_sha256": run.get("source_sha256"),
        "approved_plan_hash": (run.get("plan_approval") or {}).get("plan_hash"),
        "approved": (run.get("plan_approval") or {}).get("approval_status") == "APPROVED",
        "policy": run.get("verification_surface_policy"),
        "first_legal_mutation_step": (progress.get("first_legal_mutation") or {}).get("tool_step"),
        "candidate_hashes": candidate_hashes,
        "final_source_sha256": hashlib.sha256(final_source.read_bytes()).hexdigest(),
        "browser_results": run.get("verification_browser_results", []),
        "repairer_calls": run.get("repairer_calls", 0),
        "child_verified": any(event.get("kind") == "CHILD_VERIFIED" for event in events),
        "child_receipt_verified": receipt.get("verified"),
        "integration_readiness_reason": readiness.get("reason"),
        "integration_missing_coverage": (readiness.get("coverage") or {}).get("missing_coverage_ids", []),
        "root_verified": any(event.get("kind") == "ROOT_VERIFIED" for event in events),
        "first_blocker": run.get("first_blocker"),
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions", "dnt_execution_violations")),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
        "status": run.get("status"),
    }


def report(current, discovery, original, live_workspaces):
    if current["source_sha256"] != discovery["source_sha256"]:
        raise ValueError("A/B candidate bytes differ")
    if original["source_sha256"] == discovery["source_sha256"]:
        raise ValueError("original control must differ from candidate")
    if current["requirement"] != discovery["requirement"] or original["requirement"] != discovery["requirement"]:
        raise ValueError("requirements differ")
    return {
        "candidate_sha256": current["source_sha256"],
        "original_sha256": original["source_sha256"],
        "requirement": current["requirement"],
        "direct": {
            "current": direct_summary(current),
            "discovery": direct_summary(discovery),
            "original_control": direct_summary(original),
        },
        "live_runs": [live_summary(path) for path in live_workspaces],
    }


def markdown(data):
    a, b, original = (data["direct"][key] for key in ("current", "discovery", "original_control"))
    def show(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "نعم" if value else "لا"
        return str(value).replace("|", "\\|")
    rows = [
        ("surface_type", "نوع سطح التحقق"),
        ("selected_surface", "الواجهة المختارة"),
        ("behavior_test_executed", "اختبار سلوكي نُفذ"),
        ("classification", "التصنيف"),
        ("passed", "النتيجة"),
    ]
    lines = ["# Experiment 7 — Verification Surface Discovery", "",
             "المقارنة الأساسية تستخدم نفس candidate byte-for-byte؛ الملف الأصلي ضابط سلبي للاختبار.", "",
             "| المقياس | current candidate | discovery candidate | original discovery |",
             "|---|---:|---:|---:|"]
    lines.extend(f"| {label} | {show(a[key])} | {show(b[key])} | {show(original[key])} |"
                 for key, label in rows)
    lines += ["", "## اختبارات السلوك", "",
              "| الاختبار | candidate | original |", "|---|---:|---:|"]
    names = list(dict.fromkeys(item["name"] for item in b["checks"] + original["checks"]))
    for name in names:
        candidate = next((item for item in b["checks"] if item["name"] == name), {})
        baseline = next((item for item in original["checks"] if item["name"] == name), {})
        lines.append(f"| {name} | {show(candidate.get('passed'))} | {show(baseline.get('passed'))} |")
    lines += ["", "## HIVO live runs", ""]
    for index, item in enumerate(data["live_runs"], 1):
        if item is None:
            continue
        lines += [f"### Run {index}", "",
                  f"- أول تعديل قانوني: الخطوة {show(item['first_legal_mutation_step'])}",
                  f"- candidate hash: `{show(item['candidate_hashes'])}`",
                  f"- final source hash: `{item['final_source_sha256']}`",
                  f"- browser: `{show(item['browser_results'])}`",
                  f"- Repairer calls: {item['repairer_calls']}",
                  f"- Child verified: {show(item['child_verified'])}",
                  f"- Child receipt verified: {show(item['child_receipt_verified'])}",
                  f"- Integration readiness: `{show(item['integration_readiness_reason'])}`",
                  f"- Missing integration coverage: `{show(item['integration_missing_coverage'])}`",
                  f"- Root verified: {show(item['root_verified'])}",
                  f"- أول توقف: `{show(item['first_blocker'])}`",
                  f"- Scope / preservation violations: {item['scope_violations']} / {item['preservation_violations']}",
                  ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--live", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    data = report(load(args.current), load(args.discovery), load(args.original), args.live)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown(data), encoding="utf-8")
    print(args.markdown_output)


if __name__ == "__main__":
    main()
