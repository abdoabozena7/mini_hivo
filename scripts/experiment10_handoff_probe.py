"""Replay one frozen post-child projection through unchanged verification gates."""

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from hivo.child_handoff_diagnostics import trace_handoff
from hivo.integration_gate import canonical_hash


RUN_FIELDS = ("source_contract", "project_invariants", "repository_evidence", "planning_route", "impact_planning_required",
              "plan_approval", "approved_plan_snapshot", "approved_change_plan", "execution_contracts",
              "execution_contract_by_id", "execution_contract_status", "verification_environment_policy",
              "verification_surface_policy", "child_receipt_policy", "integration_target_policy", "semantic_evidence_policy")


def read_run(path):
    return json.loads(path.read_text(encoding="utf-8").splitlines()[-1])


def events_for(path):
    return [json.loads(line) for file in sorted((path.parent / ".agent_runs").glob("*.jsonl"))
            for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def historical_audit(path, child_id):
    saved, events = read_run(path), events_for(path)
    relevant = [e for e in events if e.get("child_id", e.get("task_id")) == child_id]
    aggregation = next((e for e in relevant if e["kind"] == "verification_evidence_aggregated"), {})
    first_failure = next((r for r in aggregation.get("actual_failures", []) if r.get("required")), {})
    return {"input_run": str(path.resolve()), "run_id": saved["run_id"],
            "terminal_blocker": saved.get("first_blocker"),
            "first_required_route_failure": first_failure,
            "browser_results": [e for e in relevant if e["kind"] == "verification_browser_result"],
            "worker_context": [e for e in relevant if e["kind"] == "context_sufficiency_decision" and e.get("role") == "Builder"],
            "repairer_started": any(e["kind"] == "context_sufficiency_initial_context" and e.get("role") == "Repairer" for e in relevant)}


def historical_projection(path, child_id):
    """Preserve archived records verbatim; disclose lost full result payloads."""
    saved, events = read_run(path), events_for(path)
    contract = copy.deepcopy(saved["execution_contract_by_id"][child_id])
    approval = saved.get("plan_approval") or {}
    if approval.get("approval_status") != "APPROVED" or approval.get("plan_hash") != contract.get("plan_hash"):
        raise ValueError("saved contract is not bound to saved approval")
    child = next(t for t in saved["task_tree"] if t["task_id"] == child_id)
    task = {"id": child_id, "parent": child["parent_id"], "depth": child["depth"], "goal": child["goal"],
            "scope_hint": contract["allowed_mutation_paths"], "done_when": contract["done_when"],
            "execution_contract": contract, "execution_contract_child": True,
            "execution_contract_id": child_id, "execution_contract_hash": contract["contract_hash"],
            "plan_node_ids": contract["plan_node_ids"]}
    finish = {role: next((e for e in events if e.get("kind") == "agent_finished" and e.get("task_id") == child_id
                         and e.get("role") == role), {}) for role in ("Builder", "Falsifier")}
    evidence = copy.deepcopy((saved.get("child_receipts", {}).get(child_id) or {}).get("verification_evidence", []))
    count = finish["Builder"].get("evidence_count", 0)
    context = next((e for e in reversed(events) if e.get("kind") == "context_sufficiency_decision"
                    and e.get("task_id") == child_id and e.get("role") == "Builder"), {})
    builder = {"status": finish["Builder"].get("status"), "summary": finish["Builder"].get("summary", ""),
               "tool_evidence": evidence[:count], "context_sufficiency": {
                   "context_status": context.get("context_status"), "failure_code": context.get("failure_code"),
                   "mutation_allowed": context.get("mutation_authorized"), "state": context.get("lifecycle_state")}}
    falsifier = {"status": finish["Falsifier"].get("status"), "tool_evidence": evidence[count:]}
    complete = bool(finish["Builder"] and context and len(evidence) ==
                    count + finish["Falsifier"].get("evidence_count", 0))
    tool_contract = {"goal": task["goal"], "requirements": task["done_when"],
                     "constraints": saved["source_contract"].get("constraints", []), "success_criteria": task["done_when"],
                     "task_id": child_id, "project_invariants": saved.get("project_invariants", []),
                     "execution_contract_child": True}
    # These fields are the same authority projection used by execute_leaf.
    with patch.object(mini, "RUN", copy.deepcopy(saved)):
        tool_contract.update(mini._active_plan_tool_contract_fields(task))
    snapshot = {"task": task, "tool_contract": tool_contract, "builder": builder, "falsifier": falsifier,
                "records_complete": complete, "capture_mode": "historical_compact_projection",
                "limits": ["Archive stores compact tool results, not the full Worker/Falsifier payloads.",
                           "The post-verification commit/receipt lifecycle is not replayed."],
                "input_run": str(path.resolve()), "input_run_id": saved["run_id"]}
    return saved, snapshot


def materialize(path, saved, child_id, workspace):
    contract = saved["execution_contract_by_id"][child_id]
    allowed = set(contract["allowed_inspection_paths"]) | set(contract["allowed_mutation_paths"])
    candidates = {}
    for manifest_path in saved.get("candidate_patch_artifacts", []):
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if manifest["task_id"] == child_id:
            candidates.update({r["path"]: r for r in manifest["files"]})
    workspace.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for relative in sorted(allowed):
        source = path.parent / relative
        if relative in candidates:
            record = candidates[relative]
            source = Path(record["candidate_path"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != record["candidate_sha256"]:
                raise ValueError("candidate bytes have changed")
        destination = (workspace / relative).resolve()
        destination.relative_to(workspace.resolve())
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            hashes[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def replay(saved, snapshot, workspace):
    mini.WORKSPACE = workspace.resolve()
    mini.reset_run("experiment10-frozen-child-handoff")
    mini.RUN.update({key: copy.deepcopy(saved[key]) for key in RUN_FIELDS if key in saved})
    mini.TASKS = {snapshot["task"]["id"]: copy.deepcopy(snapshot["task"])}
    mini.ACTIVE_TRANSACTION = None
    if snapshot.get("transaction_files"):
        mini.ACTIVE_TRANSACTION = {"task_id": snapshot["task"]["id"], "files": {
            str((workspace / p).resolve()): {"existed": item["existed"],
                 "content": base64.b64decode(item["content_base64"]) if item["content_base64"] is not None else None}
            for p, item in snapshot["transaction_files"].items()}}
    mini.ACTIVE_TOOL_CONTRACT = copy.deepcopy(snapshot["tool_contract"])
    backend = SimpleNamespace(**{name: getattr(mini, name) for name in (
        "_authority_terminal_failure", "_context_sufficiency_failed", "CONTEXT_INSUFFICIENT_FAILURE",
        "merged_verification_evidence", "analyze_verification_applicability", "_verification_route",
        "BROWSER_VERIFICATION", "REQUIRED_VERIFICATION_TARGET_UNRESOLVED",
        "_combined_syntax_validation_failures", "evidence_gate", "classify_failure")})

    def browser_check(*args, on_start, **kwargs):
        original = mini.verify_browser_application

        def observe(requested_path=None, task_id="ROOT", **options):
            on_start(target=requested_path, task_id=task_id, source="existing_verify_browser_application")
            return original(requested_path, task_id, **options)

        with patch.object(mini, "verify_browser_application", side_effect=observe):
            return mini.optional_browser_check(*args, **kwargs)

    backend.observed_browser_check = browser_check
    result = trace_handoff(snapshot, backend)
    result.update({"model_calls": mini.RUN["model_calls"], "repairer_calls": mini.RUN["repairer_calls"],
                   "child_receipts_issued": len(mini.RUN.get("child_receipts", {})), "root_verification_attempted": False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run-file", type=Path)
    source.add_argument("--snapshot", type=Path, help="Exact snapshot from experiment10_capture.py")
    parser.add_argument("--audit-run-file", type=Path, action="append", default=[])
    parser.add_argument("--child-id", default="EXEC-001")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 2:
        parser.error("at least two repetitions are required")
    mini.configure_console_streams()
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise SystemExit("dependencies unavailable")
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        saved = snapshot["run_fields"]
        contract = snapshot["task"].get("execution_contract") or {}
        approval = saved.get("plan_approval") or {}
        if (snapshot.get("capture_mode") != "full_pre_browser_handoff"
                or approval.get("approval_status") != "APPROVED"
                or approval.get("plan_hash") != contract.get("plan_hash")):
            raise ValueError("snapshot is not a captured handoff bound to saved approval")
    else:
        saved, snapshot = historical_projection(args.run_file, args.child_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "frozen_handoff.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    records = []
    expected = None
    for index in range(args.repeat):
        workspace = args.output_dir / f"repeat-{index + 1}"
        if args.snapshot:
            workspace.mkdir(parents=True, exist_ok=False)
            before = {}
            for relative, encoded in snapshot["workspace_files"].items():
                target = (workspace / relative).resolve()
                target.relative_to(workspace.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                content = base64.b64decode(encoded)
                target.write_bytes(content)
                before[relative] = hashlib.sha256(content).hexdigest()
        else:
            before = materialize(args.run_file, saved, args.child_id, workspace)
        expected = before if expected is None else expected
        if before != expected:
            raise ValueError("replay subjects differ")
        result = replay(saved, snapshot, workspace)
        after = {p: hashlib.sha256((workspace / p).read_bytes()).hexdigest() for p in before}
        if before != after:
            raise ValueError("read-only handoff changed source bytes")
        result.update({"source_sha256": before, "source_unchanged": True, "input_hash": canonical_hash(snapshot)})
        (workspace / "handoff.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(result)
        print(f"repeat {index + 1}: started={result['verification_started']} blocker={result['first_blocker']}", flush=True)
    data = {"experiment": 10, "capture_mode": snapshot["capture_mode"], "limits": snapshot["limits"],
            "sample_size": 1, "repeat_count": args.repeat, "input_hash": canonical_hash(snapshot),
            "historical_audits": [historical_audit(p, args.child_id)
                                  for p in [args.run_file, *args.audit_run_file] if p is not None],
            "replays": records, "verification_started": sum(r["verification_started"] for r in records),
            "decision_consistent": len({r["decision_hash"] for r in records}) == 1,
            "same_source_and_input": True, "gate_bypasses": 0}
    (args.output_dir / "comparison.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
