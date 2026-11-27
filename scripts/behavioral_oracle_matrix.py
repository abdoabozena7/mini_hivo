"""Actual bounded browser oracle matrix; fixture selectors never enter policy."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from hivo import behavioral_obligations as behavior
from m0_characterize import HTML, CSS, js


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    browser = json.loads((ROOT / 'output/m0-characterization/20261120-canonical-005/provenance.json').read_text())['browser_executable']
    source = [
        {'requirement_id': 'R1', 'text': 'Users can add a nonempty row.'},
        {'requirement_id': 'R2', 'text': 'Users can delete the selected row.'},
        {'requirement_id': 'R3', 'text': 'Completion toggles the rendered row state.'},
        {'requirement_id': 'R4', 'text': 'Rows and completion persist after reload.'}]
    add = [{'action': 'assert_count', 'selector': '#taskList li', 'expected': 0},
           {'action': 'fill', 'selector': '#taskInput', 'value': 'Check'},
           {'action': 'click', 'selector': '#addTaskButton'},
           {'action': 'assert_count', 'selector': '#taskList li', 'expected': 1}]
    toggle = add + [{'action': 'assert_count', 'selector': '#taskList li.done', 'expected': 0},
                    {'action': 'check', 'selector': '#taskList input[type=checkbox]'},
                    {'action': 'assert_count', 'selector': '#taskList li.done', 'expected': 1}]
    sequences = [add, add + [{'action': 'click', 'selector': '#taskList button'},
                           {'action': 'assert_count', 'selector': '#taskList li', 'expected': 0}],
                 toggle + [{'action': 'uncheck', 'selector': '#taskList input[type=checkbox]'},
                           {'action': 'assert_count', 'selector': '#taskList li.done', 'expected': 0}],
                 toggle + [{'action': 'reload'}, {'action': 'assert_count', 'selector': '#taskList li', 'expected': 1},
                           {'action': 'assert_text', 'selector': '#taskList li span', 'expected': 'Check'},
                           {'action': 'assert_count', 'selector': '#taskList li.done', 'expected': 1}]]
    oracles = [dict(requirement_id=r['requirement_id'], source_text=r['text'], target='index.html',
                    kind='browser_scenario', steps=s) for r, s in zip(source, sequences)]
    results = {}
    for mode in ('full', 'inert', 'no_add', 'no_delete', 'no_toggle', 'no_persistence', 'runtime_error', 'missing_js', 'disconnected'):
        workspace = out / mode
        workspace.mkdir()
        (workspace / 'index.html').write_text(HTML.replace('<script src="app.js"></script>', '') if mode == 'disconnected' else HTML)
        (workspace / 'style.css').write_text(CSS)
        if mode != 'missing_js':
            (workspace / 'app.js').write_text(js(mode if mode != 'disconnected' else 'full'))
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in workspace.iterdir()}
        actual = behavior.verify(workspace, source, [r['requirement_id'] for r in source], oracles,
            {'headless': True, 'executable_path': browser}, allowed_paths=['index.html', 'style.css', 'app.js'])
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in workspace.iterdir()}
        results[mode] = {'expected_pass': mode == 'full', 'actual': actual, 'files_unchanged': before == after}
        print(mode, actual['passed'], flush=True)
    checks = {mode: (r['actual']['passed'] == r['expected_pass'] and r['files_unchanged']) for mode, r in results.items()}
    (out / 'results.json').write_text(json.dumps({'checks': checks, 'results': results,
        'source': source, 'oracles': oracles, 'scope': 'Real Chromium and production adapter on explicit positive/negative fixtures; not agent-generated or root-accepted.',
        'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                          for p in ['hivo/behavioral_obligations.py', 'scripts/behavioral_oracle_matrix.py']}}, indent=2), encoding='utf-8')
    return int(not all(checks.values()))


if __name__ == '__main__':
    raise SystemExit(main())
