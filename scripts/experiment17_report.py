"""Audit field-scoped profile isolation and fresh Timer/game execution."""

import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hivo.verification import infer_web_profile
from scripts import experiment17_run as experiment
from scripts.experiment12_report import SAFETY_KEYS, audit_trial, load, pct, rate


def frozen_contracts():
    sources = (
        ("timer_pause", Path(r"D:\projects\Ai\mini_hivo_experiment16\suite-v1")),
        ("arena_arrow", Path(r"D:\projects\Ai\mini_hivo_experiment15\suite-v1")),
        ("arena_q_restart", Path(r"D:\projects\Ai\mini_hivo_experiment15\suite-v1")),
    )
    for case_id, source in sources:
        for repeat in range(1, 4):
            workspace = source / case_id / f"evidence_bound-{repeat}"
            run = json.loads((workspace / ".agent_experiment.jsonl").read_text(
                encoding="utf-8").splitlines()[-1])
            contract = run["execution_contract_by_id"]["EXEC-001"]
            yield case_id, repeat, contract.get("goal", ""), contract


def profile_protocol():
    rows = []
    for case_id, repeat, goal, contract in frozen_contracts():
        current = infer_web_profile(goal, contract)
        scoped = infer_web_profile(goal, contract, classification_policy="field_scoped")
        expected = "timer" if case_id == "timer_pause" else "game"
        variants = (
            {"contract_hash": "3d-game-webgl", "execution_contract_hash": "game-3d"},
            {"plan_id": "3D GAME", "provenance": {"source": "game-webgl"}},
            {"evidence_digest": "timer-countdown", "metadata": {"hash": "3d-game"}},
        )
        invariant = []
        for injection in variants:
            modified = copy.deepcopy(contract)
            modified.update(injection)
            variant = infer_web_profile(goal, modified, classification_policy="field_scoped")
            invariant.append(variant == scoped)
        if scoped.kind != expected or not all(invariant):
            raise RuntimeError(f"profile or identity invariance failed: {case_id}/{repeat}")
        rows.append({"case_id": case_id, "repeat": repeat, "old_kind": current.kind,
                     "field_scoped_kind": scoped.kind, "expected_kind": expected,
                     "identity_variants_unchanged": sum(invariant),
                     "input_contract_hash": contract.get("contract_hash")})
    return rows


