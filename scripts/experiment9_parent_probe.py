"""Compare parent integration routes on one frozen, previously verified patch."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--complete-root", action="store_true",
                        help="Continue the saved non-promotion root through its existing completion boundary.")
    args = parser.parse_args()
    saved = json.loads(args.run_file.read_text(encoding="utf-8").splitlines()[-1])
    receipts = saved["child_receipts"]
    assert receipts and all(item["verified"] is True for item in receipts.values())
    if args.complete_root:
        approval = saved.get("plan_approval") or {}
        if approval.get("approval_status") != "APPROVED":
            raise ValueError("root continuation requires the saved user-approved plan")
        if (saved.get("execution_graph_execution") or {}).get("approval_bound") is not False:
            raise ValueError("this probe does not resume the promotion lifecycle")
        if set(receipts) != set(saved["execution_contract_by_id"]):
            raise ValueError("all approved graph children must have canonical verified receipts")
        for child_id, receipt in receipts.items():
            if ((receipt.get("authority") or {}).get("plan_hash") != approval.get("plan_hash")
                    or (receipt.get("authority") or {}).get("execution_contract_hash")
                    != saved["execution_contract_by_id"][child_id].get("contract_hash")):
                raise ValueError("saved child receipt does not bind to the approved contract")
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise SystemExit("dependencies unavailable")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for policy in ("current", "resolved"):
        workspace = args.output_dir / policy
        workspace.mkdir(exist_ok=False)
        records = {item["path"]: item for receipt in receipts.values()
                   for item in receipt["verified_subject_state"]["paths"] if item["exists"]}
        for relative, expected in records.items():
            source = (args.run_file.parent / relative).resolve()
            source.relative_to(args.run_file.parent.resolve())
            assert hashlib.sha256(source.read_bytes()).hexdigest() == expected["sha256"]
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        mini.WORKSPACE = workspace.resolve()
        mini.reset_run("experiment9-parent-probe")
        mini.RUN.update({key: copy.deepcopy(saved[key]) for key in (
            "planning_route", "source_contract", "source_requirement_ledger", "project_mode",
            "impact_planning_required", "execution_contract_status", "stage5c_enabled",
            "plan_approval", "approved_plan_snapshot", "execution_contracts") if key in saved})
        mini.RUN.update({"stage5b_enabled": True, "child_receipt_policy": "atomic_verified",
                         "experiment_case_id": saved.get("experiment_case_id"),
                         "integration_target_policy": policy, "child_receipts": copy.deepcopy(receipts),
                         "verification_environment_policy": "resolved", "verification_surface_policy": "discovery"})
        contract = copy.deepcopy(saved["stage5b_parent_contract"])
        root = mini.root_task_from_contract(contract)
        root["stage5b_enabled"] = True
        root["stage5b_parent_contract"] = contract
        root["validated_child_plan"] = []
        root["children"] = list(receipts)
        children = []
        mini.TASKS = {"ROOT": root}
        for child_id, receipt in receipts.items():
            child_contract = saved["execution_contract_by_id"][child_id]
            child = {"id": child_id, "parent": "ROOT", "status": "done",
                     "execution_contract": copy.deepcopy(child_contract),
                     "execution_contract_id": child_contract["execution_contract_id"],
                     "execution_contract_hash": child_contract["contract_hash"],
                     "plan_node_ids": child_contract["plan_node_ids"],
                     "verified_child_receipt": copy.deepcopy(receipt)}
            mini.TASKS[child_id] = child
            children.append({"task": child, "result": {"status": "done", "verified_child_receipt": copy.deepcopy(receipt)}})
            root["validated_child_plan"].append({"child_id": child_id, "required": True,
                                                 "plan_node_ids": child_contract["plan_node_ids"]})
        snapshot = mini.inspect_repository(workspace)
        readiness = mini._stage5b_parent_readiness(root, contract, children, snapshot)
        assert readiness["readiness"] == "READY"
        result = mini._aggregate_stage5b_parent(root, contract, children, {}, snapshot, root=True, readiness=readiness)
        if args.complete_root:
            # Same root completion boundary as execute_approved_plan_graph.
            # A child receipt is only a readiness prerequisite: the result
            # above must contain a new parent verification receipt to pass.
            if result["status"] == "done" and result.get("integration_result") != mini.PARENT_VERIFIED:
                raise ValueError("root continuation lacks fresh parent verification")
            mini._mark_task_result(root, result)
            if result["status"] == "done":
                mini._experiment_event("ROOT_VERIFIED", continuation=True,
                                       parent_receipt_hash=result["parent_verification_receipt"]["receipt_hash"])
            else:
                mini._experiment_blocked("PARENT_INTEGRATION", result)
        source_hashes = {path: hashlib.sha256((workspace / path).read_bytes()).hexdigest()
                         for path in records if not path.startswith(".")}
        source_unchanged = all(hashlib.sha256((workspace / path).read_bytes()).hexdigest() == record["sha256"]
                               for path, record in records.items())
        assert source_unchanged
        outputs[policy] = {"status": result["status"], "integration_result": result["integration_result"],
                           "summary": result.get("summary"), "parent_verification_receipt": result.get("parent_verification_receipt"),
                           "resolution": root.get("integration_target_resolution"),
                           "parent_verification_runs": mini.RUN.get("parent_verification_runs", []),
                           "parent_requirement_coverage": root.get("parent_requirement_coverage", {}),
                           "child_evidence_reused_as_proof": 0, "source_sha256": source_hashes,
                           "root_verified": mini.RUN.get("root_verified") if args.complete_root else None,
                           "root_verified_event": any(item["kind"] == "ROOT_VERIFIED" for item in mini.RUN.get("experiment_events", [])),
                           "source_unchanged": source_unchanged,
                           "model_calls": mini.RUN.get("model_calls", 0), "readiness": readiness["readiness"]}
        print(policy, result["integration_result"], result.get("summary"), flush=True)
    assert outputs["current"]["source_sha256"] == outputs["resolved"]["source_sha256"]
    data = {"comparison": "same candidate bytes and same canonical child receipts; new parent verification in resolved route",
            "completion_mode": "continue_existing_verified_children" if args.complete_root else "parent_probe_only",
            "input_run": str(args.run_file.resolve()), "policies": outputs}
    (args.output_dir / "comparison.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
