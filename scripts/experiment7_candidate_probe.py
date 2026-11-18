"""Run the same browser requirement against one frozen candidate workspace."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini
from hivo import verification_environment as verification_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--original-source", type=Path, required=True)
    parser.add_argument("--surface-policy", choices=("current", "discovery"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise SystemExit("dependencies unavailable")
    mini.WORKSPACE = mini.get_workspace(str(args.workspace))
    mini.reset_run("experiment-7-candidate-probe")
    mini.RUN["verification_environment_policy"] = "resolved"
    mini.RUN["verification_surface_policy"] = args.surface_policy
    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    profile = mini.infer_web_profile("game " + prompt, {"requirements": [prompt]})
    result = mini.verify_browser_application(
        "index.html", "experiment-7", profile=profile,
        evidence={"verification_requirement": prompt},
    )
    content = (mini.WORKSPACE / "index.html").read_bytes()
    original = args.original_source.read_bytes()
    transaction = {"files": {str((mini.WORKSPACE / "index.html").resolve()):
                             {"existed": True, "content": original}}}
    output = {
        "surface_policy": args.surface_policy,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "requirement": prompt,
        "profile": profile.__dict__,
        "classification": verification_env.classify_browser_result(
            result, transaction=transaction, workspace=mini.WORKSPACE),
        "result": result,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result.get("passed"),
                      "classification": output["classification"],
                      "surface": (result.get("verification_surface") or {}).get("surface_type"),
                      "behavior_test_executed": result.get("behavior_test_executed"),
                      "checks": [(item.get("name"), item.get("passed"))
                                 for item in result.get("interaction_checks", [])],
                      "failure_codes": [item.get("code") for item in result.get("failures", [])]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
