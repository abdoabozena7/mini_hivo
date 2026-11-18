"""Compare paired current and progress-constrained Worker runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_run(source):
    path = Path(source)
    if path.is_dir():
        path /= ".agent_experiment.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected exactly one run in {path}; found {len(lines)}")
    return json.loads(lines[0])


def _event(run, kind):
    return next((item for item in run.get("experiment_events", [])
                 if item.get("kind") == kind), None)


def summarize(run):
    attempts = run.get("worker_progress_runs") or []
    progress = attempts[0] if attempts else {}
    blocker = run.get("first_blocker") or {}
    mutation = progress.get("first_legal_mutation")
    mutation_attempts = [item for item in progress.get("events", [])
                         if item.get("tool") in {"write_file", "edit_file", "edit_file_range"}]
    budget = 28
    return {
        "policy": run.get("worker_progress_policy"),
        "status": run.get("status"),
        "worker_started": _event(run, "FIRST_WORKER_STARTED") is not None,
        "first_legal_mutation": mutation,
        "mutation_occurred": mutation is not None,
        "steps_to_first_legal_mutation": mutation.get("tool_step") if mutation else None,
        "steps_to_first_mutation_attempt": (
            mutation_attempts[0]["tool_step"] if mutation_attempts else None),
        "mutation_attempts": len(mutation_attempts),
        "rejected_mutation_attempts": sum(
            item.get("novelty") == "rejected" for item in mutation_attempts),
        "budget_remaining_at_first_mutation": mutation.get("remaining_budget") if mutation else None,
        "tool_steps_observed": progress.get("tool_steps"),
        "tool_budget_used_percent": round(
            100 * progress["tool_steps"] / budget, 1) if progress.get("tool_steps") is not None else None,
        "model_calls": run.get("model_calls"),
        "pre_mutation_read_steps": progress.get("pre_mutation_read_steps"),
        "unique_evidence": progress.get("unique_evidence"),
        "repeated_inspections": progress.get("repeated_inspections"),
        "repeated_gate_checks": progress.get("repeated_gate_checks"),
        "same_file_revisits_without_new_info": progress.get("same_file_revisits_without_new_info"),
        "invalid_rejected_tool_calls": progress.get("invalid_rejected_tool_calls"),
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "verified_child": _event(run, "CHILD_VERIFIED") is not None,
        "root_verified": _event(run, "ROOT_VERIFIED") is not None,
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions",
            "dnt_execution_violations")),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
        "budget_usage_percent_before_mutation": round(
            100 * mutation["model_round"] / budget, 1) if mutation else None,
        "budget": budget,
        "attempts": len(attempts),
    }


def report(current, constrained):
    if (current.get("worker_progress_policy", "current") != "current"
            or constrained.get("worker_progress_policy") != "progress_constrained"):
        raise ValueError("runs must be current then progress_constrained")
    for field in ("experiment_case_id", "planning_route", "model", "source_sha256",
                  "experiment_subject_fingerprint", "mission_advice_policy"):
        if not current.get(field) or current.get(field) != constrained.get(field):
            raise ValueError(f"unpaired runs: {field} differs")
    approvals = [run.get("plan_approval") or {} for run in (current, constrained)]
    if any(item.get("approval_status") != "APPROVED" for item in approvals):
        raise ValueError("both runs require approved plans")
    if not approvals[0].get("plan_hash") or approvals[0]["plan_hash"] != approvals[1].get("plan_hash"):
        raise ValueError("approved plan hashes differ")
    if any(run.get("project_mode") != "EXISTING_PROJECT" for run in (current, constrained)):
        raise ValueError("Experiment 3 requires an existing project")
    return {
        "case_id": current["experiment_case_id"],
        "route": current["planning_route"],
        "mission_advice_policy": current["mission_advice_policy"],
        "approved_plan_hash": approvals[0]["plan_hash"],
        "runs": {"current": summarize(current), "progress_constrained": summarize(constrained)},
    }


def format_markdown(result):
    current, constrained = (result["runs"][key] for key in ("current", "progress_constrained"))
    def value(item):
        if item is True:
            return "نعم"
        if item is False:
            return "لا"
        return "—" if item is None else str(item)
    rows = (
        ("worker_started", "وصل للـWorker"),
        ("mutation_occurred", "حدث تعديل قانوني"),
        ("steps_to_first_legal_mutation", "خطوات الأدوات حتى أول تعديل"),
        ("steps_to_first_mutation_attempt", "خطوات الأدوات حتى أول محاولة تعديل"),
        ("mutation_attempts", "محاولات تعديل"),
        ("rejected_mutation_attempts", "محاولات تعديل مرفوضة"),
        ("budget_remaining_at_first_mutation", "الميزانية الباقية عند أول تعديل"),
        ("budget_usage_percent_before_mutation", "نسبة الميزانية المستهلكة قبل أول تعديل"),
        ("tool_budget_used_percent", "نسبة خطوات الميزانية المستخدمة عند التوقف"),
        ("pre_mutation_read_steps", "خطوات القراءة قبل أول تعديل"),
        ("unique_evidence", "أدلة جديدة"),
        ("repeated_inspections", "فحوص ملفات متكررة"),
        ("repeated_gate_checks", "فحوص سياق متكررة"),
        ("same_file_revisits_without_new_info", "عودة لنفس الملف دون معلومة جديدة"),
        ("invalid_rejected_tool_calls", "استدعاءات مرفوضة أو غير صالحة"),
        ("tool_steps_observed", "خطوات أدوات مرصودة"),
        ("verified_child", "Child متحقق"),
        ("root_verified", "Root متحقق"),
        ("scope_violations", "خرق النطاق"),
        ("preservation_violations", "خرق preservation"),
        ("first_blocker_stage", "مرحلة أول توقف"),
        ("first_blocker_reason", "سبب أول توقف"),
    )
    lines = [f"# Experiment 3 — {result['case_id']}", "",
             f"الخطة المعتمدة في المسارين: `{result['approved_plan_hash']}`", "",
             "| المقياس | current | progress_constrained |", "|---|---:|---:|"]
    lines.extend(f"| {label} | {value(current[key])} | {value(constrained[key])} |"
                 for key, label in rows)
    lines += ["", "النسب الخاصة بالميزانية تخص هذا التشغيل فقط. حالة واحدة لا تمثل نسبة نجاح عامة."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current")
    parser.add_argument("progress_constrained")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    result = report(load_run(args.current), load_run(args.progress_constrained))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(format_markdown(result), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
