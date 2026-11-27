"""Independent structural readback of controlled packet captures; no providers.

Does not import the production compactor. Original records remain untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def decode_objects(text):
    if text.startswith('Object syntax:'):
        text = text.split('\n', 1)[1]
        lexer = r'"(?:\\.|[^"\\])*"|\b[A-Za-z_][A-Za-z_0-9]*(?=\s*:)'
        text = '\n'.join(re.sub(lexer, lambda m: m[0] if m[0].startswith('"') else json.dumps(m[0]), line)
                         if line.startswith(('{', '[')) else line for line in text.split('\n'))
    if text.startswith('Exact text macros;'):
        _, definition, text = text.split('\n', 2)
        macros = json.loads(definition)
        for _ in range(12):
            before = text
            for key, value in macros.items(): text = text.replace(key, value)
            if text == before: break
    lines = text.split('\n')
    definitions = json.loads(lines[1]) if lines and lines[0].startswith('Exact JSON') else {}
    def expand(value, seen=()):
        if isinstance(value, dict):
            if set(value) == {'$ref'}:
                name = value['$ref']
                assert name in definitions and name not in seen, 'invalid/cyclic JSON reference'
                return expand(definitions[name], seen + (name,))
            if '$base' in value:
                name = value['$base']
                assert name in definitions and name not in seen, 'invalid/cyclic object base'
                base = expand(definitions[name], seen + (name,))
                extra = {k: expand(v, seen) for k, v in value.items() if k != '$base'}
                assert isinstance(base, dict) and not set(base).intersection(extra), 'object base override'
                return dict(base, **extra)
            return {k: expand(v, seen) for k, v in value.items()}
        if isinstance(value, list): return [expand(v, seen) for v in value]
        return value
    values = []
    for line in lines[2:] if definitions else lines:
        try: value = json.loads(line)
        except ValueError: continue
        if isinstance(value, (dict, list)): values.append(expand(value))
    return values


def audit(folder):
    result = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    audits = json.loads((folder / 'packet-audit.json').read_text(encoding='utf-8'))
    packets = json.loads((folder / 'packets.json').read_text(encoding='utf-8'))
    checked_objects = checked_refs = checked_history = checked_scopes = checked_oracles = 0
    assert audits, 'no worker compaction evidence'
    for entry in audits:
        assert entry['compacted_messages'] is not None, 'compaction failed'
        records = entry['evidence']
        for digest, raw in records.items():
            assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == digest, 'corrupt immutable record'
            checked_refs += 1
        def read(reference):
            raw = records[reference['sha256']]
            assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == reference['sha256']
            return json.loads(raw)
        def original_values(value):
            if isinstance(value, dict):
                if set(value) == {'$json_text', 'parsed'}:
                    raw = read(value['$json_text'])
                    source = json.loads(raw)
                    def restore_at(view, path=()):
                        if isinstance(view, dict):
                            if '$at' in view:
                                original = source
                                pointer = path if view['$at'] is True else view['$at']
                                assert isinstance(pointer, (list, tuple)), 'invalid diagnostic reference'
                                for key in pointer: original = original[key]
                                if 'hash' in view: assert view['hash'] == original['hash'], 'snapshot hash altered'
                                if 'head' in view: assert original.startswith(view['head']), 'diagnostic prefix altered'
                                if 'view' in view:
                                    assert all(original.get(k) == v for k, v in view['view'].items()), 'diagnostic state altered'
                                return original
                            return {k: restore_at(v, path + (k,)) for k, v in view.items()}
                        if isinstance(view, list): return [restore_at(v, path + (i,)) for i, v in enumerate(view)]
                        return view
                    assert source == restore_at(value['parsed']), 'parsed evidence lost data'
                    return raw
                return {k: original_values(v) for k, v in value.items()}
            if isinstance(value, list): return [original_values(v) for v in value]
            return value
        reconstructed_history, originals, recovered = [], [], []
        for message in entry['original_messages']:
            if message.get('role') == 'user': originals.extend(decode_objects(message.get('content', '')))
        for message in entry['compacted_messages']:
            if message.get('role') in {'assistant', 'tool'}:
                reconstructed_history.append(message)
            if message.get('role') != 'user': continue
            for value in decode_objects(message.get('content', '')):
                value = original_values(value)
                recovered.append(value)
                if not isinstance(value, dict): continue
                if 'complete_projection' in value: recovered.append(original_values(read(value['complete_projection'])))
                if 'complete_mission' in value: recovered.append(original_values(read(value['complete_mission'])))
                if 'complete_impact' in value:
                    recovered.append(original_values(read(value['complete_impact'])))
                    assert value['execution_authority'] == entry['authority'], 'authority changed in projection'
                if 'historical_tool_exchange' in value:
                    span = read(value['historical_tool_exchange'])
                    reconstructed_history.extend(span)
                    if 'gate_receipt' in value:
                        gates = [json.loads(m['content']) for m in span if m.get('role') == 'tool' and m.get('tool_name') == 'context_sufficiency_check']
                        assert gates, 'gate source missing'
                        gate = gates[-1]
                        expected = {k: v for k, v in gate.items()
                            if not (k in {'history', 'semantic_resolutions', 'evidence'} and v in (None, []))}
                        assert value['gate_receipt'] == expected, 'gate state/limits changed'
        for value in originals:
            assert value in recovered, 'source JSON object was lost or altered'
            checked_objects += 1
        actual_history = [m for m in entry['original_messages'] if m.get('role') in {'assistant', 'tool'}]
        assert reconstructed_history == actual_history, 'tool arguments/results/history order changed'
        checked_history += len(actual_history)
        original_tools = {t['function']['name']: t['function'] for t in entry['original_tools']}
        compacted_tools = {t['function']['name']: t['function'] for t in entry['compacted_tools']}
        assert set(original_tools) <= set(compacted_tools), 'permitted tool lost'
        for name, definition in original_tools.items():
            assert definition['parameters'] == compacted_tools[name]['parameters'], 'tool arguments/schema changed'
        authority = entry['authority']
        if authority is not None:
            source = entry['source_tool_contract'] or {}
            assert authority['read_paths'] == source.get('allowed_inspection_paths'), 'read scope changed'
            candidate = (entry['task'] or {}).get('impact_contract_candidate') or (entry['task'] or {}).get('impact_contract') or {}
            expected_write = [] if entry['role'] == 'falsifier' else candidate.get('authorized_mutation_paths')
            assert authority['write_paths'] == expected_write, 'write scope changed'
            checked_scopes += 1
        owned = entry['ownership']
        if owned is not None:
            task = entry['task']
            assert owned['requirement_ids'] == task.get('requirement_ids', []), 'requirement ownership changed'
            assert read(owned['oracles']) == task.get('verification_obligations', []), 'oracle changed'
            checked_oracles += len(task.get('verification_obligations', []))
    worker_packets = [p for p in packets if re.sub('[^a-z]', '', p['role'].lower()) in {'builder', 'falsifier', 'repairer'}]
    assert len(worker_packets) == len(audits), 'dispatch/audit count differs'
    metrics = []
    for packet, entry in zip(worker_packets, audits):
        count = (len(json.dumps({k: packet[k] for k in ('messages', 'tools', 'format')}, ensure_ascii=False)) + 2) // 3
        assert count + 1024 <= 4096, 'packet exceeds fixed context/output budget'
        permitted = {t['function']['name']: t['function'] for t in entry['compacted_tools']}
        for native in packet['tools']:
            function = native['function']
            assert function['name'] in permitted, 'native tool outside current runtime permission set'
            assert function['parameters'] == permitted[function['name']]['parameters'], 'native schema changed'
        metrics.append(count)
    return {'passed': True, 'packets': len(audits), 'source_json_objects_preserved': checked_objects,
            'digest_records_checked': checked_refs, 'history_messages_preserved': checked_history,
            'scope_comparisons': checked_scopes, 'assigned_oracles_preserved': checked_oracles,
            'first_input_tokens': metrics[0], 'max_input_tokens': max(metrics),
            'context': 4096, 'output_reserve': 1024, 'root_status': result['root_result']['status'],
            'scope': 'Independent structural/contract audit of captured controlled packets, not live-model proof'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.run_dir)
    with (args.run_dir / 'independent-packet-audit.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2); stream.write('\n')
    print(json.dumps(report))


if __name__ == '__main__': main()
