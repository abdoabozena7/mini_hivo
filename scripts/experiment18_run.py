"""Frozen Python comparison and final Timer/Python diagnostic after Exp17."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment15_run as previous
from scripts.experiment12_fixtures import get_case


CASE_SETS = {"python": ("python_clamp",),
             "cross_domain": ("timer_pause", "python_clamp")}
GROUNDING = "evidence_bound"
REPEATS = 3


def preregister(directory, baseline, case_set, no_tool_policy):
    directory.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    records = []
    for case_id in CASE_SETS[case_set]:
        case = get_case(case_id)
        folder = directory / case_id
        folder.mkdir()
        previous.engine.materialize(case, folder / "seed")
        approved = json.loads((baseline / case_id / "authority.json").read_text(encoding="utf-8"))
        regenerated = previous.engine.authority(case, folder / "seed")
        if (regenerated["plan"]["plan_hash"] != approved["plan"]["plan_hash"]
                or regenerated["execution_contract_hash"] != approved["execution_contract_hash"]):
            raise ValueError("frozen authority changed")
        previous.save(folder / "authority.json", approved)
        records.append(copy.deepcopy(next(c for c in frozen["cases"] if c["case_id"] == case_id)))
    manifest = {
        "experiment": 18, "case_set": case_set, "cases": records, "repeats": REPEATS,
        "model": frozen["model"], "worker_budget": frozen["worker_budget"],
        "baseline_suite": str(baseline.resolve()),
        "policies": {**previous.POLICIES, "mutation_grounding_policy": GROUNDING},
        "fixed_semantic_evidence_policy": "strict",
        "verification_classification_policy": "field_scoped",
        "worker_no_tool_policy": no_tool_policy,
        "production_sha256": {p: previous.sha((previous.engine.ROOT / p).read_bytes())
                              for p in previous.engine.PRODUCTION},
        "default_change_allowed": False,
    }
    previous.save(directory / "manifest.json", manifest)
    print("preregistered", case_set, no_tool_policy, len(records) * REPEATS, flush=True)


def batch(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    previous.engine.check_pin(manifest)
    case_ids = [c["case_id"] for c in manifest["cases"]]
    for repeat in range(1, REPEATS + 1):
        for case_id in (list(reversed(case_ids)) if repeat == 2 else case_ids):
            workspace = directory / case_id / f"{GROUNDING}-{repeat}"
            result = workspace.parent / f"{workspace.name}-result.json"
            if workspace.exists():
                if result.exists():
                    continue
                raise ValueError(f"incomplete trial: {workspace}")
            with (workspace.parent / f"{workspace.name}.log").open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "trial",
                     "--output-dir", str(directory), "--case-id", case_id, "--repeat", str(repeat)],
                    cwd=previous.engine.ROOT, stdout=log, stderr=subprocess.STDOUT,
                )
            print("finished", case_id, repeat, "exit", completed.returncode, flush=True)
            if completed.returncode:
                raise RuntimeError(f"trial failed: {workspace.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preregister", "trial", "batch"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--case-set", choices=CASE_SETS)
    parser.add_argument("--no-tool-policy", choices=("current", "bounded_reanchor"))
    parser.add_argument("--case-id", choices=tuple({c for v in CASE_SETS.values() for c in v}))
    parser.add_argument("--repeat", type=int, choices=range(1, REPEATS + 1))
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if args.mode == "preregister":
        if args.baseline is None or args.case_set is None or args.no_tool_policy is None:
            parser.error("--baseline, --case-set and --no-tool-policy are required")
        preregister(directory, args.baseline.resolve(), args.case_set, args.no_tool_policy)
    elif args.mode == "batch":
        batch(directory)
    else:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if args.case_id not in [c["case_id"] for c in manifest["cases"]]:
            raise ValueError("case outside manifest")
        previous.execute_trial(directory, args.case_id, GROUNDING, args.repeat)


if __name__ == "__main__":
    main()
