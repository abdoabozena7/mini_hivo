"""Real Mini Hivo controller through provider adapters, entirely scripted HTTP.

No real network/inference. Resource/capability qualification is injected; real
authorization, tools, transactions, browser and read-only parent run unchanged.
"""
import argparse
import copy
import functools
import hashlib
import http.server
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = [ROOT / 'mini.py', *sorted((ROOT / 'hivo').glob('*.py')),
                Path(__file__).resolve(), ROOT / 'scripts/m0_characterize.py',
                ROOT / 'scripts/acceptance_phase_functional.py', ROOT / 'scripts/browser_selection.py',
                ROOT / 'tests/test_behavioral_obligations.py']
SOURCE_AT_IMPORT = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_PATHS}
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
import mini
from hivo import host_preflight, provider_preflight, requirements
from hivo.http_client import JsonResponse
from hivo.model_routing import RoleRouter, RoutingConfig, RoutingPolicy
from hivo.providers import ModelSelection, ProviderClient
from m0_characterize import initialize, mission, tool, DONE, dump
from acceptance_phase_functional import HTML, SCRIPT, INERT
from test_behavioral_obligations import scenario
from playwright.sync_api import sync_playwright, Error as BrowserRuntimeError
from browser_selection import select_browser, validate_browser, BrowserSelectionError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--variant', choices=['working', 'inert'], default='working')
    parser.add_argument('--worker-context', type=int, default=32768)
    parser.add_argument('--capture-packets', action='store_true', help='Private full pre-dispatch packets in the new output directory')
    parser.add_argument('--expect-compact-success', action='store_true', help='Require working root acceptance at the supplied context')
    parser.add_argument('--browser-executable', help='Explicit installed Chromium-compatible executable; never installed automatically')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    dump(out / 'source-at-start.json', SOURCE_AT_IMPORT)
    try:
        # Validate explicit paths before starting Playwright. Discovery uses
        # its installed bundle, PATH or standard installed browser locations.
        selection = select_browser(args.browser_executable) if args.browser_executable else None
        with sync_playwright() as engine:
            if selection is None:
                selection = select_browser(bundled_path=engine.chromium.executable_path)
            browser_provenance = validate_browser(selection, engine.chromium)
    except (BrowserSelectionError, BrowserRuntimeError) as exc:
        reason = str(exc) if isinstance(exc, BrowserSelectionError) else 'BROWSER_DRIVER_UNAVAILABLE'
        dump(out / 'browser-provenance.json', {'status': 'UNAVAILABLE', 'reason': reason})
        dump(out / 'results.json', {'status': 'BROWSER_UNAVAILABLE', 'checks': {'browser_ready': False},
                                  'provider_requests': 0, 'source_sha256': SOURCE_AT_IMPORT})
        print(reason)
        return 2
    browser = selection.executable
    dump(out / 'browser-provenance.json', browser_provenance)
    rows = [{'text': 'Create index.html, style.css and app.js.', 'explicit_items': ['index.html', 'style.css', 'app.js']},
            {'text': 'Clicking Increase increments the visible count.'}, {'text': 'Count persists after reload.'}]
    ledger = requirements.build_source_requirement_ledger(rows)
    source = mini.normalize_goal_contract('Build a browser counter.',
        {'goal': 'Build a browser counter.', 'requirements': [r['text'] for r in rows]}, source_ledger=ledger)
    ids = [r['requirement_id'] for r in mini.ledger_requirements(ledger)]
    plan = {'children': [
        {'goal': 'Create browser counter structure and styling', 'done_when': ['Page loads its assets'],
         'scope_hint': ['index.html', 'style.css', 'app.js'], 'depends_on': [], 'requirement_ids': ids[:1],
         'verification_obligations': [dict(requirement_id=ids[0], source_text=rows[0]['text'], kind='file_exists', target=p)
                                      for p in ['index.html', 'style.css', 'app.js']]},
        {'goal': 'Implement increment and persisted counter state', 'done_when': ['Click increments count; reload retains it'],
         'scope_hint': ['app.js'], 'depends_on': ['1'], 'requirement_ids': ids[1:],
         'verification_obligations': [scenario(ids[1], rows[1]['text']), scenario(ids[2], rows[2]['text'], reload=True)]}],
        'parent_requirement_ids': [], 'parent_verification_obligations': []}
    # Deliberately not the target 4096-context claim: controller compatibility
    # uses an explicit large synthetic context; --worker-context 4096 tests refusal.
    orch = ModelSelection('openrouter', 'fixture/planner:free', context=32768, max_output=4096)
    worker = ModelSelection('ollama', 'fixture-worker:small', context=args.worker_context, reasoning='off')
    state = {'task': None, 'role_counts': {}}
    transport_calls = []
    router = None
    def get(url, **kwargs):
        if url.endswith('/models'):
            return JsonResponse(200, json.dumps({'data': [{'id': orch.model, 'context_length': 32768,
                'supported_parameters': ['response_format', 'structured_outputs'], 'pricing': {'prompt': '0', 'completion': '0'}}]}))
        if url.endswith('/key'): return JsonResponse(200, '{"data":{"is_free_tier":true}}')
        if url.endswith('/api/tags'): return JsonResponse(200, json.dumps({'models': [{'name': worker.model, 'size': 1}]}))
        if url.endswith('/api/ps'): return JsonResponse(200, '{"models":[]}')
        raise AssertionError('Unexpected metadata URL')
    def post(url, *, payload, **kwargs):
        if url.endswith('/api/show'):
            return JsonResponse(200, json.dumps({'capabilities': ['completion', 'tools'],
                'model_info': {'fixture.context_length': 32768}, 'thinking': {'values': [False, True], 'default': False}}))
        role = router.active_role
        messages = payload['messages']
        user = '\n'.join(str(m.get('content', '')) for m in messages if m.get('role') == 'user')
        transport_calls.append({'provider': 'ollama' if url.endswith('/api/chat') else 'openrouter',
                                'model': payload['model'], 'role': role,
                                'serialized_prompt_chars': len(json.dumps(messages)),
                                'tool_schema_chars': len(json.dumps(payload.get('tools', [])))})
        if 'Reply with exactly: HIVO_PREFLIGHT_OK' in user:
            message = {'role': 'assistant', 'content': host_preflight.CANARY_EXPECTED_RESPONSE}
        elif user == 'Return exactly {"ok":true}.':
            message = {'role': 'assistant', 'content': '{"ok":true}'}
        elif 'Call hivo_capability_probe' in user:
            message = tool('hivo_capability_probe', ok=True)
        elif payload['model'] == orch.model:
            value = plan if 'Split CURRENT NODE' in user else mission(state['task'], source)
            message = {'role': 'assistant', 'content': json.dumps(value)}
        else:
            task = state['task']
            counts = state['role_counts']
            index = counts.get(role, 0)
            counts[role] = index + 1
            if role == 'builder':
                if task['id'] == '1':
                    actions = [tool('write_file', path=p, content=c) for p, c in
                               [('index.html', HTML), ('style.css', 'body {font-family:sans-serif}'), ('app.js', INERT)]]
                else:
                    actions = [tool('read_file', path='index.html'), tool('read_file', path='app.js'),
                               tool('edit_file', path='app.js', old=INERT, new=SCRIPT if args.variant == 'working' else '// inert feature'),
                               tool('run_command', command='node --check app.js')]
                replies = [tool('context_sufficiency_check', context_status='sufficient'), *actions,
                           tool('verify_web_app', path='index.html'), DONE]
            elif role == 'falsifier':
                replies = [tool('read_file', path='index.html'), tool('read_file', path='app.js'),
                           tool('verify_web_app', path='index.html'), DONE]
            elif role == 'repairer':
                replies = [tool('context_sufficiency_check', context_status='sufficient'), tool('read_file', path='app.js'),
                           tool('verify_web_app', path='index.html'), DONE]
            else:
                raise AssertionError('Unexpected worker role')
            message = copy.deepcopy(replies[index] if index < len(replies) else DONE)
            offered = {t['function']['name'] for t in payload.get('tools', [])}
            needed = (message.get('tool_calls') or [{}])[0].get('function', {}).get('name')
            if needed and needed not in offered and 'select_worker_tools' in offered:
                counts[role] -= 1
                message = tool('select_worker_tools', names=[needed])
        if payload['model'] == worker.model:
            return JsonResponse(200, json.dumps({'model': worker.model, 'done': True, 'done_reason': 'stop', 'message': message}))
        return JsonResponse(200, json.dumps({'model': orch.model, 'choices': [{'finish_reason': 'stop', 'message': message}], 'usage': {'cost': 0}}))
    client = ProviderClient(get=get, post=post, environ={'OPENROUTER_API_KEY': 'fixture-not-a-real-key'},
        cloud_catalog_authorized=True, cloud_inference_authorized=True, request_budget=80)
    router = RoleRouter(RoutingConfig(orch, worker, request_budget=80), client)
    packets = []
    audits = []
    original_compact = mini.worker_packets.compact
    def capture_compaction(messages, tools, store=None):
        result = None
        try:
            result = original_compact(messages, tools, store)
            return result
        finally:
            if args.capture_packets:
                audits.append({'original_messages': copy.deepcopy(messages), 'original_tools': copy.deepcopy(tools),
                'compacted_messages': copy.deepcopy(result[0] if result else None), 'compacted_tools': copy.deepcopy(result[1] if result else None),
                'evidence': copy.deepcopy(store._values if store else {}),
                'ownership': copy.deepcopy(store.obligations if store else None),
                'authority': copy.deepcopy(store.authority if store else None),
                'source_contract': copy.deepcopy(store.source_contract if store else None),
                'task': copy.deepcopy(store.task if store else None),
                'role': state.get('current_role'),
                'source_tool_contract': copy.deepcopy(mini.ACTIVE_TOOL_CONTRACT)})
    if args.capture_packets:
        original_chat = router.chat
        def capture_chat(role, messages, **kwargs):
            packets.append({'role': role, 'messages': copy.deepcopy(messages),
                            'tools': copy.deepcopy(kwargs.get('tools')),
                            'format': copy.deepcopy(kwargs.get('response_format'))})
            return original_chat(role, messages, **kwargs)
        router.chat = capture_chat
    workspace = out / 'workspace'
    initialize(workspace, source)
    resources = lambda: {'available_system_ram_bytes': 8 * 2**30, 'total_system_ram_bytes': 16 * 2**30}
    def host_runner(*a, **k):
        return host_preflight.run_host_preflight(*a, **k, sleep=lambda _: None)
    qualification = provider_preflight.qualify(router, workspace, resource_sampler=resources, host_runner=host_runner)
    if not qualification['passed']: raise AssertionError(qualification)
    mini.PROVIDER_ROUTER = router
    mini.MODEL_POLICY = RoutingPolicy(router.config)
    mini.MODEL = worker.model
    mini._load_optional_imports()
    mini.RUN['role_models'] = mini.MODEL_POLICY.role_models()
    parent = mini.make_task('ROOT', source['goal'], done_when=source['requirements'])
    mini.TASKS['ROOT'] = parent
    state['task'] = parent
    child_results = []
    original_execute = mini.execute_agent_task
    def observe_execute(*a, **k):
        key = ''.join(c for c in k.get('role', 'Builder').lower() if c.isalnum())
        state['current_role'] = key
        state['role_counts'][key] = 0
        return original_execute(*a, **k)
    def execute(task, contract, memory, snapshot, parent_summary='', dependency_summaries=None):
        state['task'] = task
        result = mini.execute_leaf(task, contract, memory, snapshot, parent_summary, dependency_summaries)
        child_results.append({'task': task, 'result': result})
        return result
    with patch.object(mini, 'browser_launch_kwargs', return_value={'headless': True, 'executable_path': browser}), \
         patch.object(mini, 'execute_agent_task', side_effect=observe_execute), \
         patch.object(mini.worker_packets, 'compact', side_effect=capture_compaction), \
         patch('urllib.request.urlopen', side_effect=AssertionError('No real provider network')):
        children = mini.decompose_task(parent, source, mini.inspect_repository())
        result = mini._execute_children(parent, children, 0, source, {}, mini.inspect_repository(), '', [],
            fit_decider=lambda *a, **k: {'decision': 'execute'}, leaf_executor=execute, aggregator=mini.aggregate_task)
    independent = {'increment': False, 'persistence': False}
    if (workspace / 'index.html').exists():
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(workspace)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True, executable_path=browser)
                try:
                    page = b.new_page()
                    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
                    page.locator('#increase').click()
                    independent['increment'] = page.locator('#value').inner_text() == '1'
                    page.reload()
                    independent['persistence'] = page.locator('#value').inner_text() == '1'
                finally: b.close()
        finally: server.shutdown(); server.server_close()
    small = args.worker_context == 4096
    expected_done = args.variant == 'working' and (not small or args.expect_compact_success)
    checks = {'root_outcome_expected': (result['status'] == 'done') == expected_done,
              'independent_outcome_expected': all(independent.values()) == expected_done,
              'all_requests_exact_roles': all(c['model'] == (worker.model if c['role'] in {'builder', 'repairer', 'falsifier'} else orch.model)
                                            for c in transport_calls if c['role'] is not None),
              'no_implicit_model_substitution': all(c['model'] in {orch.model, worker.model} for c in transport_calls)}
    if small and not args.expect_compact_success:
        checks['undersized_context_blocks_before_project_mutation'] = (
            not (workspace / 'index.html').exists()
            and any(e.get('code') == 'CONTEXT_BUDGET_EXCEEDED' for e in router.events))
    if args.variant == 'inert' and not small:
        checks['foundation_retained_after_failed_child'] = (workspace / 'app.js').read_text() == INERT
    if args.variant == 'inert' and args.expect_compact_success:
        checks['foundation_retained_after_failed_child'] = (workspace / 'app.js').read_text() == INERT
    metrics = []
    for packet in packets:
        if ''.join(c for c in packet['role'].lower() if c.isalnum()) not in {'builder', 'repairer', 'falsifier'}:
            continue
        estimate = (len(json.dumps({k: packet[k] for k in ('messages', 'tools', 'format')}, ensure_ascii=False)) + 2) // 3
        metrics.append({'role': packet['role'], 'estimated_input_tokens': estimate,
                        'reserved_output_tokens': worker.max_output, 'context': worker.context,
                        'within_budget': estimate + worker.max_output <= worker.context})
    if args.capture_packets and args.expect_compact_success:
        checks['all_worker_packets_fit'] = bool(metrics) and all(m['within_budget'] for m in metrics)
    checks['source_unchanged_during_run'] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                                              for name, digest in SOURCE_AT_IMPORT.items())
    dump(out / 'results.json', {'checks': checks, 'root_result': result, 'children': child_results,
        'independent': independent, 'provider_calls': transport_calls, 'routing_events': router.events,
        'qualification': qualification, 'config': router.config.to_dict(), 'source': source,
        'browser_provenance': browser_provenance,
        'packet_metrics': metrics,
        'scope': 'Real provider adapters/controller/tools/gates/browser; all provider HTTP/model decisions and host resource samples scripted. No real provider calls.',
        'source_sha256': SOURCE_AT_IMPORT})
    if args.capture_packets:
        dump(out / 'packets.json', packets)
        dump(out / 'packet-audit.json', audits)
    print(json.dumps(checks))
    return int(not all(checks.values()))


if __name__ == '__main__': raise SystemExit(main())
