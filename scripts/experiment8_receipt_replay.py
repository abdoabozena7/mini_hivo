"""Compare only the receipt boundary using one saved, verified child and patch."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from hivo.atomic_child_receipt import validate_atomic_child_receipt
from hivo.integration_gate import canonical_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--child-id", default="EXEC-001")
    args = parser.parse_args()
    saved = json.loads(args.run_file.read_text(encoding="utf-8").splitlines()[-1])
    old_receipt = saved["child_receipts"][args.child_id]
    contract = saved["execution_contract_by_id"][args.child_id]
    old_task = next(item for item in saved["task_tree"] if item["task_id"] == args.child_id)
    aggregation = copy.deepcopy(old_receipt["verification_aggregation"])
    aggregation["verification_routes"] = copy.deepcopy(old_receipt["verification_routes"])
    aggregation["required_execution_verification_set"] = copy.deepcopy(old_receipt["required_execution_verification_set"])
    assert aggregation["passed"] is True and aggregation["evidence_available"] is True
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for policy in ("current", "atomic_verified"):
        workspace = args.output_dir / policy
        workspace.mkdir(exist_ok=False)
        for path in contract["allowed_mutation_paths"]:
            source = args.run_file.parent / path
            expected = next(item for item in old_receipt["verified_subject_state"]["paths"] if item["path"] == path)
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected["sha256"]
            target = workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        backups = args.run_file.parent / ".agent_backups"
        if backups.is_dir():
            shutil.copytree(backups, workspace / ".agent_backups")
        mini.WORKSPACE = workspace.resolve()
        mini.reset_run("experiment8-receipt-replay")
        mini.RUN.update({key: copy.deepcopy(saved[key]) for key in (
            "planning_route", "source_contract", "project_mode", "impact_planning_required",
            "execution_contract_status", "stage5b_parent_contract") if key in saved})
        mini.RUN.update({"stage5b_enabled": True, "child_receipt_policy": policy,
                         "experiment_case_id": saved.get("experiment_case_id")})
        task = {"id": args.child_id, "parent": "ROOT", "depth": 1,
                "goal": old_task["goal"], "execution_contract": copy.deepcopy(contract),
                "execution_contract_id": contract["execution_contract_id"],
                "execution_contract_hash": contract["contract_hash"],
                "approved_plan_hash": contract["plan_hash"],
                "plan_node_ids": list(contract["plan_node_ids"]),
                "plan_requirement_ids": list(contract["requirement_ids"])}
        parent_contract = copy.deepcopy(saved["stage5b_parent_contract"])
        root = {"id": "ROOT", "stage5b_enabled": True,
                "stage5b_parent_contract": parent_contract,
                "goal": saved["source_contract"].get("goal", ""),
                "validated_child_plan": [{"child_id": args.child_id, "required": True,
                                           "plan_node_ids": list(contract["plan_node_ids"])}]}
        mini.TASKS = {"ROOT": root, args.child_id: task}
        result = {"status": old_receipt["terminal_child_status"], "summary": old_task["summary"],
                  "verification_applicability": copy.deepcopy(old_task["verification_applicability"]),
                  "gate": {"verification_aggregation": copy.deepcopy(aggregation)},
                  "verification_evidence": copy.deepcopy(old_receipt["verification_evidence"])}
        mini._mark_task_result(task, result, count=False)
        receipt = result["verified_child_receipt"]
        readiness = mini._stage5b_parent_readiness(root, parent_contract, [{"task": task, "result": result}])
        checked = validate_atomic_child_receipt(receipt, workspace=workspace)
        outputs[policy] = {
            "receipt": receipt, "readiness": readiness,
            "receipt_valid": checked["valid"] if policy == "atomic_verified" else False,
            "verification_evidence_hash_matches": (
                receipt.get("verification_evidence_hash") == canonical_hash(receipt["verification_evidence"])
                if policy == "atomic_verified" else None),
            "child_verified_events": sum(item["kind"] == "CHILD_VERIFIED" for item in mini.RUN.get("experiment_events", [])),
            "events": mini.RUN.get("experiment_events", []),
            "source_sha256": hashlib.sha256((workspace / contract["allowed_mutation_paths"][0]).read_bytes()).hexdigest(),
            "model_calls": mini.RUN.get("model_calls", 0),
        }
    assert outputs["current"]["source_sha256"] == outputs["atomic_verified"]["source_sha256"]
    output = {"comparison": "same historical child verification evidence, same candidate bytes; no Worker rerun",
              "input_run": str(args.run_file.resolve()), "input_receipt_hash": old_receipt["receipt_hash"],
              "historical_child_verified_events": sum(item["kind"] == "CHILD_VERIFIED" for item in saved["experiment_events"]),
              "policies": outputs}
    (args.output_dir / "comparison.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: {"verified": item["receipt"]["verified"], "valid": item["receipt_valid"],
                           "readiness": item["readiness"]["readiness"], "reason": item["readiness"]["reason"],
                           "coverage": item["readiness"]["coverage"], "events": item["child_verified_events"]}
                      for key, item in outputs.items()}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
