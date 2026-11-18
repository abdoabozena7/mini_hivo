"""Summarize paired Experiment 1 runs from subject workspace metrics files."""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


ROUTES = ("current_recursive", "decomposition_first_recursive")
RATE_FIELDS = (
    ("worker_reached", "وصل لأول Worker", "eligible"),
    ("pre_worker_blocked", "اتوقف قبل Worker", "eligible"),
    ("runs_with_verified_child", "تحقق أول child", "eligible"),
    ("root_verified", "تحقق الهدف النهائي", "eligible"),
    ("awaiting_approval", "بانتظار الموافقة", "all"),
    ("unsafe_terminals", "انتهى بخرق أمان", "eligible"),
)


def event(run, kind):
    return next((item for item in run.get("experiment_events", [])
                 if item.get("kind") == kind), None)


def summarize_run(run):
    first_worker = event(run, "FIRST_WORKER_STARTED")
    approval_required = event(run, "APPROVAL_REQUIRED")
    approved = event(run, "APPROVED")
    human_wait = (max(0, approved["elapsed_seconds"] - approval_required["elapsed_seconds"])
                  if approval_required and approved else 0)
    blocker = run.get("first_blocker") or {}
    return {
        "run_id": run.get("run_id"),
        "case_id": run.get("experiment_case_id"),
        "route": run.get("planning_route"),
        "status": run.get("status"),
        "first_blocker_stage": blocker.get("stage"),
        "first_blocker_reason": blocker.get("reason"),
        "first_blocker_detail": blocker.get("detail"),
        "worker_reached": bool(first_worker),
        "awaiting_approval": run.get("status") == "plan_approval_required",
        "approval_rejected": run.get("status") == "plan_rejected",
        "pre_worker_blocked": bool(blocker) and not bool(first_worker),
        "verified_children": sum(item.get("kind") == "CHILD_VERIFIED"
                                 for item in run.get("experiment_events", [])),
        "verified_early_responsibilities": sum(
            item.get("kind") == "EARLY_CHILD_VERIFIED"
            for item in run.get("experiment_events", [])
        ),
        "root_verified": bool(event(run, "ROOT_VERIFIED")),
        "model_calls_before_worker": first_worker.get("model_calls") if first_worker else None,
        "seconds_before_worker_excluding_approval": (
            round(first_worker["elapsed_seconds"] - human_wait, 3) if first_worker else None
        ),
        "total_model_calls": run.get("model_calls", 0),
        "elapsed_seconds": run.get("elapsed_seconds"),
        "safety_blocks": sum(int(run.get(key, 0) or 0) for key in (
            "mutation_scope_violations", "dnt_execution_violations",
            "unapproved_scope_expansions", "precommit_invariant_gate_rejections",
        )),
        "unsafe_terminal": (run.get("execution_graph_execution") or {}).get(
            "lifecycle_terminal_state") in {"UNAUTHORIZED_MUTATION", "DNT_VIOLATION"},
    }


