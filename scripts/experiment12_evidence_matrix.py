"""Actual reference verification payloads plus declared incompatible evidence.

This protocol matrix is separate from fresh model runs. Altered records are
adversarial replay inputs, never Worker evidence or new application authority.
"""

import argparse
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts.experiment12_fixtures import CASES
from scripts.experiment12_run import POLICIES, materialize, save
from hivo import evidence_compatibility as semantic
from hivo.atomic_child_receipt import create_atomic_child_receipt, validate_atomic_child_receipt
from hivo.integration_gate import fingerprint_dependency_paths
from hivo.verification_routing import aggregate_verification_evidence


def reference_source(case):
    source=case["files"][case["source"]]
    replacements={
        "arena_arrow":("if(event.key === 'ArrowDown') move('up');","if(event.key === 'ArrowUp') move('up');"),
        "arena_q_restart":("// Extra restart key is intentionally not connected yet.",
            "if(event.key.toLowerCase() === 'q' && ['gameover','won'].includes(state.status)) restart();"),
        "timer_pause":("/* Pause is not connected to the running interval yet. */","clearInterval(interval); interval=null;"),
        "python_clamp":("return max(lower, value)","return max(lower, min(upper, value))"),
        "node_unique":("return [...values].sort();","return [...new Set(values)];")}
    old,new=replacements[case["case_id"]]
    if source.count(old)!=1: raise ValueError("reference correction anchor is not unique")
    return source.replace(old,new)


def browser_records(payload,claims,subject,tool="verify_web_app"):
    return semantic.normalize_browser_result(payload,claims,tool=tool,source="controller_tool_result",
        subject_before_hash=subject["hash"],subject_after_hash=subject["hash"])


def evaluate(case,workspace,contract,artifact,raw,browser,records,policy,claims):
    assessments=None
    if policy=="compatible":
        assessments={}
        if browser is not None:
            assessments[case["source"]]=semantic.assess(claims,records,required_requirement_ids=contract["requirement_ids"])
    aggregation=aggregate_verification_evidence(artifact,raw,browser,semantic_browser_evidence=assessments)
    task={"id":contract["execution_contract_id"],"parent":"ROOT","execution_contract":contract,
          "plan_node_ids":contract["plan_node_ids"]}
    result={"status":"done","gate":{"verification_aggregation":aggregation},"verification_evidence":raw}
    receipt=create_atomic_child_receipt(task,result,workspace=workspace,verification_applicability=artifact)
    checked=validate_atomic_child_receipt(receipt,workspace=workspace,expected_contract_hash=contract["contract_hash"],
        expected_node_ids=contract["plan_node_ids"],expected_requirement_ids=contract["requirement_ids"],
        expected_requirements=contract["requirements"])
    return {"policy":policy,"aggregation_accepted":aggregation["passed"],"valid_receipt":checked["valid"],
        "errors":checked["errors"],"failure_codes":aggregation["failure_codes"],"record_count":len(records)}


