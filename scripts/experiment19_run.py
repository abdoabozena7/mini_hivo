"""Frozen Python A/B for bounded context-decision closure after inspection."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import experiment18_run as previous
from scripts.experiment12_report import load


POLICIES = ("current", "bounded_closure")


def preregister(directory, baseline, policy):
    previous.preregister(directory, baseline, "python", "bounded_reanchor")
    manifest = load(directory / "manifest.json")
    manifest["experiment"] = 19
    manifest["worker_context_decision_policy"] = policy
    previous.previous.save(directory / "manifest.json", manifest)
    print("preregistered Experiment 19", policy, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preregister", "batch"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--context-closure-policy", choices=POLICIES)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    if args.mode == "preregister":
        if args.baseline is None or args.context_closure_policy is None:
            parser.error("--baseline and --context-closure-policy are required")
        preregister(directory, args.baseline.resolve(), args.context_closure_policy)
    else:
        manifest = load(directory / "manifest.json")
        if manifest.get("experiment") != 19 or manifest.get("worker_context_decision_policy") not in POLICIES:
            raise ValueError("not an Experiment 19 suite")
        previous.batch(directory)


if __name__ == "__main__":
    main()
