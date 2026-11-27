"""Bounded declarative browser oracles, source-bound independently of Builder.

This module grants no implementation authority and executes no generated test
code or shell commands. Unsupported semantics remain uncovered.
"""
import functools
import http.server
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit, quote

from hivo.integration_gate import canonical_hash, derive_evidence_dependency_paths, fingerprint_dependency_paths

UNCOVERED = 'VERIFICATION_OBLIGATION_UNCOVERED'
FAILED = 'BEHAVIORAL_VERIFICATION_FAILED'
MAX_ORACLES = 64
MAX_STEPS = 32
STEP_KEYS = {
    'click': {'action', 'selector'}, 'fill': {'action', 'selector', 'value'},
    'check': {'action', 'selector'}, 'uncheck': {'action', 'selector'}, 'reload': {'action'},
    'assert_text': {'action', 'selector', 'expected'}, 'assert_count': {'action', 'selector', 'expected'},
    'assert_value': {'action', 'selector', 'expected'}, 'assert_checked': {'action', 'selector', 'expected'},
    'assert_visible': {'action', 'selector', 'expected'},
}


def safe_relative(root, raw):
    if not isinstance(raw, str) or not raw or any(c in raw for c in ('\0', '\n', '\r', '?', '#')):
        return None
    p = Path(raw)
    if p.is_absolute() or '..' in p.parts or any(x.casefold() in {'.git', '.hivo'} or x.startswith('.agent') for x in p.parts):
        return None
    try:
        (root / p).resolve().relative_to(root)
    except (ValueError, OSError):
        return None
    return p.as_posix()


def file_only(record):
    text = record['text']
    names = [x for x in record.get('explicit_items', []) if isinstance(x, str) and Path(x).suffix]
    if not names:
        return False
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, '')
    # Do not reduce a compound behavior/content requirement to file existence.
    return bool(re.fullmatch(r'\s*(?:Create|Generate|Provide)\s+(?:(?:the|files?|and)\b|[\s`,.;])+', text, re.I))


def validate(records, ids, oracles, root):
    source = {r['requirement_id']: r for r in records}
    errors = []
    covered = set()
    files = {}
    if not isinstance(oracles, list) or not 1 <= len(oracles) <= MAX_ORACLES:
        return ['missing or unbounded verification obligations']
    for oracle in oracles:
        if not isinstance(oracle, dict):
            errors.append('malformed obligation')
            continue
        key = oracle.get('requirement_id')
        record = source.get(key)
        target = safe_relative(root, oracle.get('target'))
        if record is None or key not in ids or oracle.get('source_text') != record['text'] or target is None:
            errors.append('wrong source, owner, source text or unsafe target')
            continue
        kind = oracle.get('kind')
        if kind == 'file_exists':
            if not file_only(record) or target not in record.get('explicit_items', []):
                errors.append('file existence cannot certify source behavior or content')
                continue
            files.setdefault(key, set()).add(target)
        elif kind == 'browser_scenario':
            if not re.search(r'\b(?:click\w*|press\w*|select\w*|toggl\w*|mark|add|remov\w*|delet\w*|updat\w*|chang\w*|increment\w*|persist\w*|reload|refresh|save|retain\w*)\b', record['text'], re.I):
                errors.append('unsupported source meaning; scenario cannot invent coverage')
                continue
            if Path(target).suffix.casefold() not in {'.html', '.htm'}:
                errors.append('scenario must name an HTML entry')
                continue
            steps = oracle.get('steps')
            if not isinstance(steps, list) or not 2 <= len(steps) <= MAX_STEPS:
                errors.append('missing or unbounded action/assertion scenario')
                continue
            seen_action = False
            observed = {}
            changed_assertion = False
            invalid = False
            for step in steps:
                action = step.get('action') if isinstance(step, dict) else None
                if action not in STEP_KEYS or set(step) != STEP_KEYS[action]:
                    invalid = True
                    break
                if action != 'reload' and (not isinstance(step.get('selector'), str) or not 1 <= len(step['selector']) <= 240):
                    invalid = True
                    break
                if action.startswith('assert_'):
                    expected = step['expected']
                    if action in {'assert_visible', 'assert_checked'} and type(expected) is not bool:
                        invalid = True
                    if action == 'assert_count' and (type(expected) is not int or expected < 0):
                        invalid = True
                    if action in {'assert_text', 'assert_value'} and (not isinstance(expected, str) or len(expected) > 1000):
                        invalid = True
                    identity = (action, step['selector'])
                    if seen_action and action != 'assert_visible' and identity in observed and observed[identity] != expected:
                        changed_assertion = True
                    observed[identity] = expected
                else:
                    seen_action = True
                    if action == 'fill' and (not isinstance(step['value'], str) or len(step['value']) > 1000):
                        invalid = True
            reload_required = bool(re.search(r'\b(?:persist\w*|reload|refresh)\b', record['text'], re.I))
            if invalid or not changed_assertion or not steps[-1].get('action', '').startswith('assert_'):
                errors.append('behavior needs a bounded action and asserted observable state transition')
                continue
            if reload_required and not any(s['action'] == 'reload' for s in steps):
                errors.append('persistence requirement lacks reload verification')
                continue
        else:
            errors.append('unsupported oracle kind')
            continue
        covered.add(key)
    for key in ids:
        if key not in covered:
            errors.append('uncovered obligation: ' + key)
        elif file_only(source[key]) and set(source[key].get('explicit_items', [])) - files.get(key, set()):
            errors.append('required files incompletely verified: ' + key)
    return errors


