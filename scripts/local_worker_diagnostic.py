"""One bounded local qualification/coding probe; never cloud or a campaign."""
import argparse
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hivo import http_client
from hivo.model_routing import RoleRouter, RoutingConfig
from hivo.provider_preflight import qualify, resource_guard
from hivo.providers import ModelSelection, ProviderClient, ProviderFailure


def validate_source(source):
    """Exact pure-function AST before executing any provider-produced Python."""
    if not isinstance(source, str) or len(source) > 1024:
        raise ProviderFailure('CODING_ORACLE_FAILED')
    try:
        tree = ast.parse(source)
    except SyntaxError:
        raise ProviderFailure('CODING_ORACLE_FAILED') from None
    expected = ast.parse('def increment(value):\n    return value + 1\n')
    if ast.dump(tree, include_attributes=False) != ast.dump(expected, include_attributes=False):
        raise ProviderFailure('CODING_ORACLE_FAILED')
    namespace = {}
    exec(compile(tree, 'probe.py', 'exec'), {'__builtins__': {}}, namespace)
    if [namespace['increment'](v) for v in (0, 2, -1)] != [1, 3, 0]:
        raise ProviderFailure('CODING_ORACLE_FAILED')
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 90
    def bounded(call):
        def invoke(url, **kwargs):
            if not url.startswith('http://127.0.0.1:11434/'):
                raise ProviderFailure('LOCAL_DIAGNOSTIC_ENDPOINT_DENIED')
            remaining = deadline - time.monotonic()
            if remaining < 1:
                raise ProviderFailure('DIAGNOSTIC_DEADLINE')
            kwargs['timeout'] = min(kwargs.get('timeout', 15), 15, remaining)
            return call(url, **kwargs)
        return invoke
    spec = ModelSelection('ollama', args.model, context=4096, max_output=128,
                          reasoning='off', timeout=15, retries=0, keep_alive='30s')
    client = ProviderClient(get=bounded(http_client.get_json), post=bounded(http_client.post_json), request_budget=6)
    router = RoleRouter(RoutingConfig(spec, spec, request_budget=6), client)
    result = {'status': 'BLOCKED', 'scope': 'Local qualification and one pure coding/tool probe; not autonomous application acceptance'}
    try:
        report = qualify(router, out)
        result['qualification'] = report
        if report['passed']:
            tool = {'type': 'function', 'function': {'name': 'propose_python_function',
                'description': 'Propose a single pure Python function.', 'parameters': {
                    'type': 'object', 'properties': {'path': {'type': 'string'}, 'source': {'type': 'string'}},
                    'required': ['path', 'source'], 'additionalProperties': False}}}
            answer = router.chat('Builder', [{'role': 'user', 'content':
                'Call propose_python_function with path probe.py and source exactly a Python function named increment, with one argument value, returning value + 1. No imports, annotations, decorators or other statements.'}], tools=[tool])
            calls = answer.get('tool_calls', [])
            if len(calls) != 1 or calls[0]['function']['name'] != 'propose_python_function':
                raise ProviderFailure('CODING_TOOL_CALL_FAILED')
            data = calls[0]['function']['arguments']
            if set(data) != {'path', 'source'} or data['path'] != 'probe.py':
                raise ProviderFailure('CODING_SCOPE_FAILED')
            source = validate_source(data['source'])
            (out / 'probe.py').write_text(source, encoding='utf-8')
            result.update(status='PASS', code_sha256=hashlib.sha256((out / 'probe.py').read_bytes()).hexdigest(),
                          oracle={'inputs': [0, 2, -1], 'outputs': [1, 3, 0]}, resources_after=resource_guard(spec))
        else:
            result['failure_reason'] = report['failure_reason']
    except ProviderFailure as exc:
        result.update(status='FAILED', failure_reason=exc.code)
    finally:
        result['inference_requests'] = client.requests
        result['source_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in [Path(__file__).resolve()] + list((ROOT / 'hivo').glob('*.py'))}
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result.get(k) for k in ('status', 'failure_reason', 'inference_requests')}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
