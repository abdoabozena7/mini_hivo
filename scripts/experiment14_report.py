"""Audit strict aggregation separately from the unchanged final receipt gate."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.experiment14_run import ARMS, CASE_IDS, engine
from scripts.experiment12_report import audit_trial, load, rate, summarize, pct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("suite", "probe", "handoffs", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    manifest = load(args.suite / "manifest.json")
    engine.check_pin(manifest)
    trials = [audit_trial(args.suite, c, p, r) for c in manifest["cases"] for p in ARMS for r in range(1,4)]
    if not all(t["completed"] for t in trials):
        raise RuntimeError("All 18 frozen-version trials must complete before reporting")
    summary = {p:summarize([t for t in trials if t["policy"] == p]) for p in ARMS}
    for p in ARMS:
        passed = [t for t in trials if t["policy"] == p and t["verification_pass"]]
        summary[p]["all_pass_receipt_rejection_rate"] = rate(sum(not t["valid_receipt"] for t in passed), len(passed))
    by_case = {c:{p:summarize([t for t in trials if t["policy"] == p and t["case_id"] == c]) for p in ARMS} for c in CASE_IDS}
    rows = load(args.probe)["outcomes"]
    protocol = {}
    for p in ("current", *ARMS):
        rr = [r for r in rows if r["policy"] == p]
        pos = [r for r in rr if r["expected_compatible"]]
        neg = [r for r in rr if not r["expected_compatible"]]
        protocol[p] = {"positive_aggregation_rate":rate(sum(r["aggregation_accepted"] for r in pos),len(pos)),
            "positive_receipt_rate":rate(sum(r["valid_receipt"] for r in pos),len(pos)),
            "aggregation_false_accept_rate":rate(sum(r["aggregation_false_accept"] for r in neg),len(neg)),
            "final_false_accept_rate":rate(sum(r["false_accept"] for r in neg),len(neg))}
    strict = {(r["case_id"],r["scenario"]):r for r in rows if r["policy"] == "strict"}
    preservation = {}
    for p in ("current", "monotonic"):
        gold = [r for r in rows if r["policy"] == p and r["expected_compatible"] and r["valid_receipt"]]
        preservation[p] = rate(sum(strict[(r["case_id"],r["scenario"])]["aggregation_accepted"]
            and strict[(r["case_id"],r["scenario"])]["valid_receipt"] for r in gold),len(gold))
    handoffs = load(args.handoffs)["rows"]
    paired = {c:{p:rate(sum(next(a for a in r["arms"] if a["policy"] == p)["child_verified"] is True
        for r in handoffs if r["eligible"] and r["case_id"] == c),
        sum(r["eligible"] and r["case_id"] == c for r in handoffs)) for p in ARMS} for c in CASE_IDS}
    same_inputs = all(len({a["input_hash"] for a in r["arms"]}) == 1 for r in handoffs if r["eligible"])
    expected_scope = all(sum(summary[p]["safety_counters"].values()) == 0 and summary[p]["test_file_mutations"] == 0 for p in ARMS)
    positive_preserved = all(v["numerator"] == v["denominator"] for v in preservation.values())
    same_state_preserved = all(paired[c]["strict"]["numerator"] >= paired[c]["monotonic"]["numerator"] for c in CASE_IDS)
    fresh_root_preserved = all(by_case[c]["strict"]["root_verified_rate"]["numerator"] >= by_case[c]["monotonic"]["root_verified_rate"]["numerator"] for c in CASE_IDS)
    confirmed = (positive_preserved and same_state_preserved and fresh_root_preserved and same_inputs and expected_scope
        and protocol["strict"]["aggregation_false_accept_rate"]["numerator"] == 0
        and protocol["strict"]["final_false_accept_rate"]["numerator"] == 0)
    data = {"experiment":14,"all_completed":True,"model":manifest["model"],"worker_budget":manifest["worker_budget"],
        "fresh_trials":trials,"fresh_summary":summary,"by_case":by_case,"protocol_summary":protocol,
        "correct_evidence_preserved":preservation,"paired_handoffs":paired,"same_input_hashes":same_inputs,
        "fixed_component_pins_valid":True,"final_receipt_gate_changed":False,"default_changed":False,
        "hypothesis_confirmed_on_tested_sample":confirmed,"fresh_root_rate_not_lower_by_case":fresh_root_preserved,
        "paired_child_rate_not_lower_by_case":same_state_preserved,"protocol_outcomes":rows,
        "upstream_exclusions":["timer_pause","python_clamp"],
        "development_revision":"suite-v1 interrupted during implementation after skipped-browser empty artifact regression was found in paired Node replay. suite-v2 is the complete frozen-version comparison; pilot retained separately, not mixed into v2 rates.",
        "evidence_paths":{"suite":str(args.suite.resolve()),"probe":str(args.probe.resolve()),"handoffs":str(args.handoffs.resolve())}}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    engine.save(args.output_dir / "experiment14-results.json",data)
    lines = ["# Experiment 14 — Strict Aggregation Compatibility", "",
        "3 مهام × 3 محاولات جديدة × سياستين = 18 محاولة. نفس gemma4:e4b و28 خطوة وعقود Experiment 13.", "",
        "المتغير الوحيد: aggregation matching. بوابة final receipt والـWorker والـgrounding والـVerifier والـintegration ثابتة. default ما زال current.", "",
        "## الأدلة: أول طبقة مقابل آخر طبقة", "",
        "| المقياس | monotonic | strict |", "|---|---:|---:|"]
    for title,key in (("False aggregation accepts","aggregation_false_accept_rate"),("Final false accepts","final_false_accept_rate"),
                      ("Positive evidence accepted","positive_receipt_rate")):
        lines.append(f"| {title} | {pct(protocol['monotonic'][key])} | {pct(protocol['strict'][key])} |")
    lines += ["",f"الأدلة الصحيحة القديمة محفوظة: current **{pct(preservation['current'])}**، monotonic **{pct(preservation['monotonic'])}**.","",
        "UNKNOWN لا يساوي MATCH. Browser يحتاج كل assertions المطلوبة منفذة على نفس surface؛ نجاح تحميل الصفحة وحده لا يكفي. Node يقبل نتيجة تنفيذ فعلية لـsuite المحددة في route المعتمدة، التي تربط obligation بالـbehavior. لا يعتمد على كلمة tests أو path داخل stdout.","",
        "الـprovenance موثقة ومقيدة بقنوات التنفيذ المعروفة؛ unit_test_result alias غير المدعومة تظل مرفوضة كما قبل التجربة. ليست regression جديدة.","",
        "هذه حالات protocol معلنة وليست تقديرًا لمعدل الأخطاء الميداني. الاختبارات البديلة للـbehavior والـtarget منفذة بالفعل؛ تغيير provenance/requirement جزء معلن من إعادة تشغيل البروتوكول.","",
        "## نفس post-child state", "", "| المهمة | monotonic child | strict child |", "|---|---:|---:|"]
    for c in CASE_IDS:lines.append(f"| {c} | {pct(paired[c]['monotonic'])} | {pct(paired[c]['strict'])} |")
    lines += ["",f"نفس input hashes: **{same_inputs}**. كل Worker مكتملة من Exp13 monotonic أُعيدت دون اختيار حسب PASS، مع Browser جديد وتأكيد Node suite فعلية. هذا القياس لا يدّعي Worker أو Root جديدين.","",
        "## المحاولات الجديدة", "", "| المقياس | monotonic | strict |", "|---|---:|---:|"]
    for title,key in (("Valid receipt / actual PASS","valid_receipt_rate"),("Child verified","child_verified_rate"),
        ("Root verified","root_verified_rate"),("Receipt rejection / actual PASS","all_pass_receipt_rejection_rate"),
        ("Runs using Repairer","repairer_run_rate")):
        lines.append(f"| {title} | {pct(summary['monotonic'][key])} | {pct(summary['strict'][key])} |")
    for title,key in (("Model calls / Root success","model_calls_per_root_verified"),("Seconds / Root success","seconds_per_root_verified")):
        lines.append(f"| {title} | {summary['monotonic'][key]} | {summary['strict'][key]} |")
    lines += ["", "| المهمة | monotonic Root | strict Root |", "|---|---:|---:|"]
    for c in CASE_IDS:lines.append(f"| {c} | {pct(by_case[c]['monotonic']['root_verified_rate'])} | {pct(by_case[c]['strict']['root_verified_rate'])} |")
    lines += ["", "تكاليف كل المحاولات الفاشلة داخلة في calls/time لكل Root ناجحة. التخطيط وhost preflight خارج حدود القياس. نجاح Root يتطلب parent verification جديدة تغطي requirement؛ child evidence لم تُستخدم كبديل.","",
        f"Scope/preservation: monotonic={sum(summary['monotonic']['safety_counters'].values())}, strict={sum(summary['strict']['safety_counters'].values())}. Read-only tests changed: monotonic={summary['monotonic']['test_file_mutations']}, strict={summary['strict']['test_file_mutations']}.","",
        "## القرار وحدود القياس", "", f"Hypothesis confirmed on tested sample: **{confirmed}**.", "",
        "strict تظل experimental اختيارية. العينة صغيرة؛ لا تعميم على wrappers أو verifier protocols غير المدعومة أو على Timer/Python المستبعدتين upstream. mutation grounding لم يتغير، وأي فشل قبل verification يظل داخل denominator.", "",
        "نسخة التطوير v1 كشفت artifact فارغة من browser غير applicable عند Node؛ أُصلح توليدها في aggregation فقط. v1 محفوظة، والمحاولات التجريبية الموقوفة لا تُخلط مع الـ18 محاولة المكتملة بعد تثبيت v2.","",
        f"- [Results]({(args.output_dir/'experiment14-results.json').resolve().as_posix()}).",
        f"- [Preregistered suite]({(args.suite/'manifest.json').resolve().as_posix()}).",
        f"- [Protocol evidence]({args.probe.resolve().as_posix()}).",
        f"- [Paired handoffs]({args.handoffs.resolve().as_posix()}).", ""]
    (args.output_dir / "experiment14-report.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"confirmed":confirmed,"protocol":protocol,"preserved":preservation,"paired":paired,"fresh":summary},ensure_ascii=False,indent=2))


if __name__ == "__main__":main()
