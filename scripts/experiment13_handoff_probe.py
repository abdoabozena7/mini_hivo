"""Re-evaluate every eligible current handoff from Exp12, without PASS filtering."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts.experiment12_handoff_probe import replay, save
from scripts.experiment12_fixtures import get_case
from scripts.experiment13_run import CASE_IDS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    mini._load_optional_imports();mini.ensure_dependencies(auto_install=False)
    rows=[]
    for cid in CASE_IDS:
        case=get_case(cid)
        for repeat in range(1,4):
            path=args.baseline/cid/f"current-{repeat}-EXEC-001-handoff.json"
            if not path.exists():
                rows.append({"case_id":cid,"repeat":repeat,"eligible":False,"reason":"NO_COMPLETED_WORKER_HANDOFF"});continue
            snapshot=json.loads(path.read_text(encoding="utf-8"))
            if snapshot["builder"]["status"]!="done":
                rows.append({"case_id":cid,"repeat":repeat,"eligible":False,"reason":"WORKER_NOT_COMPLETED"});continue
            row={"case_id":cid,"repeat":repeat,"eligible":True,"source":str(path.resolve()),"arms":[]}
            folder=args.output_dir/f"{cid}-{repeat}";folder.mkdir()
            for policy in ("current","compatible","monotonic"):
                arm=replay(snapshot,folder/policy,policy)
                # Browser is already executed freshly by the original handoff.
                # Unit outputs in the handoff are captured evidence; independently
                # execute the real suite again against the reconstructed source.
                if case.get("test_target"):
                    native=mini.run_command(case["integration_target"])
                    arm["fresh_unit_confirmation"]={"output":native,"passed":"[exit_code=0]" in native and "unique behavior tests: 4 passed" in native}
                    if not arm["fresh_unit_confirmation"]["passed"]:raise RuntimeError("frozen unit candidate failed native verification")
                save(folder/(policy+".json"),arm)
                row["arms"].append({k:arm.get(k) for k in ("policy","input_hash","eligible","child_verified","blocker",
                    "commit_status","model_calls","repairer_calls","root_verification_executed","receipt_validation","fresh_unit_confirmation")})
                print(cid,repeat,policy,arm.get("child_verified"),flush=True)
            rows.append(row)
    save(args.output_dir/"comparison.json",{"experiment":13,"scope":"exact captured child handoffs + native verification confirmation; no Root success claim",
        "selection":"Every terminally completed current Worker, no selection on verification PASS", "rows":rows})


if __name__=="__main__":main()
