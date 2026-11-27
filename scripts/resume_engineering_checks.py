"""Selected offline cohort with fresh workspace-local output and no model access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import mini


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    temporary = out / 'tmp'
    temporary.mkdir()
    tempfile.tempdir = str(temporary)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    names = ['test_browser_dependency_freshness', 'test_manifest_path_identity',
             'test_verified_manifest_provenance',
             'test_adaptive_architecture', 'test_verified_child_integration',
             'test_verification_outcome_integrity', 'test_run4_scope_regression',
             'test_repair_cycle_001', 'test_browser_requirement_authority']
    with (out / 'tests.log').open('x', encoding='utf-8') as stream, \
         patch.object(mini, 'ask_ollama', side_effect=AssertionError('No model')), \
         patch.object(mini, 'structured_model_call', side_effect=AssertionError('No model')), \
         patch.object(mini, 'http_post_json', side_effect=AssertionError('No provider HTTP')), \
         patch.object(mini, 'http_get_json', side_effect=AssertionError('No provider HTTP')):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromNames(names))
    sources = ['mini.py', 'hivo/integration_gate.py',
               'tests/test_browser_dependency_freshness.py', 'scripts/resume_engineering_checks.py']
    report = {'modules': names, 'tests': result.testsRun,
              'failures': [(str(t), s) for t, s in result.failures],
              'errors': [(str(t), s) for t, s in result.errors], 'skips': result.skipped,
              'successful': result.wasSuccessful(), 'argv': sys.argv, 'python': sys.version,
              'scope': 'Selected offline controls; scripted model decisions, real tools/gates where declared.',
              'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('tests', 'successful', 'skips')}))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())
