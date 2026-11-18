"""Paired, fresh verification of actual captured child handoffs; zero model calls."""

import argparse
import base64
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts.experiment10_handoff_probe import RUN_FIELDS
from hivo.atomic_child_receipt import validate_atomic_child_receipt
from hivo.integration_gate import fingerprint_dependency_paths


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")


def replay(snapshot,workspace,policy):
    workspace.mkdir(parents=True,exist_ok=False)
    for relative,encoded in snapshot["workspace_files"].items():
        target=(workspace/relative).resolve(); target.relative_to(workspace.resolve())
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(base64.b64decode(encoded))
    mini.WORKSPACE=workspace.resolve()
    mini.reset_run("experiment12-frozen-verification-handoff")
    mini.RUN.update({k:copy.deepcopy(snapshot["run_fields"][k]) for k in RUN_FIELDS if k in snapshot["run_fields"]})
    mini.RUN["semantic_evidence_policy"]=policy
    task=copy.deepcopy(snapshot["task"])
    mini.TASKS={task["id"]:task, str(task["parent"]):{"id":task["parent"],"stage5b_parent_contract":snapshot["run_fields"]["source_contract"]}}
    mini.RUN["stage5b_enabled"]=True
    mini.ACTIVE_TOOL_CONTRACT=copy.deepcopy(snapshot["tool_contract"])
    mini.ACTIVE_TRANSACTION={"task_id":task["id"],"files":{str((workspace/p).resolve()):{
        "existed":v["existed"],"content":base64.b64decode(v["content_base64"]) if v["content_base64"] is not None else None}
        for p,v in snapshot["transaction_files"].items()}}
    builder,falsifier=copy.deepcopy(snapshot["builder"]),copy.deepcopy(snapshot["falsifier"])
    paths=list(snapshot["workspace_files"])
    before=fingerprint_dependency_paths(workspace,paths)
    result={"policy":policy,"model_calls":0,"repairer_calls":0,"root_verification_executed":False,
            "input_hash":mini.semantic_evidence.canonical_hash(snapshot),"subject_before":before}
    authority=mini._authority_terminal_failure(task)
    if authority or mini._context_sufficiency_failed(builder) or builder.get("status")!="done":
        result.update(eligible=False,blocker=authority or builder.get("failure_type") or builder.get("status"))
        return result
    evidence=mini.merged_verification_evidence(builder,falsifier)
    browser=mini.optional_browser_check(task,snapshot["tool_contract"],
        syntax_failures=mini._combined_syntax_validation_failures(builder,falsifier),execution_evidence=evidence)
    gate=mini.evidence_gate(builder,falsifier,browser)
    result.update(eligible=True,browser=browser,gate=gate)
    if gate.get("passed") is True:
        committed=mini._commit_verified_leaf(task,snapshot["tool_contract"],builder,falsifier,browser,gate,mini.load_memory())
        mini._mark_task_result(task,committed)
        receipt=mini.RUN.get("child_receipts",{}).get(task["id"])
        checked=validate_atomic_child_receipt(receipt,workspace=workspace,
            expected_contract_hash=task["execution_contract_hash"],expected_node_ids=task["plan_node_ids"],
            expected_requirement_ids=task["execution_contract"]["requirement_ids"],
            expected_requirements=task["execution_contract"]["requirements"])
        result.update(commit_status=committed["status"],receipt=receipt,receipt_validation=checked,
                      child_verified=checked["valid"],impact_comparison=committed.get("impact_comparison"))
        if checked["valid"] is not True:
            result["blocker"] = committed.get("summary") or checked["errors"]
    else:
        result.update(child_verified=False,blocker=(gate.get("verification_aggregation")or{}).get("failure_codes"))
    result.update(subject_after=fingerprint_dependency_paths(workspace,paths),
                  model_calls=mini.RUN["model_calls"],repairer_calls=mini.RUN["repairer_calls"])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    mini.configure_console_streams();mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False): raise RuntimeError("dependencies unavailable")
    args.output_dir.mkdir(parents=True,exist_ok=True)
    comparisons=[]
    excluded=[]
    # Earliest completed Worker handoff per task; no PASS filter.
    for case_dir in sorted(p for p in args.suite.iterdir() if p.is_dir() and (p/"authority.json").exists()):
        captures=sorted(case_dir.glob("*-EXEC-001-handoff.json"))
        if not captures:
            excluded.append({"case_id":case_dir.name,"reason":"NO_COMPLETED_WORKER_HANDOFF"});continue
        # Prefer terminally completed Workers for an eligible handoff comparison.
        eligible=[p for p in captures if json.loads(p.read_text(encoding="utf-8"))["builder"]["status"]=="done"]
        if not eligible:
            excluded.append({"case_id":case_dir.name,"reason":"NO_COMPLETED_WORKER_HANDOFF"});continue
        capture=min(eligible,key=lambda p:json.loads(p.read_text(encoding="utf-8"))["input_run_id"])
        snapshot=json.loads(capture.read_text(encoding="utf-8"))
        destination=args.output_dir/case_dir.name
        comparison_path=destination/"comparison.json"
        if comparison_path.exists():
            pair=json.loads(comparison_path.read_text(encoding="utf-8"))
            for arm in pair["arms"]:
                if arm.get("child_verified") is False and arm.get("receipt_validation",{}).get("errors"):
                    arm.setdefault("blocker",arm["receipt_validation"]["errors"])
            comparisons.append(pair);continue
        destination.mkdir()
        pair={"case_id":case_dir.name,"input_capture":str(capture.resolve()),"arms":[]}
        for policy in ("current","compatible"):
            arm=replay(snapshot,destination/policy,policy);pair["arms"].append(arm)
            save(destination/(policy+".json"),arm)
            print(case_dir.name,policy,arm.get("child_verified"),arm.get("blocker"),flush=True)
        save(comparison_path,pair);comparisons.append(pair)
    save(args.output_dir/"comparison.json",{"experiment":12,"mode":"paired_frozen_child_handoff",
        "root_proof_reused":False,"comparisons":comparisons,"excluded_cases":excluded})


if __name__=="__main__":main()
