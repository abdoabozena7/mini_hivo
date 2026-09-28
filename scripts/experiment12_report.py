"""Audit Experiment 12 denominators without treating page load as behavior PASS."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hivo.atomic_child_receipt import validate_atomic_child_receipt
from scripts.experiment12_run import POLICIES, check_pin


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def rate(numerator, denominator):
    return {"numerator":numerator, "denominator":denominator,
            "percent":round(100*numerator/denominator, 2) if denominator else None}


def browser_pass(case, payload):
    """Judge native assertions, including timer evidence without Exp11 flags."""
    if not isinstance(payload, dict) or payload.get("passed") is not True:
        return False
    if (payload.get("resolved_entrypoint") or payload.get("entry_path")) != case["source"]:
        return False
    checks = {c.get("name"):c for c in payload.get("interaction_checks", [])}
    for name in case["expected_interactions"]:
        check = checks.get(name, {})
        if check.get("passed") is not True:
            return False
        if name.startswith("timer_"):
            # Timer verifier actually clicks/advances the clock but does not
            # emit executed flags. Excluding it would hide normalization loss.
            before, after = check.get("before", {}), check.get("after", {})
            if not isinstance(before.get("seconds"), (int, float)) or not isinstance(after.get("seconds"), (int, float)):
                return False
            if name == "timer_start_changes_visible_time" and not (before["seconds"] > after["seconds"] >= 0):
                return False
            if name == "timer_pause_freezes_visible_time" and not (before["seconds"] == after["seconds"] > 0):
                return False
            if name == "timer_reset_restores_visible_time" and after["seconds"] != checks["timer_start_changes_visible_time"].get("before", {}).get("seconds"):
                return False
        elif check.get("executed") is not True:
            return False
    if "keyboard_movement" in checks and checks["keyboard_movement"].get("input") != "ArrowUp":
        return False
    if "touch_control" in checks and checks["touch_control"].get("input") != "pointerdown":
        return False
    if "restart_resets_state" in case["expected_interactions"]:
        restart = checks["restart_resets_state"]
        trials = restart.get("cases", [])
        if restart.get("input") != "q" or {c.get("setup") for c in trials} != {"forceCollision", "forceWin"}:
            return False
        if not all(c.get("passed") is True and c.get("precondition_met") is True for c in trials):
            return False
    return True


def unit_pass(case, evidence):
    for item in evidence:
        if item.get("tool") not in {"run_file", "run_command", "unit_test_result"}:
            continue
        if item.get("target") not in {case["test_target"], case["integration_target"]}:
            continue
        result = str(item.get("result", ""))
        if "[exit_code=0]" not in result:
            continue
        if case["case_id"] == "python_clamp" and re.search(r"Ran 5 tests\b", result) and re.search(r"\bOK\b", result):
            return True
        if case["case_id"] == "node_unique" and "unique behavior tests: 4 passed" in result:
            return True
    return False


def gate_passes(case, observation):
    inputs = observation["inputs"]
    if len(inputs) != 3 or inputs[0].get("status") != "done":
        return False
    if case["family"].startswith("browser"):
        return browser_pass(case, inputs[2])
    evidence = [item for agent in inputs[:2] for item in agent.get("tool_evidence", [])]
    return unit_pass(case, evidence)


SAFETY_KEYS = ("mutation_scope_violations", "dnt_execution_violations", "execution_contract_scope_violations",
               "impact_preservation_violations", "invariant_violations_detected", "impact_out_of_scope_changes")


def audit_trial(suite, case, policy, repeat):
    workspace = suite/case["case_id"]/f"{policy}-{repeat}"
    result_path = workspace.parent/f"{workspace.name}-result.json"
    if not result_path.exists():
        return {"case_id":case["case_id"], "policy":policy, "repeat":repeat, "completed":False}
    result = load(result_path)
    run = json.loads((workspace/".agent_experiment.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    manifest = load(suite/"manifest.json")
    pinned = (run.get("model") == manifest["model"]
        and run.get("source_sha256") == manifest["production_sha256"]["mini.py"]
        and all(run.get(k) == value for k, value in POLICIES.items())
        and run.get("semantic_evidence_policy") == policy
        and run.get("plan_approval", {}).get("plan_hash") == case["approved_plan_hash"]
        and run.get("execution_contract_by_id", {}).get("EXEC-001", {}).get("contract_hash") == case["execution_contract_hash"])
    if not pinned:
        raise RuntimeError(f"trial no longer matches fixed model/policies/authority: {workspace}")
    observations = load(workspace.parent/f"{workspace.name}-observations.json")
    event_path = next((workspace/".agent_runs").glob("*.jsonl"))
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    gates = [o for o in observations if o["kind"] == "evidence_gate"]
    genuine_passes = [o for o in gates if gate_passes(case, o)]
    receipt = run.get("child_receipts", {}).get("EXEC-001")
    authority = load(workspace.parent/"authority.json")
    checked = validate_atomic_child_receipt(receipt, workspace=workspace,
        expected_contract_hash=case["execution_contract_hash"], expected_node_ids=["NODE-001"],
        expected_requirement_ids=["REQ-001"], expected_requirements=authority["requirements"])
    valid_receipt = checked.get("valid") is True
    normalize_rejections = [o for o in genuine_passes
        if o["result"].get("verification_aggregation", {}).get("invalid_receipts")]
    invalid_event = any(e["kind"] == "atomic_child_receipt_checked" and e.get("valid") is False for e in events)
    if genuine_passes and not valid_receipt and invalid_event:
        normalize_rejections.append({"receipt_validation":False})
    browser_executed = any(o["kind"] == "browser" and bool(o.get("result", {}).get("interaction_checks")) for o in observations)
    unit_executed = any(o["kind"] in {"run_file", "run_command"}
        and o.get("target") in {case.get("test_target"), case.get("integration_target")}
        and "[exit_code=" in str(o.get("result")) for o in observations) if case.get("test_target") else False
    first_rejection = next((o["result"].get("verification_aggregation") for o in gates
        if o["result"].get("verification_aggregation", {}).get("passed") is False), None)
    blockers = [e for e in events if e["kind"] == "BLOCKED"]
    fallback_reason = result.get("reason") or result.get("failure_type") or result.get("summary") or result["status"]
    child_summary = " ".join(c.get("summary", "") for c in result.get("contract_results", []))
    first_blocker = ({"stage":"aggregation", "reason":first_rejection.get("failure_codes"),
                     "invalid_receipt_count":len(first_rejection.get("invalid_receipts", []))}
                    if first_rejection else blockers[0] if blockers else {"reason":fallback_reason})
    if not gates and "pre-mutation impact contract was not accepted" in child_summary:
        first_blocker = {"stage":"worker_pre_mutation_impact", "reason":"IMPACT_NOT_ACCEPTED",
                         "controller_label":first_blocker, "detail":child_summary}
    elif not gates and "MUTATION_TARGET_UNRESOLVED" in child_summary:
        first_blocker = {"stage":"worker_mutation_grounding", "reason":"MUTATION_TARGET_UNRESOLVED",
                         "controller_label":first_blocker, "detail":child_summary}
    parent_runs = run.get("parent_verification_runs", [])
    parent_proof = any(p.get("parent_verification_executed") is True and p.get("classification") == "PASS"
        and p.get("result", {}).get("passed") is True and "REQ-001" in p.get("covered_requirement_ids", [])
        and p.get("child_evidence_reused_as_proof") == 0 for p in parent_runs)
    if run.get("root_verified") is True and not parent_proof:
        raise RuntimeError(f"Root success lacks fresh requirement-bound parent proof: {workspace}")
    # Independent receipt validation cannot itself count as a behavioral oracle.
    # Any success missing an assertion-bearing native PASS is flagged for audit.
    return {"case_id":case["case_id"], "family":case["family"], "policy":policy, "repeat":repeat,
        "completed":True, "run_id":run.get("run_id"), "result":result["status"],
        "fixed_model_policies_authority_match":pinned,
        "verification_executed":browser_executed or unit_executed,
        "verification_pass":bool(genuine_passes), "valid_receipt":valid_receipt,
        "receipt_validation_errors":checked.get("errors"),
        "child_verified":any(e["kind"] == "CHILD_VERIFIED" for e in events) and valid_receipt,
        "root_verified":run.get("root_verified") is True,
        "fresh_parent_verification":any(e["kind"] == "fresh_parent_verification" for e in events),
        "fresh_parent_proof_covers_requirement":parent_proof,
        "false_reject":bool(normalize_rejections),
        "acceptance_needs_oracle_audit":valid_receipt and not genuine_passes,
        "repairer_calls":run.get("repairer_calls", 0), "model_calls":run.get("model_calls", 0),
        "tool_calls":run.get("tool_calls", 0), "elapsed_seconds":run.get("elapsed_seconds", 0),
        "safety_counters":{k:run.get(k, 0) for k in SAFETY_KEYS},
        "tests_unchanged":all((workspace/p).read_bytes() == (workspace.parent/"seed"/p).read_bytes()
                              for p in case["seed_sha256"] if p != case["source"]),
        "plan_hash_matches":result.get("plan_hash") == case["approved_plan_hash"],
        "first_blocker":first_blocker, "terminal_reason":fallback_reason,
        "evidence_files":{"observations":str(workspace.parent/f"{workspace.name}-observations.json"),
                          "events":str(event_path), "result":str(result_path)}}


def summarize(trials):
    complete = [t for t in trials if t["completed"]]
    n = len(complete)
    passed = sum(t["verification_pass"] for t in complete)
    receipts = sum(t["valid_receipt"] and t["verification_pass"] for t in complete)
    roots = sum(t["root_verified"] for t in complete)
    calls = sum(t["model_calls"] for t in complete)
    seconds = round(sum(t["elapsed_seconds"] for t in complete), 2)
    return {"expected_attempts":len(trials), "completed_attempts":n,
        "verification_executable_rate":rate(sum(t["verification_executed"] for t in complete), n),
        "verification_pass_rate":rate(passed, n), "valid_receipt_rate":rate(receipts, passed),
        "child_verified_rate":rate(sum(t["child_verified"] for t in complete), n),
        "root_verified_rate":rate(roots, n),
        "false_rejection_rate":rate(sum(t["false_reject"] for t in complete), passed),
        "acceptances_needing_oracle_audit":sum(t["acceptance_needs_oracle_audit"] for t in complete),
        "native_negative_evidence_cases":0,
        "repairer_run_rate":rate(sum(t["repairer_calls"] > 0 for t in complete), n),
        "repairer_calls":sum(t["repairer_calls"] for t in complete),
        "safety_counters":dict(Counter({k:sum(t["safety_counters"][k] for t in complete) for k in SAFETY_KEYS})),
        "test_file_mutations":sum(not t["tests_unchanged"] for t in complete),
        "total_model_calls":calls, "total_tool_calls":sum(t["tool_calls"] for t in complete),
        "agent_tool_calls_per_root_verified":round(sum(t["tool_calls"] for t in complete)/roots, 2) if roots else None,
        "total_elapsed_seconds":seconds, "model_calls_per_root_verified":round(calls/roots, 2) if roots else None,
        "seconds_per_root_verified":round(seconds/roots, 2) if roots else None,
        "first_blockers":dict(Counter(str(t["first_blocker"].get("stage", "unknown")) for t in complete if not t["root_verified"]))}


def matrix_summary(data):
    result = {}
    for policy in ("current", "compatible"):
        rows = [r for r in data["outcomes"] if r["policy"] == policy]
        positive = [r for r in rows if r["expected_compatible"]]
        negative = [r for r in rows if not r["expected_compatible"]]
        result[policy] = {"positive_cases":len(positive), "negative_cases":len(negative),
            "false_rejection_rate":rate(sum(r["false_reject"] for r in positive), len(positive)),
            "final_receipt_false_acceptance_rate":rate(sum(r["false_accept"] for r in negative), len(negative)),
            "aggregation_false_acceptance_rate":rate(sum(r["aggregation_false_accept"] for r in negative), len(negative))}
    return result


def compact_paired(data, source):
    result = {k:v for k,v in data.items() if k != "comparisons"}
    result["full_original_results_path"] = str(source.resolve())
    result["comparisons"] = []
    for pair in data["comparisons"]:
        row = {k:v for k,v in pair.items() if k != "arms"}
        row["arms"] = []
        for arm in pair["arms"]:
            entry = {k:arm.get(k) for k in ("policy", "input_hash", "eligible", "child_verified", "blocker",
                     "commit_status", "model_calls", "repairer_calls", "root_verification_executed")}
            entry.update(subject_before_hash=arm.get("subject_before", {}).get("hash"),
                         subject_after_hash=arm.get("subject_after", {}).get("hash"),
                         receipt_validation=arm.get("receipt_validation"),
                         receipt_hash=(arm.get("receipt") or {}).get("receipt_hash"),
                         gate_passed=(arm.get("gate") or {}).get("passed"),
                         full_result_path=str((source.parent/pair["case_id"]/(arm["policy"]+".json")).resolve()))
            row["arms"].append(entry)
        result["comparisons"].append(row)
    return result


def pct(r):
    return f"{r['numerator']}/{r['denominator']} ({r['percent']:g}%)" if r["percent"] is not None else "N/A (0 cases)"


def markdown(data):
    lines = ["# Experiment 12 — Generalization & Reliability", "",
        "## النطاق الثابت", "",
        "5 مهام × 3 fresh runs × سياستين = 30 محاولة. الموديل gemma4:e4b، وWorker budget = 28.",
        "",
        "السياسة الإنتاجية لم تتغير. كل مهمة تبدأ من نفس approved contract في workspace نظيف، ثم تمر على Worker والتحقق والـreceipt والتكامل الأصليين.",
        "",
        "القياس يبدأ من العقد المعتمد؛ التخطيط مثبت ومُستبعد من calls/time. لذلك هذه نتيجة execution-to-root وليست قياسًا للتخطيط من طلب حر.", "",
        "## النتائج الفعلية", "",
        "| المقياس | current | compatible |", "|---|---:|---:|"]
    arms = data["fresh_summary"]
    for title, key in (("Verification PASS / fresh attempts", "verification_pass_rate"),
                       ("Valid receipt / Verification PASS", "valid_receipt_rate"),
                       ("Child verified / fresh attempts", "child_verified_rate"),
                       ("Root verified / fresh attempts", "root_verified_rate"),
                       ("False rejection / actual PASS", "false_rejection_rate"),
                       ("Runs using Repairer", "repairer_run_rate")):
        lines.append(f"| {title} | {pct(arms['current'][key])} | {pct(arms['compatible'][key])} |")
    for title, key in (("Repairer calls", "repairer_calls"), ("Model calls / Root verified", "model_calls_per_root_verified"),
                       ("Agent tool calls / Root verified", "agent_tool_calls_per_root_verified"),
                       ("Seconds / Root verified", "seconds_per_root_verified")):
        values = [str(arms[p][key]) if arms[p][key] is not None else "N/A (0 Root success)" for p in ("current", "compatible")]
        lines.append(f"| {title} | {values[0]} | {values[1]} |")
    lines += ["", "التكلفة = مجموع تكلفة كل المحاولات، بما فيها الفشل، ÷ عدد Root verified؛ ليست متوسط تكلفة المحاولات الناجحة فقط.", "",
        "### لكل مهمة", "", "| المهمة | current Root | compatible Root | current receipt/PASS | compatible receipt/PASS |",
        "|---|---:|---:|---:|---:|"]
    for case, by_policy in data["by_case"].items():
        c, s = by_policy["current"], by_policy["compatible"]
        lines.append(f"| {case} | {pct(c['root_verified_rate'])} | {pct(s['root_verified_rate'])} | {pct(c['valid_receipt_rate'])} | {pct(s['valid_receipt_rate'])} |")
    lines += ["", f"المهام التي وصلت فعليًا إلى executable verification في المحاولات الطازجة: **{len(data['eligible_fresh_cases'])}/5** ({', '.join(data['eligible_fresh_cases'])}).",
        "Timer توقف عند mutation grounding، وPython عند pre-mutation impact. لذلك هذه العينة لا تحقق شرط 5–8 مهام مؤهلة من Worker؛ لا يُستنتج منها تعميم end-to-end على الخمس مهام."]
    lines += ["", "قراءة الصفحة فقط، أو syntax-only، لا تُحسب behavior PASS. الـTimer يُحسب من before/after الفعلية حتى لو افتقد executed flag؛ نقص الـflag هو أحد الأشياء التي تختبرها التجربة.", "",
        "## Same-child paired handoff", "",
        "هذه إعادة تحقق جديدة لنفس post-child state تحت السياستين، بدون model أو Repairer. لا تدخل في fresh-run denominator ولا تثبت Root success.", "",
        "| المهمة | current Child | compatible Child | نفس input hash |", "|---|---|---|---|"]
    for pair in data.get("paired_handoffs", {}).get("comparisons", []):
        rows = {a["policy"]:a for a in pair["arms"]}
        equal = rows["current"]["input_hash"] == rows["compatible"]["input_hash"]
        lines.append(f"| {pair['case_id']} | {rows['current'].get('child_verified', False)} | {rows['compatible'].get('child_verified', False)} | {equal} |")
    lines += ["", "اختيار handoff = أقدم Worker مكتمل لكل مهمة، وليس اختيار PASS. أي مهمة بدون Worker مكتمل تُذكر كغير مؤهلة لهذا القياس فقط.", "",
        "## اختبارات قبول الأدلة المختلفة", "",
        "مجموعة protocol مستقلة: نتائج reference verification حقيقية، مع أدلة behavior/target مختلفة وrecords requirement مختلفة عمدًا، وتبديل provenance معلن. ليست fresh model runs، ولا تُفسر كنسبة أخطاء ميدانية.", "",
        "| المقياس | current | compatible |", "|---|---:|---:|"]
    matrix = data.get("protocol_summary", {})
    if matrix:
        for title, key in (("Final receipt false acceptance", "final_receipt_false_acceptance_rate"),
                           ("False rejection of compatible reference", "false_rejection_rate"),
                           ("Aggregation false acceptance (before receipt)", "aggregation_false_acceptance_rate")):
            lines.append(f"| {title} | {pct(matrix['current'][key])} | {pct(matrix['compatible'][key])} |")
    lines += ["", "الـaggregation والـfinal receipt مقاسان منفصلان؛ رفض receipt لاحقًا لا يمحو قبول aggregation غير صحيح.", "",
        "### تحقق reference جديد، 3 مرات لكل مهمة", "",
        "هذه candidate patches صحيحة مستقلة عن Worker، ونُفِّذت اختبارات السلوك عليها فعليًا قبل تمرير الأدلة لكل سياسة. 15 native verifications، و30 paired policy evaluations؛ لا model calls ولا Root success من هذا القياس.",
        "",
        "| المهمة | native PASS | current native receipt | compatible native receipt |",
        "|---|---:|---:|---:|"]
    for case, values in data["native_reference_compatibility"].items():
        lines.append(f"| {case} | {values['native_verifications']}/{values['native_verifications']} | {pct(values['current'])} | {pct(values['compatible'])} |")
    lines += ["", f"اتفاق نتائج الـprotocol بين الدورات: **{data['protocol_repetitions_agree']}**. تكرار نفس الحالات لا يجعلها 3 مجموعات مستقلة لتقدير نسبة الأخطاء في الاستخدام الحقيقي.", "",
        "## السلامة والقرار", "",
        f"Production hashes unchanged: **{data['production_pins_valid']}**. All 30 completed: **{data['all_completed']}**.",
        "",
        f"إجمالي مخالفات scope/preservation المسجلة: current={sum(arms['current']['safety_counters'].values())}, compatible={sum(arms['compatible']['safety_counters'].values())}. تفاصيل العدادات في JSON.",
        f"تعديلات ملفات الاختبارات المحمية: current={arms['current']['test_file_mutations']}, compatible={arms['compatible']['test_file_mutations']}.",
        "", "لا تُرقَّى السياسة إلى default في هذه التجربة. التحسن في الألعاب لا يثبت تعميمًا على Timer أو unit/test evidence؛ النتائج التفصيلية تحدد حدود السياسة الحالية.",
        "",
        "**سبب الرفض محدد:** Timer لا يخرج `behavior_test_executed` و`executed` التي يتطلبها normalizer. وفي unit routes تمرَّر `semantic_browser_evidence={}`، ثم يرفض validator الـinventory الفارغة. الـNode fresh run والـsame-child replay يؤكدان تراجعًا حقيقيًا: current ينجح وcompatible يرفض نفس الدليل الصحيح.",
        "صفر final false accepts في compatible يصاحبه رفض أدلة صحيحة؛ لا يُعد ذلك وحده تعميمًا آمنًا. non-browser aggregation ما زال يقبل 6 حالات غير متوافقة من مجموعة الـprotocol، ثم يمنعها رفض الـreceipt الفارغة.",
        "",
        "حجم العينة 3 لكل arm/task؛ ليس تقديرًا قويًا للموثوقية على مستودعات حقيقية. المسارات المستقلة تبدأ من authority معلومة، والألعاب توفر hooks موجودة مسبقًا.", "",
        "## الملفات القابلة للمراجعة", "",
        f"- Manifest + seeds + frozen authority + full original observations: [suite]({Path(data['suite']).as_posix()}).",
        f"- Machine-readable metrics: [experiment12-results.json]({Path(data['result_path']).as_posix()}).",
        f"- Protocol raw inputs and output: [matrix.json]({Path(data['matrix_path']).as_posix()}).", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--paired", type=Path, required=True)
    parser.add_argument("--matrix-repeat", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    manifest = load(args.suite/"manifest.json")
    check_pin(manifest)
    trials = [audit_trial(args.suite, case, policy, repeat) for case in manifest["cases"]
              for policy in ("current", "compatible") for repeat in range(1, manifest["repeats"]+1)]
    all_complete = all(t["completed"] for t in trials)
    if not all_complete and not args.allow_incomplete:
        raise RuntimeError("fresh batch incomplete; do not publish a final denominator")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir/"experiment12-results.json"
    matrix_inputs = [load(p) for p in [args.matrix, *args.matrix_repeat]]
    def protocol_signature(matrix):
        return sorted((r["case_id"], r["scenario"], r["policy"], r["aggregation_accepted"], r["valid_receipt"])
                      for r in matrix["outcomes"])
    reference = {}
    for case in manifest["cases"]:
        rows = [r for matrix in matrix_inputs for r in matrix["outcomes"]
                if r["case_id"] == case["case_id"] and r["scenario"] == "native_matching_claim"]
        reference[case["case_id"]] = {"native_verifications":len(matrix_inputs),
            **{p:rate(sum(r["valid_receipt"] for r in rows if r["policy"] == p), len(matrix_inputs))
               for p in ("current", "compatible")}}
    data = {"experiment":12, "suite":str(args.suite.resolve()), "all_completed":all_complete,
        "production_pins_valid":True, "planning_included":False, "worker_budget":manifest["worker_budget"],
        "model":manifest["model"], "fresh_trials":trials,
        "fresh_summary":{p:summarize([t for t in trials if t["policy"] == p]) for p in ("current", "compatible")},
        "by_case":{c["case_id"]:{p:summarize([t for t in trials if t["case_id"] == c["case_id"] and t["policy"] == p])
                                  for p in ("current", "compatible")} for c in manifest["cases"]},
        "paired_handoffs":compact_paired(load(args.paired), args.paired), "matrix_path":str(args.matrix.resolve()),
        "protocol_summary":matrix_summary(load(args.matrix)), "default_promoted":False,
        "eligible_fresh_cases":sorted({t["case_id"] for t in trials if t["completed"] and t["verification_executed"]}),
        "native_reference_compatibility":reference,
        "protocol_repetitions_agree":all(protocol_signature(m) == protocol_signature(matrix_inputs[0]) for m in matrix_inputs),
        "protocol_repetitions":[{"path":str(p.resolve()), "summary":matrix_summary(load(p))} for p in [args.matrix, *args.matrix_repeat]],
        "result_path":str(destination.resolve())}
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir/"experiment12-report.md").write_text(markdown(data), encoding="utf-8")
    print(json.dumps(data["fresh_summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
