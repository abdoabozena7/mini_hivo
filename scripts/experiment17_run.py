"""Frozen Timer and game contracts under optional field-scoped classification."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment15_run as previous
from scripts.experiment12_fixtures import get_case


CASES = ("timer_pause", "arena_arrow", "arena_q_restart")
POLICY = "evidence_bound"
REPEATS = 3


def preregister(directory: Path, baseline: Path):
    directory.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for case_id in CASES:
        case = get_case(case_id)
        folder = directory / case_id
        folder.mkdir()
        previous.engine.materialize(case, folder / "seed")
        authority = json.loads((baseline / case_id / "authority.json").read_text(encoding="utf-8"))
        regenerated = previous.engine.authority(case, folder / "seed")
        if (regenerated["plan"]["plan_hash"] != authority["plan"]["plan_hash"]
                or regenerated["execution_contract_hash"] != authority["execution_contract_hash"]):
            raise ValueError(f"frozen authority changed: {case_id}")
        previous.save(folder / "authority.json", authority)
        records.append(copy.deepcopy(next(c for c in frozen["cases"] if c["case_id"] == case_id)))
    manifest = {
        "experiment": 17, "cases": records, "repeats": REPEATS,
        "model": frozen["model"], "worker_budget": frozen["worker_budget"],
        "baseline_suite": str(baseline.resolve()),
        "policies": {**previous.POLICIES, "mutation_grounding_policy": POLICY},
        "fixed_semantic_evidence_policy": "strict",
        "verification_classification_policy": "field_scoped",
        "production_sha256": {p: previous.sha((previous.engine.ROOT / p).read_bytes())
                              for p in previous.engine.PRODUCTION},
        "default_change_allowed": False,
        "other_execution_changes_allowed": False,
    }
    previous.save(directory / "manifest.json", manifest)
    print("preregistered Timer + 2 games; 9 fresh runs", flush=True)


def batch(directory: Path):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    previous.engine.check_pin(manifest)
    for repeat in range(1, REPEATS + 1):
        order = CASES if repeat != 2 else tuple(reversed(CASES))
        for case_id in order:
            workspace = directory / case_id / f"{POLICY}-{repeat}"
            result = workspace.parent / f"{workspace.name}-result.json"
            if workspace.exists():
                if result.exists():
                    continue
                raise ValueError(f"incomplete existing attempt: {workspace}")
            with (workspace.parent / f"{workspace.name}.log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "trial",
                     "--output-dir", str(directory), "--case-id", case_id, "--repeat", str(repeat)],
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
            parser.error("--baseline required for preregistration")
        preregister(directory, args.baseline.resolve())
    elif args.mode == "batch":
        batch(directory)
    else:
        previous.execute_trial(directory, args.case_id, POLICY, args.repeat)


if __name__ == "__main__":
    main()
