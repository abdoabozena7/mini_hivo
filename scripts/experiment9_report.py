"""Report target resolution, new parent proof and independent live root success."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hivo.approval_authority import canonical_hash
from experiment8_report import percentage, ratio


def summary(value, requirement_ids, root_verified=None):
    resolution = value.get("resolution") or {}
    selections = resolution.get("resolutions", [])
    chosen = next((item for item in selections if item.get("kind") == "INTEGRATION_TEST"), {})
    runs = value.get("parent_verification_runs", [])
    receipt = value.get("parent_verification_receipt") or {}
    fresh_ids = {item["verification_id"] for item in runs}
    proof = receipt.get("integration_evidence", [])
    unbound = sum((item["result"].get("verification_id") if isinstance(item.get("result"), dict) else None)
                  not in fresh_ids for item in proof)
    covered = set(value.get("parent_requirement_coverage", {}).get("covered_requirement_ids", []))
    checks = [check for item in runs for check in item.get("result", {}).get("interaction_checks", [])]
    hash_matches = sum(item.get("evidence_hash") == canonical_hash({
        key: data for key, data in item.items() if key not in {"evidence_hash", "artifact_path"}}) for item in runs)
    return {"target_resolved": resolution.get("status") == "RESOLVED", "target": chosen.get("target"),
            "target_source": chosen.get("source"), "parent_verification_executed": any(item.get("parent_verification_executed") for item in runs),
            "behavior_checks_passed": ratio(sum(check.get("passed") is True for check in checks), len(checks)),
            "parent_requirements_covered": ratio(len(set(requirement_ids) & covered), len(requirement_ids)),
            "covered_requirement_ids": sorted(covered), "fresh_proof_hash_matches": ratio(hash_matches, len(runs)),
            "child_evidence_reused_as_proof": unbound, "parent_verified": value.get("integration_result") == "PARENT_VERIFIED",
            "root_verified": root_verified, "status": value.get("status"), "summary": value.get("summary"),
            "root_verified_event": value.get("root_verified_event"), "source_unchanged": value.get("source_unchanged"),
            "parent_receipt_hash": receipt.get("receipt_hash"), "fresh_verification_ids": sorted(fresh_ids)}


def live_value(workspace):
    workspace = Path(workspace)
    run = json.loads((workspace / ".agent_experiment.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    resolutions = run.get("integration_target_resolutions", [])
    runs = [item for item in run.get("parent_verification_runs", []) if item.get("parent_id") == "ROOT"]
    # The tree stores a compact receipt. Read the final aggregation's fresh
    # evidence from the durable parent event for the independent proof audit.
    events = [json.loads(line) for file in (workspace / ".agent_runs").glob("*.jsonl")
              for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    aggregated = next((item for item in reversed(events)
                       if item.get("kind") == "parent_integration_aggregated" and item.get("parent_id") == "ROOT"), {})
    required_ids = {rid for item in runs for rid in item.get("requirement_ids", [])}
    covered_ids = [rid for rid in required_ids
                   if all(rid in item.get("covered_requirement_ids", [])
                          for item in runs if rid in item.get("requirement_ids", []))]
    value = {"resolution": next((item for item in reversed(resolutions) if item.get("parent_id") == "ROOT"), {}),
             "parent_verification_runs": runs,
             "parent_verification_receipt": {"receipt_hash": aggregated.get("parent_verification_receipt"),
                                               "integration_evidence": aggregated.get("actual_evidence", [])},
             "parent_requirement_coverage": {"covered_requirement_ids": sorted(covered_ids)},
             "integration_result": aggregated.get("integration_result"), "status": run.get("status")}
    return value, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--live", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    required = probe["policies"]["resolved"]["parent_requirement_coverage"]["required_requirement_ids"]
    baseline = json.loads(Path(probe["input_run"]).read_text(encoding="utf-8").splitlines()[-1])
    data = {"sample_size": 1, "comparison": probe["comparison"], "required_requirement_ids": required,
            "completion_mode": probe.get("completion_mode", "parent_probe_only"),
            "probe": {key: summary(value, required, root_verified=value.get("root_verified")
                                    if probe.get("completion_mode") == "continue_existing_verified_children"
                                    else baseline.get("root_verified") is True if key == "current" else None)
                      for key, value in probe["policies"].items()}, "live_runs": []}
    for workspace in args.live:
        value, run = live_value(workspace)
        data["live_runs"].append({**summary(value, required, root_verified=run.get("root_verified") is True),
                        "workspace": str(workspace.resolve()),
                        "parent_ready_reached": bool(run.get("integration_target_resolutions")),
                        "root_verified_event": any(item["kind"] == "ROOT_VERIFIED" for item in run.get("experiment_events", [])),
                        "first_blocker": run.get("first_blocker"), "repairer_calls": run.get("repairer_calls", 0),
                        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
                            "mutation_scope_violations", "unapproved_scope_expansions", "dnt_execution_violations")),
                        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
                        "model": run.get("model"), "approved_plan_hash": (run.get("plan_approval") or {}).get("plan_hash")})
    eligible = [item for item in data["live_runs"] if item["parent_ready_reached"]]
    data["live_rates"] = {"root_success_all_attempts": ratio(sum(item["root_verified"] for item in data["live_runs"]), len(data["live_runs"])),
                          "root_success_after_parent_ready": ratio(sum(item["root_verified"] for item in eligible), len(eligible))}
    if data["completion_mode"] == "continue_existing_verified_children":
        data["root_continuation_success"] = ratio(int(data["probe"]["resolved"]["root_verified"] is True), 1)
    a, b = data["probe"]["current"], data["probe"]["resolved"]
    lines = ["# Experiment 9 — Integration Target Resolution", "",
             "المقارنة المعزولة تستخدم نفس patch ونفس receipts؛ المسار الجديد ينفّذ Parent verification جديدًا.",
             "النسب تخص R-key واحدة. نجاح استكمال Root والتشغيل الجديد من البداية معروضان بشكل منفصل.", "",
             "| المقياس | current | resolved |", "|---|---:|---:|"]
    for key, label in (("target_resolved", "Integration target resolved"), ("parent_verification_executed", "Parent verification actually executed"),
                       ("parent_verified", "PARENT_VERIFIED")):
        lines.append(f"| {label} | {int(a[key])}/1 ({100 * int(a[key])}%) | {int(b[key])}/1 ({100 * int(b[key])}%) |")
    lines += [f"| Parent requirement coverage | {percentage(a['parent_requirements_covered'])} | {percentage(b['parent_requirements_covered'])} |",
              f"| Behavioral checks | {percentage(a['behavior_checks_passed'])} | {percentage(b['behavior_checks_passed'])} |",
              f"| Child evidence reused as proof | {a['child_evidence_reused_as_proof']} | {b['child_evidence_reused_as_proof']} |", "",
              f"- Target: `{b['target']}`; source: `{b['target_source']}`",
              f"- Fresh proof IDs: `{b['fresh_verification_ids']}`",
              f"- Parent receipt hash: `{b['parent_receipt_hash']}`", ""]
    if data["completion_mode"] == "continue_existing_verified_children":
        lines += ["## استكمال Root من تشغيل Experiment 8 المتحقق", "",
                  f"- Current ROOT_VERIFIED: {a['root_verified']}; resolved ROOT_VERIFIED: {b['root_verified']}",
                  f"- Root event: {b['root_verified_event']}; source unchanged: {b['source_unchanged']}",
                  f"- Root continuation success: {percentage(data['root_continuation_success'])}",
                  "- الـChild والـpatch والـapproval محفوظون من التشغيل السابق؛ Parent behavior نُفّذ من جديد.",
                  "- ده استكمال بعد READY، وليس إعادة جديدة للـPlanner أو الـWorker.", ""]
    for index, live in enumerate(data["live_runs"], 1):
        lines += [f"## تشغيل HIVO الكامل — محاولة {index}", "",
                  f"- Status: `{live['status']}`; ROOT_VERIFIED: {live['root_verified']}; root event: {live['root_verified_event']}",
                  f"- Fresh behavior: {percentage(live['behavior_checks_passed'])}",
                  f"- Parent requirements: {percentage(live['parent_requirements_covered'])}",
                  f"- Parent evidence hashes: {percentage(live['fresh_proof_hash_matches'])}",
                  f"- Child proof reused: {live['child_evidence_reused_as_proof']}",
                  f"- Scope / preservation violations: {live['scope_violations']} / {live['preservation_violations']}",
                  f"- Repairer: {live['repairer_calls']}; first blocker: `{live['first_blocker']}`", ""]
    lines += ["## نسب التشغيل الكامل", "",
              f"- ROOT_VERIFIED من كل المحاولات: {percentage(data['live_rates']['root_success_all_attempts'])}",
              f"- ROOT_VERIFIED بعد الوصول إلى Parent READY: {percentage(data['live_rates']['root_success_after_parent_ready'])}", ""]
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
