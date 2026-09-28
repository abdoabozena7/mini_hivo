"""Report frozen compatibility results and every fresh trial with denominators."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hivo.atomic_child_receipt import validate_atomic_child_receipt


def read(path):
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "percent": round(100 * numerator / denominator, 1) if denominator else None}


def show(value):
    return f"{value['numerator']}/{value['denominator']} ({value['percent']:g}%)" if value["denominator"] else "N/A"


def summarize(path):
    run = read(path)
    events = [json.loads(line) for file in sorted((path.parent / ".agent_runs").glob("*.jsonl"))
              for line in file.read_text(encoding="utf-8").splitlines() if line]
    receipts = run.get("child_receipts", {})
    checked = {}
    for child_id, receipt in receipts.items():
        contract = run["execution_contract_by_id"][child_id]
        checked[child_id] = validate_atomic_child_receipt(receipt, workspace=path.parent,
            expected_contract_hash=contract["contract_hash"], expected_node_ids=contract["plan_node_ids"],
            expected_requirement_ids=contract["requirement_ids"], expected_requirements=contract["requirements"])
    experiment = run.get("experiment_events", [])
    blocker = next((e for e in experiment if e["kind"] == "BLOCKED"), None)
    browser = run.get("verification_browser_results", [])
    parent_runs = run.get("parent_verification_runs", [])
    covered = {req for item in parent_runs if item.get("classification") == "PASS"
               and (item.get("result") or {}).get("passed") is True for req in item.get("covered_requirement_ids", [])}
    return {"workspace": str(path.parent.resolve()), "run_id": run["run_id"], "source_sha256": run["source_sha256"],
            "model": run["model"], "plan_hash": (run.get("plan_approval") or {}).get("plan_hash"),
            "approval_status": (run.get("plan_approval") or {}).get("approval_status"),
            "execution_contract_hashes": {k: v["contract_hash"] for k, v in run.get("execution_contract_by_id", {}).items()},
            "policies": {k: run.get(k) for k in ("planning_route", "mission_advice_policy", "worker_progress_policy",
                "mutation_grounding_policy", "target_locator_policy", "verification_environment_policy",
                "verification_surface_policy", "child_receipt_policy", "integration_target_policy", "semantic_evidence_policy")},
            "unchanged_worker_component_hashes": {k: run.get(k) for k in ("worker_progress_source_sha256",
                "mutation_grounding_source_sha256", "target_locator_source_sha256")},
            "worker_started": any(e["kind"] == "FIRST_WORKER_STARTED" for e in experiment),
            "legal_mutation_committed": bool(run.get("first_legal_mutation")) and any(r.get("verified") for r in receipts.values()),
            "first_legal_mutation": run.get("first_legal_mutation"),
            "child_behavior_pass": any(e.get("status") == "PASS" and e.get("behavior_test_executed") is True
                                       for e in browser if e.get("task_id") != "ROOT"),
            "canonical_evidence_records": len(run.get("canonical_evidence_records", [])),
            "semantic_aggregation_pass": any(e.get("kind") == "semantic_evidence_assessed" and e.get("status") == "PASS" for e in events),
            "child_verified_events": sum(e["kind"] == "CHILD_VERIFIED" for e in experiment),
            "verified_receipts": sum(c["valid"] for c in checked.values()), "receipt_validations": checked,
            "node_001_preserved": any("NODE-001" in r.get("covered_node_ids", []) for r in receipts.values() if r.get("verified")),
            "fresh_parent_behavior_executed": any((e.get("result") or {}).get("behavior_test_executed") is True for e in parent_runs),
            "parent_requirement_ids_covered": sorted(covered),
            "child_evidence_reused_as_parent_proof": sum(e.get("child_evidence_reused_as_proof", 0) for e in parent_runs),
            "root_verified": run["root_verified"], "first_blocker": blocker, "status": run["status"],
            "model_calls": run["model_calls"], "repairer_calls": run["repairer_calls"], "elapsed_seconds": run["elapsed_seconds"],
            "provider_timeouts": run.get("ollama_timeout_failures", 0), "provider_retries": run.get("ollama_retry_count", 0),
            "safety": {k: run.get(k, 0) for k in ("execution_contract_scope_violations", "mutation_scope_violations",
                "impact_out_of_scope_changes", "impact_preservation_violations", "dnt_execution_violations",
                "unapproved_scope_expansions", "invariant_violations_detected")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--fresh-run-file", type=Path, required=True, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frozen = json.loads(args.comparison.read_text(encoding="utf-8"))
    trials = [summarize(path) for path in args.fresh_run_file]
    metrics = {key: rate(sum(bool(r[key]) for r in trials), len(trials)) for key in
               ("worker_started", "child_behavior_pass", "semantic_aggregation_pass", "node_001_preserved",
                "fresh_parent_behavior_executed", "root_verified")}
    metrics["valid_receipts_per_verified_child_event"] = rate(sum(r["verified_receipts"] for r in trials),
                                                              sum(r["child_verified_events"] for r in trials))
    data = {"experiment": 11, "sample_tasks": 1, "fixed_worker_budget": 28, "frozen_comparison": frozen,
            "fresh_trials": trials, "metrics": metrics,
            "scope_preservation_violation_count": sum(sum(r["safety"].values()) for r in trials),
            "repairer_calls": sum(r["repairer_calls"] for r in trials),
            "child_evidence_reused_as_parent_proof": sum(r["child_evidence_reused_as_parent_proof"] for r in trials)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Experiment 11 — Semantic Evidence Compatibility", "",
             "## المقارنة على نفس الحالة القديمة", "",
             "نفس approved contract ونفس candidate patch، مع اختبار Browser جديد في كل مسار.", "",
             "| المسار | اختبار behavior | Evidence gate | Verified Child Receipt |", "|---|---|---|---|"]
    for branch in frozen["policies"]:
        lines.append(f"| {branch['policy']} | {'PASS' if branch['browser']['passed'] else 'FAIL'} | "
                     f"{'PASS' if branch['evidence_gate_passed'] else branch['first_blocker']['reason']} | {branch['child_verified']} |")
    lines += ["", "## المحاولات الجديدة من البداية للنهاية", "",
              "| المحاولة | Worker | Child verified | Parent test جديد | Root verified | أول blocker |", "|---|---|---|---|---|---|"]
    for trial in trials:
        lines.append(f"| {Path(trial['workspace']).name} | {trial['worker_started']} | {trial['verified_receipts']} | "
                     f"{trial['fresh_parent_behavior_executed']} | {trial['root_verified']} | {trial['first_blocker'] or 'لا يوجد'} |")
    lines += ["", "## النسب", "", "| القياس | النتيجة |", "|---|---|"]
    labels = {"worker_started": "الوصول للـWorker", "child_behavior_pass": "اختبار Child سلوكي ناجح",
              "semantic_aggregation_pass": "قبول الأدلة المتوافقة", "node_001_preserved": "الحفاظ على تغطية NODE-001",
              "fresh_parent_behavior_executed": "تنفيذ اختبار Parent جديد", "root_verified": "نجاح Root",
              "valid_receipts_per_verified_child_event": "Receipts صحيحة / CHILD_VERIFIED"}
    lines.extend(f"| {labels[key]} | {show(value)} |" for key, value in metrics.items())
    lines += ["", f"مخالفات scope/preservation المسجلة: **{data['scope_preservation_violation_count']}**.",
              f"استدعاءات Repairer: **{data['repairer_calls']}**. إعادة استخدام child proof بدل parent proof: **{data['child_evidence_reused_as_parent_proof']}**.",
              "", "## اختبارات قبول ورفض الأدلة", "",
              "- أدوات مختلفة لنفس requirement/target/assertions: ACCEPT.",
              "- نفس الملف مع behavior مختلف، أو target/requirement/input مختلف: REJECT.",
              "- Page-load فقط، evidence قديمة، interaction لم ينفذ، أو terminal case فاشلة: REJECT.",
              "- Approved authority/direct oracle/scope/impact gates: الاختبارات الحالية مستمرة.",
              "", "## الوقت والتكلفة", "",
              "| المحاولة | الوقت بالثواني | Model calls | Provider timeouts | Repairer calls |", "|---|---|---|---|---|"]
    lines.extend(f"| {Path(t['workspace']).name} | {t['elapsed_seconds']} | {t['model_calls']} | {t['provider_timeouts']} | {t['repairer_calls']} |" for t in trials)
    lines += [
              "", "## حدود الاستنتاج وإعادة التشغيل", "",
              "هذه محاولات متكررة لمهمة R-key واحدة؛ النسب لا تمثل كل مشاريع HIVO.",
              "الاختبار المجمد يعزل سبب aggregation. المحاولات الجديدة تختبر السلسلة كاملة، وتشمل أي فشل سابق للتحقق في المقام.",
              "الأرشيف القديم يحتفظ بنتائج tools مختصرة. تمت استعادة accepted Impact Contract من capture لاحقة بعد مطابقة hash مع authorization القديمة، ومطابقة execution contract وcontext anchor وsource bytes.",
              "المقارنة المجمدة لا تتضمن Worker/Falsifier أو Parent جديدين؛ الـBrowser جديد والـimpact/commit/receipt seam فعلي.",
              "اختلف hash لملف mini.py أثناء استخراج helper لإعادة دخول نفس post-verification block دون تغيير منطقه؛ تفاصيل hash محفوظة لكل محاولة. أضيف أيضًا رفض deterministic لأي ملخص PASS يحتوي terminal case فاشلة داخل normalizer. جميع receipts النهائية أعيد فحصها بالـvalidator النهائي؛ الـWorker والـverifier والـintegration لم تتغير.",
              "", "تفاصيل كل run والسياسات وhashes وreceipt validation موجودة في ملف JSON المجاور.",
              "", "## ملفات الأدلة", "", f"- [Frozen comparison]({args.comparison.resolve().as_posix()})"]
    lines.extend(f"- [{path.parent.name}]({path.resolve().as_posix()})" for path in args.fresh_run_file)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": metrics, "safety": data["scope_preservation_violation_count"], "report": str(args.output.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
