"""Compare a frozen failed aggregation, then resume the real child receipt seam.

The original archive has compact tool results. A missing accepted Impact
Contract can be recovered from a complete capture only when its content hash
matches the original authorization event, execution contract and context anchor.
No Worker, Falsifier, Repairer or parent proof is rerun or synthesized.
"""

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from hivo.atomic_child_receipt import validate_atomic_child_receipt
from scripts.experiment10_handoff_probe import events_for, historical_projection, materialize, replay


def digest(content):
    return hashlib.sha256(content).hexdigest()


def recover_input(run_file, capture_file, child_id):
    saved, snapshot = historical_projection(run_file, child_id)
    if not snapshot["records_complete"]:
        raise ValueError("original evidence inventory is incomplete")
    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    contract = snapshot["task"]["execution_contract"]
    if capture["task"]["execution_contract"] != contract:
        raise ValueError("recovery capture has a different execution contract")
    accepted = capture["task"]["impact_contract"]
    if mini.stage10_impact.impact_mutation_block_reason(accepted):
        raise ValueError("recovered impact authorization is invalid")
    events = events_for(run_file)
    authorization = next(e for e in events if e.get("kind") == "impact_contract_authorized"
                         and e.get("task_id") == child_id and e.get("mutation_authorized") is True)
    if authorization.get("contract_hash") != accepted["contract_hash"]:
        raise ValueError("recovered impact hash differs from original authorization")
    context = next(e for e in events if e.get("kind") == "context_sufficiency_decision"
                   and e.get("task_id") == child_id and e.get("role") == "Builder")
    if context.get("anchor_hash") != capture["builder"]["context_sufficiency"]["anchor_hash"]:
        raise ValueError("recovery capture has a different context anchor")
    before_hashes, candidate_hashes = {}, {}
    for relative, transaction in capture["transaction_files"].items():
        if relative not in contract["allowed_mutation_paths"] or not transaction["existed"]:
            raise ValueError("replay supports only the archived existing mutation paths")
        before = base64.b64decode(transaction["content_base64"])
        if before != (run_file.parent / relative).read_bytes():
            raise ValueError("original rollback bytes differ from recovery transaction")
        before_hashes[relative] = digest(before)
        candidate_hashes[relative] = digest(base64.b64decode(capture["workspace_files"][relative]))
    snapshot["transaction_files"] = copy.deepcopy(capture["transaction_files"])
    snapshot["task"].update(impact_contract=copy.deepcopy(accepted), impact_contract_required=True)
    snapshot["builder"].update(impact_contract=copy.deepcopy(accepted), impact_required=True,
                                impact_authorized=True, mutation_authorized=True)
    recovery = {"capture_path": str(capture_file.resolve()), "impact_hash": accepted["contract_hash"],
                "original_impact_authorization_hash_matched": True,
                "context_anchor_hash_matched": True, "execution_contract_equal": True,
                "before_source_sha256": before_hashes, "candidate_source_sha256": candidate_hashes}
    snapshot["limits"] = ["Original tool payloads are archived in compact form; matcher fields and inventory are preserved.",
                           "Accepted Impact Contract recovered by matching its original authorization hash from a later full capture.",
                           "No parent integration or fresh Worker/Falsifier execution is claimed in this comparison."]
    return saved, snapshot, recovery


def resume_receipt(saved, snapshot, result):
    task = mini.TASKS[snapshot["task"]["id"]]
    mini.RUN["stage5b_enabled"] = True
    mini.TASKS[str(task["parent"])] = {"id": task["parent"],
        "stage5b_parent_contract": saved.get("stage5b_parent_contract") or saved["source_contract"]}
    committed = mini._commit_verified_leaf(task, snapshot["tool_contract"],
        copy.deepcopy(snapshot["builder"]), copy.deepcopy(snapshot["falsifier"]),
        result["browser"], result["gate"], mini.load_memory())
    mini._mark_task_result(task, committed)
    receipt = mini.RUN.get("child_receipts", {}).get(task["id"])
    checked = validate_atomic_child_receipt(receipt, workspace=mini.WORKSPACE,
        expected_contract_hash=task["execution_contract_hash"], expected_node_ids=task["plan_node_ids"],
        expected_requirement_ids=task["execution_contract"]["requirement_ids"],
        expected_requirements=task["execution_contract"]["requirements"])
    return {"status": committed["status"], "failure_type": committed.get("failure_type"),
            "impact_comparison": committed.get("impact_comparison"), "receipt_validation": checked,
            "receipt_path": committed.get("verified_child_receipt_path"), "receipt": receipt}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-file", type=Path, required=True)
    parser.add_argument("--recovery-capture", type=Path, required=True)
    parser.add_argument("--child-id", default="EXEC-001")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    mini.configure_console_streams()
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise SystemExit("dependencies unavailable")
    saved, snapshot, recovery = recover_input(args.run_file, args.recovery_capture, args.child_id)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "frozen_handoff.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    comparisons = []
    for policy in ("current", "compatible"):
        workspace = args.output_dir / policy
        before = materialize(args.run_file, saved, args.child_id, workspace)
        if any(before.get(p) != sha for p, sha in recovery["candidate_source_sha256"].items()):
            raise ValueError("recovered transaction and original candidate are different")
        branch_saved = {**copy.deepcopy(saved), "semantic_evidence_policy": policy}
        result = replay(branch_saved, snapshot, workspace)
        if result["evidence_gate_passed"]:
            result["receipt_continuation"] = resume_receipt(branch_saved, snapshot, result)
        after = {p: digest((workspace / p).read_bytes()) for p in before}
        result.update(policy=policy, source_sha256=before, source_unchanged=before == after,
                      model_calls=mini.RUN["model_calls"], repairer_calls=mini.RUN["repairer_calls"],
                      canonical_record_count=len(mini.RUN.get("canonical_evidence_records", [])),
                      child_verified=bool((mini.RUN.get("child_receipts", {}).get(args.child_id) or {}).get("verified")),
                      parent_verification_executed=False)
        (workspace / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        comparisons.append(result)
        print(f"{policy}: browser_pass={(result['browser'] or {}).get('passed')} gate={result['evidence_gate_passed']} child_verified={result['child_verified']}", flush=True)
    data = {"experiment": 11, "input_run": str(args.run_file.resolve()), "input_run_id": saved["run_id"],
            "capture_mode": snapshot["capture_mode"], "limits": snapshot["limits"], "recovered_artifact": recovery,
            "same_frozen_input": True, "same_candidate_source": True, "policies": comparisons}
    (args.output_dir / "comparison.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
