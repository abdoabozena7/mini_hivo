"""Offline structural oracles for exact packet values and scoped schema paging."""
import copy
import hashlib
import json
import re
from pathlib import Path
import unittest

from hivo import worker_packets as wp
from hivo.providers import ProviderFailure, ProviderClient, ModelSelection, ModelInfo

FIXTURE = Path(__file__).parent / 'fixtures/worker-packet/oversized.json'


def read_all(store, reference):
    offset, chunks = 0, []
    while True:
        row = store.read(reference['sha256'], offset)
        chunks.append(row['content'])
        offset = row['next_offset']
        if offset is None: break
    raw = ''.join(chunks)
    assert hashlib.sha256(raw.encode('utf-8')).hexdigest() == reference['sha256']
    return json.loads(raw)


def expand_text(text):
    if text.startswith('Object syntax:'):
        text = text.split('\n', 1)[1]
        # Independent lexer: quote bare keys only outside JSON strings.
        pattern = r'"(?:\\.|[^"\\])*"|\b[A-Za-z_][A-Za-z_0-9]*(?=\s*:)'
        text = '\n'.join(re.sub(pattern, lambda m: m[0] if m[0].startswith('"') else json.dumps(m[0]), line)
                         if line.startswith(('{', '[')) else line for line in text.split('\n'))
    if text.startswith('Exact text macros;'):
        _, data, text = text.split('\n', 2)
        definitions = json.loads(data)
        for _ in range(12):
            previous = text
            for marker, value in definitions.items(): text = text.replace(marker, value)
            if text == previous: break
    return text


def objects(text):
    text = expand_text(text)
    lines = text.splitlines()
    definitions = json.loads(lines[1]) if lines and lines[0].startswith('Exact JSON') else {}
    def resolve(value, seen=()):
        if isinstance(value, dict):
            if set(value) == {'$ref'}:
                name = value['$ref']
                assert name in definitions and name not in seen
                return resolve(definitions[name], seen + (name,))
            if '$base' in value:
                name = value['$base']
                assert name in definitions and name not in seen
                base = resolve(definitions[name], seen + (name,))
                extra = {k: resolve(v, seen) for k, v in value.items() if k != '$base'}
                assert isinstance(base, dict) and not set(base).intersection(extra)
                return dict(base, **extra)
            return {k: resolve(v, seen) for k, v in value.items()}
        if isinstance(value, list): return [resolve(v, seen) for v in value]
        return value
    result = []
    for line in lines[2:] if definitions else lines:
        try: result.append(resolve(json.loads(line)))
        except ValueError: pass
    return result


class WorkerPacketTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def current(self):
        row = copy.deepcopy(self.fixture)
        row['messages'][0]['content'] = wp.system_instructions('Builder', 'window.AGENT_GAME') + wp.CONTEXT_INSTRUCTION + wp.IMPACT_INSTRUCTION
        content = row['messages'][1]['content']
        start = content.index('Absent assigned files are outputs')
        end = content.index('\n\nROOT CONTRACT:', start)
        row['messages'][1]['content'] = content[:start] + wp.CREATION_INSTRUCTION + content[end:]
        store = wp.PacketEvidence()
        paths = ['index.html', 'style.css', 'app.js']
        store.authority = {'write_paths': paths, 'read_paths': paths,
                           'scope_is_exhaustive': True, 'worker_claims_grant_no_authority': True}
        owned = row['ownership']
        store.obligations = {'task_id': owned['id'], 'requirement_ids': owned['requirement_ids'],
                             'oracles': store.put(owned['verification_obligations'])}
        return row, store

    def test_original_real_packet_exceeds_unchanged_budget(self):
        f = self.fixture
        count = (len(json.dumps({k: f[k] for k in ('messages', 'tools', 'format')}, ensure_ascii=False)) + 2) // 3
        self.assertEqual(count, 3769)
        self.assertEqual(count + 1024 - 4096, 697)

    def test_real_packet_fits_with_full_contracts_and_unchanged_schemas(self):
        row, store = self.current()
        before = copy.deepcopy(row)
        messages, tools = wp.compact(row['messages'], row['tools'], store)
        messages, native = wp.ToolWindow().project(messages, tools)
        count = (len(json.dumps({'messages': messages, 'tools': native, 'format': None}, ensure_ascii=False)) + 2) // 3
        self.assertLessEqual(count + 1024, 4096)
        self.assertEqual(row, before)
        declared = {t['function']['name']: t for t in tools}
        for original in row['tools']:
            actual = declared[original['function']['name']]
            self.assertEqual(actual['function']['parameters'], original['function']['parameters'])
        decoded = objects(messages[2]['content'])
        original_objects = objects(row['messages'][1]['content'])
        root = next(v for v in original_objects if isinstance(v, dict) and 'source_requirement_ids' in v)
        self.assertIn(root, decoded)
        for value in decoded:
            if isinstance(value, dict) and 'complete_impact' in value:
                full = read_all(store, value['complete_impact'])
                self.assertIn(full, original_objects)
                self.assertEqual(value['execution_authority'], store.authority)
                self.assertEqual(value['verification_obligations'], full['verification_obligations'])
            if isinstance(value, dict) and 'complete_projection' in value:
                self.assertIn(read_all(store, value['complete_projection']), original_objects)
            if isinstance(value, dict) and 'complete_mission' in value:
                self.assertIn(read_all(store, value['complete_mission']), original_objects)
        self.assertEqual(read_all(store, store.obligations['oracles']), row['ownership']['verification_obligations'])
        self.assertEqual(store.obligations['requirement_ids'], row['ownership']['requirement_ids'])

    def test_exact_requirements_and_unknown_repair_text_survive(self):
        text = 'REPAIR LIMIT=2; attempt=1; preserve user data; obligation=REQ-91\n' + json.dumps({
            'requirements': ['REQ-91: preserve  two spaces\nand exact bytes'], 'write_paths': [],
            'read_paths': ['module.rs'], 'prerequisites': ['child-a', 'child-b'], 'repair_history': [{'attempt': 1, 'failed': True}]})
        rows, _ = wp.compact([{'role': 'user', 'content': text}], [], wp.PacketEvidence())
        self.assertEqual(objects(rows[0]['content']), objects(text))
        self.assertIn('REPAIR LIMIT=2; attempt=1;', rows[0]['content'])

    def test_multi_language_paths_are_losslessly_factored(self):
        for path in ['src/main.py', 'web/main.js', 'src/engine.cpp', 'src/lib.rs', 'config/settings.json']:
            with self.subTest(path=path):
                root = 'D:\\test\\long-project-directory\\nested-project'
                original = json.dumps({'read_paths': [root + '\\' + path] * 3, 'write_paths': [],
                                       'requirements': ['Read ' + root + '\\' + path] * 3})
                compacted = wp.text_macros(original, root)
                self.assertEqual(expand_text(compacted), original)
                self.assertEqual(json.loads(expand_text(compacted))['write_paths'], [])

    def test_ambiguous_macro_marker_is_not_reinterpreted(self):
        text = '@W@ is literal required source text ' * 20
        self.assertEqual(wp.text_macros(text, 'D:/anything'), text)

    def test_literal_json_file_read_is_not_reformatted(self):
        raw = '{ "key" : "literal  content" }\n'
        rows, _ = wp.compact([{'role': 'tool', 'tool_name': 'read_file', 'content': raw}], [])
        self.assertEqual(rows[0]['content'], raw)

    def test_all_scope_restrictions_are_preserved_by_exact_reference(self):
        value = {'authorized_mutation_paths': [], 'forbidden_or_out_of_scope': ['secrets/'],
                 'required_preservations': [{'path': 'data.db', 'sha256': 'a' * 64}],
                 'provenance': [{'source_identity': 'approved:plan', 'revision': 4}],
                 'verification_obligations': [{'id': 'R-1', 'required': True}]}
        store = wp.PacketEvidence()
        self.assertEqual(read_all(store, store.put(value)), value)
        altered = copy.deepcopy(value); altered['authorized_mutation_paths'] = ['secrets/']
        self.assertNotEqual(store.put(value), store.put(altered))

    def test_stale_unknown_and_corrupt_references_fail(self):
        first, second = wp.PacketEvidence(), wp.PacketEvidence()
        ref = first.put({'requirement_id': 'R-1'})
        with self.assertRaisesRegex(ProviderFailure, 'UNKNOWN_OR_STALE'): second.read(ref['sha256'])
        first._values[ref['sha256']] = '{}'
        with self.assertRaisesRegex(ProviderFailure, 'CORRUPT'): first.read(ref['sha256'])

    def test_invalid_offsets_and_reference_limits_fail_closed(self):
        store = wp.PacketEvidence(); ref = store.put({'a': 'b'})
        for offset in [-1, True, '0', 9999]:
            with self.assertRaises(ProviderFailure): store.read(ref['sha256'], offset)
        with self.assertRaisesRegex(ProviderFailure, 'LIMIT'): store.put('x' * 262145)

    def test_chunk_retrieval_restores_exact_unicode_record(self):
        store = wp.PacketEvidence(); value = {'path': 'module.py', 'source': 'λ\n' * 2000}
        self.assertEqual(read_all(store, store.put(value)), value)

    def test_reference_length_is_derived_without_losing_integrity_or_bounds(self):
        store = wp.PacketEvidence()
        value = {'requirement_id': 'R1', 'write_paths': [], 'source': 'λ\n' * 1000}
        reference = store.put(value)
        self.assertEqual(set(reference), {'sha256'})
        raw = wp.canonical(value)
        self.assertEqual(store.read(reference['sha256'])['chars'], len(raw))
        self.assertEqual(read_all(store, reference), value)
        with self.assertRaisesRegex(ProviderFailure, 'INVALID_OFFSET'):
            store.read(reference['sha256'], len(raw) + 1)
        store._values[reference['sha256']] = raw + ' '
        with self.assertRaisesRegex(ProviderFailure, 'CORRUPT'):
            store.read(reference['sha256'])

    def test_schema_window_preserves_every_tool_without_granting_new_ones(self):
        window = wp.ToolWindow(); _, tools = wp.compact([], self.fixture['tools'])
        window.update(tools)
        originals = {t['function']['name']: t for t in tools}
        for name in originals:
            window.select([name]); _, native = window.project([], tools)
            self.assertEqual(native[0], originals[name])
        self.assertEqual(set(window.available), set(originals))

    def test_unknown_mutation_tool_and_excessive_window_are_denied(self):
        window = wp.ToolWindow(); window.update(self.fixture['tools'])
        for request in [['write_file'], ['invent_tool'], [], ['read_file'] * 2,
                        ['read_file', 'run_file', 'run_command', 'list_files']]:
            with self.assertRaisesRegex(ProviderFailure, 'SELECTION_DENIED'): window.select(request)

    def test_stale_schema_selection_does_not_retain_mutation_permission(self):
        window = wp.ToolWindow()
        write = {'type': 'function', 'function': {'name': 'write_file', 'parameters': {'type': 'object'}}}
        window.update([write]); window.select(['write_file'])
        _, native = window.project([], self.fixture['tools'])
        self.assertNotIn('write_file', [t['function']['name'] for t in native])
        with self.assertRaises(ProviderFailure): window.select(['write_file'])

    def test_unpaired_call_is_not_collapsed(self):
        messages = [{'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'write_file', 'arguments': {'path': 'a.py', 'content': 'x' * 2000}}}]}]
        actual, _ = wp.compact(messages, [], wp.PacketEvidence())
        self.assertEqual(actual, messages)

    def test_large_completed_exchange_is_exactly_retrievable(self):
        messages = [{'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'write_file', 'arguments': {'path': 'a.py', 'content': 'x' * 2000}}}]},
            {'role': 'tool', 'tool_name': 'write_file', 'content': 'wrote file: a.py'}]
        store = wp.PacketEvidence(); actual, _ = wp.compact(messages, [], store)
        receipt = objects(actual[0]['content'])[0]
        self.assertEqual(read_all(store, receipt['historical_tool_exchange']), messages)
        self.assertEqual(receipt['calls'][0], ['write_file', 'a.py'])
        self.assertIn('not authority/fresh proof', receipt['status'])

    def test_failure_and_active_repair_evidence_stay_inline(self):
        messages = [{'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': 'edit_file', 'arguments': {'path': 'a.py', 'old': 'x' * 1000, 'new': 'y'}}}]},
            {'role': 'tool', 'tool_name': 'edit_file', 'content': 'error: stale source; preserve R-1'}]
        actual, _ = wp.compact(messages, [], wp.PacketEvidence())
        self.assertEqual(actual, messages)

    def test_noncompactable_required_content_is_still_rejected_before_http(self):
        called = []
        client = ProviderClient(post=lambda *a, **k: called.append(k))
        selection = ModelSelection('ollama', 'any-model:custom', context=4096, max_output=1024)
        info = ModelInfo('ollama', selection.model, frozenset({'completion', 'tools'}), 8192)
        messages, tools = wp.compact([{'role': 'user', 'content': 'MANDATORY ' + 'x' * 20000}], [])
        with self.assertRaisesRegex(ProviderFailure, 'CONTEXT_BUDGET_EXCEEDED'):
            client.chat(selection, info, messages, tools=tools)
        self.assertEqual(called, [])

    def test_provider_and_model_names_do_not_change_packet_generation(self):
        messages = [{'role': 'user', 'content': json.dumps({'requirements': ['R1'], 'write_paths': ['src/core.c']})}]
        outputs = []
        for provider, model in [('ollama', 'custom:one'), ('openrouter', 'vendor/custom:free')]:
            ModelSelection(provider, model)
            outputs.append(wp.compact(messages, self.fixture['tools']))
        self.assertEqual(outputs[0], outputs[1])

    def test_missing_mandatory_contract_field_is_rejected(self):
        for missing in ['goal', 'requirements', 'constraints', 'success_criteria']:
            value = {'goal': 'Build', 'requirements': ['R1'], 'constraints': [], 'success_criteria': ['verified']}
            del value[missing]
            with self.assertRaisesRegex(ProviderFailure, 'REQUIRED_FIELD_MISSING'):
                wp.compact([{'role': 'user', 'content': 'ROOT CONTRACT:\n' + json.dumps(value)}], [])

    def test_truncated_source_requirements_and_ids_are_rejected(self):
        value = {'goal': 'Build', 'requirements': ['R1'], 'constraints': [], 'success_criteria': [],
                 'source_requirement_count': 2, 'source_requirement_ids': ['R1']}
        with self.assertRaisesRegex(ProviderFailure, 'ID_MISMATCH'):
            wp.compact([{'role': 'user', 'content': 'ROOT CONTRACT:\n' + json.dumps(value)}], [])
        value.update(source_requirement_count=1, source_requirement_ids_truncated=True)
        with self.assertRaisesRegex(ProviderFailure, 'TRUNCATED'):
            wp.compact([{'role': 'user', 'content': 'ROOT CONTRACT:\n' + json.dumps(value)}], [])

    def test_clipped_json_section_fails_closed(self):
        with self.assertRaisesRegex(ProviderFailure, 'SECTION_INCOMPLETE'):
            wp.compact([{'role': 'user', 'content': 'CURRENT NODE:\n{"goal":'}], [])

    def test_missing_oracle_cannot_make_assignment_fit(self):
        store = wp.PacketEvidence()
        store.obligations = {'task_id': 'C2', 'requirement_ids': ['R2'], 'oracles': store.put([])}
        with self.assertRaisesRegex(ProviderFailure, 'ORACLES_MISSING'):
            wp.compact([{'role': 'user', 'content': 'small task'}], [], store)

    def test_forged_history_pair_cannot_be_archived(self):
        messages = [{'role': 'assistant', 'tool_calls': [{'id': 'call-1', 'function': {
            'name': 'read_file', 'arguments': {'path': 'a.py'}}}]},
            {'role': 'tool', 'tool_name': 'write_file', 'tool_call_id': 'different', 'content': 'OK'}]
        with self.assertRaisesRegex(ProviderFailure, 'BINDING_INVALID'):
            wp.compact(messages, [], wp.PacketEvidence())

    def test_shared_dependency_subset_expands_to_exact_original(self):
        base = {'task_id': 'prior-child', 'goal': 'Preserve callers and runtime state ' * 6,
                'changed_files': ['pkg/engine.py', 'tests/test_engine.py'], 'status': 'verified'}
        richer = dict(base, integration_manifest={'invariants': ['never erase persistence'], 'source_sha256': 'c' * 64})
        text = json.dumps({'dependencies': [base], 'verified': [richer]})
        actual, _ = wp.compact([{'role': 'user', 'content': text}], [])
        self.assertIn('$base', actual[0]['content'])
        self.assertEqual(objects(actual[0]['content']), [json.loads(text)])

    def test_source_json_reference_keys_are_not_mistaken_for_packet_macros(self):
        value = {'schema': {'$ref': '#/$defs/object'}, 'long': ['critical text ' * 30] * 3}
        actual, _ = wp.compact([{'role': 'user', 'content': json.dumps(value)}], [])
        self.assertFalse(actual[0]['content'].startswith('Exact JSON'))
        self.assertEqual(json.loads(expand_text(actual[0]['content'])), value)

    def test_key_syntax_preserves_values_literals_and_unicode(self):
        value = {'plain': 'literal {scope: "*"} and two  spaces\n', 'ключ': True,
                 'nested': [{'path': 'src/a.py', 'allowed': [], 'unknown-key': None}], '12': 4.5}
        encoded = wp.compact_key_lines(json.dumps(value, ensure_ascii=False))
        self.assertEqual(objects(encoded), [value])

    def test_full_gate_limits_and_state_survive_history_aggregation(self):
        gate = {'context_status': 'sufficient', 'mutation_allowed': True, 'anchor_hash': 'f' * 64,
                'round': 2, 'max_rounds': 3, 'max_requests_per_round': 3, 'working_evidence_limit': 4200,
                'required_custom_constraint': 'Never modify secrets/', 'needed_evidence': [], 'errors': []}
        messages = [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'context_sufficiency_check',
                    'arguments': {'context_status': 'sufficient'}}}]},
                    {'role': 'tool', 'tool_name': 'context_sufficiency_check', 'content': json.dumps(gate)},
                    {'role': 'assistant', 'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'path': 'a.py'}}}]},
                    {'role': 'tool', 'tool_name': 'read_file', 'content': 'source\n' * 400}]
        store = wp.PacketEvidence(); output, _ = wp.compact(messages, [], store)
        receipt = objects(output[0]['content'])[0]
        self.assertEqual(receipt['gate_receipt'], gate)
        self.assertEqual(read_all(store, receipt['historical_tool_exchange']), messages)

    def test_insufficient_context_requests_stay_inline(self):
        gate = {'context_status': 'insufficient', 'mutation_allowed': False,
                'needed_evidence': [{'target': 'state.json', 'why': 'preserve persistence', 'kind': 'contract'}]}
        messages = [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'context_sufficiency_check',
                     'arguments': {'context_status': 'insufficient'}}}]},
                    {'role': 'tool', 'tool_name': 'context_sufficiency_check', 'content': json.dumps(gate)}]
        output, _ = wp.compact(messages, [], wp.PacketEvidence())
        self.assertEqual(output, messages)

    def test_both_actual_source_contract_shapes_are_validated(self):
        root = {'goal': 'Build safely', 'requirements': ['Preserve state'], 'constraints': [], 'success_criteria': [],
                'source_requirement_ids': ['R1'], 'source_requirement_count': 1}
        rows = [{'role': 'user', 'content': 'ROOT CONTRACT:\n' + json.dumps(root)}]
        for source in [root, {'root_goal': root['goal'], 'user_stated_requirements': [
                {'requirement_id': 'R1', 'text': 'Preserve state'}]}]:
            store = wp.PacketEvidence(); store.source_contract = source
            wp.compact(rows, [], store)
        store.source_contract['user_stated_requirements'].append({'requirement_id': 'R2', 'text': 'Do not erase database'})
        with self.assertRaisesRegex(ProviderFailure, 'SOURCE_CONTRACT_INCOMPLETE'): wp.compact(rows, [], store)

    def test_missing_prerequisite_is_not_silently_omitted(self):
        store = wp.PacketEvidence(); store.task = {'depends_on': ['first', 'second']}
        for content, code in [('DEPENDENCIES (verified summaries only):\n[{"task_id":"first"}]', 'DEPENDENCY_CONTEXT_INCOMPLETE'),
                              ('DEPENDENCIES (verified summaries only):\n[{"task_id":', 'SOURCE_SECTION_INCOMPLETE')]:
            with self.assertRaisesRegex(ProviderFailure, code):
                wp.compact([{'role': 'user', 'content': content}], [], store)

    def test_added_tool_restriction_is_never_removed_as_boilerplate(self):
        tools = copy.deepcopy(self.fixture['tools'])
        for tool in tools:
            if tool['function']['name'] in {'run_command', 'context_sufficiency_check'}:
                tool['function']['description'] += ' REQUIRE APPROVAL XYZ.'
        self.assertEqual(wp.compact_tools(tools), tools)

    def test_total_evidence_and_input_limits_fail_closed(self):
        store = wp.PacketEvidence()
        for i in range(4): store.put(str(i) * 250000)
        with self.assertRaisesRegex(ProviderFailure, 'LIMIT'): store.put('z' * 250000)
        with self.assertRaisesRegex(ProviderFailure, 'INPUT_LIMIT'):
            wp.compact([{'role': 'user', 'content': 'x' * 2097153}], [])

    def test_intervening_repair_instruction_is_not_crossed_by_history_packing(self):
        pair = [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'path': 'lib.rs'}}}]},
                {'role': 'tool', 'tool_name': 'read_file', 'content': 'source ' * 200}]
        repair = {'role': 'user', 'content': 'Repair attempt 2/2. Preserve R1, database and allowed scope.'}
        output, _ = wp.compact(pair + [repair] + pair, [], wp.PacketEvidence())
        self.assertIn(repair, output)
        self.assertEqual(len(output), 3)

    def test_verbose_failure_evidence_is_exactly_recoverable(self):
        error = "Expected count 1\nActual 0\nCall log:\n" + 'observed unchanged state\n' * 20
        snapshot = {'schema_version': 'V21.5B', 'paths': [{'path': 'state.py', 'sha256': 'a' * 64}], 'hash': 'b' * 64}
        original = {'passed': False, 'source_hash': 'c' * 64, 'obligation_hash': 'd' * 64,
                    'checks': [{'requirement_id': 'REQ-20', 'target': 'state.py', 'passed': False, 'error': error}],
                    'subject_before': snapshot, 'subject_after': snapshot, 'receipt_hash': 'e' * 64,
                    'custom_required_repair': 'Preserve all saved records'}
        raw = json.dumps(original)
        store = wp.PacketEvidence()
        output, _ = wp.compact([{'role': 'user', 'content': json.dumps({'evidence': raw})}], [], store)
        view = objects(output[0]['content'])[0]['evidence']
        self.assertEqual(read_all(store, view['$json_text']), raw)
        parsed = view['parsed']
        self.assertEqual(parsed['custom_required_repair'], original['custom_required_repair'])
        self.assertEqual(parsed['checks'][0]['requirement_id'], 'REQ-20')
        self.assertIs(parsed['checks'][0]['error']['$at'], True)
        self.assertEqual(parsed['checks'][0]['error']['head'], error.split('Call log:')[0])
        self.assertIs(parsed['subject_before']['$at'], True)
        self.assertIs(parsed['source_hash']['$at'], True)
        self.assertEqual(json.loads(read_all(store, view['$json_text']))['subject_before']['hash'], snapshot['hash'])

    def test_repair_and_round_counters_are_present_without_changing_schemas(self):
        window = wp.ToolWindow(); window.rounds_left = 7; window.repair_state = [2, 2]
        messages, native = window.project([{'role': 'system', 'content': wp.CONTEXT_INSTRUCTION}], self.fixture['tools'])
        self.assertEqual(json.loads(messages[1]['content'])['repair'], [2, 2])
        self.assertEqual(json.loads(messages[1]['content'])['rounds_left'], 7)
        original = next(t for t in self.fixture['tools'] if t['function']['name'] == 'context_sufficiency_check')
        self.assertEqual(native[0]['function']['parameters'], original['function']['parameters'])
        self.assertEqual(window.available['context_sufficiency_check'], original)

    def test_excessive_nesting_fails_with_precise_boundary(self):
        value = {'requirement': 'preserve'}
        for _ in range(80): value = {'nested': value}
        with self.assertRaisesRegex(ProviderFailure, 'PACKET_STRUCTURE_LIMIT'):
            wp.compact([{'role': 'user', 'content': json.dumps(value)}], [])

    def test_failed_repair_diagnostics_are_never_reclassified_as_pass(self):
        store = wp.PacketEvidence()
        value = {'evidence': json.dumps({'passed': False, 'failure_type': 'BEHAVIORAL_VERIFICATION_FAILED',
                   'checks': [{'requirement_id': 'R1', 'passed': False, 'error': 'Interaction absent ' * 30}]})}
        output, _ = wp.compact([{'role': 'user', 'content': json.dumps(value)}], [], store)
        view = objects(output[0]['content'])[0]['evidence']
        self.assertIs(view['parsed']['passed'], False)
        self.assertEqual(json.loads(read_all(store, view['$json_text'])), json.loads(value['evidence']))

    def test_required_route_state_and_unknown_constraints_remain_visible(self):
        route = {'kind': 'SYNTAX_STATIC_GATE', 'required': True, 'applicable': True,
                 'target': 'src/core.py', 'result': 'PENDING', 'reason_codes': ['CONTRACT_REQUIRES_SYNTAX'],
                 'evidence_refs': ['child:2', 'contract:mutation_paths'], 'resolution_status': 'RESOLVED',
                 'resolution_source': 'contract_source_paths', 'custom_preservation': 'Never erase state'}
        raw = json.dumps({'child_id': '2', 'failure_codes': ['REQUIRED_VERIFICATION_NOT_RUN'], 'routes': [route]})
        store = wp.PacketEvidence()
        messages, _ = wp.compact([{'role': 'user', 'content': json.dumps({'evidence': raw})}], [], store)
        encoded = objects(messages[0]['content'])[0]['evidence']
        projected = encoded['parsed']['routes'][0]
        self.assertIs(projected['$at'], True)
        for key in ('kind', 'required', 'applicable', 'target', 'result', 'custom_preservation'):
            self.assertEqual(projected['view'][key], route[key])
        self.assertEqual(json.loads(read_all(store, encoded['$json_text']))['routes'][0], route)


if __name__ == '__main__': unittest.main()
