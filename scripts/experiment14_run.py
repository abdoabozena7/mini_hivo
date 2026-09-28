"""Experiment 14: same three eligible tasks, frozen contracts, 18 fresh runs."""

import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts import experiment12_run as engine
from scripts.experiment12_fixtures import get_case

engine.PRODUCTION = [*engine.PRODUCTION, "hivo/evidence_monotonic.py", "hivo/evidence_strict.py"]
CASE_IDS = ("arena_arrow", "arena_q_restart", "node_unique")
ARMS = ("monotonic", "strict")


def preregister(directory, baseline):
    directory.mkdir(parents=True,exist_ok=False)
    previous=json.loads((baseline/"manifest.json").read_text(encoding="utf-8"))
    cases=[]
    for cid in CASE_IDS:
        case=get_case(cid); folder=directory/cid;folder.mkdir()
        engine.materialize(case,folder/"seed")
        approved=json.loads((baseline/cid/"authority.json").read_text(encoding="utf-8"))
        generated=engine.authority(case,folder/"seed")
        if generated["execution_contract_hash"]!=approved["execution_contract_hash"] or generated["plan"]["plan_hash"]!=approved["plan"]["plan_hash"]:
            raise ValueError("fixture contract differs from Experiment 13")
        engine.save(folder/"authority.json",approved)
        cases.append(copy.deepcopy(next(c for c in previous["cases"] if c["case_id"]==cid)))
    pins={p:engine.sha((engine.ROOT/p).read_bytes()) for p in engine.PRODUCTION}
    unchanged=("hivo/verification.py","hivo/verification_surfaces.py","hivo/worker_progress.py",
               "hivo/mutation_grounding.py","hivo/integration_targets.py",
               "hivo/atomic_child_receipt.py","hivo/evidence_monotonic.py","hivo/evidence_compatibility.py")
    if any(pins[p]!=previous["production_sha256"][p] for p in unchanged):
        raise ValueError("a fixed experiment component changed")
    manifest={"experiment":14,"model":previous["model"],"worker_budget":previous["worker_budget"],"repeats":3,
        "baseline_suite":str(baseline.resolve()),"arms":ARMS,"cases":cases,"policies":engine.POLICIES,
        "production_sha256":pins,"unchanged_component_sha256":{p:pins[p] for p in unchanged},
        "primary_boundary":previous["primary_boundary"],"planning_cost_included":False,
        "excluded_cases":{"timer_pause":"upstream grounding failure","python_clamp":"upstream impact failure"},
        "hypothesis":"Exact approved-suite proof and complete browser assertion identities stay accepted; foreign or UNKNOWN identity does not match.",
        "final_receipt_gate_changed":False,"default_change_allowed":False}
    engine.save(directory/"manifest.json",manifest)
    print("preregistered 3 tasks; 18 fresh trials",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("preregister","trial","batch"))
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--baseline",type=Path)
    parser.add_argument("--case-id",choices=CASE_IDS)
    parser.add_argument("--policy",choices=ARMS)
    parser.add_argument("--repeat",type=int,choices=(1,2,3))
    args=parser.parse_args(); directory=args.output_dir.resolve()
    if args.mode=="preregister":
        preregister(directory,args.baseline);return
    if args.mode=="trial":
        engine.execute_trial(directory,args.case_id,args.policy,args.repeat);return
    manifest=json.loads((directory/"manifest.json").read_text(encoding="utf-8"));engine.check_pin(manifest)
    for cid in CASE_IDS:
        for repeat in range(1,4):
            for policy in reversed(ARMS) if repeat==2 else ARMS:
                workspace=directory/cid/f"{policy}-{repeat}"
                result=workspace.parent/f"{workspace.name}-result.json"
                if workspace.exists():
                    if result.exists():continue
                    raise ValueError(f"incomplete trial requires audit: {workspace}")
                with (workspace.parent/f"{workspace.name}.log").open("w",encoding="utf-8") as log:
                    completed=subprocess.run([sys.executable,"-X","utf8",str(Path(__file__).resolve()),"trial",
                        "--output-dir",str(directory),"--case-id",cid,"--policy",policy,"--repeat",str(repeat)],
                        cwd=engine.ROOT,stdout=log,stderr=subprocess.STDOUT)
                print("finished",cid,policy,repeat,"exit",completed.returncode,flush=True)
                if completed.returncode:raise RuntimeError("trial harness failed; inspect log")


if __name__=="__main__":main()