def load_runs(paths):
    runs = []
    for source in paths:
        path = Path(source)
        metric_files = [path / ".agent_experiment.jsonl"] if path.is_dir() else [path]
        for metric_file in metric_files:
            with metric_file.open(encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        run = json.loads(line)
                        if run.get("planning_route") in ROUTES:
                            runs.append(run)
    return runs


def rate(count, total):
    return {"count": count, "total": total,
            "percent": round(100 * count / total, 1) if total else None}


def report(runs):
    grouped = collections.defaultdict(lambda: collections.defaultdict(list))
    for run in runs:
        grouped[run.get("experiment_case_id")][run.get("planning_route")].append(run)
    if not grouped:
        raise ValueError("no recursive Experiment 1 runs found")
    for case_id, routes in grouped.items():
        counts = [len(routes[route]) for route in ROUTES]
        if not case_id or min(counts) == 0 or counts[0] != counts[1]:
            raise ValueError(f"unpaired case {case_id}: route counts {counts}")
        if any(run.get("project_mode") != "EXISTING_PROJECT"
               for items in routes.values() for run in items):
            raise ValueError(f"case {case_id} is not an existing-project task")
        models = {run.get("model") for items in routes.values() for run in items}
        sources = {run.get("source_sha256") for items in routes.values() for run in items}
        subjects = {run.get("experiment_subject_fingerprint")
                    for items in routes.values() for run in items}
        if len(models) != 1 or len(sources) != 1 or len(subjects) != 1:
            raise ValueError(f"case {case_id} used different model, code, or subject snapshots")
    detail = [summarize_run(run) for routes in grouped.values()
              for items in routes.values() for run in items]
    aggregate = {}
    for route in ROUTES:
        items = [item for item in detail if item["route"] == route]
        blockers = collections.Counter(item["first_blocker_stage"] for item in items
                                       if item["first_blocker_stage"])
        aggregate[route] = {
            "runs": len(items),
            "worker_reached": sum(item["worker_reached"] for item in items),
            "awaiting_approval": sum(item["awaiting_approval"] for item in items),
            "approval_rejected": sum(item["approval_rejected"] for item in items),
            "pre_worker_blocked": sum(item["pre_worker_blocked"] for item in items),
            "runs_with_verified_child": sum(item["verified_children"] > 0 for item in items),
            "verified_early_responsibilities": sum(
                item["verified_early_responsibilities"] for item in items
            ),
            "root_verified": sum(item["root_verified"] for item in items),
            "safety_blocks": sum(item["safety_blocks"] for item in items),
            "unsafe_terminals": sum(item["unsafe_terminal"] for item in items),
            "first_blocker_stages": dict(sorted(blockers.items())),
        }
    for route in ROUTES:
        item = aggregate[route]
        item["eligible_runs"] = item["runs"] - item["awaiting_approval"] - item["approval_rejected"]
        item["rates"] = {
            key: rate(item[key], item["eligible_runs"] if denominator == "eligible"
                      else item["runs"])
            for key, _, denominator in RATE_FIELDS
        }
        item["average_model_calls"] = round(
            sum(run["total_model_calls"] for run in detail if run["route"] == route)
            / item["runs"], 2,
        )
        item["average_elapsed_seconds"] = round(
            sum(run["elapsed_seconds"] or 0 for run in detail if run["route"] == route)
            / item["runs"], 2,
        )
    comparison = {}
    for key, _, _ in RATE_FIELDS:
        left = aggregate[ROUTES[0]]["rates"][key]["percent"]
        right = aggregate[ROUTES[1]]["rates"][key]["percent"]
        comparison[key + "_delta_percentage_points"] = (
            round(right - left, 1) if left is not None and right is not None else None
        )
    return {"cases": len(grouped), "aggregate": aggregate,
            "comparison": comparison, "runs": detail}


def format_markdown(result):
    baseline = result["aggregate"][ROUTES[0]]
    experiment = result["aggregate"][ROUTES[1]]
    lines = [
        f"# Experiment 1 — حالات مزدوجة: {result['cases']}",
        "",
        "| المقياس | المسار الحالي | التقسيم المبكر | الفرق |",
        "|---|---:|---:|---:|",
    ]
    for key, label, _ in RATE_FIELDS:
        left = baseline["rates"][key]
        right = experiment["rates"][key]
        delta = result["comparison"][key + "_delta_percentage_points"]
        left_percent = f"{left['percent']:g}%" if left["percent"] is not None else "غير متاح"
        right_percent = f"{right['percent']:g}%" if right["percent"] is not None else "غير متاح"
        delta_text = f"{delta:+g} نقطة مئوية" if delta is not None else "غير متاح"
        lines.append(
            f"| {label} | {left['count']}/{left['total']} ({left_percent}) "
            f"| {right['count']}/{right['total']} ({right_percent}) "
            f"| {delta_text} |"
        )
    lines += [
        "",
        "| التكلفة لكل run | المسار الحالي | التقسيم المبكر |",
        "|---|---:|---:|",
        f"| متوسط استدعاءات النموذج | {baseline['average_model_calls']:g} "
        f"| {experiment['average_model_calls']:g} |",
        f"| متوسط الزمن بالثواني | {baseline['average_elapsed_seconds']:g} "
        f"| {experiment['average_elapsed_seconds']:g} |",
        "",
        "نِسب التنفيذ مقامها الحالات المؤهلة بعد استبعاد انتظار/رفض الموافقة. "
        "نسبة انتظار الموافقة مقامها كل الحالات. النسبة توضّح العينة المقاسة فقط؛ "
        "لا تثبت تحسنًا إحصائيًا.",
        "متوسط التكلفة للملاحظة فقط: المقارنة لا تعني كفاءة أعلى عندما يتوقف "
        "المساران في مراحل مختلفة.",
        "",
        "## أول مرحلة توقف",
        "",
    ]
    for route, name in ((ROUTES[0], "المسار الحالي"), (ROUTES[1], "التقسيم المبكر")):
        blockers = [run for run in result["runs"]
                    if run["route"] == route and run["first_blocker_stage"]]
        if not blockers:
            lines.append(f"- {name}: لا توجد حالة توقف مسجلة.")
        for run in blockers:
            lines.append(
                f"- {name}، `{run['case_id']}`: "
                f"`{run['first_blocker_stage']}` / `{run['first_blocker_reason']}` "
                f"(وصل للـWorker: {'نعم' if run['worker_reached'] else 'لا'})."
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", nargs="+", help="workspace directories or .agent_experiment.jsonl files")
    parser.add_argument("--output", type=Path, help="write the report as JSON")
    parser.add_argument("--markdown-output", type=Path,
                        help="write an Arabic percentage summary as Markdown")
    args = parser.parse_args()
    result = report(load_runs(args.metrics))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(format_markdown(result), encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