def scenario_inputs(case,contract,payload,raw,claims,subject,other_behavior=None,other_target=None):
    records=browser_records(payload,claims,subject) if payload else []
    target=case["source"] if payload else case["test_target"]
    kind="BROWSER" if payload else "FOCUSED_TEST"
    artifact={"child_id":contract["execution_contract_id"],"verification_routes":[
        {"kind":kind,"target":target,"required":True,"applicable":True,"result":"PENDING"}]}
    yield "native_matching_claim",True,copy.deepcopy(raw),copy.deepcopy(payload),copy.deepcopy(records),artifact
    if payload:
        page_only={"resolved_entrypoint":target,"passed":True,"behavior_test_executed":False,"interaction_checks":[]}
        page_raw=[{"tool":"run_file","target":target,"result":json.dumps(page_only)}]
        yield "run_file_load_plus_fresh_behavior",True,page_raw,copy.deepcopy(payload),copy.deepcopy(records),artifact
        # Same assertion-bearing full payload, different tool provenance: protocol replay.
        cross=records+browser_records(payload,claims,subject,tool="run_file")
        yield "cross_tool_same_executed_assertions",True,copy.deepcopy(raw),copy.deepcopy(payload),cross,artifact
        other=copy.deepcopy(other_target)
        wrong_target_records=copy.deepcopy(records)
        for record in wrong_target_records:
            record["target"]="other.html";record["surface_id"]="file:other.html"
            record["record_hash"]=semantic.canonical_hash({k:v for k,v in record.items() if k!="record_hash"})
        yield "different_target",False,[{"tool":"verify_web_app","target":"other.html","result":json.dumps(other)}],other,wrong_target_records,artifact
        other=copy.deepcopy(other_behavior)
        yield "same_file_different_behavior",False,[{"tool":"verify_web_app","target":target,"result":json.dumps(other)}],other,browser_records(other,claims,subject),artifact
        other_records=copy.deepcopy(records)
        for record in other_records:
            record["requirement_id"]="OTHER-REQ"
            record["record_hash"]=semantic.canonical_hash({k:v for k,v in record.items() if k!="record_hash"})
        yield "different_requirement",False,[{**r,"requirement_id":"OTHER-REQ"} for r in raw],copy.deepcopy(payload),other_records,artifact
        yield "unit_pass_cannot_replace_browser_behavior",False,[{"tool":"run_command","target":"python tests/unrelated.py","result":"[exit_code=0]\n1 test passed"}],None,[],artifact
    else:
        for provenance in ("run_file","run_command","unit_test_result"):
            yield "same_unit_assertions_"+provenance,True,[{**r,"tool":provenance} for r in raw],None,[],artifact
        for name,field,value in (("different_requirement","requirement_id","OTHER-REQ"),
                                 ("same_file_different_behavior","behavior","unrelated_behavior"),
                                 ("different_target","target","tests/unrelated.py")):
            yield name,False,[{**r,field:value} for r in raw],None,[],artifact
        yield "unit_cannot_replace_browser_obligation",False,copy.deepcopy(raw),None,[],{
            "child_id":contract["execution_contract_id"],"verification_routes":[
                {"kind":"BROWSER","target":"unrelated.html","required":True,"applicable":True,"result":"PENDING"}]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    mini.configure_console_streams();mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):raise RuntimeError("dependencies unavailable")
    outcomes=[]
    for case in CASES:
        workspace=args.output_dir/case["case_id"]
        materialize(case,workspace)
        (workspace/case["source"]).write_text(reference_source(case),encoding="utf-8")
        mini.WORKSPACE=workspace.resolve();mini.reset_run("experiment12-reference-evidence")
        mini.RUN.update(POLICIES)
        approved=json.loads((args.suite/case["case_id"]/"authority.json").read_text(encoding="utf-8"))
        snapshot=mini.stage4.create_approved_plan_snapshot(approved["plan"],approved["approval"],case["goal"],
            approved["requirements"],approved["repository_evidence"],{})
        contract=mini.stage4.compile_execution_contracts(snapshot)["contracts"][0]
        subject=fingerprint_dependency_paths(workspace,contract["allowed_inspection_paths"])
        claims=semantic.required_claims(contract["requirements"],contract_hash=contract["contract_hash"],
            child_id=contract["execution_contract_id"],target=case["source"],subject_hash=subject["hash"],
            subject_paths=[p["path"] for p in subject["paths"]])
        browser=None
        other_behavior=other_target=None
        if case["family"].startswith("browser"):
            browser=mini.verify_browser_application(case["source"],contract["execution_contract_id"],
                profile=mini.infer_web_profile(case["goal"]),evidence={"verification_requirement":case["goal"],
                    "harness_config":{"entrypoint":case["source"]}})
            raw=[{"tool":"verify_web_app","target":case["source"],"result":json.dumps(browser)}]
            actual_pass=browser.get("passed") is True
            alternative_profile=replace(mini.infer_web_profile(case["goal"]),required_interactions=(
                "timer_start_changes_visible_time" if case["family"]=="browser_timer" else "goal_win_state",))
            other_behavior=mini.verify_browser_application(case["source"],"OTHER-REQ",profile=alternative_profile,
                evidence={"verification_requirement":"Observe only the alternative assertion.",
                    "harness_config":{"entrypoint":case["source"]}})
            (workspace/"other.html").write_text(reference_source(case),encoding="utf-8")
            other_target=mini.verify_browser_application("other.html","OTHER-TARGET",profile=mini.infer_web_profile(case["goal"]),
                evidence={"verification_requirement":case["goal"],"harness_config":{"entrypoint":"other.html"}})
            save(workspace/"alternative_native_payloads.json",{"different_behavior":other_behavior,"different_target":other_target})
            if other_behavior.get("passed") is not True or other_target.get("passed") is not True:
                raise RuntimeError("alternative native evidence did not execute")
        else:
            file_result=mini.run_file(case["test_target"])
            command_result=mini.run_command(case["integration_target"])
            raw=[{"tool":"run_file","target":case["test_target"],"result":file_result},
                 {"tool":"run_command","target":case["integration_target"],"result":command_result}]
            actual_pass=all("[exit_code=0]" in r["result"] for r in raw)
        save(workspace/"actual_reference_payload.json",{"browser":browser,"evidence":raw,"passed":actual_pass,
            "different_behavior_native_result":other_behavior,"different_target_native_result":other_target})
        if not actual_pass:raise RuntimeError(f"reference acceptance did not execute successfully for {case['case_id']}")
        for name,expected,scenario_raw,payload,records,artifact in scenario_inputs(case,contract,browser,raw,claims,subject,other_behavior,other_target):
            for policy in ("current","compatible"):
                verdict=evaluate(case,workspace,contract,artifact,scenario_raw,payload,records,policy,claims)
                verdict.update(case_id=case["case_id"],family=case["family"],scenario=name,expected_compatible=expected,
                    false_accept=not expected and verdict["valid_receipt"],false_reject=expected and not verdict["valid_receipt"],
                    aggregation_false_accept=not expected and verdict["aggregation_accepted"],
                    aggregation_false_reject=expected and not verdict["aggregation_accepted"])
                outcomes.append(verdict)
        print("matrix",case["case_id"],"reference PASS",flush=True)
    save(args.output_dir/"matrix.json",{"experiment":12,"mode":"reference_payload_and_adversarial_protocol_replay",
        "model_calls":0,"Worker_or_root_success_claimed":False,"outcomes":outcomes,
        "provenance_limit":"Cross-tool alias and mismatch records are deliberately replayed protocol fixtures; native reference tool results are separately retained."})


if __name__=="__main__":main()
