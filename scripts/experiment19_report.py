"""Audit frozen Python context-decision closure without counting claims as proof."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment19_run as experiment
from scripts.experiment12_report import SAFETY_KEYS, audit_trial, load, rate


def audit_suite(suite, expected_policy):
    manifest = load(suite / "manifest.json")
    experiment.previous.previous.engine.check_pin(manifest)
    if (manifest.get("experiment") != 19 or manifest.get("case_set") != "python"
            or manifest.get("worker_context_decision_policy") != expected_policy
            or manifest.get("worker_no_tool_policy") != "bounded_reanchor"
            or manifest.get("verification_classification_policy") != "field_scoped"
            or manifest.get("worker_budget") != 28
            or manifest.get("fixed_semantic_evidence_policy") != "strict"
            or manifest.get("policies", {}).get("mutation_grounding_policy") != "evidence_bound"):
        raise RuntimeError(f"experiment policy pin mismatch: {suite}")
    case = manifest["cases"][0]
    if case["case_id"] != "python_clamp":
        raise RuntimeError("only frozen Python case is authorized")
    rows = []
    for repeat in range(1, 4):
        core = audit_trial(suite, case, experiment.previous.GROUNDING, repeat,
                           expected_semantic_policy="strict",
                           expected_policies=manifest["policies"])
        if not core["completed"]:
            raise RuntimeError(f"missing trial: {suite}/{repeat}")
        workspace = suite / "python_clamp" / f"{experiment.previous.GROUNDING}-{repeat}"
        run = json.loads((workspace / ".agent_experiment.jsonl").read_text(
            encoding="utf-8").splitlines()[-1])
        if (run.get("worker_context_decision_policy", "current") != expected_policy
                or run.get("worker_no_tool_policy") != "bounded_reanchor"):
            raise RuntimeError(f"runtime policy mismatch: {workspace}")
        event_path = next((workspace / ".agent_runs").glob("*.jsonl"))
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        decisions = [e for e in events if e.get("kind") == "context_sufficiency_decision"
                     and e.get("task_id") == "EXEC-001"]
        missing_events = [e for e in events if e.get("kind") == "CONTEXT_DECISION_MISSING"
                          and e.get("task_id") == "EXEC-001"]
        unsafe_authorizations = [e for e in decisions if e.get("mutation_authorized")
                                 and (e.get("contradictions", 0) > 0
                                      or e.get("working_evidence_count", 0) == 0
                                      or set(e.get("semantic_resolution_statuses", []))
                                      & {"partial", "unresolved", "conflicting"})]
        progress = next((p for p in run.get("worker_progress_runs", [])
                         if p.get("task_id") == "EXEC-001"), {})
        blockers = [e for e in run.get("experiment_events", []) if e.get("kind") == "BLOCKED"
                    and e.get("stage") != "PARENT_INTEGRATION"]
        rows.append({
            "repeat": repeat, "policy": expected_policy,
            "first_tool_call": progress.get("tool_steps", 0) > 0,
            "inspection_reads": progress.get("pre_mutation_read_steps", 0),
            "unique_inspection_evidence": progress.get("unique_evidence", 0),
            "context_decision_submitted": bool(decisions),
            "context_decision_count": len(decisions),
            "context_decision_statuses": [e.get("context_status") for e in decisions],
            "context_mutation_authorized": any(e.get("mutation_authorized") for e in decisions),
            "context_decision_reanchors": run.get("context_decision_reanchors", 0),
            "context_decision_missing_exits": run.get("context_decision_missing_exits", 0),
            "context_decision_missing_source": (missing_events[0].get("source")
                                                if missing_events else None),
            "filtered_empty_builder_responses": sum(
                e.get("kind") == "model_response_incomplete" and e.get("role") == "Builder"
                for e in events),
            "unsupported_sufficient_authorizations": len(unsafe_authorizations),
            "first_legal_mutation": bool(run.get("first_legal_mutation")),
            "verification_executed": core["verification_executed"],
            "verification_pass": core["verification_pass"],
            "child_verified": core["child_verified"],
            "root_verified": core["root_verified"],
            "first_reported_blocker": blockers[0] if blockers else core["first_blocker"],
            "repairer_calls": core["repairer_calls"],
            "model_calls": core["model_calls"],
            "elapsed_seconds": core["elapsed_seconds"],
            "safety_counters": core["safety_counters"],
            "protected_tests_unchanged": core["tests_unchanged"],
            "workspace": str(workspace.resolve()),
        })
    return rows


def summarize(rows):
    n = len(rows)
    names = ("first_tool_call", "context_decision_submitted", "context_mutation_authorized",
             "first_legal_mutation", "verification_executed", "verification_pass",
             "child_verified", "root_verified")
    return {name: rate(sum(row[name] for row in rows), n) for name in names} | {
        "context_decision_reanchors": sum(row["context_decision_reanchors"] for row in rows),
        "context_decision_missing_exits": sum(row["context_decision_missing_exits"] for row in rows),
        "unsupported_sufficient_authorizations": sum(
            row["unsupported_sufficient_authorizations"] for row in rows),
        "decision_statuses": dict(Counter(status for row in rows
                                          for status in row["context_decision_statuses"])),
        "missing_sources": dict(Counter(row["context_decision_missing_source"] for row in rows
                                        if row["context_decision_missing_source"])),
        "filtered_empty_builder_responses": sum(row["filtered_empty_builder_responses"]
                                                for row in rows),
        "model_calls_total": sum(row["model_calls"] for row in rows),
        "elapsed_seconds_total": round(sum(row["elapsed_seconds"] for row in rows), 2),
        "repairer_calls": sum(row["repairer_calls"] for row in rows),
        "first_reported_blockers": dict(Counter(
            str((row["first_reported_blocker"] or {}).get("reason")) for row in rows)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    current_manifest = load(args.current.resolve() / "manifest.json")
    closure_manifest = load(args.closure.resolve() / "manifest.json")
    fixed = ("production_sha256", "model", "worker_budget", "policies", "cases",
             "fixed_semantic_evidence_policy", "verification_classification_policy",
             "worker_no_tool_policy")
    if any(current_manifest[key] != closure_manifest[key] for key in fixed):
        raise RuntimeError("A/B suites differ in source, authority, or fixed policy")
    current = audit_suite(args.current.resolve(), "current")
    closure = audit_suite(args.closure.resolve(), "bounded_closure")
    all_rows = current + closure
    if not all(row["protected_tests_unchanged"] for row in all_rows):
        raise RuntimeError("protected tests changed")
    safety = {key: sum(row["safety_counters"][key] for row in all_rows) for key in SAFETY_KEYS}
    summary = {"current_guard": summarize(current), "bounded_closure": summarize(closure)}
    data = {"experiment": 19, "comparison_variable": "worker_context_decision_policy",
            "model": current_manifest["model"], "worker_budget": 28,
            "fixed_worker_no_tool_policy": "bounded_reanchor",
            "summary": summary, "rows": all_rows, "safety_counters": safety,
            "production_default_changed": False,
            "safety_metric_limit": "Unsupported sufficient authorization checks empty evidence, contradictions, and unresolved semantic statuses. It does not independently prove semantic sufficiency when behavior verification is absent.",
            "scope_limit": "Frozen approved Python contract, three fresh runs per arm. Planning cost and other domains excluded."}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "experiment19-results.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Experiment 19 — Mandatory Context Decision Closure", "",
             "مقارنة Python على نفس العقد والموديل و28 خطوة؛ Experiment 18 guard ثابت. المتغير الوحيد هو إغلاق قرار السياق بعد inspection.",
             "", "| المسار | أول tool | قرار context | أول legal mutation | Verification PASS | Root verified | missing exits |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for key, label in (("current_guard", "current guard"), ("bounded_closure", "closure guard")):
        row = summary[key]
        lines.append(f"| {label} | {row['first_tool_call']['numerator']}/3 | "
                     f"{row['context_decision_submitted']['numerator']}/3 | "
                     f"{row['first_legal_mutation']['numerator']}/3 | "
                     f"{row['verification_pass']['numerator']}/3 | "
                     f"{row['root_verified']['numerator']}/3 | "
                     f"{row['context_decision_missing_exits']} |")
    lines += ["", "## Safety وموضع التوقف", ""]
    for key, label in (("current_guard", "current guard"), ("bounded_closure", "closure guard")):
        row = summary[key]
        lines.append(f"- {label}: decision statuses={row['decision_statuses']}; "
                     f"reanchors={row['context_decision_reanchors']}; "
                     f"filtered empty Builder responses={row['filtered_empty_builder_responses']}; "
                     f"model calls={row['model_calls_total']}; elapsed seconds={row['elapsed_seconds_total']}; "
                     f"Repairer calls={row['repairer_calls']}; "
                     f"missing sources={row['missing_sources']}; "
                     f"unsupported sufficient authorizations={row['unsupported_sufficient_authorizations']}; "
                     f"first blockers={row['first_reported_blockers']}")
    lines += ["", f"Scope/preservation counters: {sum(safety.values())}. Protected tests unchanged: yes.",
              "فحص false sufficient هنا يغطي التفويض رغم evidence فارغة أو متناقضة أو semantic status غير محسوم. بدون behavior verification لا يمكن الجزم بصحة كل قرار sufficient دلاليًا.",
              "لم يُقدَّم أي قرار sufficient في التشغيلات الستة، لذا false-sufficient rate غير قابل للحساب من الـfresh runs؛ الاختبارات المباشرة تثبت رفض claim كاذب عند وجود أدلة متعارضة.",
              "", "## القرار", "",
              "فرضية رفع معدل قرار السياق لم تتأكد في هذه العينة: 0/3 في المسارين. الحارس الجديد حسّن تصنيف أول عائق فقط، وتسبب في model calls ووقت إضافيين؛ لذلك يبقى تجريبيًا ولا يتحول إلى default.",
              "العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مسار لا تقدر reliability العامة.",
              "", f"[Raw results]({output.resolve().as_posix()})", ""]
    (args.output_dir / "experiment19-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"summary": summary, "safety": safety}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
