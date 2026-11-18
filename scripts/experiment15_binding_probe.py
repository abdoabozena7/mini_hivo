"""Declared grounding challenges, real file tools and fresh native verification.

These are deterministic protocol inputs, not new Worker or Root successes.
The historical failing call arguments were not saved; no exact replay is claimed.
"""

import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import mini
from hivo.mutation_grounding import MutationGrounding, MAX_REFRESH_LINES
from scripts.experiment15_run import ARMS, CASE_IDS, engine
from scripts.experiment12_fixtures import get_case
from scripts.experiment12_evidence_matrix import reference_source
from scripts.experiment12_report import browser_pass

OLD = {"arena_arrow":"if(event.key === 'ArrowDown') move('up');",
       "arena_q_restart":"// Extra restart key is intentionally not connected yet.",
       "node_unique":"return [...values].sort();"}
NEW = {"arena_arrow":"if(event.key === 'ArrowUp') move('up');",
       "arena_q_restart":"if(event.key.toLowerCase() === 'q' && ['gameover','won'].includes(state.status)) restart();",
       "node_unique":"return [...new Set(values)];"}
SCENARIOS = ("missing_anchor_full_refresh", "post_change_full_refresh", "bounded_range_control",
             "imagined_text", "stale_after_refresh", "large_full_read", "duplicate_anchor",
             "fabricated_read", "wrong_refresh_region", "foreign_target", "full_write_after_refresh")
POSITIVE = set(SCENARIOS[:3])


