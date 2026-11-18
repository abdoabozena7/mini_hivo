"""Separate declared grounding challenge results from unforced fresh Workers."""

import argparse
import difflib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from scripts.experiment15_run import ARMS, CASE_IDS, engine
from scripts.experiment12_report import audit_trial, load, pct, rate, summarize


def true_region(case,text):
    lines=text.splitlines()
    if case['case_id']=='node_unique':
        first=next((i for i,l in enumerate(lines) if re.search(r'function\s+uniqueValues\s*\(',l)),None)
        last=next((i for i,l in enumerate(lines) if 'module.exports' in l),len(lines))-1
    else:
        first=next((i for i,l in enumerate(lines) if re.search(r"document\.addEventListener\s*\(\s*['\"]keydown",l)),None)
        last=next((i for i in range(first or 0,len(lines)) if '});' in lines[i]),len(lines)-1)
    return (first,last) if first is not None else None


def region_changed(case,item):
    if item.get('before') is None or item.get('after') is None:return False
    span=true_region(case,item['before'])
    if span is None:return False
    for tag,first,last,_a,_b in difflib.SequenceMatcher(None,item['before'].splitlines(),item['after'].splitlines()).get_opcodes():
        if tag=='equal':continue
        if first==last:
            if span[0]<=first<=span[1]+1:return True
        elif first<=span[1] and last-1>=span[0]:return True
    return False


