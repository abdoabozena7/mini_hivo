"""Compare paired strict and contract-fallback Mission Compiler runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


POLICIES = ("strict", "contract_fallback")


def load_run(source):
    path = Path(source)
    if path.is_dir():
        path /= ".agent_experiment.jsonl"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected exactly one run in {path}; found {len(lines)}")
    return json.loads(lines[0])


def has_event(run, kind):
    return any(item.get("kind") == kind for item in run.get("experiment_events", []))


def summarize(run):
    blocker = run.get("first_blocker") or {}
    return {
        "policy": run.get("mission_advice_policy"),
        "status": run.get("status"),
        "advice_rejected": int(run.get("mission_advice_rejected", 0) or 0),
        "fallback_used": int(run.get("mission_advice_fallbacks", 0) or 0),
        "fallback_failed": int(run.get("mission_advice_fallback_failures", 0) or 0),
        "worker_started": has_event(run, "FIRST_WORKER_STARTED"),
        "verified_child": has_event(run, "CHILD_VERIFIED"),
        "root_verified": has_event(run, "ROOT_VERIFIED"),
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "scope_violations": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "unapproved_scope_expansions",
            "dnt_execution_violations",
        )),
        "preservation_violations": int(run.get("impact_preservation_violations", 0) or 0),
        "model_calls": int(run.get("model_calls", 0) or 0),
        "elapsed_seconds": run.get("elapsed_seconds"),
    }


def report(strict, fallback):
    if strict.get("mission_advice_policy") != POLICIES[0] or fallback.get(
        "mission_advice_policy"
    ) != POLICIES[1]:
        raise ValueError("runs must be strict then contract_fallback")
    paired_fields = (
        "experiment_case_id", "planning_route", "model", "source_sha256",
        "experiment_subject_fingerprint",
    )
    for field in paired_fields:
        if not strict.get(field) or strict.get(field) != fallback.get(field):
            raise ValueError(f"unpaired runs: {field} differs")
    if any(run.get("project_mode") != "EXISTING_PROJECT" for run in (strict, fallback)):
        raise ValueError("Experiment 2 requires an existing project")
    approvals = [run.get("plan_approval") or {} for run in (strict, fallback)]
    if any(item.get("approval_status") != "APPROVED" for item in approvals):
        raise ValueError("both runs require approved plans")
    if not approvals[0].get("plan_hash") or approvals[0]["plan_hash"] != approvals[1].get(
        "plan_hash"
    ):
        raise ValueError("approved plan hashes differ")
    return {
        "case_id": strict["experiment_case_id"],
        "planning_route": strict["planning_route"],
        "approved_plan_hash": approvals[0]["plan_hash"],
        "runs": {"strict": summarize(strict), "contract_fallback": summarize(fallback)},
    }


def format_markdown(result):
    strict = result["runs"]["strict"]
    fallback = result["runs"]["contract_fallback"]
    metrics = (
        ("advice_rejected", "Advice مرفوضة"),
        ("fallback_used", "Mission fallback مستخدمة"),
        ("worker_started", "وصل لأول Worker"),
        ("verified_child", "Child متحقق"),
        ("root_verified", "Root متحقق"),
        ("scope_violations", "خرق للنطاق"),
        ("preservation_violations", "خرق للـpreservation"),
    )
    lines = [
        f"# Experiment 2 — {result['case_id']}", "",
        f"الخطة المعتمدة في المسارين: `{result['approved_plan_hash']}`", "",
        "| المقياس | strict | contract_fallback |", "|---|---:|---:|",
    ]
    for key, label in metrics:
        def display(value):
            return "نعم" if value is True else "لا" if value is False else str(value)
        lines.append(f"| {label} | {display(strict[key])} | {display(fallback[key])} |")
    lines += [
        "", "| النتيجة | strict | contract_fallback |", "|---|---|---|",
        f"| أول blocker | `{strict['first_blocker_stage']}` / "
        f"`{strict['first_blocker_reason']}` | `{fallback['first_blocker_stage']}` / "
        f"`{fallback['first_blocker_reason']}` |",
        f"| استدعاءات النموذج | {strict['model_calls']} | {fallback['model_calls']} |",
        f"| الزمن بالثواني | {strict['elapsed_seconds']} | {fallback['elapsed_seconds']} |",
        "", "حالة واحدة لا تكفي لتقدير نسبة نجاح عامة؛ الجدول يقارن انتقال البوابة لنفس المهمة.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strict")
    parser.add_argument("fallback")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    result = report(load_run(args.strict), load_run(args.fallback))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(format_markdown(result), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
