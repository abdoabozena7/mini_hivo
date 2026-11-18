"""Experiment 15: same three eligible tasks, frozen contracts, 18 fresh runs."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts import experiment12_run as engine
from scripts.experiment12_fixtures import get_case
from scripts.experiment12_run import materialize, sha, save, POLICIES, check_pin

engine.PRODUCTION = [*engine.PRODUCTION, "hivo/evidence_monotonic.py", "hivo/evidence_strict.py"]
CASE_IDS = ("arena_arrow", "arena_q_restart", "node_unique")
ARMS = ("evidence_grounded", "evidence_bound")


def preregister(directory, baseline):
    directory.mkdir(parents=True,exist_ok=False)
    previous=json.loads((baseline/"manifest.json").read_text(encoding="utf-8"))
    cases=[]
    for cid in CASE_IDS:
        case=get_case(cid); folder=directory/cid;folder.mkdir()
        engine.materialize(case,folder/"seed")
        approved=json.loads((baseline/cid/"authority.json").read_text(encoding="utf-8"))
        generated=engine.authority(case,folder/"seed")
        if generated["execution_contract_hash"]!=approved["execution_contract_hash"] or generated["plan"]["plan_hash"]!=approved["plan"]["plan_hash"]:
            raise ValueError("fixture contract differs from Experiment 14")
        engine.save(folder/"authority.json",approved)
        cases.append(copy.deepcopy(next(c for c in previous["cases"] if c["case_id"]==cid)))
    pins={p:engine.sha((engine.ROOT/p).read_bytes()) for p in engine.PRODUCTION}
    import ast
    names=("execute_agent_task","ask_ollama","run_tool","optional_browser_check","_verification_aggregation",
           "falsify_task","_commit_verified_leaf","_stage5b_parent_readiness","_aggregate_stage5b_parent")
    baseline_tree=ast.parse(subprocess.check_output(["git","show","b61c474:mini.py"],encoding="utf-8"))
    current_tree=ast.parse((engine.ROOT/"mini.py").read_text(encoding="utf-8"))
    ast_pins={}
    for name in names:
        before=next(n for n in baseline_tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        after=next(n for n in current_tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        if ast.dump(before)!=ast.dump(after):raise ValueError(f"fixed controller changed: {name}")
        ast_pins[name]=engine.sha(ast.dump(after).encode("utf-8"))
    unchanged=("hivo/verification.py","hivo/verification_surfaces.py","hivo/worker_progress.py",
               "hivo/integration_targets.py", "hivo/verification_routing.py", "hivo/evidence_strict.py",
               "hivo/atomic_child_receipt.py","hivo/evidence_monotonic.py","hivo/evidence_compatibility.py")
    if any(pins[p]!=previous["production_sha256"][p] for p in unchanged):
        raise ValueError("a fixed experiment component changed")
    manifest={"experiment":15,"model":previous["model"],"worker_budget":previous["worker_budget"],"repeats":3,
        "baseline_suite":str(baseline.resolve()),"arms":ARMS,"cases":cases,"policies":engine.POLICIES,
        "production_sha256":pins,"unchanged_component_sha256":{p:pins[p] for p in unchanged},
        "primary_boundary":previous["primary_boundary"],"planning_cost_included":False,
        "excluded_cases":{"timer_pause":"upstream grounding failure","python_clamp":"upstream impact failure"},
        "hypothesis":"Identical bounded current source can authorize one exact retry independently of read tool spelling.",
        "fixed_semantic_evidence_policy":"strict",
        "fixed_controller_ast_sha256":ast_pins,
        "final_receipt_gate_changed":False,"default_change_allowed":False}
    engine.save(directory/"manifest.json",manifest)
    print("preregistered 3 tasks; 18 fresh trials",flush=True)


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
    classification_policy = manifest.get("verification_classification_policy", "current")
    if classification_policy not in {"current", "field_scoped"}:
        raise ValueError("unknown verification classification policy in manifest")
    mini.RUN.update(semantic_evidence_policy="strict", mutation_grounding_policy=policy, experiment_case_id=case_id,
        verification_classification_policy=classification_policy,
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
    original_tool = mini.run_tool
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
    def observed_tool(name,args,role="System"):
        if name not in {"edit_file","edit_file_range","write_file"}:
            return original_tool(name,args,role=role)
        path=mini.safe_path(args.get("path"))
        inspect=path is not None and path.resolve()==(workspace/case["source"]).resolve()
        before=path.read_bytes() if inspect and path.is_file() else None
        result=original_tool(name,args,role=role)
        after=path.read_bytes() if inspect and path.is_file() else None
        observations.append({"kind":"mutation_tool","tool":name,"role":role,"args":copy.deepcopy(args),
            "target":args.get("path"),"before":before.decode("utf-8") if before is not None else None,
            "after":after.decode("utf-8") if after is not None else None,
            "before_hash":sha(before) if before is not None else None,"after_hash":sha(after) if after is not None else None,
            "result":result})
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
             patch.object(mini,"run_tool",side_effect=observed_tool), \
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

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("preregister","trial","batch"))
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--baseline",type=Path)
    parser.add_argument("--case-id",choices=CASE_IDS)
    parser.add_argument("--policy",choices=ARMS)
    parser.add_argument("--repeat",type=int,choices=(1,2,3))
    args=parser.parse_args(); directory=args.output_dir.resolve()
    if args.mode=="preregister":
        preregister(directory,args.baseline);return
    if args.mode=="trial":
        execute_trial(directory,args.case_id,args.policy,args.repeat);return
    manifest=json.loads((directory/"manifest.json").read_text(encoding="utf-8"));engine.check_pin(manifest)
    for cid in CASE_IDS:
        for repeat in range(1,4):
            for policy in reversed(ARMS) if repeat==2 else ARMS:
                workspace=directory/cid/f"{policy}-{repeat}"
                result=workspace.parent/f"{workspace.name}-result.json"
                if workspace.exists():
                    if result.exists():continue
                    raise ValueError(f"incomplete trial requires audit: {workspace}")
                with (workspace.parent/f"{workspace.name}.log").open("w",encoding="utf-8") as log:
                    completed=subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).resolve()),"trial",
                        "--output-dir",str(directory),"--case-id",cid,"--policy",policy,"--repeat",str(repeat)],
                        cwd=engine.ROOT,stdout=log,stderr=subprocess.STDOUT)
                print("finished",cid,policy,repeat,"exit",completed.returncode,flush=True)
                if completed.returncode:raise RuntimeError("trial harness failed; inspect log")


if __name__=="__main__":main()
