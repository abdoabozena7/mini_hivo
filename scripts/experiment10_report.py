"""Summarize stability at each unchanged child verification boundary."""

import argparse
import json
from pathlib import Path


def rate(count, total):
    return f"{count}/{total} ({100 * count / total:.0f}%)" if total else "N/A"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--supplemental-comparison", type=Path, action="append", default=[])
    parser.add_argument("--capture-run-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    captured_run = None
    data = json.loads(args.comparison.read_text(encoding="utf-8"))
    runs = data["replays"]
    total = len(runs)
    def count(kind):
        return sum(any(e["kind"] == kind for e in r["events"]) for r in runs)

    rows = [("Target resolved", count("VERIFICATION_TARGET_RESOLVED")),
            ("Verification applicable", count("VERIFICATION_APPLICABLE")),
            ("Existing Worker context sufficient", count("VERIFICATION_CONTEXT_SUFFICIENT")),
            ("Verification started", count("VERIFICATION_STARTED")),
            ("Fresh behavioral PASS", sum((r.get("browser") or {}).get("passed") is True
                                         and (r.get("browser") or {}).get("behavior_test_executed") is True for r in runs)),
            ("Evidence gate accepted", sum(r["evidence_gate_passed"] for r in runs))]
    first = runs[0]
    audit = next((a for a in first.get("evidence_match_audit", []) if a["kind"] == "BROWSER"), {})
    checks = [c for r in runs for c in (r.get("browser") or {}).get("interaction_checks", [])]
    mode = data["capture_mode"]
    lines = ["# Experiment 10 — Child Verification Handoff Stability", "",
             f"حالة واحدة ثابتة، و{total} إعادات لحدّ التحقق، من غير إعادة Worker أو Falsifier أو Repairer.",
             f"Input mode: `{mode}`.",
             ("مدخلات gate محفوظة مباشرة بعد Falsifier وقبل Browser كما هي، دون اختصار إضافي أثناء التسجيل."
              if mode == "full_pre_browser_handoff" else "الحالات مأخوذة من الأرشيف؛ نتائج الأدوات محفوظة مختصرة."),
             "دي تجربة تشخيصية؛ إصدار receipt والـcommit والـParent integration لم يُعاد تشغيلهم.", "",
             "| المرحلة | الوصول |", "|---|---:|"]
    lines += [f"| {label} | {rate(value, total)} |" for label, value in rows]
    lines += ["", f"- Behavior checks: {rate(sum(c.get('passed') is True for c in checks), len(checks))}",
              f"- Same source/input hashes: {data['same_source_and_input']}",
              f"- Same gate decision: {data['decision_consistent']}",
              f"- First blocker: `{first['first_blocker']}`",
              f"- Browser related tools: `{audit.get('related_tools')}`; matched tools: `{audit.get('matched_tools')}`",
              f"- Separate fresh Browser PASS: {audit.get('separate_browser_pass')}",
              f"- Model / Repairer calls: {sum(r['model_calls'] for r in runs)} / {sum(r['repairer_calls'] for r in runs)}",
              f"- Receipts issued: {sum(r['child_receipts_issued'] for r in runs)}; gate bypasses: {data['gate_bypasses']}",
              f"- Source unchanged: {all(r['source_unchanged'] for r in runs)}", "",
              "## أول سبب في التشغيلين الأصليين", ""]
    for historical in data["historical_audits"]:
        lines += [f"- `{historical['run_id']}`: Browser PASS ثم `{historical['first_required_route_failure'].get('result')}` في evidence aggregation.",
                  f"  - النهاية المعلنة: `{(historical.get('terminal_blocker') or {}).get('reason')}`؛ Repairer started: {historical['repairer_started']}."]
    supplements = [json.loads(p.read_text(encoding="utf-8")) for p in args.supplemental_comparison]
    for supplement in supplements:
        repeats = supplement["replays"]
        lines += ["", "## إعادات الحالة التاريخية المختصرة", "",
                  f"- Input mode: `{supplement['capture_mode']}`; decision consistent: {supplement['decision_consistent']}",
                  f"- Verification started: {rate(sum(r['verification_started'] for r in repeats), len(repeats))}",
                  f"- Evidence gate accepted: {rate(sum(r['evidence_gate_passed'] for r in repeats), len(repeats))}",
                  f"- First blocker: `{repeats[0]['first_blocker']}`",
                  "- نفس bytes للـcandidate، لكن هذه الحالة تستعمل مدخلات أدوات مختصرة من الأرشيف."]
    if args.capture_run_file:
        captured_run = json.loads(args.capture_run_file.read_text(encoding="utf-8").splitlines()[-1])
        lines += ["", "## التشغيل الجديد الذي سجّل الحالة الكاملة", "",
                  f"- ROOT_VERIFIED: {captured_run.get('root_verified')}; status: {captured_run.get('status')}",
                  f"- Valid verified child: {sum(r.get('verified') is True for r in captured_run.get('child_receipts', {}).values())}",
                  f"- Repairer calls: {captured_run.get('repairer_calls', 0)}",
                  f"- Scope / preservation violations: {captured_run.get('mutation_scope_violations', 0)} / {captured_run.get('impact_preservation_violations', 0)}",
                  f"- Plan hash: `{(captured_run.get('plan_approval') or {}).get('plan_hash')}`",
                  "- تشغيل جديد واحد مع تسجيل observational؛ النتيجة لا تعني إن سبب الرفض اتصلح أو إن reliability = 100%."]
    shadowed = all(any(a["kind"] == "BROWSER" and a["related_without_match"] and a["separate_browser_pass"]
                       for a in r.get("evidence_match_audit", []))
                   and (r.get("first_blocker") or {}).get("reason") == "INVALID_RECEIPT" for r in runs)
    lines += ["", "## النتيجة", ""]
    if shadowed:
        lines += ["الـChild المؤهل يصل لبدء التحقق بشكل ثابت. الفشل المشترك يأتي بعد Browser PASS، عند مطابقة أدلة الـBrowser.",
                  "أدلة run_file المرتبطة بنفس target لا تطابق verify_web_app؛ existing aggregator يعطيها أولوية تجعل route = INVALID_RECEIPT.",
                  "NOT_APPLICABLE وCONTEXT_INSUFFICIENT في التشغيلين الأصليين نهايتان لاحقتان لنفس الرفض الأول؛ مش دليل على عدم استقرار applicability أو Worker context."]
    else:
        lines += [("مدخلات الحالة الكاملة اجتازت verification handoff في كل الإعادات."
                   if all(r["evidence_gate_passed"] for r in runs)
                   else f"التشخيص الحالي: `{first['first_blocker']}`؛ راجع gate وevidence_match_audit لكل إعادة.")]
        if all(r["evidence_gate_passed"] for r in runs) and supplements:
            lines += ["الحالة الكاملة تحتوي verify_web_app evidence من الـFalsifier؛ الحالة التاريخية المرفوضة تحتوي run_file لنفس target دون evidence مطابقة لأداة Browser.",
                      "القرار ثابت داخل كل حالة. الاختلاف بين الحالات في protocol/projection للأدلة، ويظهر أولًا في aggregation بعد تنفيذ Browser ناجح."]
    lines += ["لم يتم إصلاح القرار في هذه التجربة. النتيجة تخص حالة واحدة؛ الإعادات لا تقيس end-to-end reliability.", ""]
    args.output.write_text("\n".join(lines), encoding="utf-8")
    report = {"primary": data, "supplemental": supplements}
    if captured_run:
        report["fresh_capture_run"] = {key: captured_run.get(key) for key in (
            "run_id", "root_verified", "status", "repairer_calls", "mutation_scope_violations",
            "impact_preservation_violations", "model", "model_calls", "plan_approval")}
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(args.output.resolve()))


if __name__ == "__main__":
    main()
