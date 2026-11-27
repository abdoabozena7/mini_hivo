"""Real browser/receipt/readiness comparison; no agent/model or repair claims."""
import argparse
import functools
import hashlib
import http.server
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'tests')]
import mini
from hivo import integration_gate as gate
from hivo.verification import infer_web_profile
from m0_characterize import initialize
from test_verified_child_integration import VerifiedChildIntegrationGateTests
from playwright.sync_api import sync_playwright

HTML = '<!doctype html><title>Counter</title><link rel="stylesheet" href="style.css">' \
       '<button id="increment">Increase</button><output id="value">0</output>' \
       '<script src="state.js"></script><script src="app.js"></script>'
SCRIPT = "let count=Number(localStorage.getItem(storageKey)||0);" \
         "const output=document.querySelector('#value');output.textContent=count;" \
         "document.querySelector('#increment').onclick=()=>{" \
         "count++;output.textContent=count;localStorage.setItem(storageKey,count);};"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'tmp').mkdir()
    tempfile.tempdir = str(out / 'tmp')
    provenance = json.loads((ROOT / 'output/m0-characterization/20261120-canonical-005/provenance.json').read_text())
    browser = provenance['browser_executable']
    workspace = out / 'workspace'
    initialize(workspace, {'goal': 'A browser counter with increment and reload persistence',
                           'requirements': ['Increment visible count; retain count after reload']})
    for name, content in {'index.html': HTML, 'style.css': 'body {font-family:sans-serif}',
                          'app.js': SCRIPT, 'state.js': "const storageKey='counter';"}.items():
        (workspace / name).write_text(content, encoding='utf-8')
    mini._load_optional_imports()
    spec = importlib.util.spec_from_file_location('baseline_integration',
        ROOT / 'output/resume-engineering/20261121-001/integration_gate-before.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(workspace))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/index.html'
    def independent():
        with sync_playwright() as playwright:
            b = playwright.chromium.launch(headless=True, executable_path=browser)
            try:
                page = b.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url)
                page.wait_for_timeout(300)
                page.locator('#increment').click()
                page.wait_for_timeout(100)
                increment = page.locator('#value').inner_text() == '1'
                page.reload()
                page.wait_for_timeout(300)
                persistence = page.locator('#value').inner_text() == '1'
                return {'increment': increment, 'reload_persistence': persistence,
                        'no_runtime_errors': not errors, 'page_errors': errors,
                        'passed': increment and persistence and not errors}
            finally:
                b.close()
    fixture = VerifiedChildIntegrationGateTests()
    fixture.setUp()
    fixture.root = workspace
    def receipt_for(module, native):
        assert native['passed'], 'Cannot issue a successful receipt from failed native verification'
        task, result = fixture.child('A', 'index.html', focused='index.html')
        route = {'kind': 'BROWSER', 'required': True, 'applicable': True,
                 'target': 'index.html', 'result': 'PASS' if native['passed'] else 'FAIL'}
        result['gate']['verification_aggregation'].update(
            verification_routes=[route], actual_passes=[route], skipped_not_applicable=[])
        result['builder']['tool_evidence'] = [{'tool': 'verify_web_app', 'target': 'index.html',
                                             'result': json.dumps(native)}]
        return task, result, module.create_verified_child_receipt(
            task, result, parent_id='PARENT', parent_contract=fixture.parent_contract, workspace=workspace)
    try:
        with patch.object(mini, 'browser_launch_kwargs', return_value={'headless': True, 'executable_path': browser}), \
             patch.object(mini, 'ask_ollama', side_effect=AssertionError('No model')), \
             patch.object(mini, 'structured_model_call', side_effect=AssertionError('No model')):
            native = mini.verify_browser_application('index.html', 'A', profile=infer_web_profile('Browser counter'))
            before_behavior = independent()
            task, result, receipt = receipt_for(gate, native)
            _, _, old_receipt = receipt_for(baseline, native)
            def readiness(r):
                return gate.assess_integration_readiness(
                    fixture.parent, [(task, result)], {'A': r},
                    parent_contract=fixture.parent_contract, validated_child_plan=fixture.plan[:1],
                    workspace=workspace)
            ready_before = readiness(receipt)
            (workspace / 'app.js').write_text('// inert replacement after browser verification', encoding='utf-8')
            broken_behavior = independent()
            broken_native = mini.verify_browser_application('index.html', 'A', profile=infer_web_profile('Browser counter'))
            old_fresh = baseline.receipt_freshness(old_receipt, workspace)
            new_fresh = gate.receipt_freshness(receipt, workspace)
            ready_after = readiness(receipt)
            # Test-driver restoration, explicitly not an authorized agent Repairer run.
            (workspace / 'app.js').write_text(SCRIPT + '\n// fresh restored fixture', encoding='utf-8')
            restored_native = mini.verify_browser_application('index.html', 'A', profile=infer_web_profile('Browser counter'))
            restored_behavior = independent()
            _, _, restored_receipt = receipt_for(gate, restored_native)
            ready_restored = readiness(restored_receipt)
        checks = {'native_before_pass': native['passed'], 'behavior_before_pass': before_behavior['passed'],
                  'ready_before': ready_before['readiness'] == gate.READY,
                  'broken_behavior_rejected': not broken_behavior['passed'],
                  'clean_load_alone_still_insufficient': broken_native['passed'],
                  'baseline_stale_false_fresh_reproduced': old_fresh['fresh'],
                  'new_receipt_stale': not new_fresh['fresh'],
                  'parent_not_ready_after_change': ready_after['reason'] == gate.NOT_READY_STALE_EVIDENCE,
                  'restored_behavior': restored_behavior['passed'],
                  'fresh_restored_ready': ready_restored['readiness'] == gate.READY}
        report = {'checks': checks, 'successful': all(checks.values()),
                  'before_behavior': before_behavior, 'broken_behavior': broken_behavior,
                  'restored_behavior': restored_behavior,
                  'native_results': {'before': native, 'broken': broken_native, 'restored': restored_native},
                  'baseline_freshness': old_fresh, 'treatment_freshness': new_fresh,
                  'readiness': {'before': ready_before, 'broken': ready_after, 'restored': ready_restored},
                  'scope': 'Real Chromium/actions/native browser/receipt/readiness. Planned authority scripted. Test-driver mutation/restoration, not an agent task, authorized Repairer or root acceptance.',
                  'argv': sys.argv, 'python': sys.version,
                  'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                    for p in ['mini.py', 'hivo/integration_gate.py', 'scripts/browser_freshness_functional.py']},
                  'retained_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in workspace.iterdir() if p.is_file()}}
        (out / 'results.json').write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
        print(json.dumps(checks))
        return int(not all(checks.values()))
    finally:
        fixture.tearDown()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
