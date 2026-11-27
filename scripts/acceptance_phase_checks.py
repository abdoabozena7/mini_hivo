"""Exclusive-output selected offline acceptance checks; never discover live tests."""
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
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('modules', nargs='+')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'tmp').mkdir()
    tempfile.tempdir = str(out / 'tmp')
    os.environ['TEMP'] = os.environ['TMP'] = tempfile.tempdir
    with (out / 'tests.log').open('x', encoding='utf-8') as stream, \
         patch.object(mini, 'ask_ollama', side_effect=AssertionError('No provider')), \
         patch.object(mini, 'structured_model_call', side_effect=AssertionError('No provider')), \
         patch.object(mini, 'http_post_json', side_effect=AssertionError('No provider HTTP')), \
         patch.object(mini, 'http_get_json', side_effect=AssertionError('No provider HTTP')):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromNames(args.modules))
    sources = [ROOT / 'mini.py'] + list((ROOT / 'hivo').glob('*.py'))
    sources += [ROOT / 'tests' / (m.split('.')[0] + '.py') for m in args.modules]
    report = {'tests': result.testsRun, 'failures': [(str(t), s) for t, s in result.failures],
              'errors': [(str(t), s) for t, s in result.errors], 'skipped': result.skipped,
              'successful': result.wasSuccessful(), 'modules': args.modules, 'argv': sys.argv,
              'python': sys.version, 'source_sha256': {p.relative_to(ROOT).as_posix():
                  hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.exists()}}
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped)}))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    raise SystemExit(main())