def verify(workspace, records, ids, oracles, launch_kwargs, *, allowed_paths):
    root = Path(workspace).resolve()
    errors = validate(records, ids, oracles, root)
    report = {'passed': False, 'failure_type': UNCOVERED, 'errors': errors,
              'source_hash': canonical_hash(records), 'obligation_hash': canonical_hash(oracles), 'checks': []}
    if errors:
        return report
    status = {}
    dependencies = derive_evidence_dependency_paths(
        verification_evidence=[{'target': o['target']} for o in oracles], workspace=root, derivation_status=status)
    allowed = set()
    for raw in allowed_paths:
        try:
            path = Path(raw)
            relative = path.resolve().relative_to(root).as_posix() if path.is_absolute() else raw
            normalized = safe_relative(root, relative)
            if normalized:
                allowed.add(normalized)
        except (ValueError, OSError, TypeError):
            continue
    if not status.get('complete') or any(p not in allowed for p in dependencies):
        report['errors'] = ['unbounded or unauthorized verification dependency']
        return report
    before = fingerprint_dependency_paths(root, dependencies)
    report['subject_before'] = before
    browser_oracles = [o for o in oracles if o['kind'] == 'browser_scenario']
    for o in oracles:
        if o['kind'] == 'file_exists':
            report['checks'].append({'requirement_id': o['requirement_id'], 'target': o['target'],
                                     'passed': (root / o['target']).is_file()})
    if browser_oracles:
        deadline = time.monotonic() + 20.0
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                path = unquote(urlsplit(self.path).path).lstrip('/')
                if path == 'favicon.ico' and path not in dependencies:
                    self.send_response(204)
                    self.end_headers()
                elif path not in dependencies:
                    self.send_error(404)
                else:
                    super().do_GET()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(**{'timeout': 5000, **launch_kwargs})
                try:
                    for oracle in browser_oracles:
                        context = browser.new_context()
                        try:
                            page = context.new_page()
                            page.set_default_timeout(1500)
                            faults = []
                            page.on('pageerror', lambda e: faults.append(str(e)))
                            page.on('console', lambda m: faults.append(m.text) if m.type == 'error' else None)
                            page.on('response', lambda r: faults.append(str(r.status) + ' ' + r.url) if r.status >= 400 else None)
                            def route(request):
                                url = urlsplit(request.request.url)
                                if (url.scheme + '://' + url.netloc) != origin:
                                    faults.append('external request refused')
                                    request.abort()
                                else:
                                    request.continue_()
                            context.route('**/*', route)
                            page.goto(origin + '/' + quote(oracle['target'], safe='/'), wait_until='load', timeout=5000)
                            from playwright.sync_api import expect
                            for step in oracle['steps']:
                                if time.monotonic() > deadline:
                                    raise TimeoutError('bounded behavioral verification deadline exceeded')
                                action = step['action']
                                locator = page.locator(step['selector']) if 'selector' in step else None
                                if action == 'reload': page.reload(wait_until='load', timeout=5000)
                                elif action == 'click': locator.click()
                                elif action == 'fill': locator.fill(step['value'])
                                elif action == 'check': locator.check()
                                elif action == 'uncheck': locator.uncheck()
                                elif action == 'assert_text': expect(locator).to_have_text(step['expected'], timeout=1200)
                                elif action == 'assert_value': expect(locator).to_have_value(step['expected'], timeout=1200)
                                elif action == 'assert_count': expect(locator).to_have_count(step['expected'], timeout=1200)
                                elif action == 'assert_checked': expect(locator).to_be_checked(checked=step['expected'], timeout=1200)
                                elif action == 'assert_visible':
                                    expect(locator).to_be_visible(timeout=1200) if step['expected'] else expect(locator).not_to_be_visible(timeout=1200)
                            if faults:
                                raise ValueError('; '.join(faults))
                            report['checks'].append({'requirement_id': oracle['requirement_id'], 'target': oracle['target'], 'passed': True})
                        except Exception as exc:
                            report['checks'].append({'requirement_id': oracle['requirement_id'], 'target': oracle['target'],
                                                     'passed': False, 'error': str(exc)[:1200]})
                        finally:
                            context.close()
                finally:
                    browser.close()
        except Exception as exc:
            report['environment_error'] = True
            report['errors'].append(str(exc)[:600])
        finally:
            server.shutdown()
            server.server_close()
    after = fingerprint_dependency_paths(root, dependencies)
    report['subject_after'] = after
    if before != after:
        report['errors'].append('verification subject changed during execution')
    report['passed'] = not report['errors'] and bool(report['checks']) and all(c['passed'] for c in report['checks'])
    report['failure_type'] = None if report['passed'] else FAILED
    report['receipt_hash'] = canonical_hash(report)
    return report
