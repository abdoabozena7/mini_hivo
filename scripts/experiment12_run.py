"""Frozen approved fixture -> fresh production Worker/verification/parent runs.

The public benchmark authorizes only declared source paths in disposable
workspaces. Every plan passes the existing Stage 3 validator, snapshot and
Stage 4 graph compiler. No production gate, prompt, result or tool is replaced.
Planning is a fixed input; measured calls/time start at the execution boundary.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from scripts.experiment12_fixtures import CASES, get_case

ROOT = Path(__file__).resolve().parents[1]
POLICIES = {"planning_route":"decomposition_first_recursive", "mission_advice_policy":"contract_fallback",
    "worker_progress_policy":"progress_constrained", "mutation_grounding_policy":"evidence_grounded",
    "target_locator_policy":"evidence_directed", "verification_environment_policy":"resolved",
    "verification_surface_policy":"discovery", "child_receipt_policy":"atomic_verified",
    "integration_target_policy":"resolved"}
PRODUCTION = ["mini.py","hivo/evidence_compatibility.py","hivo/atomic_child_receipt.py",
              "hivo/verification_routing.py","hivo/verification.py","hivo/verification_surfaces.py",
              "hivo/worker_progress.py","hivo/mutation_grounding.py","hivo/integration_targets.py"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def materialize(case, workspace):
    workspace.mkdir(parents=True, exist_ok=False)
    for relative, content in case["files"].items():
        target = (workspace / relative).resolve()
        target.relative_to(workspace.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))


def authority(case, workspace):
    goal = case["goal"]
    requirement = {"requirement_id":"REQ-001", "text":goal, "status":"active", "provenance":"USER_STATED"}
    ledger = {"version":1,"immutable":True,"requirements":[requirement]}
    tests = [case["test_target"]] if case.get("test_target") else []
    contract = {"status":"ready", "goal":goal, "original_goal":goal, "requirements":[goal],
        "success_criteria":[goal], "constraints":[f"Do not modify {p}." for p in tests],
        "source_requirement_ledger":ledger, "source_requirements":[requirement],
        "source_contract":{"root_goal":goal,"source_requirement_ledger":ledger},
        "integration_test_target":case["integration_target"]}
    evidence = []
    for index, path in enumerate([case["source"], *tests], 1):
        content = (workspace / path).read_text(encoding="utf-8")
        symbol = case["symbol"] if index == 1 else ""
        if symbol and symbol not in content:
            raise ValueError("declared current symbol is absent from fixture")
        evidence.append({"evidence_id":f"REPO-{index:03d}",
            "category":"CURRENT_OWNER" if index == 1 else "CURRENT_TEST", "path":path,"symbol":symbol,
            "fact":f"{path} contains the existing {symbol or 'test'} implementation.",
            "line_start":1, "line_end":len(content.splitlines()), "file_sha256":sha(content.encode("utf-8")),
            "provenance":"REPOSITORY_EVIDENCE"})
    impact = {"impact_id":"IMP-001", "path":case["source"], "existing_owner":case["symbol"],
        "impact_kind":"BEHAVIOR_CHANGE", "necessity_status":"MUST_CHANGE", "disposition":"MUST_CHANGE",
        "candidate_change":goal, "requirement_ids":["REQ-001"], "repository_evidence_ids":["REPO-001"],
        "preserve":[goal]}
    plan = mini.stage3.build_minimal_change_plan({"impacts":[impact]}, [requirement], evidence, task_goal=goal)
    if len(plan["approved_change_nodes"]) != 1:
        raise ValueError("fixture must compile to exactly one mutation responsibility")
    node = plan["approved_change_nodes"][0]
    node["inspect_targets"] = tests
    node["evidence_ids"] = [e["evidence_id"] for e in evidence]
    node["do_not_touch"] = tests
    node["done_when"] = [goal]
    node["local_test_contract"] = tests
    node["test_contract"] = tests
    plan["do_not_touch"] = tests
    plan["integration_verification"] = [case["integration_target"]]
    plan = mini.stage3.finalize_plan_identity(plan)
    gate = mini.stage3.validate_change_plan(plan, [requirement], evidence, authoritative_task_goal=goal)
    if gate.get("valid") is not True:
        raise ValueError(f"Stage 3 fixture plan rejected: {gate}")
    approval = {"approval_status":"APPROVED", "plan_id":plan["plan_id"], "plan_hash":plan["plan_hash"],
                "approval_source":"USER_AUTHORIZED_EXPERIMENT12_DISPOSABLE_FIXTURE"}
    snapshot = mini.stage4.create_approved_plan_snapshot(plan, approval, goal, [requirement], evidence, {})
    compiled = mini.stage4.compile_execution_contracts(snapshot)
    if len(compiled["contracts"]) != 1 or compiled["contracts"][0]["allowed_mutation_paths"] != [case["source"]]:
        raise ValueError("compiled mutation scope differs from authorized fixture source")
    graph = mini.stage4.build_execution_graph(snapshot, compiled["contracts"])
    checked = mini.stage4.validate_execution_graph(snapshot, graph, compiled["contracts"])
    if not checked["valid"]:
        raise ValueError(checked)
    brain = mini.stage2.build_task_brain("ROOT", goal, mini.EXISTING_PROJECT, contract, repository_evidence=evidence)
    brain_check = mini.stage2.validate_task_brain(brain, ["REQ-001"], evidence)
    if not brain_check.get("valid"):
        raise ValueError(brain_check)
    return {"contract":contract, "requirements":[requirement], "repository_evidence":evidence,
            "task_brain":brain, "task_brain_validation":brain_check, "plan":plan, "plan_gate":gate,
            "approval":approval, "execution_contract_hash":compiled["contracts"][0]["contract_hash"]}


def preregister(directory):
    directory.mkdir(parents=True, exist_ok=False)
    cases = []
    for case in CASES:
        case_dir = directory / case["case_id"]
        case_dir.mkdir()
        materialize(case, case_dir / "seed")
        approved = authority(case, case_dir / "seed")
        save(case_dir / "authority.json", approved)
        cases.append({k:v for k,v in case.items() if k != "files"} | {
            "seed_sha256":{p:sha(s.encode("utf-8")) for p,s in case["files"].items()},
            "approved_plan_hash":approved["plan"]["plan_hash"], "execution_contract_hash":approved["execution_contract_hash"]})
    manifest = {"experiment":12, "model":"gemma4:e4b", "worker_budget":28, "repeats":3,
        "primary_boundary":"approved contract -> fresh Worker -> child receipt -> fresh parent verification",
        "planning_cost_included":False, "policies":POLICIES, "cases":cases,
        "production_sha256":{p:sha((ROOT / p).read_bytes()) for p in PRODUCTION},
        "eligibility":"At least one actual executable verification invocation in the preregistered runs; no selection on PASS.",
        "false_accept_definition":"Final verified receipt despite independently known mismatched obligation/behavior/target or failing acceptance oracle.",
        "false_reject_definition":"Same current source, required assertions actually passed, aggregation/receipt normalization rejects compatible evidence.",
        "order":"case-major; repeat1 current/compatible, repeat2 compatible/current, repeat3 current/compatible",
        "default_change_allowed":False}
    save(directory / "manifest.json", manifest)
    print("preregistered",len(cases),"tasks; 30 fresh trials",flush=True)


def check_pin(manifest):
    if mini.MAX_TOOL_STEPS != manifest["worker_budget"]:
        raise ValueError("Worker budget changed")
    actual = {p:sha((ROOT / p).read_bytes()) for p in PRODUCTION}
    if actual != manifest["production_sha256"]:
        raise ValueError("production source changed after preregistration")


def execute_trial(directory, case_id, policy, repeat):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    check_pin(manifest)
    case = get_case(case_id)
    record = next(c for c in manifest["cases"] if c["case_id"] == case_id)
    approved = json.loads((directory / case_id / "authority.json").read_text(encoding="utf-8"))
    if approved["plan"]["plan_hash"] != record["approved_plan_hash"]:
        raise ValueError("preregistered plan changed")
    workspace = directory / case_id / f"{policy}-{repeat}"
    materialize(case, workspace)
    before = {p:sha((workspace / p).read_bytes()) for p in case["files"]}
    if before != record["seed_sha256"]:
        raise ValueError("fresh workspace differs from fixed seed")
    mini.configure_console_streams()
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise RuntimeError("dependencies unavailable")
    mini.WORKSPACE = workspace.resolve()
    mini.HOST_PREFLIGHT_RESULT = mini.run_host_preflight(mini.WORKSPACE, mini.MODEL, mini.OLLAMA_BASE_URL)
    if not mini.HOST_PREFLIGHT_RESULT.get("passed"):
        raise RuntimeError("host preflight failed")
    mini.select_local_ollama_model()
    if mini.MODEL != manifest["model"]:
        raise ValueError("model differs from pinned experiment model")
    mini.reset_run("decomposition_first_recursive")
    mini.RUN.update(copy.deepcopy(POLICIES))
    mini.RUN.update(semantic_evidence_policy=policy, experiment_case_id=case_id,
        project_mode=mini.EXISTING_PROJECT, impact_planning_required=True,
        repository_evidence=copy.deepcopy(approved["repository_evidence"]),
        task_brain=copy.deepcopy(approved["task_brain"]), task_brain_validation=copy.deepcopy(approved["task_brain_validation"]),
        source_requirement_ledger=copy.deepcopy(approved["contract"]["source_requirement_ledger"]),
        approved_change_plan=copy.deepcopy(approved["plan"]), plan_approval=copy.deepcopy(approved["approval"]))
    contract = copy.deepcopy(approved["contract"])
    mini.begin_durable_run(contract)
    mini._experiment_event("TASK_ACCEPTED")
    mini._experiment_event("APPROVED", plan_id=approved["plan"]["plan_id"], source="frozen_experiment12_authority")
    # Observers save original return values; all decisions stay in production.
    observations = []
    original_browser, original_command = mini.verify_browser_application, mini.run_command
    original_run_file, original_gate = mini.run_file, mini.evidence_gate
    original_falsify = mini.falsify_task
    from unittest.mock import patch
    def observed_browser(*args, **kwargs):
        result = original_browser(*args, **kwargs)
        observations.append({"kind":"browser", "args":list(args), "kwargs":kwargs, "result":copy.deepcopy(result)})
        return result
    def observed_command(command):
        result = original_command(command)
        observations.append({"kind":"run_command", "target":command, "result":result})
        return result
    def observed_file(path):
        result = original_run_file(path)
        observations.append({"kind":"run_file", "target":path, "result":result})
        return result
    def observed_gate(*args, **kwargs):
        result = original_gate(*args, **kwargs)
        observations.append({"kind":"evidence_gate", "inputs":copy.deepcopy(args), "result":copy.deepcopy(result)})
        return result
    def observed_falsify(task, tool_contract, memory, builder, repo_snapshot, node_context=""):
        result = original_falsify(task, tool_contract, memory, builder, repo_snapshot, node_context)
        from scripts.experiment10_capture import capture
        snapshot = capture(task, tool_contract, builder, result)
        destination = workspace.parent / f"{workspace.name}-{task['id']}-handoff.json"
        save(destination, snapshot)
        return result
    result = None
    try:
        with patch.object(mini,"verify_browser_application",side_effect=observed_browser), \
             patch.object(mini,"run_command",side_effect=observed_command), \
             patch.object(mini,"run_file",side_effect=observed_file), \
             patch.object(mini,"evidence_gate",side_effect=observed_gate), \
             patch.object(mini,"falsify_task",side_effect=observed_falsify):
            result, _ = mini.execute_approved_plan_graph(contract, mini.load_memory(), repo_snapshot=mini.inspect_repository())
        mini.finish_metrics(result.get("status","failed"))
    except Exception as exc:
        result = {"status":"HARNESS_ERROR", "error":str(exc), "traceback":traceback.format_exc()}
        mini.finish_metrics("HARNESS_ERROR")
    finally:
        save(workspace.parent / f"{workspace.name}-observations.json", observations)
        save(workspace.parent / f"{workspace.name}-result.json", result)
    print("TRIAL_RESULT",case_id,policy,repeat,result["status"],flush=True)


def batch(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    check_pin(manifest)
    for case in manifest["cases"]:
        for repeat in range(1,manifest["repeats"]+1):
            order = ("compatible","current") if repeat == 2 else ("current","compatible")
            for policy in order:
                workspace = directory / case["case_id"] / f"{policy}-{repeat}"
                if workspace.exists():
                    if (workspace.parent / f"{workspace.name}-result.json").exists():
                        continue
                    raise ValueError(f"incomplete existing trial must be audited: {workspace}")
                with (workspace.parent / f"{workspace.name}.log").open("w",encoding="utf-8") as log:
                    completed = subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).resolve()),"trial",
                        "--output-dir",str(directory),"--case-id",case["case_id"],"--policy",policy,"--repeat",str(repeat)],
                        cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                print("finished",case["case_id"],policy,repeat,"process_exit",completed.returncode,flush=True)
                if completed.returncode:
                    raise RuntimeError("trial harness failed; inspect log before resuming")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("preregister","trial","batch"))
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--case-id",choices=[c["case_id"] for c in CASES])
    parser.add_argument("--policy",choices=("current","compatible"))
    parser.add_argument("--repeat",type=int,choices=(1,2,3))
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if args.mode == "preregister": preregister(directory)
    elif args.mode == "batch": batch(directory)
    else: execute_trial(directory,args.case_id,args.policy,args.repeat)


if __name__ == "__main__": main()
