"""Run one approved Experiment 3 case against an isolated workspace."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--route", choices=(
        "current_recursive", "decomposition_first_recursive"), required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--approved-hash", required=True)
    parser.add_argument("--approved-path", action="append", required=True)
    parser.add_argument("--worker-progress-policy", choices=(
        "current", "progress_constrained"), required=True)
    parser.add_argument("--mutation-grounding-policy", choices=(
        "current", "evidence_grounded"), default="current")
    parser.add_argument("--target-locator-policy", choices=(
        "current", "evidence_directed"), default="current")
    parser.add_argument("--verification-environment-policy", choices=(
        "current", "resolved"), default="current")
    parser.add_argument("--verification-surface-policy", choices=(
        "current", "discovery"), default="current")
    parser.add_argument("--child-receipt-policy", choices=(
        "current", "atomic_verified"), default="current")
    parser.add_argument("--mission-advice-policy", choices=(
        "strict", "contract_fallback"), default="contract_fallback")
    args = parser.parse_args()

    mini.configure_console_streams()
    mini._load_optional_imports()
    if not mini.ensure_dependencies(auto_install=False):
        raise SystemExit("dependencies unavailable")
    mini.WORKSPACE = mini.get_workspace(args.workspace)
    mini.HOST_PREFLIGHT_RESULT = mini.run_host_preflight(
        mini.WORKSPACE, mini.MODEL, mini.OLLAMA_BASE_URL)
    print("preflight:", mini.HOST_PREFLIGHT_RESULT.get("passed"), flush=True)
    if not mini.HOST_PREFLIGHT_RESULT.get("passed"):
        raise SystemExit("preflight failed")
    mini.select_local_ollama_model()

    def select_only_approved_plan(plan, **_kwargs):
        actual = plan.get("plan_hash")
        paths = sorted({path for node in plan.get("approved_change_nodes", [])
                        for path in node.get("target_paths", [])})
        print("proposed_plan_hash:", actual, "target_paths:", paths, flush=True)
        if actual != args.approved_hash or paths != sorted(args.approved_path):
            print("approved plan did not reproduce exactly; stopping before Worker", flush=True)
            return None
        print("approved plan reproduced exactly; applying user approval", flush=True)
        return 0

    result, _ = mini.run_recursive_request(
        args.prompt_file.read_text(encoding="utf-8"), mini.load_memory(),
        interactive=True, terminal_available=True,
        planning_route=args.route, experiment_case_id=args.case_id,
        mission_advice_policy=args.mission_advice_policy,
        worker_progress_policy=args.worker_progress_policy,
        mutation_grounding_policy=args.mutation_grounding_policy,
        target_locator_policy=args.target_locator_policy,
        verification_environment_policy=args.verification_environment_policy,
        verification_surface_policy=args.verification_surface_policy,
        child_receipt_policy=args.child_receipt_policy,
        plan_approval_selector=select_only_approved_plan,
    )
    print("FINAL_STATUS:", result.get("status"), flush=True)
    print("FINAL_SUMMARY:", result.get("summary"), flush=True)


if __name__ == "__main__":
    main()
