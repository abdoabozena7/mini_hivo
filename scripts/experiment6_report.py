"""Compare paired Experiment 6 runs with the same approved R-key plan."""

import argparse
import json
import sqlite3
from pathlib import Path


def load(workspace):
    path = Path(workspace) / ".agent_experiment.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected one run in {path}; found {len(lines)}")
    return json.loads(lines[0])


def tool_evidence(workspace):
    path = Path(workspace) / ".hivo" / "memory.sqlite3"
    if not path.is_file():
        return []
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "select role,tool,target,status,content from events "
            "where tool in ('run_command','run_file','verify_web_app') order by id"
        ).fetchall()
    output = []
    for role, tool, target, status, content in rows:
        item = {"role": role, "tool": tool, "target": target, "status": status}
        if tool == "run_command":
            item["result"] = content[:500]
        else:
            try:
                result = json.loads(content)
            except ValueError:
                result = {}
            item["passed"] = result.get("passed")
            item["environment_error"] = result.get("environment_error")
            item["failure_codes"] = [failure.get("code") for failure in result.get("failures", [])
                                     if isinstance(failure, dict)]
            item["interaction_checks"] = len(result.get("interaction_checks", []))
        output.append(item)
    return output


def summary(run, workspace):
    progress = (run.get("worker_progress_runs") or [{}])[0]
    mutation = progress.get("first_legal_mutation") or {}
    events = run.get("experiment_events") or []
    evidence = tool_evidence(workspace)
    manifests = []
    for path in run.get("candidate_patch_artifacts", []) or []:
        file = Path(path)
        if file.is_file():
            manifests.append(json.loads(file.read_text(encoding="utf-8")))
    blocker = run.get("first_blocker") or {}
    return {
        "verification_environment_policy": run.get("verification_environment_policy"),
        "worker_started": any(item.get("kind") == "FIRST_WORKER_STARTED" for item in events),
        "first_legal_mutation_step": mutation.get("tool_step"),
        "npm_preflights": [item for item in run.get("verification_command_preflights", [])
                           if item.get("command") == "npm test"],
        "npm_results": [item for item in run.get("verification_command_results", [])
                        if item.get("command") == "npm test"],
        "browser_results": run.get("verification_browser_results", []),
        "verification_resolution": run.get("verification_resolution_events", []),
        "tool_evidence": evidence,
        "repairer_calls": run.get("repairer_calls", 0),
        "candidate_patches": manifests,
        "child_verified": any(item.get("kind") == "CHILD_VERIFIED" for item in events),
        "root_verified": any(item.get("kind") == "ROOT_VERIFIED" for item in events),
        "first_blocker": blocker,
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions", "dnt_execution_violations")),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
        "status": run.get("status"),
    }


def compare(current, resolved, current_workspace, resolved_workspace):
    if (current.get("verification_environment_policy") != "current"
            or resolved.get("verification_environment_policy") != "resolved"):
        raise ValueError("runs must be current then resolved")
    fields = ("experiment_case_id", "planning_route", "model", "source_sha256",
              "worker_progress_source_sha256", "mutation_grounding_source_sha256",
              "target_locator_source_sha256", "experiment_subject_fingerprint",
              "mission_advice_policy", "worker_progress_policy", "mutation_grounding_policy",
              "target_locator_policy")
    for field in fields:
        if not current.get(field) or current[field] != resolved.get(field):
            raise ValueError(f"unpaired runs: {field} differs")
    approvals = [run.get("plan_approval") or {} for run in (current, resolved)]
    if any(item.get("approval_status") != "APPROVED" for item in approvals):
        raise ValueError("both runs require approval")
    if not approvals[0].get("plan_hash") or approvals[0]["plan_hash"] != approvals[1]["plan_hash"]:
        raise ValueError("approved plan hashes differ")
    if current.get("project_mode") != "EXISTING_PROJECT" or resolved.get("project_mode") != "EXISTING_PROJECT":
        raise ValueError("both runs require EXISTING_PROJECT")
    return {"case_id": current["experiment_case_id"],
            "approved_plan_hash": approvals[0]["plan_hash"],
            "source_sha256": current["experiment_subject_fingerprint"],
            "runs": {"current": summary(current, current_workspace),
                     "resolved": summary(resolved, resolved_workspace)}}


def markdown(result):
    a, b = (result["runs"][key] for key in ("current", "resolved"))
    def show(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "نعم" if value else "لا"
        return str(value).replace("|", "\\|")
    rows = [
        ("worker_started", "Worker بدأ"),
        ("first_legal_mutation_step", "أول تعديل قانوني: خطوة"),
        ("repairer_calls", "استدعاءات Repairer"),
        ("child_verified", "Child متحقق"),
        ("root_verified", "Root متحقق"),
        ("scope_violations", "خرق النطاق"),
        ("preservation_violations", "خرق preservation"),
        ("status", "حالة التشغيل"),
    ]
    lines = [f"# Experiment 6 — {result['case_id']}", "",
             f"الخطة المعتمدة: `{result['approved_plan_hash']}`", "",
             "| المقياس | current | resolved |", "|---|---:|---:|"]
    lines.extend(f"| {label} | {show(a[key])} | {show(b[key])} |" for key, label in rows)
    for key, run in (("current", a), ("resolved", b)):
        lines += ["", f"## {key}", "",
                  f"- أول توقف: `{show(run['first_blocker'].get('stage'))}` / "
                  f"`{show(run['first_blocker'].get('reason'))}`",
                  f"- npm preflight: `{show(run['npm_preflights'])}`",
                  f"- browser verifier: `{show(run['browser_results'])}`",
                  f"- تصنيف التحقق: `{show(run['verification_resolution'])}`",
                  f"- candidate patch محفوظ: `{show(bool(run['candidate_patches']))}`"]
        for item in run["tool_evidence"]:
            if item["tool"] in {"run_command", "verify_web_app"}:
                lines.append("- " + json.dumps(item, ensure_ascii=False))
    if result.get("npm_probe"):
        lines += ["", "## Deterministic npm probe", ""]
        for item in result["npm_probe"]:
            lines.append("- " + json.dumps(item, ensure_ascii=False))
    lines += ["", "فشل أو تعذر التحقق لا يعني صحة الـpatch؛ candidate المحفوظ غير متحقق منه."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("resolved", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(load(args.current), load(args.resolved), args.current, args.resolved)
    probe = args.output.parent / "npm_probe.json"
    if probe.is_file():
        result["npm_probe"] = json.loads(probe.read_text(encoding="utf-8"))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown(result), encoding="utf-8")
    print(args.markdown_output)


if __name__ == "__main__":
    main()
