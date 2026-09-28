"""Report Experiment 8 receipt percentages separately from live root results."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hivo.atomic_child_receipt import validate_atomic_child_receipt
from hivo.integration_gate import canonical_hash


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "percent": 100 * numerator / denominator if denominator else None}


def live_summary(workspace):
    workspace = Path(workspace)
    run = json.loads((workspace / ".agent_experiment.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    verified = [event for event in run.get("experiment_events", []) if event["kind"] == "CHILD_VERIFIED"]
    receipts = run.get("child_receipts", {})
    valid = sum(validate_atomic_child_receipt(receipts.get(event["child_id"]), workspace=workspace)["valid"]
                for event in verified)
    hashes = sum(event.get("receipt_hash") == (receipts.get(event["child_id"]) or {}).get("receipt_hash")
                 and event.get("verification_evidence_hash") == canonical_hash(
                     (receipts.get(event["child_id"]) or {}).get("verification_evidence", []))
                 for event in verified)
    durable = [json.loads(line) for file in (workspace / ".agent_runs").glob("*.jsonl")
               for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    readiness = next((event for event in reversed(durable) if event["kind"] == "integration_readiness_checked"), {})
    coverage = readiness.get("coverage", {})
    required = set(coverage.get("required_coverage_ids", []))
    received = set(coverage.get("received_coverage_ids", []))
    return {"workspace": str(workspace.resolve()), "status": run.get("status"),
            "child_verified_count": len(verified), "valid_receipts_per_verified_child": ratio(valid, len(verified)),
            "receipt_event_evidence_hash_match": ratio(hashes, len(verified)),
            "coverage_preservation": ratio(len(required & received), len(required)),
            "received_node_ids": sorted(received), "integration_readiness": readiness.get("readiness"),
            "integration_reason": readiness.get("reason"), "root_verified": run.get("root_verified") is True,
            "first_blocker": run.get("first_blocker"), "repairer_calls": run.get("repairer_calls", 0),
            "browser_results": run.get("verification_browser_results", []),
            "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
                "mutation_scope_violations", "unapproved_scope_expansions", "dnt_execution_violations")),
            "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
            "model": run.get("model"), "approved_plan_hash": (run.get("plan_approval") or {}).get("plan_hash")}


def report(replay, live=None):
    data = {"comparison": replay["comparison"], "sample_size": 1, "replay": {}, "live": live}
    for policy, value in replay["policies"].items():
        required = set(value["readiness"]["coverage"]["required_coverage_ids"])
        received = set(value["readiness"]["coverage"]["received_coverage_ids"])
        data["replay"][policy] = {
            "receipt_verified": value["receipt"]["verified"],
            "valid_verified_receipts": ratio(int(value["receipt_valid"]), 1),
            "coverage_preservation": ratio(len(required & received), len(required)),
            "evidence_hash_match": ratio(int(value["verification_evidence_hash_matches"] is True),
                                         int(value["verification_evidence_hash_matches"] is not None)),
            "received_node_ids": sorted(received), "readiness": value["readiness"]["readiness"],
            "reason": value["readiness"]["reason"], "receipt_hash": value["receipt"]["receipt_hash"],
            "candidate_sha256": value["source_sha256"], "model_calls": value["model_calls"]}
    return data


def percentage(value):
    return (f"{value['numerator']}/{value['denominator']} ({value['percent']:.0f}%)"
            if value["percent"] is not None else "N/A")


def markdown(data):
    a, b = data["replay"]["current"], data["replay"]["atomic_verified"]
    lines = ["# Experiment 8 — Atomic Verified Child Receipt", "",
             "المقارنة المعزولة تستخدم نفس patch ونفس دليل نجاح Child المحفوظ من Experiment 7.",
             "النسب تخص حالة R-key واحدة، وليست تقديرًا لأداء HIVO عمومًا.", "",
             "| المقياس | current | atomic_verified |", "|---|---:|---:|"]
    for key, label in (("valid_verified_receipts", "Receipts صالحة لكل Child ناجح"),
                       ("coverage_preservation", "حفظ تغطية الـnodes"), ("evidence_hash_match", "مطابقة hash الدليل")):
        lines.append(f"| {label} | {percentage(a[key])} | {percentage(b[key])} |")
    lines += [f"| جاهزية Integration | {a['readiness']} | {b['readiness']} |", "",
              f"- نفس candidate SHA-256: `{b['candidate_sha256']}`",
              f"- Nodes وصلت للـParent: `{b['received_node_ids']}`",
              "- لا توجد استدعاءات model أو تعديل source أثناء replay.", ""]
    live = data.get("live")
    if live:
        lines += ["## إعادة HIVO الفعلية", "",
                  f"- CHILD_VERIFIED: {live['child_verified_count']}",
                  f"- Receipts صالحة / children verified: {percentage(live['valid_receipts_per_verified_child'])}",
                  f"- Hash event/receipt/evidence: {percentage(live['receipt_event_evidence_hash_match'])}",
                  f"- Coverage: {percentage(live['coverage_preservation'])}; nodes: `{live['received_node_ids']}`",
                  f"- Integration: `{live['integration_readiness']}` / `{live['integration_reason']}`",
                  f"- ROOT_VERIFIED: {live['root_verified']}",
                  f"- First blocker: `{live['first_blocker']}`",
                  f"- Repairer: {live['repairer_calls']}",
                  f"- Scope / preservation violations: {live['scope_violations']} / {live['preservation_violations']}", ""]
    lines += ["## حدود النتيجة", "",
              "نجاح replay يثبت إصلاح تسليم الدليل والتغطية إلى بوابة integration القائمة.",
              "ROOT_VERIFIED يُقاس فقط من الإعادة الفعلية. منطق integration والـVerifier والـWorker لم يتغيروا.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--live", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    data = report(json.loads(args.replay.read_text(encoding="utf-8")),
                  live_summary(args.live) if args.live else None)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown(data), encoding="utf-8")
    print(json.dumps({"replay": data["replay"], "live": data["live"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