def fresh_trial(suite, case, repeat):
    workspace = suite / case["case_id"] / f"{experiment.POLICY}-{repeat}"
    core = audit_trial(suite, case, experiment.POLICY, repeat,
                       expected_semantic_policy="strict",
                       expected_policies={**experiment.previous.POLICIES,
                                          "mutation_grounding_policy": experiment.POLICY})
    if not core["completed"]:
        raise RuntimeError(f"missing fresh run: {workspace}")
    run = json.loads((workspace / ".agent_experiment.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    if run.get("verification_classification_policy") != "field_scoped":
        raise RuntimeError(f"wrong classification policy: {workspace}")
    observations = load(workspace.parent / f"{workspace.name}-observations.json")
    child_browser = [o for o in observations if o.get("kind") == "browser"
                     and len(o.get("args", [])) > 1 and o["args"][1] == "EXEC-001"]
    expected = "timer" if case["case_id"] == "timer_pause" else "game"
    profile_matches = [f"kind='{expected}'" in str(o.get("kwargs", {}).get("profile", ""))
                       for o in child_browser]
    if not all(profile_matches):
        raise RuntimeError(f"wrong child browser profile: {workspace}")
    grounds = run.get("mutation_grounding_runs", [])
    events = run.get("experiment_events", [])
    blockers = [e for e in events if e.get("kind") == "BLOCKED"
                and e.get("stage") != "PARENT_INTEGRATION"]
    return {
        "case_id": case["case_id"], "repeat": repeat,
        "profile_policy_pinned": True, "expected_profile": expected,
        "child_browser_checks": len(child_browser),
        "child_browser_profiles_correct": sum(profile_matches),
        "child_browser_environment_errors": sum(o.get("result", {}).get("environment_error") is True
                                                for o in child_browser),
        "first_legal_mutation": bool(run.get("first_legal_mutation")),
        "applied_mutations": sum(g.get("applied_mutation_attempts", 0) for g in grounds),
        "grounding_terminal_failure": any(g.get("terminal_reason") for g in grounds),
        "formal_child_verification_started": bool(child_browser),
        "child_verified": core["child_verified"], "root_verified": core["root_verified"],
        "first_reported_blocker": blockers[0] if blockers else None,
        "repairer_calls": core["repairer_calls"],
        "safety_counters": core["safety_counters"],
        "protected_tests_unchanged": core["tests_unchanged"],
        "evidence_workspace": str(workspace.resolve()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    suite = args.suite.resolve()
    manifest = load(suite / "manifest.json")
    experiment.previous.engine.check_pin(manifest)
    protocol = profile_protocol()
    fresh = [fresh_trial(suite, case, repeat) for case in manifest["cases"]
             for repeat in range(1, 4)]
    if len(protocol) != 9 or len(fresh) != 9:
        raise RuntimeError("incomplete experiment")
    safety = {k: sum(r["safety_counters"][k] for r in fresh) for k in SAFETY_KEYS}
    if not all(r["protected_tests_unchanged"] for r in fresh):
        raise RuntimeError("protected test changed")
    summary = {}
    for cid in experiment.CASES:
        rows = [r for r in fresh if r["case_id"] == cid]
        summary[cid] = {
            "first_legal_mutation": rate(sum(r["first_legal_mutation"] for r in rows), 3),
            "formal_child_verification": rate(sum(r["formal_child_verification_started"] for r in rows), 3),
            "child_verified": rate(sum(r["child_verified"] for r in rows), 3),
            "root_verified": rate(sum(r["root_verified"] for r in rows), 3),
            "grounding_terminal_failure": rate(sum(r["grounding_terminal_failure"] for r in rows), 3),
            "correct_child_profiles": rate(sum(r["child_browser_profiles_correct"] for r in rows),
                                           sum(r["child_browser_checks"] for r in rows)),
        }
    data = {"experiment": 17, "model": manifest["model"], "worker_budget": 28,
            "fixed_semantic_policy": "strict", "fixed_grounding_policy": experiment.POLICY,
            "classification_policy": "field_scoped", "protocol": protocol, "fresh": fresh,
            "summary": summary, "safety_counters": safety,
            "identity_mutation_checks": sum(r["identity_variants_unchanged"] for r in protocol),
            "production_default_changed": False,
            "limits": "The deterministic protocol uses nine frozen contract instances and 27 identity-field perturbations. Fresh execution is three attempts per task from frozen approved contracts, not an estimate for all domains."}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    experiment.previous.save(args.output_dir / "experiment17-results.json", data)
    timer = [r for r in protocol if r["case_id"] == "timer_pause"]
    games = [r for r in protocol if r["case_id"] != "timer_pause"]
    lines = ["# Experiment 17 — Field-Scoped Verification Classification", "",
             "التغيير الوحيد هو مدخلات infer_web_profile: goal/requirements/approved paths بدل JSON العقد كله. current يظل الـdefault.",
             "", "## عقود مجمدة ونفس المعنى", "",
             "| تحقق التصنيف | current | field_scoped |", "|---|---:|---:|",
             f"| Timer contracts classified timer | {sum(r['old_kind']=='timer' for r in timer)}/3 | {sum(r['field_scoped_kind']=='timer' for r in timer)}/3 |",
             f"| Game contracts classified game | {sum(r['old_kind']=='game' for r in games)}/6 | {sum(r['field_scoped_kind']=='game' for r in games)}/6 |",
             f"| Identity/hash perturbations preserving field-scoped profile | N/A | {data['identity_mutation_checks']}/27 |",
             "", "كل perturbation يغير IDs أو hashes أو provenance فقط. المرجع عقود Timer من Exp16 وعقود اللعبتين من Exp15.",
             "", "## تشغيل جديد بنفس Worker و28 خطوة", "",
             "| المهمة | أول تعديل قانوني | Child verifier started | Child verified | Root verified | Grounding terminal |",
             "|---|---:|---:|---:|---:|---:|"]
    for cid in experiment.CASES:
        s = summary[cid]
        lines.append(f"| {cid} | {pct(s['first_legal_mutation'])} | {pct(s['formal_child_verification'])} | {pct(s['child_verified'])} | {pct(s['root_verified'])} | {pct(s['grounding_terminal_failure'])} |")
    lines += ["", "Child browser profiles الصحيحة: " + ", ".join(
        f"{cid}={pct(summary[cid]['correct_child_profiles'])}" for cid in experiment.CASES),
        f". Scope/preservation counters: {sum(safety.values())}. Protected tests unchanged: yes.",
        "أي فشل بعد اختيار profile صحيح يُسجل منفصلًا، ولا ينسب إلى classifier.",
        "", "## الحدود", "",
        "العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مهمة لا تقدّر reliability العامة.",
        f"[Raw results]({(args.output_dir / 'experiment17-results.json').resolve().as_posix()})",
        f"[Frozen suite]({suite.as_posix()})", ""]
    (args.output_dir / "experiment17-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"profile_protocol": {"timer_new": sum(r['field_scoped_kind']=='timer' for r in timer),
                                          "games_new": sum(r['field_scoped_kind']=='game' for r in games),
                                          "identity_checks": data["identity_mutation_checks"]},
                      "fresh": summary, "safety": safety}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
