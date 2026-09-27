"""Compare paired target-localizer runs against a declared expected source span."""

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


def _overlaps(item, expected):
    try:
        return (str(item.get("path", "")).replace("\\", "/").casefold()
                == expected["path"].casefold()
                and int(item["start_line"]) <= expected["end_line"]
                and int(item["end_line"]) >= expected["start_line"])
    except (KeyError, TypeError, ValueError):
        return False


def summarize(run, expected):
    locator = (run.get("target_locator_runs") or [{}])[0]
    candidates = locator.get("candidates") or []
    reads = [item for item in run.get("worker_read_spans", [])
             if item.get("task_id") == "EXEC-001"]
    progress = (run.get("worker_progress_runs") or [{}])[0]
    grounding = (run.get("mutation_grounding_runs") or [{}])[0]
    mutation = progress.get("first_legal_mutation")
    first_change_step = mutation.get("tool_step") if mutation else None
    post_change_checks = [item for item in progress.get("events", [])
                          if first_change_step is not None
                          and item.get("tool_step", 0) > first_change_step
                          and item.get("tool") in {
                              "run_file", "run_command", "verify_web_app"}]
    blocker = run.get("first_blocker") or {}
    relevant = [item for item in reads if _overlaps(item, expected)]
    return {
        "policy": run.get("target_locator_policy", "current"),
        "worker_started": _event(run, "FIRST_WORKER_STARTED") is not None,
        "candidate_count": len(candidates),
        "true_target_top1": bool(candidates and _overlaps(candidates[0], expected)),
        "true_target_top3": any(_overlaps(item, expected) for item in candidates[:3]),
        "candidate_spans": [f"{item['candidate_id']} {item['path']}:{item['start_line']}-{item['end_line']}"
                            for item in candidates],
        "first_relevant_bounded_read_step": min(
            (item["tool_step"] for item in relevant), default=None),
        "irrelevant_bounded_reads": sum(not _overlaps(item, expected) for item in reads),
        "bounded_read_spans": [f"{item['path']}:{item['start_line']}-{item['end_line']}"
                               for item in reads],
        "mutation_attempts": grounding.get("mutation_attempts", 0),
        "grounded_mutation_attempts": grounding.get("grounded_mutation_attempts", 0),
        "grounded_attempt_percent": round(
            100 * grounding.get("grounded_mutation_attempts", 0)
            / grounding.get("mutation_attempts", 1), 1
        ) if grounding.get("mutation_attempts") else None,
        "first_legal_file_change_step": mutation.get("tool_step") if mutation else None,
        "budget_remaining_at_first_change": mutation.get("remaining_budget") if mutation else None,
        "verification_tool_calls_after_change": len(post_change_checks),
        "verification_attempted_after_change": bool(post_change_checks),
        "verified_child_commit": _event(run, "CHILD_VERIFIED") is not None,
        "root_verified": _event(run, "ROOT_VERIFIED") is not None,
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions",
            "dnt_execution_violations")),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
    }


def report(current, directed, expected):
    if (current.get("target_locator_policy", "current") != "current"
            or directed.get("target_locator_policy") != "evidence_directed"):
        raise ValueError("runs must be current then evidence_directed")
    for field in ("experiment_case_id", "planning_route", "model", "source_sha256",
                  "worker_progress_source_sha256",
                  "mutation_grounding_source_sha256", "target_locator_source_sha256",
                  "experiment_subject_fingerprint", "mission_advice_policy",
                  "worker_progress_policy", "mutation_grounding_policy"):
        if not current.get(field) or current.get(field) != directed.get(field):
            raise ValueError(f"unpaired runs: {field} differs")
    if (current["worker_progress_policy"] != "progress_constrained"
            or current["mutation_grounding_policy"] != "evidence_grounded"):
        raise ValueError("Experiment 5 requires progress and grounding in both runs")
    approvals = [run.get("plan_approval") or {} for run in (current, directed)]
    if any(item.get("approval_status") != "APPROVED" for item in approvals):
        raise ValueError("both runs require approved plans")
    if not approvals[0].get("plan_hash") or approvals[0]["plan_hash"] != approvals[1].get("plan_hash"):
        raise ValueError("approved plan hashes differ")
    if any(run.get("project_mode") != "EXISTING_PROJECT" for run in (current, directed)):
        raise ValueError("Experiment 5 requires an existing project")
    return {
        "case_id": current["experiment_case_id"],
        "expected_target": expected,
        "approved_plan_hash": approvals[0]["plan_hash"],
        "runs": {"current": summarize(current, expected),
                 "evidence_directed": summarize(directed, expected)},
    }


def format_markdown(result):
    current, directed = (result["runs"][key] for key in ("current", "evidence_directed"))
    def display(value):
        if value is True:
            return "نعم"
        if value is False:
            return "لا"
        if isinstance(value, list):
            return ", ".join(value) or "—"
        return "—" if value is None else str(value)
    rows = (
        ("candidate_spans", "المرشحون بالترتيب"),
        ("true_target_top1", "الهدف الحقيقي في Top-1"),
        ("true_target_top3", "الهدف الحقيقي في Top-3"),
        ("first_relevant_bounded_read_step", "أول قراءة محدودة للموضع الصحيح"),
        ("irrelevant_bounded_reads", "قراءات محدودة غير مرتبطة"),
        ("bounded_read_spans", "المواضع المقروءة"),
        ("mutation_attempts", "محاولات التعديل"),
        ("grounded_mutation_attempts", "محاولات تعديل مربوطة بالنص"),
        ("grounded_attempt_percent", "نسبة المحاولات المربوطة بالنص"),
        ("first_legal_file_change_step", "أول تغيير فعلي قانوني"),
        ("budget_remaining_at_first_change", "الميزانية المتبقية عند التغيير"),
        ("verification_tool_calls_after_change", "أدوات تحقق بعد التغيير"),
        ("verification_attempted_after_change", "بدأ التحقق بعد التغيير"),
        ("verified_child_commit", "Child متحقق وتعديل مثبت"),
        ("root_verified", "Root متحقق"),
        ("scope_violations", "خرق النطاق"),
        ("preservation_violations", "خرق preservation"),
        ("first_blocker_stage", "مرحلة أول توقف"),
        ("first_blocker_reason", "سبب أول توقف"),
    )
    expected = result["expected_target"]
    lines = [f"# Experiment 5 — {result['case_id']}", "",
             f"الهدف المقاس: `{expected['path']}:{expected['start_line']}-{expected['end_line']}`؛ "
             f"الخطة المعتمدة: `{result['approved_plan_hash']}`", "",
             "| المقياس | current | evidence_directed |", "|---|---:|---:|"]
    lines.extend(f"| {label} | {display(current[key])} | {display(directed[key])} |"
                 for key, label in rows)
    lines += ["", "التغيير الفعلي ونجاح التحقق مرحلتان منفصلتان. حالة واحدة لا تمثل نسبة نجاح عامة."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current")
    parser.add_argument("evidence_directed")
    parser.add_argument("--expected-path", required=True)
    parser.add_argument("--expected-start", type=int, required=True)
    parser.add_argument("--expected-end", type=int, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    expected = {"path": args.expected_path, "start_line": args.expected_start,
                "end_line": args.expected_end}
    result = report(load_run(args.current), load_run(args.evidence_directed), expected)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(format_markdown(result), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