def historic(path):
    run=json.loads((path/'.agent_experiment.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    g=run['mutation_grounding_runs'][0]
    return {"source":str(path.resolve()),"first_legal_mutation":run['first_legal_mutation'],
            "applied_before_rollback":g['applied_mutation_attempts'],"terminal":g['terminal_reason'],
            "bounded_refreshes":g['bounded_refreshes'],"attempts":g['attempts'],
            "exact_rejected_arguments_available":False,
            "meaning":"Two legal edits preceded a later stale-anchor rejection; full reread did not register as bounded refresh. Last rejected old/new text is unavailable."}


def evaluate(case,workspace,scenario,policy,approved):
    engine.materialize(case,workspace)
    mini.WORKSPACE=workspace.resolve();mini.reset_run('experiment15-binding-protocol')
    mini.RUN.update(engine.POLICIES,semantic_evidence_policy='strict',mutation_grounding_policy=policy)
    mini.ACTIVE_TOOL_CONTRACT=None;mini.ACTIVE_TRANSACTION=None
    path=workspace/case['source'];old,new=OLD[case['case_id']],NEW[case['case_id']]
    request={'path':case['source'],'old':old,'new':new,'expected_replacements':1}
    state=MutationGrounding(workspace,(case['source'].casefold(),),policy=policy)
    marker='<!-- revision -->\n' if case['source'].endswith('.html') else '// revision\n'
    if scenario=='post_change_full_refresh':
        state.observe_read('read_file',{'path':case['source']},mini.read_file(case['source']),path)
        path.write_text(marker+path.read_text(encoding='utf-8'),encoding='utf-8')
    if scenario=='large_full_read':path.write_text(marker*(MAX_REFRESH_LINES+1)+path.read_text(encoding='utf-8'),encoding='utf-8')
    if scenario=='duplicate_anchor':
        comment='\n<!-- '+old+' -->\n' if case['source'].endswith('.html') else '\n/* '+old+' */\n'
        path.write_text(path.read_text(encoding='utf-8')+comment,encoding='utf-8')
    if scenario=='imagined_text':request['old']='imagined code that is absent'
    if scenario=='full_write_after_refresh':request={'path':case['source'],'content':reference_source(case)}
    name='write_file' if scenario=='full_write_after_refresh' else 'edit_file'
    if scenario=='foreign_target':
        path=workspace/'foreign.js';path.write_text('const x=1;',encoding='utf-8')
        request={'path':'foreign.js','old':'const x=1;','new':'const x=2;'}
    # Controller databases/logs are instrumentation, not project source.
    tracked=[workspace/p for p in case['files']]
    if scenario=='foreign_target':tracked.append(path)
    before={p.relative_to(workspace).as_posix():engine.sha(p.read_bytes()) for p in tracked}
    first=state.before_mutation(name,request,path,tool_step=1)
    scope_authorized=request['path']==case['source']
    if first['allowed'] and scope_authorized:raise RuntimeError('protocol expected a missing/stale initial anchor')
    source=path.read_text(encoding='utf-8')
    line=source[:source.find(old)].count('\n')+1 if old in source else 1
    if scenario in {'bounded_range_control','wrong_refresh_region'}:
        first_line=line if scenario=='bounded_range_control' else 1
        result=mini.read_file_range(request['path'],first_line,first_line)
        state.observe_read('read_file_range',{'path':request['path'],'start_line':first_line,'end_line':first_line},result,path)
    else:
        result=mini.read_file(request['path'])
        if scenario=='fabricated_read':result+='fabricated unseen text'
        state.observe_read('read_file',{'path':request['path']},result,path)
    if scenario=='stale_after_refresh':path.write_text(marker+source,encoding='utf-8')
    decision=state.before_mutation(name,request,path,tool_step=3)
    allowed=decision['allowed'] and scope_authorized
    result='not executed'
    proof_valid=False;target_correct=False;verification=None
    input_hash=engine.sha(json.dumps({'before':before,'request':request,'scenario':scenario},sort_keys=True).encode('utf-8'))
    if allowed:
        actual_before=path.read_bytes();text=path.read_text(encoding='utf-8')
        result=mini.edit_file(request['path'],request['old'],request['new'],request['expected_replacements'])
        applied=path.read_bytes()!=actual_before and not mini.tool_result_failed(result)
        state.after_mutation(decision,result,changed_file=applied)
        first_line=text[:text.index(old)].count('\n')+1
        proof_valid=decision['attempt']['source_before_hash']==engine.sha(actual_before)
        target_correct=decision['attempt']['source_lines']==[first_line,first_line+old.count('\n')]
        if not applied or not proof_valid or not target_correct:raise RuntimeError('authorized reference mutation did not bind/apply exactly')
        if case['family'].startswith('browser'):
            payload=mini.verify_browser_application(case['source'],'PROBE',profile=mini.infer_web_profile(case['goal']),
                evidence={'verification_requirement':case['goal'],'harness_config':{'entrypoint':case['source']}})
            verification={'native_pass':browser_pass(case,payload),'payload':payload}
        else:
            output=mini.run_command(case['integration_target'])
            verification={'native_pass':'[exit_code=0]' in output and 'unique behavior tests: 4 passed' in output,'output':output}
        if not verification['native_pass']:raise RuntimeError('reference patch failed native behavior')
    after={p.relative_to(workspace).as_posix():engine.sha(p.read_bytes()) for p in tracked}
    changed=[p for p in before if before[p]!=after[p]]
    foreign=[p for p in changed if p!=case['source']]
    tests_changed=any(p==case.get('test_target') for p in changed)
    return {'case_id':case['case_id'],'scenario':scenario,'policy':policy,'expected_compatible':scenario in POSITIVE,
        'input_hash':input_hash,'authorized':allowed,'applied':bool(state.summary()['applied_mutation_attempts']),
        'binding_valid':proof_valid,'mutation_on_true_region':target_correct,'verification':verification,
        'scope_violations':len(foreign),'read_only_tests_changed':tests_changed,'changed_paths':changed,
        'result':result,'grounding':state.summary(),'contract_hash':approved['execution_contract_hash'],
        'first_legal_mutation_step':3 if allowed else None,'root_success_claimed':False,'model_calls':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    mini._load_optional_imports();mini.ensure_dependencies(auto_install=False)
    rows=[]
    for cid in CASE_IDS:
        case=get_case(cid);folder=args.output_dir/cid;folder.mkdir()
        approved=json.loads((args.suite/cid/'authority.json').read_text(encoding='utf-8'))
        for scenario in SCENARIOS:
            for policy in ARMS:
                workspace=folder/(scenario+'-'+policy)
                row=evaluate(case,workspace,scenario,policy,approved)
                engine.save(folder/(scenario+'-'+policy+'.json'),row);rows.append(row)
        print(cid,'binding protocols complete',flush=True)
    history=historic(args.history)
    engine.save(args.output_dir/'comparison.json',{'experiment':15,'mode':'declared_binding_challenges_and_native_verification',
        'historical_failure':history,'outcomes':rows,'model_calls':0,
        'limit':'Constructed protocol requests recreate the read/refresh state class. They are not the unrecorded historical mutation arguments or fresh Worker/Root results.'})


if __name__=='__main__':main()
