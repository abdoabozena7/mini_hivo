"""Report fresh runs, exact-state preservation and final identity negatives."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.experiment13_run import ARMS, CASE_IDS, engine
from scripts.experiment12_report import audit_trial, load, rate, summarize, pct


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite",type=Path,required=True)
    parser.add_argument("--probe",type=Path,required=True)
    parser.add_argument("--handoffs",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--allow-incomplete",action="store_true")
    args=parser.parse_args();manifest=load(args.suite/"manifest.json");engine.check_pin(manifest)
    trials=[audit_trial(args.suite,c,p,r) for c in manifest["cases"] for p in ARMS for r in range(1,4)]
    if not all(t["completed"] for t in trials) and not args.allow_incomplete:raise RuntimeError("fresh batch incomplete")
    summary={p:summarize([t for t in trials if t["policy"]==p]) for p in ARMS}
    by_case={cid:{p:summarize([t for t in trials if t["policy"]==p and t["case_id"]==cid]) for p in ARMS} for cid in CASE_IDS}
    outcomes=load(args.probe)["outcomes"]
    protocol={}
    for p in ("current","compatible","monotonic"):
        rows=[r for r in outcomes if r["policy"]==p];pos=[r for r in rows if r["expected_compatible"]];neg=[r for r in rows if not r["expected_compatible"]]
        protocol[p]={"valid_positive_rate":rate(sum(r["valid_receipt"] for r in pos),len(pos)),
            "false_accept_rate":rate(sum(r["false_accept"] for r in neg),len(neg)),
            "aggregation_false_accept_rate":rate(sum(r["aggregation_false_accept"] for r in neg),len(neg))}
    gold_current=[r for r in outcomes if r["policy"]=="current" and r["expected_compatible"] and r["valid_receipt"]]
    new={(r["case_id"],r["scenario"]):r for r in outcomes if r["policy"]=="monotonic"}
    preserved=rate(sum(new[(r["case_id"],r["scenario"])]["valid_receipt"] for r in gold_current),len(gold_current))
    handoffs=load(args.handoffs)
    paired={}
    for cid in CASE_IDS:
        rows=[r for r in handoffs["rows"] if r["case_id"]==cid and r["eligible"]]
        paired[cid]={p:rate(sum(next(a for a in r["arms"] if a["policy"]==p)["child_verified"] is True for r in rows),len(rows))
                     for p in ("current","compatible","monotonic")}
    same_inputs=all(len({a["input_hash"] for a in r["arms"]})==1 for r in handoffs["rows"] if r["eligible"])
    data={"experiment":13,"all_completed":all(t["completed"] for t in trials),"model":manifest["model"],
        "worker_budget":28,"fresh_trials":trials,"fresh_summary":summary,"by_case":by_case,
        "gold_current_preservation":preserved,"protocol_summary":protocol,"paired_handoffs":paired,
        "same_input_hashes":same_inputs,"pins_valid":True,"default_changed":False,"aggregator_followup":14,
        "scope":"Frozen approved contracts -> original Worker/verification/receipt -> fresh Parent. Upstream planning excluded.",
        "evidence_paths":{"suite":str(args.suite.resolve()),"probe":str(args.probe.resolve()),"handoffs":str(args.handoffs.resolve())}}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"experiment13-results.json").write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Experiment 13 — Monotonic Semantic Compatibility","",
        "3 مهام مؤهلة × 3 fresh runs × سياستين = 18 محاولة. gemma4:e4b، 28 خطوة، ونفس عقود Experiment 12.","",
        "المقارنة تبدأ من approved contract ثابتة؛ تكاليف التخطيط وpreflight مستبعدة. Timer وPython خارج حكم التجربة.","",
        "## النتائج الطازجة","","| المقياس | current | monotonic |","|---|---:|---:|"]
    for title,key in (("Valid receipt / actual PASS","valid_receipt_rate"),("Child verified","child_verified_rate"),
                      ("Root verified","root_verified_rate"),("False rejection / actual PASS","false_rejection_rate"),
                      ("Runs using Repairer","repairer_run_rate")):
        lines.append(f"| {title} | {pct(summary['current'][key])} | {pct(summary['monotonic'][key])} |")
    for title,key in (("Model calls / Root success","model_calls_per_root_verified"),("Seconds / Root success","seconds_per_root_verified")):
        lines.append(f"| {title} | {summary['current'][key]} | {summary['monotonic'][key]} |")
    lines += ["","التكلفة تشمل المحاولات الفاشلة أيضًا، ثم تُقسم على Root successes.","",
        "| المهمة | current Root | monotonic Root |","|---|---:|---:|"]
    for cid in CASE_IDS:lines.append(f"| {cid} | {pct(by_case[cid]['current']['root_verified_rate'])} | {pct(by_case[cid]['monotonic']['root_verified_rate'])} |")
    lines += ["","## الحفاظ على الأدلة الصحيحة","",
        f"Gold-correct current evidence preserved: **{pct(preserved)}**. Different evidence final false accepts: **{pct(protocol['monotonic']['false_accept_rate'])}**.","",
        "منهج الاختيار: كل handoff من current انتهى Worker فيها، بدون اختيار بناءً على PASS. نفس input hash لكل السياسات، ثم تحقق Browser جديد أو إعادة تأكيد فعلية لاختبارات Node.","",
        "| نفس post-child state | current receipt | compatible receipt | monotonic receipt |","|---|---:|---:|---:|"]
    for cid in CASE_IDS:lines.append(f"| {cid} | {pct(paired[cid]['current'])} | {pct(paired[cid]['compatible'])} | {pct(paired[cid]['monotonic'])} |")
    lines += ["","هذا القياس لا يتضمن Worker جديدًا أو Root success؛ هو إثبات سببي للحفاظ على نفس الأدلة، منفصل عن الـ18 fresh runs.","",
        "## معنى monotonic في هذه التجربة","",
        "الحفاظ يخص الأدلة الصحيحة التي قبلها current. current نفسه قبل 9/12 أدلة خاطئة في مجموعة الهوية السلبية؛ لذلك الحفاظ الحرفي على كل قبول سابق يتعارض مع شرط صفر false accepts.","",
        "Matching يبدأ بـcurrent. النجاح الصحيح يظل مقبولًا، وغياب semantic inventory يصبح UNKNOWN، ولا يخلق سبب رفض مستقل. إن فشل matching فقط، يُجرب semantic rescue عند وجود metadata قابلة للمقارنة.","",
        "الـreceipt النهائية ترفض الهوية المخالفة المعلنة: requirement أو target أو behavior مختلف. المخزون المتاح يُعاد ربطه بالعقد ومتطلبات المهمة وhash المصدر الحالي. authority-bound/direct routes وscope/freshness/closure gates باقية.","",
        f"الـaggregator ما زال يقبل **{pct(protocol['monotonic']['aggregation_false_accept_rate'])}** من الحالات السلبية قبل رفض receipt. matching الخاص به لم يُشدَّد؛ Experiment 14 مؤجل.","",
        "Positive protocol fixtures تشمل provenance aliases مصطنعة معلنة، والبدائل Browser behaviors/targets منفذة فعليًا. ليست نسبة أخطاء ميدانية.","",
        "## القرار والملفات","",
        f"All 18 complete: **{data['all_completed']}**. Same frozen inputs: **{same_inputs}**. Production component pins: **True**.","",
        f"Scope/preservation counters: current={sum(summary['current']['safety_counters'].values())}, monotonic={sum(summary['monotonic']['safety_counters'].values())}. Read-only tests changed: current={summary['current']['test_file_mutations']}, monotonic={summary['monotonic']['test_file_mutations']}.","",
        "`monotonic` اختيار experimental جديد؛ default ما زال current، وcompatible القديمة باقية للمقارنة. لا يُدَّعى تعميم على مهام upstream مستبعدة أو على مشاريع لم تُختبر.","",
        f"- [Machine-readable results]({(args.output_dir/'experiment13-results.json').resolve().as_posix()}).",
        f"- [Preregistered manifest]({(args.suite/'manifest.json').resolve().as_posix()}).",
        f"- [Negative/positive evidence records]({args.probe.resolve().as_posix()}).",
        f"- [Exact handoff replays]({args.handoffs.resolve().as_posix()}).",""]
    (args.output_dir/"experiment13-report.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"fresh":summary,"gold_preservation":preserved,"protocol":protocol,"paired":paired},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
