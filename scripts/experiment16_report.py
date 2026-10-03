"""Audit the first blocking boundary for the two cross-domain fresh runs."""

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment16_run as experiment
from scripts.experiment12_report import audit_trial, load, pct, rate, SAFETY_KEYS
from hivo.verification import infer_web_profile


STAGES = (
    "contract_ready", "worker_started", "context_sufficient",
    "target_localized", "first_legal_mutation", "mutation_committed",
    "verification_applicable", "verification_started", "child_verified",
)


def audit(suite, case, repeat):
    policy = experiment.POLICY
    workspace = suite / case["case_id"] / f"{policy}-{repeat}"
    core = audit_trial(
        suite, case, policy, repeat, expected_semantic_policy="strict",
        expected_policies={**experiment.previous.POLICIES,
                           "mutation_grounding_policy": policy},
    )
    if not core["completed"]:
        raise RuntimeError(f"missing trial: {workspace}")
    run = json.loads((workspace / ".agent_experiment.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    trace = load(workspace.parent / f"{workspace.name}-boundary-trace.json")
    observations = load(workspace.parent / f"{workspace.name}-observations.json")
    result = load(workspace.parent / f"{workspace.name}-result.json")
    event_path = next((workspace / ".agent_runs").glob("*.jsonl"))
    durable = [json.loads(line) for line in event_path.read_text(
        encoding="utf-8").splitlines()]
    produced = run.get("experiment_events", [])
    blockers = [e for e in produced if e.get("kind") == "BLOCKED"]
    first_blocker = next((b for b in blockers if b.get("stage") != "PARENT_INTEGRATION"),
                         blockers[0] if blockers else None)
    grounds = [g for g in run.get("mutation_grounding_runs", [])
               if g.get("policy") == policy]
    attempts = [a for g in grounds for a in g.get("attempts", [])]
    writes = [o for o in observations if o.get("kind") == "mutation_tool"
              and o.get("role") == "Builder" and o.get("before_hash") != o.get("after_hash")
              and o.get("before_hash") is not None]
    applied = [a for a in attempts if a.get("applied")]
    if len(writes) != len(applied):
        raise RuntimeError(f"mutation write/grounding mismatch: {workspace}")
    for actual, authorized in zip(writes, applied):
        if (authorized.get("source_before_hash") != actual.get("before_hash")
                or authorized.get("target") != case["source"].casefold()):
            raise RuntimeError(f"committed mutation lacks source binding: {workspace}")
    source_reads = [t for t in trace if t.get("kind") == "worker_tool"
                    and t.get("tool") in {"read_file", "read_file_range"}
                    and t.get("target") == case["source"]
                    and not str(t.get("result", "")).casefold().startswith("error:")]
    context_decisions = [e for e in durable
                         if e.get("kind") == "context_sufficiency_decision"
                         and e.get("role") == "Builder" and e.get("task_id") == "EXEC-001"]
    formal_started = any(t.get("kind") == "child_verification_invoked" for t in trace)
    native_invocations = [o for o in observations if o.get("kind") in
                          {"browser", "run_file", "run_command"}]
    child_browser = [o for o in native_invocations if o.get("kind") == "browser"
                     and len(o.get("args", [])) > 1 and o["args"][1] == "EXEC-001"]
    child_browser_codes = sorted({f.get("code") for o in child_browser
                                  for f in o.get("result", {}).get("failures", [])
                                  if isinstance(f, dict) and f.get("code")})
    child_browser_environment_errors = sum(
        o.get("result", {}).get("environment_error") is True for o in child_browser
    )
    wrong_game_profile = any("kind='game'" in str(o.get("kwargs", {}).get("profile", ""))
                             for o in child_browser) and {
                                 "missing_canvas", "missing_game_bridge"
                             }.issubset(child_browser_codes)
    profile_diagnostic = None
    handoff_path = workspace.parent / f"{workspace.name}-EXEC-001-handoff.json"
    if wrong_game_profile and handoff_path.exists():
        handoff = load(handoff_path)
        goal = handoff.get("task", {}).get("goal", "")
        contract = handoff.get("tool_contract", {})
        without_hash = copy.deepcopy(contract)
        hash_value = str(without_hash.pop("execution_contract_hash", ""))
        full = infer_web_profile(goal, contract)
        stripped = infer_web_profile(goal, without_hash)
        profile_diagnostic = {
            "actual_kind": full.kind,
            "without_execution_contract_hash_kind": stripped.kind,
            "hash_contains_3d": "3d" in hash_value.casefold(),
            "hash_only_causes_game_profile": full.kind == "game" and stripped.kind == "timer"
                                             and "3d" in hash_value.casefold(),
        }
    # A ROOT applicability artifact may exist even when the child never
    # reached verification. It cannot be counted as a child milestone.
    child_applicability = [e for e in durable
                           if e.get("kind") == "verification_applicability_analyzed"
                           and e.get("child_id") == "EXEC-001"]
    if formal_started and "verification_surface_unavailable" in child_browser_codes:
        applicability = "child_surface_unavailable"
    elif formal_started and any(o.get("result", {}).get("interaction_checks")
                                for o in child_browser):
        applicability = "executable_route_observed"
    elif formal_started and core["verification_pass"]:
        applicability = "executable_route_observed"
    elif formal_started:
        applicability = "entered_but_no_executable_route_observed"
    else:
        applicability = "not_evaluated_for_child"
    receipt = (run.get("child_receipts") or {}).get("EXEC-001") or {}
    milestones = {
        "contract_ready": bool(run.get("execution_contract_by_id", {}).get("EXEC-001"))
                          and core["plan_hash_matches"],
        "worker_started": any(e.get("kind") == "FIRST_WORKER_STARTED" for e in produced),
        "context_sufficient": any(e.get("mutation_authorized") is True for e in context_decisions),
        "target_localized": bool(source_reads),
        "first_legal_mutation": bool(run.get("first_legal_mutation")),
        "mutation_committed": bool(writes),
        "verification_applicable": applicability == "executable_route_observed",
        "verification_started": formal_started,
        "child_verified": receipt.get("verified") is True and core["child_verified"],
    }
    if first_blocker:
        raw_stage = first_blocker.get("stage")
        reason = first_blocker.get("reason")
        if reason == "CONTEXT_INSUFFICIENT" and not milestones["context_sufficient"]:
            phase = "pre_mutation_context_or_impact"
        elif raw_stage == "MUTATION_GROUNDING":
            phase = "mutation_grounding_after_worker"
        elif reason == "VERIFIER_UNAVAILABLE" and wrong_game_profile:
            phase = "child_verification_profile_mismatch"
        else:
            phase = str(raw_stage or "unknown").casefold()
    else:
        phase = None
    terminal_phase = phase
    causal_candidates = [e for e in durable if e.get("kind") in
                         {"mutation_target_unresolved", "verification_failure_classified"}]
    first_causal = causal_candidates[0] if causal_candidates else None
    if first_causal and first_causal["kind"] == "mutation_target_unresolved":
        phase = "mutation_grounding_after_worker"
    elif first_causal and first_causal["kind"] == "verification_failure_classified":
        phase = ("child_verification_profile_mismatch" if wrong_game_profile
                 else "child_verification_failure")
    failed_retries = [a for a in attempts if a.get("rejected")]
    no_op = [a for a in attempts if a.get("executed") and not a.get("applied")
             and a.get("request", {}).get("old") == a.get("request", {}).get("new")]
    return {
        "case_id": case["case_id"], "repeat": repeat,
        "run_id": run["run_id"], "result_status": result["status"],
        "milestones": milestones,
        "verification_applicability": applicability,
        "child_applicability_artifacts": len(child_applicability),
        "root_applicability_artifacts": sum(e.get("kind") == "verification_applicability_analyzed"
                                            and e.get("child_id") == "ROOT" for e in durable),
        "native_verifier_invocations_any_role": len(native_invocations),
        "child_browser_failure_codes": child_browser_codes,
        "child_browser_environment_errors": child_browser_environment_errors,
        "child_browser_game_profile_mismatch": wrong_game_profile,
        "profile_diagnostic": profile_diagnostic,
        "formal_child_verifier_invoked": formal_started,
        "first_blocker": first_blocker,
        "first_causal_failure_event": first_causal,
        "first_blocker_phase": phase,
        "terminal_blocker_phase": terminal_phase,
        "secondary_parent_blockers": [b for b in blockers if b.get("stage") == "PARENT_INTEGRATION"],
        "first_legal_mutation_step": (run.get("first_legal_mutation") or {}).get("tool_step"),
        "applied_mutations": len(applied),
        "rejected_mutation_attempts": len(failed_retries),
        "last_rejected_evidence_reason": failed_retries[-1].get("evidence_reason") if failed_retries else None,
        "no_op_executed_attempts": len(no_op),
        "bounded_refreshes": sum(g.get("bounded_refreshes", 0) for g in grounds),
        "full_refreshes": sum(o.get("tool") == "read_file" for g in grounds
                              for o in g.get("refresh_observations", [])),
        "worker_tool_steps": sum(p.get("tool_steps", 0) for p in run.get("worker_progress_runs", [])),
        "context_decisions": [{k: e.get(k) for k in ("context_status", "mutation_authorized", "lifecycle_state")}
                              for e in context_decisions],
        "context_mutation_authorizations": run.get("context_mutation_authorizations", 0),
        "impact_contract_authorizations": run.get("impact_contract_authorizations", 0),
        "locator_candidate_count": sum(len(x.get("candidates", []))
                                       for x in run.get("target_locator_runs", [])),
        "source_read_count": len(source_reads),
        "child_verified_receipt": receipt.get("verified") is True,
        "root_verified": core["root_verified"],
        "repairer_calls": core["repairer_calls"],
        "safety_counters": core["safety_counters"],
        "protected_tests_unchanged": core["tests_unchanged"],
        "evidence": {"workspace": str(workspace.resolve()),
                     "events": str(event_path.resolve()),
                     "boundary_trace": str((workspace.parent / f"{workspace.name}-boundary-trace.json").resolve())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    suite = args.suite.resolve()
    manifest = load(suite / "manifest.json")
    experiment.previous.engine.check_pin(manifest)
    rows = [audit(suite, case, repeat) for case in manifest["cases"]
            for repeat in range(1, experiment.REPEATS + 1)]
    counts = {cid: {stage: sum(row["milestones"][stage] for row in rows
                           if row["case_id"] == cid) for stage in STAGES}
              for cid in experiment.CASES}
    blockers = {cid: dict(Counter(row["first_blocker_phase"] for row in rows
                                  if row["case_id"] == cid)) for cid in experiment.CASES}
    safety = {key: sum(row["safety_counters"][key] for row in rows) for key in SAFETY_KEYS}
    if not all(row["protected_tests_unchanged"] for row in rows):
        raise RuntimeError("protected test file changed")
    common = set(blockers[experiment.CASES[0]]) & set(blockers[experiment.CASES[1]])
    result = {
        "experiment": 16, "completed_attempts": len(rows), "model": manifest["model"],
        "worker_budget": manifest["worker_budget"], "fixed_stack": manifest["policies"]
            | {"semantic_evidence_policy": "strict"},
        "milestone_counts": counts, "first_blocker_counts": blockers,
        "same_first_blocker_phase_across_domains": bool(common),
        "shared_first_blocker_phases": sorted(common),
        "safety_counters": safety,
        "protected_tests_unchanged": True,
        "trial_results": rows,
        "limits": "Frozen approved contracts exclude planning. Three fresh runs per task are descriptive, not reliability estimates. A ROOT applicability artifact is never counted as child eligibility. A native verifier call during Worker execution is separate from formal child verification.",
        "production_changed": False, "default_changed": False,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    experiment.previous.save(args.output_dir / "experiment16-results.json", result)
    lines = ["# Experiment 16 — Cross-Domain First-Blocker Isolation", "",
             "Timer وPython فقط؛ 3 fresh runs لكل مهمة، من عقود Experiment 12 المعتمدة وبذور مطابقة.",
             "gemma4:e4b و28 خطوة، contract_fallback + strict evidence + evidence_bound. لا تغيير في production أو الـdefault.",
             "", "## الوصول إلى الحدود", "",
             "| الحد | Timer | Python |", "|---|---:|---:|"]
    titles = {"contract_ready": "Contract ready", "worker_started": "Worker started",
              "context_sufficient": "Context sufficient", "target_localized": "Source actually inspected",
              "first_legal_mutation": "First legal mutation", "mutation_committed": "File changed before rollback",
              "verification_applicable": "Child executable route observed",
              "verification_started": "Formal child verification invoked",
              "child_verified": "Child verified"}
    for stage in STAGES:
        a, b = (counts[cid][stage] for cid in experiment.CASES)
        lines.append(f"| {titles[stage]} | {pct(rate(a, 3))} | {pct(rate(b, 3))} |")
    lines += ["", "هذه milestones وليست بالضرورة ترتيب استدعاء الأدوات؛ بعض القراءة تحدث قبل context gate.",
              "وجود ROOT applicability artifact أو browser call داخل الـWorker لا يعني أن Child verification بدأت.",
              "File changed تعني تعديلًا فعليًا أثناء محاولة الـWorker؛ عند فشل الـChild قد تُرجع transaction الملف لاحقًا.",
              "", "## أول blocker حقيقي", "",
              "| المهمة | أول مرحلة توقف / 3 runs | التفاصيل |", "|---|---:|---|"]
    for cid in experiment.CASES:
        task_rows = [r for r in rows if r["case_id"] == cid]
        labels = ", ".join(f"{k}: {n}/3" for k, n in blockers[cid].items())
        details = "; ".join(
            f"run {r['repeat']}: {r['first_blocker_phase']}"
            f" (terminal={(r['first_blocker'] or {}).get('reason') or 'none'}, "
            f"underlying={r['last_rejected_evidence_reason'] or 'n/a'}, "
            f"commits={r['applied_mutations']}, full_refreshes={r['full_refreshes']}, "
            f"no-op attempts={r['no_op_executed_attempts']})"
            for r in task_rows)
        lines.append(f"| {cid} | {labels} | {details} |")
    lines += ["", f"Shared first-blocker phase: **{', '.join(sorted(common)) or 'none'}**.",
              "Parent INTEGRATION_NOT_READY بعد فشل الـChild سبب ثانوي، وليس أول blocker.",
              "في Timer run 3 فشل browser verification أولًا، ثم انتهت محاولة Recovery لاحقة عند grounding؛ الجدول يسجل أول فشل سببي والـterminal كلًا على حدة.",
              "في Python نفّذ الـWorker صفر tool steps في المحاولات الثلاث، فلم يصل إلى context decision؛ رفض الـpre-mutation impact contract نتيجة لهذا المسار.",
              "", "## تشخيص profile المتصفح", ""]
    collisions = [r for r in rows if (r.get("profile_diagnostic") or {}).get(
        "hash_only_causes_game_profile")]
    if collisions:
        lines.append(
            f"في {len(collisions)} محاولة، فحص المتصفح اختار game للمؤقّت. "
            "إعادة حساب نفس infer_web_profile بعد حذف execution_contract_hash فقط "
            "تعطي timer؛ الـhash يحتوي النص `3d`، والخوارزمية تبحث عنه كـsubstring "
            "داخل JSON العقد كله. المتصفح فتح الصفحة وenvironment_error=false؛ "
            "الرفض بسبب profile غير مناسب. هذا تشخيص read-only، ولم تُعدَّل دالة التصنيف أو الـverifier."
        )
    else:
        lines.append("لم تثبت هذه الدفعة أن hash العقد تسبب في profile خاطئ.")
    lines += [
              "", "## الضبط وحدود الاستنتاج", "",
              f"Scope/preservation counters: **{sum(safety.values())}**؛ protected tests unchanged: **yes**.",
              "العقود والبذور والموديل والميزانية والسياسات مثبتة؛ تم تسجيل الأدوات والحدود فقط، دون إصلاح أو تغيير قرار.",
              "هذه عينة مهمتين وثلاث محاولات لكل واحدة. لا تعميم على كل browser/Python projects.",
              "", f"[Raw results]({(args.output_dir / 'experiment16-results.json').resolve().as_posix()})",
              f"[Frozen suite]({suite.as_posix()})", ""]
    (args.output_dir / "experiment16-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"counts": counts, "first_blockers": blockers,
                      "common": sorted(common), "safety": safety}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
