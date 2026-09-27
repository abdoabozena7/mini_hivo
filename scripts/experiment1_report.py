"""Summarize paired Experiment 1 runs from subject workspace metrics files."""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


ROUTES = ("current_recursive", "decomposition_first_recursive")


def event(run, kind):
    return next((item for item in run.get("experiment_events", [])
                 if item.get("kind") == kind), None)


def summarize_run(run):
    first_worker = event(run, "FIRST_WORKER_STARTED")
    approval_required = event(run, "APPROVAL_REQUIRED")
    approved = event(run, "APPROVED")
    human_wait = (max(0, approved["elapsed_seconds"] - approval_required["elapsed_seconds"])
                  if approval_required and approved else 0)
    blocker = run.get("first_blocker") or {}
    return {
        "run_id": run.get("run_id"),
        "case_id": run.get("experiment_case_id"),
        "route": run.get("planning_route"),
        "status": run.get("status"),
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "first_blocker_detail": blocker.get("detail"),
        "worker_reached": bool(first_worker),
        "awaiting_approval": run.get("status") == "plan_approval_required",
        "approval_rejected": run.get("status") == "plan_rejected",
        "pre_worker_blocked": bool(blocker) and not bool(first_worker),
        "verified_children": sum(item.get("kind") == "CHILD_VERIFIED"
                                 for item in run.get("experiment_events", [])),
        "verified_early_responsibilities": sum(
            item.get("kind") == "EARLY_CHILD_VERIFIED"
            for item in run.get("experiment_events", [])
        ),
        "root_verified": bool(event(run, "ROOT_VERIFIED")),
        "model_calls_before_worker": first_worker.get("model_calls") if first_worker else None,
        "seconds_before_worker_excluding_approval": (
            round(first_worker["elapsed_seconds"] - human_wait, 3) if first_worker else None
        ),
        "total_model_calls": run.get("model_calls", 0),
        "elapsed_seconds": run.get("elapsed_seconds"),
        "safety_blocks": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "dnt_execution_violations",
            "unapproved_scope_expansions", "precommit_invariant_gate_rejections",
        )),
        "unsafe_terminal": (run.get("execution_graph_execution") or {}).get(
            "lifecycle_terminal_state") in {"UNAUTHORIZED_MUTATION", "DNT_VIOLATION"},
    }


def load_runs(paths):
    runs = []
    for source in paths:
        path = Path(source)
        metric_files = [path / ".agent_experiment.jsonl"] if path.is_dir() else [path]
        for metric_file in metric_files:
            with metric_file.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        run = json.loads(line)
                        if run.get("planning_route") in ROUTES:
                            runs.append(run)
    return runs


def report(runs):
    grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for run in runs:
        grouped[run.get("experiment_case_id")][run.get("planning_route")].append(run)
    if not grouped:
        raise ValueError("no recursive Experiment 1 runs found")
    for case_id, routes in grouped.items():
        counts = [len(routes[route]) for route in ROUTES]
        if not case_id or min(counts) == 0 or counts[0] != counts[1]:
            raise ValueError(f"unpaired case {case_id}: route counts {counts}")
        if any(run.get("project_mode") != "EXISTING_PROJECT"
               for items in routes.values() for run in items):
            raise ValueError(f"case {case_id} is not an existing-project task")
        models = {run.get("model") for items in routes.values() for run in items}
        sources = {run.get("source_sha256") for items in routes.values() for run in items}
        subjects = {run.get("experiment_subject_fingerprint")
                    for items in routes.values() for run in items}
        if len(models) != 1 or len(sources) != 1 or len(subjects) != 1:
            raise ValueError(f"case {case_id} used different model, code, or subject snapshots")
    detail = [summarize_run(run) for routes in grouped.values()
              for items in routes.values() for run in items]
    aggregate = {}
    for route in ROUTES:
        items = [item for item in detail if item["route"] == route]
        blockers = collections.Counter(item["first_blocker_stage"] for item in items
                                       if item["first_blocker_stage"])
        aggregate[route] = {
            "runs": len(items),
            "worker_reached": sum(item["worker_reached"] for item in items),
            "awaiting_approval": sum(item["awaiting_approval"] for item in items),
            "approval_rejected": sum(item["approval_rejected"] for item in items),
            "pre_worker_blocked": sum(item["pre_worker_blocked"] for item in items),
            "runs_with_verified_child": sum(item["verified_children"] > 0 for item in items),
            "verified_early_responsibilities": sum(
                item["verified_early_responsibilities"] for item in items
            ),
            "root_verified": sum(item["root_verified"] for item in items),
            "safety_blocks": sum(item["safety_blocks"] for item in items),
            "unsafe_terminals": sum(item["unsafe_terminal"] for item in items),
            "first_blocker_stages": dict(sorted(blockers.items())),
        }
    return {"cases": len(grouped), "aggregate": aggregate, "runs": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", nargs="+", help="workspace directories or .agent_experiment.jsonl files")
    parser.add_argument("--output", type=Path, help="write the report as JSON")
    args = parser.parse_args()
    result = report(load_runs(args.metrics))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
