"""First-blocker diagnosis for the Timer and Python fixtures; no production changes."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from scripts import experiment15_run as previous
from scripts.experiment12_fixtures import get_case


CASES = ("timer_pause", "python_clamp")
POLICY = "evidence_bound"
REPEATS = 3


def preregister(directory: Path, baseline: Path):
    directory.mkdir(parents=True, exist_ok=False)
    prior = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for case_id in CASES:
        case = get_case(case_id)
        folder = directory / case_id
        folder.mkdir()
        previous.engine.materialize(case, folder / "seed")
        frozen = json.loads((baseline / case_id / "authority.json").read_text(encoding="utf-8"))
        regenerated = previous.engine.authority(case, folder / "seed")
        if (regenerated["plan"]["plan_hash"] != frozen["plan"]["plan_hash"]
                or regenerated["execution_contract_hash"] != frozen["execution_contract_hash"]):
            raise ValueError(f"frozen authority changed for {case_id}")
        previous.save(folder / "authority.json", frozen)
        records.append(copy.deepcopy(next(c for c in prior["cases"] if c["case_id"] == case_id)))
    production = {p: previous.sha((previous.engine.ROOT / p).read_bytes())
                  for p in previous.engine.PRODUCTION}
    manifest = {
        "experiment": 16, "cases": records, "repeats": REPEATS,
        "model": prior["model"], "worker_budget": prior["worker_budget"],
        "policies": {**previous.POLICIES, "mutation_grounding_policy": POLICY},
        "fixed_semantic_evidence_policy": "strict",
        "production_sha256": production,
        "baseline_suite": str(baseline.resolve()),
        "boundary": "frozen approved contract to child verification and parent proof",
        "planning_cost_included": False,
        "decision_changes": False,
        "default_change_allowed": False,
    }
    previous.save(directory / "manifest.json", manifest)
    print("preregistered Timer/Python: 6 fresh attempts", flush=True)


def trial(directory: Path, case_id: str, repeat: int):
    if case_id not in CASES or repeat not in range(1, REPEATS + 1):
        raise ValueError("trial outside preregistered inputs")
    workspace = directory / case_id / f"{POLICY}-{repeat}"
    trace = []
    original_tool, original_falsify = mini.run_tool, mini.falsify_task

    def observed_tool(name, args, role="System"):
        result = original_tool(name, args, role=role)
        if role == "Builder" and name in {
            "read_file", "read_file_range", "read_locator_candidate",
            "context_sufficiency_check", "edit_file", "edit_file_range", "write_file",
        }:
            trace.append({"kind": "worker_tool", "tool": name,
                          "target": args.get("path") or args.get("candidate_id"),
                          "args": copy.deepcopy(args), "result": str(result)[:2000]})
        return result

    def observed_falsify(*args, **kwargs):
        trace.append({"kind": "child_verification_invoked"})
        return original_falsify(*args, **kwargs)

    try:
        # The Experiment 15 runner records native verifier and mutation tool
        # returns. These outer observers only record read/context order and
        # verifier entry; both call the original functions unchanged.
        with patch.object(mini, "run_tool", side_effect=observed_tool), \
             patch.object(mini, "falsify_task", side_effect=observed_falsify):
            previous.execute_trial(directory, case_id, POLICY, repeat)
    finally:
        if workspace.exists():
            previous.save(workspace.parent / f"{workspace.name}-boundary-trace.json", trace)


def batch(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    previous.engine.check_pin(manifest)
    for repeat in range(1, REPEATS + 1):
        for case_id in CASES if repeat != 2 else reversed(CASES):
            workspace = directory / case_id / f"{POLICY}-{repeat}"
            result = workspace.parent / f"{workspace.name}-result.json"
            if workspace.exists():
                if result.exists():
                    continue
                raise ValueError(f"incomplete existing attempt: {workspace}")
            with (workspace.parent / f"{workspace.name}.log").open(
                "w", encoding="utf-8"
            ) as log:
                completed = subprocess.run(
                    [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
                     "trial", "--output-dir", str(directory), "--case-id", case_id,
                     "--repeat", str(repeat)],
                    cwd=previous.engine.ROOT, stdout=log, stderr=subprocess.STDOUT,
                )
            print("finished", case_id, repeat, "exit", completed.returncode, flush=True)
            if completed.returncode:
                raise RuntimeError(f"trial harness failed: {workspace.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preregister", "trial", "batch"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--case-id", choices=CASES)
    parser.add_argument("--repeat", type=int, choices=range(1, REPEATS + 1))
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if args.mode == "preregister":
        if args.baseline is None:
            parser.error("--baseline is required for preregistration")
        preregister(directory, args.baseline.resolve())
    elif args.mode == "trial":
        trial(directory, args.case_id, args.repeat)
    else:
        batch(directory)


if __name__ == "__main__":
    main()
