"""Audit frozen Python A/B and fresh Timer/Python no-tool handoff runs."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment18_run as experiment
from scripts.experiment12_report import SAFETY_KEYS, audit_trial, load, rate


def audit_suite(suite, expected_set, expected_policy):
    manifest = load(suite / "manifest.json")
    experiment.previous.engine.check_pin(manifest)
    if (manifest["case_set"] != expected_set or manifest["worker_no_tool_policy"] != expected_policy
            or manifest["repeats"] != 3 or manifest["worker_budget"] != 28
            or manifest["verification_classification_policy"] != "field_scoped"):
        raise RuntimeError(f"manifest differs from fixed experiment: {suite}")
    rows = []
    for case in manifest["cases"]:
        for repeat in range(1, 4):
            core = audit_trial(suite, case, experiment.GROUNDING, repeat,
                               expected_semantic_policy="strict",
                               expected_policies=manifest["policies"])
            if not core["completed"]:
                raise RuntimeError(f"missing trial: {suite}/{case['case_id']}/{repeat}")
            workspace = suite / case["case_id"] / f"{experiment.GROUNDING}-{repeat}"
            run = json.loads((workspace / ".agent_experiment.jsonl").read_text(
                encoding="utf-8").splitlines()[-1])
            if (run.get("worker_no_tool_policy", "current") != expected_policy
                    or run.get("verification_classification_policy") != "field_scoped"):
                raise RuntimeError(f"trial policy differs from manifest: {workspace}")
            worker = next((p for p in run.get("worker_progress_runs", [])
                           if p.get("task_id") == "EXEC-001"), None)
            events = run.get("experiment_events", [])
            blockers = [e for e in events if e.get("kind") == "BLOCKED"
                        and e.get("stage") != "PARENT_INTEGRATION"]
            first_tool = bool(worker and worker.get("tool_steps", 0) > 0)
            context_decision = bool(run.get("context_sufficiency_checks", 0) > 0)
            boundary = ("NO_TOOL_EXIT" if not first_tool else
                        "POST_INSPECTION_PRE_CONTEXT_DECISION" if not context_decision else
                        str(blockers[0].get("reason")) if blockers else "NONE")
            rows.append({
                "case_id": case["case_id"], "repeat": repeat,
                "policy": expected_policy,
                "first_builder_tool_call": first_tool,
                "context_decision": context_decision,
                "first_legal_mutation": bool(run.get("first_legal_mutation")),
                "no_tool_reanchors": run.get("worker_no_tool_reanchors", 0),
                "no_progress_exits": run.get("worker_no_progress_exits", 0),
                "verification_executed": core["verification_executed"],
                "verification_pass": core["verification_pass"],
                "child_verified": core["child_verified"],
                "root_verified": core["root_verified"],
                "first_reported_blocker": blockers[0] if blockers else core["first_blocker"],
                "diagnostic_first_boundary": boundary,
                "repairer_calls": core["repairer_calls"],
                "model_calls": core["model_calls"],
                "safety_counters": core["safety_counters"],
                "protected_tests_unchanged": core["tests_unchanged"],
                "workspace": str(workspace.resolve()),
            })
    return rows


def summarize(rows):
    n = len(rows)
    return {
        key: rate(sum(bool(row[key]) for row in rows), n)
        for key in ("first_builder_tool_call", "context_decision", "first_legal_mutation",
                    "verification_executed", "verification_pass", "child_verified", "root_verified")
    } | {
        "no_tool_reanchors": sum(row["no_tool_reanchors"] for row in rows),
        "no_progress_exits": sum(row["no_progress_exits"] for row in rows),
        "repairer_calls": sum(row["repairer_calls"] for row in rows),
        "first_reported_blockers": dict(Counter(
            str((row["first_reported_blocker"] or {}).get("reason")) for row in rows)),
        "diagnostic_first_boundaries": dict(Counter(row["diagnostic_first_boundary"] for row in rows)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--reanchor", type=Path, required=True)
    parser.add_argument("--cross-domain", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifests = [load(path.resolve() / "manifest.json")
                 for path in (args.current, args.reanchor, args.cross_domain)]
    if not all(m["production_sha256"] == manifests[0]["production_sha256"]
               and m["model"] == manifests[0]["model"]
               and m["policies"] == manifests[0]["policies"] for m in manifests[1:]):
        raise RuntimeError("cross-suite source/model/policy pins differ")
    case_records = [next(c for c in m["cases"] if c["case_id"] == "python_clamp")
                    for m in manifests]
    if not all(c == case_records[0] for c in case_records[1:]):
        raise RuntimeError("Python approved authority or seed differs between suites")
    current = audit_suite(args.current.resolve(), "python", "current")
    reanchor = audit_suite(args.reanchor.resolve(), "python", "bounded_reanchor")
    cross = audit_suite(args.cross_domain.resolve(), "cross_domain", "bounded_reanchor")
    if len(current) != 3 or len(reanchor) != 3 or len(cross) != 6:
        raise RuntimeError("incomplete experiment")
    all_rows = current + reanchor + cross
    if not all(row["protected_tests_unchanged"] for row in all_rows):
        raise RuntimeError("protected test changed")
    safety = {key: sum(row["safety_counters"][key] for row in all_rows) for key in SAFETY_KEYS}
    summaries = {
        "python_current": summarize(current),
        "python_bounded_reanchor": summarize(reanchor),
        "cross_domain_python": summarize([r for r in cross if r["case_id"] == "python_clamp"]),
        "cross_domain_timer": summarize([r for r in cross if r["case_id"] == "timer_pause"]),
    }
    data = {"experiment": 18, "model": "gemma4:e4b", "worker_budget": 28,
            "fixed_stack": {"mission_advice_policy": "contract_fallback",
                            "semantic_evidence_policy": "strict",
                            "mutation_grounding_policy": "evidence_bound",
                            "verification_classification_policy": "field_scoped"},
            "comparison_variable": "worker_no_tool_policy",
            "summaries": summaries, "rows": all_rows, "safety_counters": safety,
            "production_default_changed": False,
            "limits": "Frozen approved authority and three attempts per arm; no estimate for all Python/Timer tasks."}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "experiment18-results.json"
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    labels = {"python_current": "Python current", "python_bounded_reanchor": "Python reanchor",
              "cross_domain_python": "Python fresh", "cross_domain_timer": "Timer fresh"}
    lines = ["# Experiment 18 — No-Tool Worker Exit Guard", "",
             "نفس العقود المجمدة، model و28 خطوة والسياسات الأخرى. الاختلاف الوحيد في مقارنة Python هو worker_no_tool_policy.",
             "", "| الدفعة | أول tool call | context decision | أول legal mutation | verification executed/PASS | Child verified | Root verified | no-progress exits |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, label in labels.items():
        s = summaries[key]
        lines.append(f"| {label} | {s['first_builder_tool_call']['numerator']}/3 | "
                     f"{s['context_decision']['numerator']}/3 | {s['first_legal_mutation']['numerator']}/3 | "
                     f"{s['verification_executed']['numerator']}/3 / {s['verification_pass']['numerator']}/3 | "
                     f"{s['child_verified']['numerator']}/3 | {s['root_verified']['numerator']}/3 | "
                     f"{s['no_progress_exits']} |")
    lines += ["", "## أول عائق معلن", ""]
    for key, label in labels.items():
        lines.append(f"- {label}: {summaries[key]['first_reported_blockers']}")
    lines += ["", "## أول حد فعلي في trace", ""]
    for key, label in labels.items():
        lines.append(f"- {label}: {summaries[key]['diagnostic_first_boundaries']}")
    lines += ["", f"Scope/preservation counters: {sum(safety.values())}. Protected tests unchanged: yes.",
              "في Python مع reanchor: كل التشغيلات الستة قرأت المصدر والاختبارات، ثم خرجت قبل context_sufficiency_check. رسالة controller هي CONTEXT_INSUFFICIENT مع تفصيل أن pre-mutation impact contract لم يُقبل؛ لا نعدّها failure في verification المنفذة.",
              "الأعمدة تخص كل تشغيل من الثلاثة، وأول عائق معلن لا يعاد تفسيره من إخفاقات recovery اللاحقة.",
              "العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مهمة لا تقدر reliability العامة.",
              "", f"[Raw results]({output.resolve().as_posix()})", ""]
    (args.output_dir / "experiment18-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"summaries": summaries, "safety": safety}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
