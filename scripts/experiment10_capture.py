"""Observe the approved runner and save its actual pre-browser handoff."""

import argparse
import base64
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from experiment3_approved_run import main as approved_run
from experiment10_handoff_probe import RUN_FIELDS


RESULT_FIELDS = (
    "status", "summary", "tool_evidence", "verification_evidence", "failure_type", "context_sufficiency",
    "syntax_validation_failures", "execution_obligation_evidence", "verification_obligation_coverage",
    "verification_applicability", "verification", "integration_preflight", "impact_contract",
    "impact_authorized", "mutation_authorized", "impact_required", "execution_outcome", "provider_error",
)


def capture(task, tool_contract, builder, falsifier):
    contract = task.get("execution_contract") or {}
    workspace_files, transaction_files = {}, {}
    for relative in sorted(set(contract.get("allowed_inspection_paths", []))
                           | set(contract.get("allowed_mutation_paths", []))):
        path = (mini.WORKSPACE / relative).resolve()
        path.relative_to(mini.WORKSPACE.resolve())
        if path.is_file():
            workspace_files[relative] = base64.b64encode(path.read_bytes()).decode("ascii")
    for raw, value in (mini.ACTIVE_TRANSACTION or {}).get("files", {}).items():
        relative = Path(raw).resolve().relative_to(mini.WORKSPACE.resolve()).as_posix()
        transaction_files[relative] = {
            "existed": value.get("existed"),
            "content_base64": base64.b64encode(value["content"]).decode("ascii") if value.get("content") is not None else None,
        }
    return {"capture_mode": "full_pre_browser_handoff", "records_complete": True,
            "limits": ["The post-verification commit/receipt lifecycle is not replayed."],
            "task": copy.deepcopy(task), "tool_contract": copy.deepcopy(tool_contract),
            "builder": {k: copy.deepcopy(builder[k]) for k in RESULT_FIELDS if k in builder},
            "falsifier": {k: copy.deepcopy(falsifier[k]) for k in RESULT_FIELDS if k in falsifier},
            "run_fields": {k: copy.deepcopy(mini.RUN[k]) for k in RUN_FIELDS if k in mini.RUN},
            "input_run_id": mini.RUN_ID, "workspace_files": workspace_files, "transaction_files": transaction_files}


def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--capture-dir", type=Path, required=True)
    args, runner_args = parser.parse_known_args()
    args.capture_dir.mkdir(parents=True, exist_ok=False)
    original = mini.falsify_task

    def observe(task, tool_contract, memory, builder, repo_snapshot, node_context=""):
        falsifier = original(task, tool_contract, memory, builder, repo_snapshot, node_context)
        snapshot = capture(task, tool_contract, builder, falsifier)
        destination = args.capture_dir / (task["id"].replace("/", "_") + ".json")
        if destination.exists():
            raise ValueError("refusing to overwrite a previous handoff capture")
        destination.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print("captured actual handoff:", destination.resolve(), flush=True)
        return falsifier

    # Observe one return value; call the original Falsifier and every gate.
    # The capture lives outside source workspace and cannot alter authority.
    with patch.object(mini, "falsify_task", side_effect=observe), patch.object(sys, "argv", [sys.argv[0], *runner_args]):
        approved_run()


if __name__ == "__main__":
    main()
