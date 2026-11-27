"""Controlled counter: real controller/tools/transactions/browser, scripted roles."""
import argparse
import functools
import hashlib
import http.server
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import mini
from hivo import requirements
from m0_characterize import initialize, leaf, tool, dump, ScriptedProvider
from playwright.sync_api import sync_playwright

HTML = '<!doctype html><title>Counter</title><link rel="stylesheet" href="style.css">' \
       '<button id="increase">Increase</button><output id="value">0</output><script src="app.js"></script>'
INERT = '// foundation only\n'
SCRIPT = "let n=Number(localStorage.getItem('count')||0);const value=document.querySelector('#value');" \
         "value.textContent=n;document.querySelector('#increase').onclick=()=>{" \
         "n++;value.textContent=n;localStorage.setItem('count',n);};"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--variant', choices=['working', 'inert'], default='working')
    parser.add_argument('--expect-child', choices=['done', 'failed'], default='done')
    parser.add_argument('--expect-root', choices=['done', 'failed'], default='failed')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    browser = json.loads((ROOT / 'output/m0-characterization/20261120-canonical-005/provenance.json').read_text())['browser_executable']
    rows = [{'text': 'Create index.html, style.css and app.js.', 'explicit_items': ['index.html', 'style.css', 'app.js']},
            {'text': 'Clicking Increase increments the visible count.'},
            {'text': 'The count persists after reload.'}]
    ledger = requirements.build_source_requirement_ledger(rows)
    source = mini.normalize_goal_contract('Build a browser counter.',
        {'goal': 'Build a browser counter.', 'requirements': [r['text'] for r in rows]}, source_ledger=ledger)
    workspace = out / 'workspace'
    initialize(workspace, source)
    mini._load_optional_imports()
    ids = [r['requirement_id'] for r in mini.ledger_requirements(ledger)]
    parent = mini.make_task('ROOT', source['goal'], done_when=source['requirements'])
    mini.TASKS['ROOT'] = parent
    plan = {'children': [
        {'goal': 'Create browser counter structure and styling', 'done_when': ['Page loads its stylesheet and companion script'],
         'scope_hint': ['index.html', 'style.css', 'app.js'], 'depends_on': [], 'requirement_ids': ids[:1]},
        {'goal': 'Implement increment and persisted counter state', 'done_when': ['Click increments count; reload retains it'],
         'scope_hint': ['app.js'], 'depends_on': ['1'], 'requirement_ids': ids[1:]}], 'parent_requirement_ids': []}
    plan['children'][0]['verification_obligations'] = [
        {'requirement_id': ids[0], 'source_text': rows[0]['text'], 'kind': 'file_exists', 'target': name}
        for name in ['index.html', 'style.css', 'app.js']]
    steps = [{'action': 'assert_text', 'selector': '#value', 'expected': '0'},
             {'action': 'click', 'selector': '#increase'},
             {'action': 'assert_text', 'selector': '#value', 'expected': '1'}]
    plan['children'][1]['verification_obligations'] = [
        {'requirement_id': ids[1], 'source_text': rows[1]['text'], 'kind': 'browser_scenario', 'target': 'index.html', 'steps': steps},
        {'requirement_id': ids[2], 'source_text': rows[2]['text'], 'kind': 'browser_scenario', 'target': 'index.html',
         'steps': steps + [{'action': 'reload'}, {'action': 'assert_text', 'selector': '#value', 'expected': '1'}]}]
    plan['parent_verification_obligations'] = []
    results = []
    parent_calls = []
    def aggregator(*args, **kwargs):
        with patch.object(mini, 'ask_ollama', side_effect=ScriptedProvider([], parent_calls)), \
             patch.object(mini, 'structured_model_call', side_effect=mini.StructuredOutputError('Bounded unscripted repair stop')):
            return mini.aggregate_task(*args, **kwargs)
    def executor(task, contract, memory, snapshot, parent_summary='', dependency_summaries=None, **kwargs):
        if task['id'] == '1':
            actions = [tool('write_file', path=p, content=c) for p, c in
                       [('index.html', HTML), ('style.css', 'body {font-family:sans-serif}'), ('app.js', INERT)]]
        else:
            actions = [tool('read_file', path='index.html'), tool('read_file', path='app.js'),
                       tool('edit_file', path='app.js', old=INERT, new=SCRIPT if args.variant == 'working' else '// inert feature'),
                       tool('run_command', command='node --check app.js')]
        result, calls = leaf(task, contract, actions, memory, dependency_summaries)
        results.append({'task': task, 'result': result, 'calls': calls})
        return result
    with patch.object(mini, 'browser_launch_kwargs', return_value={'headless': True, 'executable_path': browser}), \
         patch.object(mini, 'ask_ollama', side_effect=AssertionError('No unscripted provider')), \
         patch.object(mini, 'structured_model_call', return_value=plan), \
         patch.object(mini, 'http_post_json', side_effect=AssertionError('No provider HTTP')), \
         patch.object(mini, 'http_get_json', side_effect=AssertionError('No provider HTTP')):
        children = mini.decompose_task(parent, source, mini.inspect_repository())
        result = mini._execute_children(parent, children, 0, source, {}, mini.inspect_repository(), '', [],
            fit_decider=lambda *a, **k: {'decision': 'execute'}, leaf_executor=executor,
            aggregator=aggregator)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(workspace)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, executable_path=browser)
            try:
                page = b.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                page.locator('#increase').click()
                increment = page.locator('#value').inner_text() == '1'
                page.reload()
                persisted = page.locator('#value').inner_text() == '1'
            finally:
                b.close()
    finally:
        server.shutdown()
        server.server_close()
    checks = {'allocation_valid': parent.get('requirement_ownership', {}).get('valid') is True,
              'foundation_accepted': results[0]['result']['status'] == 'done',
              'child_status_expected': len(results) == 2 and results[1]['result']['status'] == args.expect_child,
              'root_status_expected': result['status'] == args.expect_root,
              'behavior_expected': (increment and persisted) == (args.variant == 'working' and args.expect_child == 'done')}
    dump(out / 'results.json', {'checks': checks, 'source': source, 'plan': plan, 'parent': parent,
         'children': results, 'root_result': result, 'parent_calls': parent_calls,
         'independent': {'increment': increment, 'persistence': persisted},
         'argv': sys.argv, 'scope': 'Scripted role decisions; real scheduler, tools, guards, transactions and Chromium.',
         'source_sha256': {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest()
                           for n in ['mini.py', 'hivo/requirement_ownership.py', 'scripts/acceptance_phase_functional.py']}})
    print(json.dumps(checks))
    return int(not all(checks.values()))


if __name__ == '__main__':
    raise SystemExit(main())