def audit(suite,case,policy,repeat):
    expected={**engine.POLICIES,'mutation_grounding_policy':policy}
    result=audit_trial(suite,case,policy,repeat,expected_semantic_policy='strict',expected_policies=expected)
    if not result['completed']:return result
    workspace=suite/case['case_id']/f'{policy}-{repeat}'
    run=json.loads((workspace/'.agent_experiment.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    grounds=[g for g in run.get('mutation_grounding_runs',[]) if g.get('policy')==policy]
    attempts=[a for g in grounds for a in g.get('attempts',[])]
    applied=[a for a in attempts if a['applied']]
    observations=load(workspace.parent/f'{workspace.name}-observations.json')
    mutations=[o for o in observations if o['kind']=='mutation_tool' and o['role']=='Builder'
        and o['before_hash']!=o['after_hash'] and not mini.tool_result_failed(o['result'])]
    if len(applied)!=len(mutations):raise RuntimeError('Grounding summary differs from actual file writes')
    bindings=[]
    for a,o in zip(applied,mutations):
        valid=(a['grounded'] is True and a['target']==case['source'].casefold()
               and a['source_before_hash']==o['before_hash'])
        if not valid:raise RuntimeError('Applied mutation lacks fresh authorized source binding')
        bindings.append({'tool_step':a['tool_step'],'request_hash':a['request_hash'],
            'source_before_hash':o['before_hash'],'source_after_hash':o['after_hash'],
            'authorized_lines':a['source_lines'],'binding_valid':valid,'true_region_changed':region_changed(case,o)})
    first=run.get('first_legal_mutation')
    if first and first['model_round']+first['remaining_budget']!=28:raise RuntimeError('Actual Worker budget is not 28')
    result.update(semantic_evidence_policy=run['semantic_evidence_policy'],grounding_policy=run['mutation_grounding_policy'],
        first_legal_mutation=first,first_legal_mutation_reached=bool(first),
        first_mutation_on_true_region=bool(bindings and bindings[0]['true_region_changed']),
        any_mutation_on_true_region=any(b['true_region_changed'] for b in bindings),
        first_legal_mutation_step=first['tool_step'] if first else None,
        first_legal_remaining_budget=first['remaining_budget'] if first else None,
        grounding_terminal_failure=any(g.get('terminal_reason') for g in grounds),
        full_refresh_exercised=any(o['tool']=='read_file' for g in grounds for o in g.get('refresh_observations',[])),
        full_refresh_followed_by_legal_mutation=any(o['tool']=='read_file' for g in grounds for o in g.get('refresh_observations',[]))
            and any(a['applied'] and a.get('refresh_state_before')=='ready' for a in attempts),
        rejected_mutation_attempts=sum(a['rejected'] for a in attempts),
        rejection_reasons=[a.get('evidence_reason') for a in attempts if a['rejected']],
        verified_after_mutation=bool(first) and result['verification_pass'],
        source_bindings=bindings,grounding=grounds)
    return result


def fresh_summary(rows):
    s=summarize(rows)
    n=len(rows);mutated=[r for r in rows if r['first_legal_mutation_reached']]
    s.update(first_legal_mutation_rate=rate(len(mutated),n),
        grounding_failure_rate=rate(sum(r['grounding_terminal_failure'] for r in rows),n),
        first_mutation_on_true_region_rate=rate(sum(r['first_mutation_on_true_region'] for r in mutated),len(mutated)),
        any_mutation_on_true_region_rate=rate(sum(r['any_mutation_on_true_region'] for r in mutated),len(mutated)),
        verification_after_mutation_rate=rate(sum(r['verified_after_mutation'] for r in mutated),len(mutated)),
        rejected_mutation_attempts=sum(r['rejected_mutation_attempts'] for r in rows),
        full_refresh_exercised_rate=rate(sum(r['full_refresh_exercised'] for r in rows),n),
        full_refresh_followed_by_legal_mutation_rate=rate(sum(r['full_refresh_followed_by_legal_mutation'] for r in rows),n),
        first_legal_mutation_steps=[r['first_legal_mutation_step'] for r in mutated],
        all_applied_bindings_valid=all(b['binding_valid'] for r in rows for b in r['source_bindings']))
    return s


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('suite','probe','output-dir'):parser.add_argument('--'+n,type=Path,required=True)
    args=parser.parse_args();manifest=load(args.suite/'manifest.json');engine.check_pin(manifest)
    trials=[audit(args.suite,c,p,r) for c in manifest['cases'] for p in ARMS for r in range(1,4)]
    if not all(r['completed'] for r in trials):raise RuntimeError('Incomplete fresh batch; no final verdict')
    summary={p:fresh_summary([r for r in trials if r['policy']==p]) for p in ARMS}
    by_case={c:{p:fresh_summary([r for r in trials if r['case_id']==c and r['policy']==p]) for p in ARMS} for c in CASE_IDS}
    probe=load(args.probe);rows=probe['outcomes'];protocol={}
    for p in ARMS:
        rr=[r for r in rows if r['policy']==p];pos=[r for r in rr if r['expected_compatible']];neg=[r for r in rr if not r['expected_compatible']]
        protocol[p]={'legal_mutation_rate':rate(sum(r['applied'] for r in pos),len(pos)),
            'false_authorization_rate':rate(sum(r['authorized'] for r in neg),len(neg)),
            'true_region_rate':rate(sum(r['mutation_on_true_region'] for r in pos),sum(r['applied'] for r in pos)),
            'native_verification_rate':rate(sum(bool(r['verification'] and r['verification']['native_pass']) for r in pos),sum(r['applied'] for r in pos)),
            'scope_violations':sum(r['scope_violations'] for r in rr),
            'read_only_tests_changed':sum(r['read_only_tests_changed'] for r in rr)}
    same=all(len({r['input_hash'] for r in rows if r['case_id']==c and r['scenario']==s})==1
             for c in CASE_IDS for s in {r['scenario'] for r in rows})
    safe=all(sum(summary[p]['safety_counters'].values())==0 and summary[p]['test_file_mutations']==0 for p in ARMS)
    root_preserved=all(by_case[c][ARMS[1]]['root_verified_rate']['numerator']>=by_case[c][ARMS[0]]['root_verified_rate']['numerator'] for c in CASE_IDS)
    proof_fix=(same and protocol[ARMS[1]]['legal_mutation_rate']['numerator']==9
               and protocol[ARMS[1]]['false_authorization_rate']['numerator']==0
               and all(protocol[p]['scope_violations']==0 and protocol[p]['read_only_tests_changed']==0 for p in ARMS))
    fresh_gain=(summary[ARMS[1]]['grounding_failure_rate']['numerator']<summary[ARMS[0]]['grounding_failure_rate']['numerator'])
    decision=('binding fix confirmed; fresh grounding failure reduction observed' if fresh_gain and safe and root_preserved and proof_fix
              else 'binding fix confirmed in declared challenges; no fresh grounding failure reduction demonstrated' if safe and root_preserved and proof_fix
              else 'mixed result; inspect fresh failures and safety before adopting')
    data={'experiment':15,'all_completed':True,'model':manifest['model'],'worker_budget':28,
        'fixed_semantic_evidence_policy':'strict','fixed_component_pins_valid':True,
        'decision':decision,'protocol_binding_fix_confirmed':proof_fix,'fresh_failure_reduction_observed':fresh_gain,
        'root_success_not_lower_by_case':root_preserved,'fresh_trials':trials,'fresh_summary':summary,'by_case':by_case,
        'protocol_summary':protocol,'same_protocol_input_hashes':same,'historical_failure':probe['historical_failure'],
        'exact_historical_mutation_replay_claimed':False,'default_changed':False,
        'limits':'Constructed challenges have known reference edits and enforced refresh state. They measure authorization, not Worker success. Full reads larger than 80 lines remain ineligible refreshes. Only three frozen tasks; planning excluded.',
        'evidence_paths':{'suite':str(args.suite.resolve()),'probe':str(args.probe.resolve())}}
    args.output_dir.mkdir(parents=True,exist_ok=True);engine.save(args.output_dir/'experiment15-results.json',data)
    a,b=ARMS
    lines=['# Experiment 15 — Mutation Grounding / Evidence-to-Edit Binding','',
        '3 مهام × 3 fresh runs × سياستين = 18 محاولة. gemma4:e4b، 28 خطوة، strict ثابتة. نفس عقود وبذور Experiment 14.','',
        'التغيير الوحيد: full read مطابقة للملف الحالي إذا كان ≤80 سطرًا تحتسب bounded refresh. لا fuzzy replacement، ولا زيادة retries أو budget. Refresh لا تفتح full-file write أو multiple replacements.','',
        '## تصحيح تشخيص الحالة الأصلية','',
        'Exp13 arena_arrow monotonic-3 نفّذت تعديلين قانونيين؛ أول تعديل عند الخطوة 3، ثم فشلت عند تعديل لاحق بالخطوة 9. full reread لم تسجل refresh، لأنها كانت تقبل read_file_range فقط.','',
        'الـold/new الكاملة لآخر محاولة مرفوضة غير محفوظة. لا ندّعي إعادة حرفية أو إثبات إصلاح الـpatch الأصلي. فحص البروتوكول يعيد نوع حالة الربط بأدلة وطلبات مرجعية معلنة.','',
        '## فحص الربط المعزول','', '| المقياس | evidence_grounded | evidence_bound |','|---|---:|---:|']
    for title,key in (('Legal mutation / positive challenges','legal_mutation_rate'),('False authorizations','false_authorization_rate'),
        ('Correct source region / applied','true_region_rate'),('Native verification / applied','native_verification_rate')):
        lines.append(f"| {title} | {pct(protocol[a][key])} | {pct(protocol[b][key])} |")
    lines+=['',f'نفس input hashes: **{same}**. الإيجابيات تشمل missing/stale anchor مع full read صغيرة وrange control؛ السلبيات تشمل fake/stale reads وold غير موجود وduplicate anchor وwrong region وlarge full read وforeign target وfull rewrite أثناء retry.','',
        'Scope counters تخص ملفات المشروع وread-only tests؛ controller logs/databases هي instrumentation. النسخة الأولى من حساب البروتوكول ضمّت logs ضمن scope/hash؛ binding-v2 تصحح المقام، دون أي تغيير في الإنتاج.','',
        'هذه حالات مصطنعة معلنة بلا model calls أو Worker/Root successes. كل تعديل مرجعي مقبول نفذته file tool الفعلية وتبعه browser/Node verification فعلية.','',
        '## الـWorker في المحاولات الجديدة','', '| المقياس | evidence_grounded | evidence_bound |','|---|---:|---:|']
    for title,key in (('Reached first legal mutation','first_legal_mutation_rate'),('Grounding terminal failure','grounding_failure_rate'),
        ('First mutation on true target region','first_mutation_on_true_region_rate'),('Any mutation on true target region','any_mutation_on_true_region_rate'),
        ('Verification PASS after mutation','verification_after_mutation_rate'),('Child verified','child_verified_rate'),
        ('Root verified','root_verified_rate'),('Runs using Repairer','repairer_run_rate')):
        lines.append(f"| {title} | {pct(summary[a][key])} | {pct(summary[b][key])} |")
    lines.append(f"| New full-refresh path exercised | {pct(summary[a]['full_refresh_exercised_rate'])} | {pct(summary[b]['full_refresh_exercised_rate'])} |")
    lines+=['',f"Steps to first legal mutation: grounded={summary[a]['first_legal_mutation_steps']}, bound={summary[b]['first_legal_mutation_steps']}.",'',
        '| المهمة | grounded Root | bound Root |','|---|---:|---:|']
    for c in CASE_IDS:lines.append(f"| {c} | {pct(by_case[c][a]['root_verified_rate'])} | {pct(by_case[c][b]['root_verified_rate'])} |")
    lines+=['','True region oracle في القياس فقط: keydown handler للألعاب، وuniqueValues body لـNode. ليست prompt أو authorization إضافية. الـdiff الفعلي يجب أن يمس المنطقة، وhash كل mutation المطبقة يُطابق fresh binding.','',
        f"Scope/preservation: grounded={sum(summary[a]['safety_counters'].values())}, bound={sum(summary[b]['safety_counters'].values())}. Read-only tests changed: grounded={summary[a]['test_file_mutations']}, bound={summary[b]['test_file_mutations']}.",'',
        'كل المحاولات تدخل المقام. أي توقف قبل verification باقٍ في Root denominator. Parent verification جديدة واجبة؛ child proof ليست بديلًا. Worker strategies/budgets/verifier/evidence/integration ثابتة بـsource/AST pins.','',
        '## القرار','',decision,'',
        'إصلاح binding المثبت في الحالات المعلنة منفصل عن تحسن الـfresh Worker؛ لا تُحوّل 3/9→9/9 في البروتوكول إلى نسبة نجاح ميدانية. evidence_bound اختيارية experimental؛ default mutation policy=current، وstrict لا تتغير.','',
        'العينة ثلاثة مشاريع صغيرة. لا تعميم على ملفات كبيرة أو upstream tasks مستبعدة. الاختبارات المركزة وregression: 145 ناجحة.','',
        f"- [Results]({(args.output_dir/'experiment15-results.json').resolve().as_posix()}).",
        f"- [Preregistered suite]({(args.suite/'manifest.json').resolve().as_posix()}).",
        f"- [Binding protocol]({args.probe.resolve().as_posix()}).",'']
    (args.output_dir/'experiment15-report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'decision':decision,'protocol':protocol,'fresh':summary,'roots_preserved':root_preserved},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
