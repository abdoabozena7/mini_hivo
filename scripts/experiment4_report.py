"""Compare paired current and evidence-grounded mutation runs."""

from __future__ import annotations

import argparse
import json
import re
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
    grounding = (run.get("mutation_grounding_runs") or [{}])[0]
    progress = (run.get("worker_progress_runs") or [{}])[0]
    attempts = grounding.get("attempts") or []
    first_applied = progress.get("first_legal_mutation")
    first_step = first_applied.get("tool_step") if first_applied else None
    later_verification_tools = [item for item in progress.get("events", [])
                                if first_step is not None
                                and item.get("tool_step", 0) > first_step
                                and item.get("tool") in {
                                    "run_file", "run_command", "verify_web_app"}]
    blocker = run.get("first_blocker") or {}
    read_ranges = []
    for receipt in (run.get("child_receipts") or {}).values():
        for item in receipt.get("verification_evidence", []) or []:
            if item.get("tool") != "read_file_range":
                continue
            match = re.search(r"\[lines (\d+)-(\d+) of", str(item.get("result", "")))
            if match:
                read_ranges.append(f"{item.get('target')}:{match.group(1)}-{match.group(2)}")
    return {
        "policy": run.get("mutation_grounding_policy", "current"),
        "status": run.get("status"),
        "worker_started": _event(run, "FIRST_WORKER_STARTED") is not None,
        "first_mutation_attempt_step": grounding.get("first_mutation_attempt_step"),
        "mutation_attempts": grounding.get("mutation_attempts", 0),
        "grounded_mutation_attempts": grounding.get("grounded_mutation_attempts", 0),
        "grounded_attempt_percent": round(
            100 * grounding.get("grounded_mutation_attempts", 0) / len(attempts), 1
        ) if attempts else None,
        "rejected_mutation_attempts": grounding.get("rejected_mutation_attempts", 0),
        "bounded_refreshes": grounding.get("bounded_refreshes", 0),
        "read_ranges": read_ranges,
        "first_applied_legal_mutation_step": first_step,
        "budget_remaining_at_first_applied_mutation": (
            first_applied.get("remaining_budget") if first_applied else None),
        "verification_attempted_after_mutation": bool(later_verification_tools),
        "verified_child_commit": _event(run, "CHILD_VERIFIED") is not None,
        "root_verified": _event(run, "ROOT_VERIFIED") is not None,
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "tool_steps_observed": progress.get("tool_steps"),
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions",
            "dnt_execution_violations")),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
    }


def report(current, grounded):
    if (current.get("mutation_grounding_policy", "current") != "current"
            or grounded.get("mutation_grounding_policy") != "evidence_grounded"):
        raise ValueError("runs must be current then evidence_grounded")
    for field in ("experiment_case_id", "planning_route", "model", "source_sha256",
                  "mutation_grounding_source_sha256",
                  "experiment_subject_fingerprint", "mission_advice_policy",
                  "worker_progress_policy"):
        if not current.get(field) or current.get(field) != grounded.get(field):
            raise ValueError(f"unpaired runs: {field} differs")
    if current["worker_progress_policy"] != "progress_constrained":
        raise ValueError("Experiment 4 requires progress_constrained in both runs")
    approvals = [run.get("plan_approval") or {} for run in (current, grounded)]
    if any(item.get("approval_status") != "APPROVED" for item in approvals):
        raise ValueError("both runs require approved plans")
    if not approvals[0].get("plan_hash") or approvals[0]["plan_hash"] != approvals[1].get("plan_hash"):
        raise ValueError("approved plan hashes differ")
    if any(run.get("project_mode") != "EXISTING_PROJECT" for run in (current, grounded)):
        raise ValueError("Experiment 4 requires an existing project")
    return {
        "case_id": current["experiment_case_id"],
        "route": current["planning_route"],
        "approved_plan_hash": approvals[0]["plan_hash"],
        "runs": {"current": summarize(current), "evidence_grounded": summarize(grounded)},
    }


def format_markdown(result):
    current, grounded = (result["runs"][key] for key in ("current", "evidence_grounded"))
    def display(value):
        if value is True:
            return "نعم"
        if value is False:
            return "لا"
        if isinstance(value, list):
            return ", ".join(value) or "—"
        return "—" if value is None else str(value)
    rows = (
        ("worker_started", "وصل للـWorker"),
        ("first_mutation_attempt_step", "خطوة أول محاولة تعديل"),
        ("mutation_attempts", "محاولات التعديل"),
        ("grounded_mutation_attempts", "محاولات مربوطة بنص مقروء"),
        ("grounded_attempt_percent", "نسبة المحاولات المربوطة بنص مقروء"),
        ("rejected_mutation_attempts", "محاولات مرفوضة"),
        ("bounded_refreshes", "إعادة قراءة محدودة"),
        ("read_ranges", "نطاقات القراءة المحدودة"),
        ("first_applied_legal_mutation_step", "خطوة أول تغيير فعلي للملف"),
        ("budget_remaining_at_first_applied_mutation", "الميزانية المتبقية عند أول تغيير"),
        ("verification_attempted_after_mutation", "محاولة تحقق بعد التغيير"),
        ("verified_child_commit", "Child متحقق وتعديل مثبت"),
        ("root_verified", "Root متحقق"),
        ("tool_steps_observed", "خطوات أدوات مرصودة"),
        ("scope_violations", "خرق النطاق"),
        ("preservation_violations", "خرق preservation"),
        ("first_blocker_stage", "مرحلة أول توقف"),
        ("first_blocker_reason", "سبب أول توقف"),
    )
    lines = [f"# Experiment 4 — {result['case_id']}", "",
             f"الخطة المعتمدة في المسارين: `{result['approved_plan_hash']}`", "",
             "| المقياس | current | evidence_grounded |", "|---|---:|---:|"]
    lines.extend(f"| {label} | {display(current[key])} | {display(grounded[key])} |"
                 for key, label in rows)
    lines += ["", "التغيير الفعلي يعني تغيّر bytes الملف داخل محاولة الـWorker؛ اعتماد الـChild بعد التحقق معروض بصورة منفصلة.",
              "حالة واحدة لا تمثل نسبة نجاح عامة."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current")
    parser.add_argument("evidence_grounded")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    result = report(load_run(args.current), load_run(args.evidence_grounded))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(format_markdown(result), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
