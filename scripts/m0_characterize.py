"""M0 controlled diagnostics only. No production fixes and no real model calls.

Creates a new evidence directory; refuses reuse. See the provisional M0 report.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mini
from hivo import requirements as req
from playwright.sync_api import sync_playwright

HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task list</title><link rel="stylesheet" href="style.css"></head>
<body><main><h1>Task list</h1><label for="taskInput">Task</label>
<input id="taskInput"><button id="addTaskButton" type="button">Add</button>
<p id="empty">No tasks yet</p><ul id="taskList"></ul></main>
<script src="app.js"></script></body></html>'''
CSS = 'body{font-family:sans-serif;margin:1rem}main{max-width:40rem;margin:auto}li{display:flex;gap:1rem;flex-wrap:wrap}input{max-width:100%;box-sizing:border-box} .done span{text-decoration:line-through}\n'
INERT = '// Foundation companion only; feature implementation belongs to child 2.\nconsole.log("foundation loaded");\n'


def js(mode):
    if mode == 'inert':
        return INERT + '// Child 2 stopped without feature implementation.\n'
    if mode == 'runtime_error':
        return 'throw new Error("M0 controlled runtime defect");\n'
    return '''const input = document.querySelector('#taskInput');
const list = document.querySelector('#taskList');
const empty = document.querySelector('#empty');
let tasks = PERSIST ? JSON.parse(localStorage.getItem('m0_tasks') || '[]') : [];
function save(){if(PERSIST)localStorage.setItem('m0_tasks',JSON.stringify(tasks));}
function render(){
 list.replaceChildren(); empty.hidden=tasks.length>0;
 tasks.forEach((task,index)=>{
  const li=document.createElement('li');li.className=task.done?'done':'';
  const check=document.createElement('input');check.type='checkbox';check.checked=task.done;
  check.setAttribute('aria-label','Complete '+task.text);
  check.addEventListener('change',()=>{if(TOGGLE){task.done=check.checked;save();render();}});
  const span=document.createElement('span');span.textContent=task.text;
  const del=document.createElement('button');del.textContent='Delete';
  del.addEventListener('click',()=>{if(DELETE){tasks.splice(index,1);save();render();}});
  li.append(check,span,del);list.append(li);
 });
}
document.querySelector('#addTaskButton').addEventListener('click',()=>{
 const text=input.value.trim();if(!text||!ADD)return;
 tasks.push({text,done:false});input.value='';save();render();
});
render();
'''.replace('PERSIST', str(mode != 'no_persistence').lower()).replace(
        'TOGGLE', str(mode != 'no_toggle').lower()).replace(
        'DELETE', str(mode != 'no_delete').lower()).replace('ADD', str(mode != 'no_add').lower())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str)+'\n', encoding='utf-8')


def tool(name, **args):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': json.dumps(args)}}]}


DONE = {'role': 'assistant', 'content': 'Controlled probe finished; use actual tool receipts.', 'tool_calls': []}


class ScriptedProvider:
    def __init__(self, actions, record, repair=False):
        self.actions = list(actions)
        self.counts = {}
        self.record = record
        self.repair = repair

    def __call__(self, messages, *args, role='Builder', **kwargs):
        n = self.counts.get(role, 0)
        self.counts[role] = n+1
        if sum(self.counts.values()) > 55:
            raise AssertionError('M0 scripted-provider call cap exceeded; not a runtime success')
        if role == 'Builder':
            replies = [tool('context_sufficiency_check', context_status='sufficient'), *self.actions,
                       tool('verify_web_app', path='index.html'), DONE]
        elif role == 'Falsifier':
            replies = [tool('read_file', path='index.html'), tool('read_file', path='app.js'),
                       tool('verify_web_app', path='index.html'), DONE]
        elif role == 'Repairer':
            replies = [tool('context_sufficiency_check', context_status='sufficient'),
                       tool('read_file', path='app.js')]
            if self.repair:
                replies += [tool('edit_file', path='app.js', old=js('runtime_error'), new=js('full'))]
            replies += [tool('verify_web_app', path='index.html'), DONE]
        else:
            raise AssertionError('Unexpected model role: '+role)
        reply = copy.deepcopy(replies[n] if n < len(replies) else DONE)
        self.record.append({'role': role, 'ordinal': n, 'reply': reply})
        return reply


def initialize(workspace, source):
    workspace.mkdir(parents=True)
    mini.WORKSPACE = workspace.resolve()
    mini.MEMORY_STORE = None
    mini.reset_run('recursive')
    mini.RUN['project_mode'] = mini.NEW_PROJECT
    mini.RUN['source_contract'] = copy.deepcopy(source)
    mini.RUN['source_requirement_ledger'] = copy.deepcopy(source.get('source_requirement_ledger'))
    mini.ACTIVE_CONTRACT = copy.deepcopy(source)
    spec = {field: [] for field in mini._PROJECT_SPECIFICATION_FIELDS}
    spec['root_goal'] = source['goal']
    mini.RUN['project_brain'] = mini.build_project_brain(source, spec, mini.inspect_repository())


def mission(task, source):
    return {'goal_anchor': source['goal'], 'task': task['goal'],
            'expected_outcome': '; '.join(task['done_when']), 'targets': task['scope_hint'],
            'existing_facts': [], 'implementation_plan': ['Implement only the assigned child duties'],
            'interfaces_to_reuse': [], 'invariants': [], 'project_specific_quality_rules': [],
            'do_not': ['Do not expand the assigned mutation scope'],
            'verification_plan': ['Verify the HTML entry and its local assets'], 'done_when': task['done_when']}


def leaf(task, source, actions, memory, deps=None, repair=False):
    calls = []
    provider = ScriptedProvider(actions, calls, repair=repair)
    def compiler(prompt, validator, *args, **kwargs):
        value = mission(task, source)
        if not validator(value):
            raise AssertionError('Scripted mission rejected by actual compiler validator')
        return value
    real_gate, real_tool, real_execute = mini.evidence_gate, mini.run_tool, mini.execute_agent_task
    gates, tools, executions = [], [], []
    def observe_gate(*a, **kw):
        result = real_gate(*a, **kw)
        gates.append(copy.deepcopy(result))
        dump(mini.WORKSPACE.parent/('gates-'+task['id']+'.json'),gates)
        return result
    def observe_tool(name, args, role='Builder'):
        result = real_tool(name, args, role=role)
        tools.append({'tool':name,'args':args,'role':role,'result':result})
        dump(mini.WORKSPACE.parent/('tools-'+task['id']+'.json'),tools)
        return result
    def observe_execute(*a, **kw):
        role = kw.get('role','Builder')
        provider.counts[role] = 0
        result = real_execute(*a, **kw)
        executions.append({'role':role,'result':copy.deepcopy(result)})
        return result
    with patch.object(mini, 'ask_ollama', side_effect=provider), \
         patch.object(mini, 'evidence_gate', side_effect=observe_gate), \
         patch.object(mini, 'run_tool', side_effect=observe_tool), \
         patch.object(mini, 'execute_agent_task', side_effect=observe_execute), \
         patch.object(mini, 'structured_model_call', side_effect=compiler):
        result = mini.execute_leaf(task, source, memory, mini.inspect_repository(), dependency_summaries=deps)
    calls.append({'observed_gates':gates,'observed_tools':tools,'observed_executions':executions})
    return result, calls


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def behavior(workspace, browser_exe):
    """Independent real DOM actions; this does not inject receipts into Mini Hivo."""
    handler = lambda *a, **kw: QuietHandler(*a, directory=str(workspace), **kw)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=str(browser_exe))
            page = browser.new_page(viewport={'width': 1000, 'height': 750})
            page.set_default_timeout(2000)
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto(f'http://127.0.0.1:{server.server_port}/index.html', wait_until='load')
            page.evaluate('localStorage.clear()')
            page.reload(wait_until='load')
            checks = {'initial_empty_state': page.locator('#empty').is_visible()}
            page.locator('#taskInput').fill('   ')
            page.get_by_role('button', name='Add', exact=True).click()
            checks['empty_input_rejected'] = page.locator('#taskList li').count() == 0
            page.locator('#taskInput').fill('M0 task A')
            page.get_by_role('button', name='Add', exact=True).click()
            added = page.locator('#taskList li').count() == 1
            checks['add_visible_task'] = added and page.locator('#taskList').inner_text().find('M0 task A') >= 0
            checks['empty_state_hidden'] = added and not page.locator('#empty').is_visible()
            if added:
                page.locator('#taskList input[type=checkbox]').click()
                checks['completion_on'] = 'done' in (page.locator('#taskList li').get_attribute('class') or '')
                page.reload(wait_until='load')
                checks['reload_text'] = page.locator('#taskList li').count() == 1
                checks['reload_completion'] = checks['reload_text'] and 'done' in (page.locator('#taskList li').first.get_attribute('class') or '')
                if page.locator('#taskList li').count():
                    page.locator('#taskList input[type=checkbox]').first.click()
                    checks['completion_off'] = 'done' not in (page.locator('#taskList li').first.get_attribute('class') or '')
                else:
                    checks['completion_off'] = False
                page.locator('#taskInput').fill('M0 task B')
                page.get_by_role('button', name='Add', exact=True).click()
                page.get_by_role('button', name='Delete', exact=True).first.click()
                checks['delete_selected_only'] = page.locator('#taskList li').count() == 1 and 'M0 task B' in page.locator('#taskList').inner_text()
            else:
                for name in ('completion_on', 'completion_off', 'reload_text', 'reload_completion', 'delete_selected_only'):
                    checks[name] = False
            page.set_viewport_size({'width': 375, 'height': 750})
            checks['mobile_no_overflow'] = page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            checks['no_runtime_errors'] = not errors
            page.screenshot(path=str(workspace/'independent-final.png'), full_page=True)
            browser.close()
            return {'checks': checks, 'passed': all(checks.values()), 'runtime_errors': errors,
                    'scope': 'independent fixture-specific action/result oracle, not production verification or model generation'}
    finally:
        server.shutdown()
        server.server_close()


def summarize(result):
    return {key: result.get(key) for key in ('status', 'failure_type', 'orchestration_failure', 'summary',
        'gate', 'browser', 'impact_comparison', 'integration_preflight', 'integration_outcome')}


def chain(out, source, mode, browser_exe, supply_syntax=False):
    case = out/('chain_'+mode)
    workspace = case/'workspace'
    initialize(workspace, source)
    parent = mini.make_task('ROOT', source['goal'], done_when=source['requirements'])
    mini.TASKS['ROOT'] = parent
    specs = {'children': [
        {'goal': 'Set up the basic structure and styling for the To-Do List application.',
         'done_when': ['The HTML entry loads its stylesheet and inert companion script.'],
         'scope_hint': ['index.html','style.css','app.js'], 'depends_on': []},
        {'goal': 'Implement adding, displaying, completion toggling, deletion and persistence of tasks.',
         'done_when': ['Users can add non-empty tasks, toggle completion, delete tasks, and retain them after reload.'],
         'scope_hint': ['app.js'], 'depends_on': ['1']}]}
    with patch.object(mini, 'structured_model_call', return_value=specs):
        children = mini.decompose_task(parent, source, mini.inspect_repository())
    observations = []
    pairs = []
    def executor(task, contract, memory, snapshot, parent_summary='', dependency_summaries=None, **kwargs):
        before = {p: digest(workspace/p) for p in ('index.html','style.css','app.js') if (workspace/p).exists()}
        if task['id'] == '1':
            actions = [tool('write_file', path=p, content=v) for p,v in [('index.html',HTML),('style.css',CSS),('app.js',INERT)]]
        else:
            actions = [tool('read_file', path='index.html'),tool('read_file', path='app.js'),
                       tool('edit_file', path='app.js', old=INERT, new=js(mode))]
            if supply_syntax:
                actions.append(tool('run_command',command='node --check app.js'))
        result, calls = leaf(task, contract, actions, memory, dependency_summaries)
        pairs.append({'task': task, 'result': result})
        observations.append({'task_id':task['id'], 'before':before,
            'after':{p:digest(workspace/p) for p in ('index.html','style.css','app.js') if (workspace/p).exists()},
            'dependency_summaries':dependency_summaries, 'result':summarize(result),
            'mutation_scope':(task.get('impact_contract_candidate') or {}).get('authorized_mutation_paths'),
            'inspection_scope':task.get('greenfield_inspection_paths'), 'model_calls':calls,
            'manifest_at_leaf_return':copy.deepcopy(result.get('integration_manifest'))})
        dump(case/('leaf-'+task['id']+'.json'),observations[-1])
        return result
    parent_calls = []
    def aggregator(task, contract, completed, memory, snapshot=None, **kwargs):
        provider = ScriptedProvider([], parent_calls)
        dump(case/'manifests-before-parent.json',[
            {'task_id':x['task']['id'],'manifest':copy.deepcopy(x['result'].get('integration_manifest'))} for x in completed])
        real_preflight = mini.run_integration_preflight
        preflights = []
        def observed_preflight(*a,**kw):
            value = real_preflight(*a,**kw)
            preflights.append({'child_info':copy.deepcopy(a[1] if len(a)>1 else kw.get('child_info')),'result':value})
            dump(case/'parent-preflights.json',preflights)
            return value
        with patch.object(mini,'ask_ollama',side_effect=provider), \
             patch.object(mini,'run_integration_preflight',side_effect=observed_preflight), \
             patch.object(mini,'structured_model_call',side_effect=mini.StructuredOutputError('M0 boundary stop: no integration repair mission scripted')):
            return mini.aggregate_task(task,contract,completed,memory,snapshot,root=True)
    result = mini._execute_children(parent,children,0,source,{},mini.inspect_repository(),'',[],
        fit_decider=lambda *a,**k:{'decision':'execute','reason':'scripted bounded granularity'},
        leaf_executor=executor,aggregator=aggregator)
    independent = behavior(workspace, browser_exe)
    # Re-evaluate preserved leaf receipts only as a separate diagnostic; no fabricated success.
    auxiliary = {}
    if len(pairs) == 2 and pairs[1]['result'].get('status') == 'done':
        child_result = pairs[1]['result']
        stale = copy.deepcopy(child_result.get('builder',{}))
        falsifier = copy.deepcopy(child_result.get('falsifier'))
        browser = copy.deepcopy(child_result.get('browser'))
        (workspace/'app.js').write_text(js('runtime_error'),encoding='utf-8')
        auxiliary['stale_receipt_gate_after_out_of_band_edit'] = mini.evidence_gate(stale,falsifier,browser)
        auxiliary['stale_receipt_scope'] = 'Direct legacy gate probe only; not a fresh parent verdict or production mutation.'
        (workspace/'app.js').write_text(js(mode),encoding='utf-8')
    record = {'mode':mode,'supply_syntax_receipt':supply_syntax,'children':observations,'scheduler':parent.get('child_scheduler'),
        'parent_result':summarize(result),'parent_model_calls':parent_calls,'independent_behavior':independent,
        'auxiliary':auxiliary,'tasks':{k:{x:v.get(x) for x in ('id','parent','goal','done_when','scope_hint','depends_on','status','verification_status')}
                                for k,v in mini.TASKS.items()},
        'scope':'Scripted decomposition, missions and role replies; real scheduler, leaf, parent, tools, gates, transactions and Chromium.'}
    dump(case/'result.json',record)
    return record


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--browser-executable',type=Path,required=True)
    parser.add_argument('--phase',choices=['chain','matrix','all'],default='all')
    parser.add_argument('--supply-syntax-receipt',action='store_true')
    args=parser.parse_args()
    out=args.output_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    mini._load_optional_imports()
    raw=(ROOT/'tests/fixtures/new_application_requirements.txt').read_bytes()
    text=raw.decode('utf-8')
    ledger=req.extract_source_requirements(text)
    source=mini.normalize_goal_contract(text,mini._deterministic_contract_from_ledger(text,ledger),source_ledger=ledger)
    sources=['mini.py','hivo/project_understanding.py','hivo/verification_scope.py','hivo/verification_routing.py',
             'hivo/pre_mutation_impact.py','hivo/integration_gate.py','hivo/requirements.py']
    provenance={'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        'python':sys.version,'python_executable':sys.executable,'browser_executable':str(args.browser_executable),'argv':sys.argv,
        'prompt_sha256':hashlib.sha256(raw).hexdigest(),'harness_sha256':digest(__file__),
        'source_worktree_sha256':{p:digest(ROOT/p) for p in sources},'ledger':ledger,
        'source_contract':source,'model_calls':'All role and structured replies scripted; HTTP provider entry points fail closed.'}
    dump(out/'provenance.json',provenance)
    records={}
    with patch.object(mini,'browser_launch_kwargs',return_value={'headless':True,'executable_path':str(args.browser_executable)}), \
         patch.object(mini,'http_post_json',side_effect=AssertionError('M0 forbids provider HTTP')), \
         patch.object(mini,'http_get_json',side_effect=AssertionError('M0 forbids provider HTTP')), \
         patch.object(mini,'ask_ollama',side_effect=AssertionError('Unscripted model call')), \
         patch.object(mini,'structured_model_call',side_effect=mini.StructuredOutputError('M0 bounded stop: no additional planner responses supplied')):
        if args.phase in ('chain','all'):
            for mode in ('inert','full'):
                try:
                    print('CASE_START chain_'+mode,flush=True)
                    records['chain_'+mode]=chain(out,source,mode,args.browser_executable,args.supply_syntax_receipt)
                except Exception:
                    records['chain_'+mode]={'diagnostic_error':traceback.format_exc()}
                    dump(out/('chain_'+mode+'_error.json'),records['chain_'+mode])
                print('CASE_END chain_'+mode,flush=True)
        if args.phase in ('matrix','all'):
            for mode in ('full','inert','missing_js','runtime_error','no_add','no_delete','no_toggle','no_persistence','disconnected_script'):
                workspace=out/('matrix_'+mode)/'workspace'
                initialize(workspace,source)
                (workspace/'index.html').write_text(HTML.replace('<script src="app.js"></script>','') if mode=='disconnected_script' else HTML,encoding='utf-8')
                (workspace/'style.css').write_text(CSS,encoding='utf-8')
                if mode!='missing_js': (workspace/'app.js').write_text(js('full' if mode=='disconnected_script' else mode),encoding='utf-8')
                profile=mini._scoped_browser_profile(source['goal'],mini._task_web_verification_contract(mini.make_task('ROOT',source['goal']),source),'index.html')
                native=mini.browser_workspace_snapshot('index.html',task_id='ROOT',profile=profile)
                independent=behavior(workspace,args.browser_executable)
                record={'native_browser':native,'profile':profile.__dict__,'independent_behavior':independent,
                        'assets':[{'kind':r['kind'],'path':r['path'].relative_to(workspace).as_posix(),'exists':r['path'].exists()}
                                  for r in mini._local_html_asset_references(workspace,workspace/'index.html')],
                        'scope':'Known fixture state; native browser and independent oracle only, not child/root acceptance.'}
                dump(workspace.parent/'result.json',record)
                records['matrix_'+mode]=record
                print('MATRIX',mode,'native=',native.get('passed'),'independent=',independent['passed'],flush=True)
    dump(out/'results.json',records)
    errors=[key for key,value in records.items() if 'diagnostic_error' in value]
    print('M0_FINISHED',len(records),'cases','diagnostic_errors=',errors,flush=True)
    return int(bool(errors))


if __name__=='__main__':
    raise SystemExit(main())
