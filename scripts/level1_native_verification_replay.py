"""Provider-free Level 1 functional replay with real gates, tools and filesystem.

Only model responses are scripted. Output must be a fresh disposable directory.
This does not measure live-model reliability.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mini


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--request', default='Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo')
    parser.add_argument('--expected-text', default='Hello Mini Hivo',
                        help='Independent exact-byte oracle; the target remains test_level_1.txt')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    mini._load_optional_imports()
    mini.WORKSPACE = workspace
    mini.reset_run('baseline')
    mini.RUN['project_mode'] = mini.NEW_PROJECT
    goal = args.request
    expected_bytes = args.expected_text.encode('utf-8')
    with patch.object(mini, 'structured_model_call', side_effect=mini.StructuredOutputError('offline replay')):
        contract = mini.get_goal_contract(goal, interactive=False)
    mini.ACTIVE_CONTRACT = contract
    mini.ACTIVE_TOOL_CONTRACT = contract

    def call(name, **arguments):
        return {'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': name, 'arguments': arguments}}]}

    done = {'role': 'assistant', 'content': 'Native exact-byte readback completed.', 'tool_calls': []}
    replies = [call('context_sufficiency_check', context_status='sufficient',
                    reason='The source defines the complete single literal text artifact.'),
               call('write_file', path='test_level_1.txt', content=args.expected_text),
               call('run_command', command='cat test_level_1.txt'),
               call('run_command', command='echo test_level_1.txt'),
               call('run_file', path='test_level_1.txt'), done,
               call('run_file', path='test_level_1.txt'), done]
    with patch.object(mini, 'ask_ollama', side_effect=replies):
        result, _ = mini.run_baseline_request(goal, {}, contract_override=contract,
                                             repo_snapshot={'files': []}, finish=False)
    target = workspace / 'test_level_1.txt'
    actual = target.read_bytes() if target.exists() else None
    summary = {
        'verification_class': 'CONTROLLED_FUNCTIONAL_REAL_GATES_AND_FILESYSTEM',
        'request': goal, 'scripted_provider_responses': len(replies), 'real_model_calls': 0,
        'status': result.get('status'), 'root_verified': mini.RUN.get('root_verified'),
        'file_exists': actual is not None, 'actual_hex': actual.hex() if actual is not None else None,
        'exact_bytes': actual == expected_bytes,
        'expected_hex': expected_bytes.hex(),
        'actual_sha256': hashlib.sha256(actual).hexdigest() if actual is not None else None,
        'expected_sha256': hashlib.sha256(expected_bytes).hexdigest(),
        'impact_comparison': result.get('impact_comparison'),
        'verification_aggregation': (result.get('gate') or {}).get('verification_aggregation'),
        'falsifier_native_readbacks': sum(e.get('tool') == 'run_file'
                                         for e in result.get('falsifier', {}).get('tool_evidence', [])),
        'production_source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                     for p in ['mini.py', 'hivo/requirements.py', 'hivo/verification_routing.py']},
    }
    (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ['status', 'root_verified', 'file_exists', 'exact_bytes',
                                            'actual_sha256', 'falsifier_native_readbacks']}, indent=2))
    return 0 if (summary['status'] == 'done' and summary['root_verified']
                 and summary['exact_bytes'] and summary['falsifier_native_readbacks']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
