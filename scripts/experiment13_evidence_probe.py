"""Fresh native proofs and explicit negative identity replays, three policies."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from hivo import evidence_compatibility as semantic, evidence_monotonic
from hivo.atomic_child_receipt import create_atomic_child_receipt, validate_atomic_child_receipt
from hivo.integration_gate import fingerprint_dependency_paths
from hivo.verification_routing import aggregate_verification_evidence
from scripts.experiment12_evidence_matrix import reference_source, scenario_inputs
from scripts.experiment12_fixtures import get_case
from scripts.experiment12_run import materialize, save
from scripts.experiment13_run import CASE_IDS


def evaluate(case, workspace, contract, artifact, raw, browser, records, policy, claims):
    assessments = None
    if policy in {"compatible", "monotonic"}:
        assessments = {}
        if browser is not None:
            assessor = evidence_monotonic.assess if policy == "monotonic" else semantic.assess
            assessments[case["source"]] = assessor(claims, records, required_requirement_ids=contract["requirement_ids"])
    aggregation = aggregate_verification_evidence(artifact, raw, browser, semantic_browser_evidence=assessments,
        semantic_evidence_policy=policy)
    task={"id":contract["execution_contract_id"],"parent":"ROOT","execution_contract":contract,
          "plan_node_ids":contract["plan_node_ids"]}
    receipt = create_atomic_child_receipt(task, {"status":"done", "gate":{"verification_aggregation":aggregation},
        "verification_evidence":raw}, workspace=workspace, verification_applicability=artifact)
    checked = validate_atomic_child_receipt(receipt, workspace=workspace, expected_contract_hash=contract["contract_hash"],
        expected_node_ids=contract["plan_node_ids"], expected_requirement_ids=contract["requirement_ids"],
        expected_requirements=contract["requirements"])
    return {"policy":policy,"aggregation_accepted":aggregation["passed"],"valid_receipt":checked["valid"],
            "errors":checked["errors"],"decisions":aggregation.get("semantic_compatibility_audit",{}).get("decisions")}


def main():
    from dataclasses import replace
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(); args.output_dir.mkdir(parents=True,exist_ok=False)
    mini._load_optional_imports();mini.ensure_dependencies(auto_install=False)
    rows=[]
    for cid in CASE_IDS:
        case=get_case(cid); workspace=args.output_dir/cid;materialize(case,workspace)
        (workspace/case["source"]).write_text(reference_source(case),encoding="utf-8")
        mini.WORKSPACE=workspace.resolve();mini.reset_run("experiment13-evidence-probe")
        mini.RUN["verification_surface_policy"]="discovery"
        approved=json.loads((args.suite/cid/"authority.json").read_text(encoding="utf-8"))
        snapshot=mini.stage4.create_approved_plan_snapshot(approved["plan"],approved["approval"],case["goal"],
            approved["requirements"],approved["repository_evidence"],{})
        contract=mini.stage4.compile_execution_contracts(snapshot)["contracts"][0]
        subject=fingerprint_dependency_paths(workspace,contract["allowed_inspection_paths"])
        claims=semantic.required_claims(contract["requirements"],contract_hash=contract["contract_hash"],
            child_id=contract["execution_contract_id"],target=case["source"],subject_hash=subject["hash"],
            subject_paths=[p["path"] for p in subject["paths"]])
        browser=other_behavior=other_target=None
        if case["family"].startswith("browser"):
            profile=mini.infer_web_profile(case["goal"])
            def verify(target, chosen_profile):
                return mini.verify_browser_application(target,"PROBE",profile=chosen_profile,
                    evidence={"verification_requirement":case["goal"],"harness_config":{"entrypoint":target}})
            browser=verify(case["source"],profile)
            other_behavior=verify(case["source"],replace(profile,required_interactions=("goal_win_state",)))
            (workspace/"other.html").write_text(reference_source(case),encoding="utf-8")
            other_target=verify("other.html",profile)
            if not all(p.get("passed") is True for p in (browser,other_behavior,other_target)):
                raise RuntimeError("actual native behavior/alternative did not pass")
            raw=[{"tool":"verify_web_app","target":case["source"],"result":json.dumps(browser)}]
        else:
            raw=[{"tool":"run_file","target":case["test_target"],"result":mini.run_file(case["test_target"])},
                 {"tool":"run_command","target":case["integration_target"],"result":mini.run_command(case["integration_target"])}]
            if not all("[exit_code=0]" in r["result"] for r in raw):raise RuntimeError("unit suite did not pass")
        save(workspace/"native_payloads.json",{"browser":browser,"evidence":raw,"different_behavior":other_behavior,"different_target":other_target})
        for name,expected,evidence,payload,records,artifact in scenario_inputs(case,contract,browser,raw,claims,subject,other_behavior,other_target):
            for policy in ("current","compatible","monotonic"):
                verdict=evaluate(case,workspace,contract,artifact,evidence,payload,records,policy,claims)
                verdict.update(case_id=cid,scenario=name,expected_compatible=expected,
                    false_accept=not expected and verdict["valid_receipt"],false_reject=expected and not verdict["valid_receipt"],
                    aggregation_false_accept=not expected and verdict["aggregation_accepted"])
                rows.append(verdict)
        print(cid,"native PASS",flush=True)
    save(args.output_dir/"comparison.json",{"experiment":13,"outcomes":rows,"model_calls":0,
        "primary_cases":CASE_IDS,"upstream_exclusions":["timer_pause","python_clamp"],
        "scope":"Reference candidate verification + declared adversarial/provenance replays; no Worker or Root success claimed."})


if __name__=="__main__":main()
