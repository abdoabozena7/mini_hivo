"""Deterministic worker packet formatting. No model-generated summaries.

JSON values and tool argument schemas are preserved. Only registered controller prose
may have a shorter equivalent; unknown text is kept. Original history remains
with its caller. Large completed tool exchanges have read-only, digest-bound
retrieval, never authorization or fresh verification status.
"""
import copy
import hashlib
import json
import re

from hivo.providers import ProviderFailure


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def validate_source(messages, store):
    sections = {
        'ROOT CONTRACT:': ('goal', 'requirements', 'constraints', 'success_criteria'),
        'CURRENT NODE:': ('goal', 'done_when', 'scope_hint', 'repair_history'),
        'FINAL HYDRATED WORKER MISSION (fresh, bounded, and contract-derived):':
            ('goal_anchor', 'task', 'targets', 'verification_plan', 'done_when'),
    }
    for message in messages:
        if message.get('role') != 'user' or not isinstance(message.get('content'), str): continue
        lines = message['content'].split('\n')
        for i, line in enumerate(lines[:-1]):
            if line in {'CURRENT DETERMINISTIC FAILURE EVIDENCE:', 'DEPENDENCIES (verified summaries only):',
                        'PROJECT BRAIN PROJECTION (relevant core + verified state):',
                        'PRE-MUTATION IMPACT CONTRACT (bounded controller projection):'}:
                try: json.loads(lines[i + 1])
                except ValueError:
                    raise ProviderFailure('PACKET_SOURCE_SECTION_INCOMPLETE') from None
        for i, line in enumerate(lines):
            if line not in sections: continue
            try: value = json.loads(lines[i + 1])
            except (ValueError, IndexError):
                raise ProviderFailure('PACKET_SOURCE_SECTION_INCOMPLETE') from None
            if not isinstance(value, dict) or not set(sections[line]) <= set(value):
                raise ProviderFailure('PACKET_REQUIRED_FIELD_MISSING')
            if value.get('source_requirement_ids_truncated') is True:
                raise ProviderFailure('PACKET_SOURCE_REQUIREMENTS_TRUNCATED')
            if 'source_requirement_count' in value and value['source_requirement_count'] != len(value.get('source_requirement_ids', [])):
                raise ProviderFailure('PACKET_SOURCE_REQUIREMENT_ID_MISMATCH')
            if store is not None and line == 'ROOT CONTRACT:' and store.source_contract is not None:
                source = store.source_contract
                for key in ('goal', 'requirements', 'constraints', 'success_criteria'):
                    if key in source and value.get(key) != source[key]:
                        raise ProviderFailure('PACKET_SOURCE_CONTRACT_INCOMPLETE')
                if 'root_goal' in source and value.get('goal') != source['root_goal']:
                    raise ProviderFailure('PACKET_SOURCE_CONTRACT_INCOMPLETE')
                stated = source.get('user_stated_requirements', [])
                source_ids = {r['requirement_id'] for r in stated if isinstance(r, dict) and r.get('requirement_id')}
                source_text = {r['text'] for r in stated if isinstance(r, dict) and r.get('text')}
                if not source_ids <= set(value.get('source_requirement_ids', [])) or not source_text <= set(value['requirements']):
                    raise ProviderFailure('PACKET_SOURCE_CONTRACT_INCOMPLETE')
            if store is not None and line == 'CURRENT NODE:' and store.task is not None:
                for key in ('goal', 'done_when', 'scope_hint', 'repair_history'):
                    if value.get(key) != store.task.get(key, [] if key != 'goal' else ''):
                        raise ProviderFailure('PACKET_TASK_CONTRACT_INCOMPLETE')
        if store is not None and store.task is not None and store.task.get('depends_on'):
            marker = 'DEPENDENCIES (verified summaries only):'
            if marker in lines:
                try: deps = json.loads(lines[lines.index(marker) + 1])
                except (ValueError, IndexError):
                    raise ProviderFailure('PACKET_DEPENDENCY_CONTEXT_INCOMPLETE') from None
                ids = {str(d.get('task_id')) for d in deps if isinstance(d, dict)} if isinstance(deps, list) else set()
                if not {str(x) for x in store.task['depends_on']} <= ids:
                    raise ProviderFailure('PACKET_DEPENDENCY_CONTEXT_INCOMPLETE')
    if store is not None and store.obligations is not None:
        owned = store.obligations
        if not {'task_id', 'requirement_ids', 'oracles'} <= set(owned) or not isinstance(owned['requirement_ids'], list):
            raise ProviderFailure('PACKET_OWNERSHIP_INCOMPLETE')
        reference = owned['oracles']
        if not isinstance(reference, dict) or 'sha256' not in reference:
            raise ProviderFailure('PACKET_REQUIRED_ORACLES_MISSING')
        # Canonical record is private/controller-owned, not a model receipt.
        store.read(reference['sha256'])
        oracles = json.loads(store._values[reference['sha256']])
        covered = {v.get('requirement_id') for v in oracles if isinstance(v, dict)} if isinstance(oracles, list) else set()
        if not set(owned['requirement_ids']) <= covered:
            raise ProviderFailure('PACKET_REQUIRED_ORACLES_MISSING')


def compact_json_lines(text):
    lines = []
    for line in text.split('\n'):
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            lines.append(line)
            continue
        if isinstance(value, (dict, list)):
            lines.append(canonical(value))
        else:
            lines.append(line)
    return '\n'.join(lines)


def key_syntax(raw, *, restore=False):
    """Reversible JSON subset: only identifier object keys lose quotes."""
    result, index = [], 0
    decoder = json.JSONDecoder()
    while index < len(raw):
        char = raw[index]
        if char == '"':
            value, length = decoder.raw_decode(raw[index:])
            token = raw[index:index + length]
            end = index + length
            after = raw[end:].lstrip()
            if not restore and isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', value) and after.startswith(':'):
                result.append(value)
            else:
                result.append(token)
            index = end
        elif restore and (char.isalpha() or char == '_'):
            match = re.match(r'[A-Za-z_][A-Za-z_0-9]*', raw[index:])
            if match and raw[index + len(match[0]):].lstrip().startswith(':'):
                result.append(json.dumps(match[0])); index += len(match[0])
            else:
                result.append(char); index += 1
        else:
            result.append(char); index += 1
    return ''.join(result)


def compact_key_lines(text):
    lines, changed = [], False
    for line in text.split('\n'):
        try: value = json.loads(line)
        except ValueError:
            lines.append(line); continue
        if not isinstance(value, (dict, list)):
            lines.append(line); continue
        encoded = key_syntax(line)
        if json.loads(key_syntax(encoded, restore=True)) != value:
            raise ProviderFailure('PACKET_STRUCTURE_ROUNDTRIP_FAILED')
        lines.append(encoded); changed = changed or encoded != line
    return ('Object syntax: bare keys; JSON values.\n' if changed else '') + '\n'.join(lines)


def system_instructions(role, game_bridge):
    base = (
        'Work ONLY inside the selected workspace and CURRENT NODE scope. Inspect before editing. '
        'write_file: new files or explicitly permitted unverified model-owned drafts only; '
        'existing files: focused edit_file/edit_file_range. Before completion, execute relevant '
        'node verification (test/command/browser); writes alone are incomplete. '
        f'Browser games expose {game_bridge}: getState(),start(),restart(),move(direction), '
        'and forceCollision/forceCollect/forceWin for requested mechanics. '
        'Report tool/environment failures truthfully; never reveal hidden reasoning.'
    )
    if role == 'Repairer':
        base += ' Repair only defects demonstrated by current deterministic failure evidence.'
    if role == 'Falsifier':
        base = ('Read-only adversarial verifier inside the workspace: seek executable counterevidence. '
                'Read/test/command/browser only; NEVER modify. At most two cheap edge probes. '
                'Prefer exposed Python/test/browser tools; no echo, shell composition or unavailable commands. '
                'Narrative suspicion is advisory; never reveal hidden reasoning.')
    return base


CONTEXT_INSTRUCTION = (
    " Before write/edit, call context_sufficiency_check: sufficient only if bounded evidence establishes "
    "contract, dependencies, invariants, caller/test expectations and downstream impact; otherwise insufficient "
    "with <=3 narrow requests (target+why). No broad repo/module requests. Runtime mutation_allowed=true is required."
)
IMPACT_INSTRUCTION = (
    ' Obey Impact Contract: never expand scope or trust Worker claims as authority. '
    'Runtime compares changes, preservations and evidence after verification.'
)
CREATION_INSTRUCTION = (
    'Create absent assigned outputs from mission/source requirements; no existing definitions/contents to request. '
    'Present files, external APIs, dependencies and unspecified interfaces need evidence. '
    'Observation grants no sufficiency/authority: honestly check context, obey Impact Contract; never perform sibling duties.'
)


class PacketEvidence:
    """Ephemeral per-execution store: contents are not reusable authority."""
    def __init__(self, workspace=None):
        self._values = {}
        self.authority = None
        self.workspace = str(workspace) if workspace is not None else None
        self.obligations = None
        self.source_contract = None
        self.task = None
        self.projection_views = False

    def put(self, value):
        raw = canonical(value)
        if len(self._values) >= 256 or len(raw) > 262144 or sum(len(v) for v in self._values.values()) + len(raw) > 1048576:
            raise ProviderFailure('PACKET_EVIDENCE_LIMIT')
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        self._values[digest] = raw
        # The digest binds the complete record. Length is derived and returned
        # by read(); repeating it in every model-visible reference wastes the
        # mandatory packet budget without adding authority or integrity.
        return {'sha256': digest}

    def read(self, sha256, offset=0):
        if not isinstance(sha256, str) or sha256 not in self._values:
            raise ProviderFailure('PACKET_EVIDENCE_UNKNOWN_OR_STALE')
        if type(offset) is not int or offset < 0:
            raise ProviderFailure('PACKET_EVIDENCE_INVALID_OFFSET')
        raw = self._values[sha256]
        if hashlib.sha256(raw.encode('utf-8')).hexdigest() != sha256:
            raise ProviderFailure('PACKET_EVIDENCE_CORRUPT')
        if offset > len(raw):
            raise ProviderFailure('PACKET_EVIDENCE_INVALID_OFFSET')
        end = min(len(raw), offset + 1024)
        return {'sha256': sha256, 'offset': offset, 'chars': len(raw), 'content': raw[offset:end],
                'next_offset': end if end < len(raw) else None,
                'trust': 'historical tool exchange only; not authorization or fresh verification'}


EVIDENCE_TOOL = {'type': 'function', 'function': {
    'name': 'read_packet_evidence',
    'description': 'Read a digest-bound historical tool exchange in 1024-character chunks. Not authorization or fresh proof.',
    'parameters': {'type': 'object', 'properties': {'sha256': {'type': 'string'},
        'offset': {'type': 'integer', 'minimum': 0}}, 'required': ['sha256'], 'additionalProperties': False}}}


def compact_tools(tools):
    """Parameters/types/required/enums and offered names are never changed."""
    tools = copy.deepcopy(tools)
    for item in tools or []:
        function = item.get('function', {})
        if function.get('name') == 'run_command':
            original = function.get('description', '')
            start = original.find('Allowed executables: ')
            end = original.find('. Use list_files', start)
            expected = ('Run a verification command inside the workspace. ' + original[start:end] +
                '. Use list_files/read_file for inspection, not shell inventory or echo commands. '
                'Use run_file or verify_web_app to verify an artifact. Shell composition and inline code are forbidden.')
            if start >= 0 and end > start and original == expected:
                function['description'] = ('Workspace verification only. ' + original[start:end] +
                    '. Inspect via list_files/read_file; verify via run_file/verify_web_app. '
                    'No shell composition, inline code, shell inventory or echo.')
        elif function.get('name') == 'context_sufficiency_check':
            # Only this exact controller schema admits this static equivalent.
            expected = ('Classify whether the current bounded task evidence is sufficient before mutation. '
                'If insufficient, request up to three narrow semantic evidence items, each with a concrete target and why. '
                'Do not request broad repository or module context.')
            if function.get('description') == expected:
                function['description'] = ('Before mutation classify bounded task evidence. Insufficient: <=3 narrow '
                    'semantic requests (target+why). Never request broad repo/module context.')
    return tools


SELECT_TOOL = {'type': 'function', 'function': {'name': 'select_worker_tools',
    'description': 'Expose <=3 permitted schemas; presentation only, no authority.',
    'parameters': {'type': 'object', 'properties': {'names': {'type': 'array', 'minItems': 1,
        'maxItems': 3, 'uniqueItems': True, 'items': {'type': 'string'}}},
        'required': ['names'], 'additionalProperties': False}}}


class ToolWindow:
    """Bounded schema discovery over the unchanged current runtime tool set."""
    def __init__(self):
        self.available = {}
        self.selected = ['context_sufficiency_check']
        self.rounds_left = None
        self.repair_state = None

    def update(self, tools):
        self.available = {t['function']['name']: copy.deepcopy(t) for t in tools or []
                          if t['function']['name'] != 'select_worker_tools'}

    def select(self, names):
        if (not isinstance(names, list) or not 1 <= len(names) <= 3
                or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names)
                or any(n not in self.available for n in names)):
            raise ProviderFailure('PACKET_TOOL_SELECTION_DENIED')
        self.selected = list(names)
        return {'selected': names, 'authority_changed': False}

    def project(self, messages, tools):
        self.update(tools)
        names = [n for n in self.selected if n in self.available]
        result = copy.deepcopy(messages)
        manifest = {'tools': sorted(self.available)}
        if self.rounds_left is not None: manifest['rounds_left'] = self.rounds_left
        if self.repair_state is not None: manifest['repair'] = list(self.repair_state)
        result.insert(1 if result and result[0].get('role') == 'system' else 0,
            {'role': 'user', 'content': canonical(manifest)})
        native = [copy.deepcopy(self.available[n]) for n in names]
        has_gate_instructions = any(m.get('role') == 'system' and CONTEXT_INSTRUCTION.strip() in m.get('content', '') for m in messages)
        if has_gate_instructions:
            for definition in native:
                if definition['function']['name'] == 'context_sufficiency_check':
                    definition['function']['description'] = 'Declare runtime context decision; obey the bounded system gate. Not standalone mutation authority.'
        return result, native + [copy.deepcopy(SELECT_TOOL)]


def text_macros(text, workspace=None):
    """Lossless raw-text substitution; source bytes can be reconstructed exactly."""
    if '@W@' in text or '@J@' in text or '@T' in text:
        return text
    definitions = {}
    if workspace:
        for marker, value in (('@J@', json.dumps(workspace, ensure_ascii=False)[1:-1]), ('@W@', workspace)):
            if len(value) > 24 and text.count(value) > 1:
                definitions[marker] = value
                text = text.replace(value, marker)
    lines = [line for line in text.split('\n') if len(line) > 160 and not line.startswith(('{', '['))]
    for i, first in enumerate(lines[:32]):
        for second in lines[i + 1:32]:
            end = 0
            for a, b in zip(first, second):
                if a != b: break
                end += 1
            common = first[:end]
            if end > 160 and text.count(common) > 1 and len(definitions) < 10:
                marker = '@T' + str(len(definitions)) + '@'
                definitions[marker] = common
                text = text.replace(common, marker)
    if not definitions:
        return text
    return 'Exact text macros; expand before use. No authority added.\n' + canonical(definitions) + '\n' + text


def _failed_receipt(value):
    if isinstance(value, dict):
        if any(value.get(k) for k in ('error', 'errors', 'failure_code', 'failures', 'environment_error')) or value.get('passed') is False:
            return True
        if str(value.get('status', '')).lower() in {'failed', 'error', 'denied', 'stale', 'invalid'}:
            return True
        if 'content' in value: return _failed_receipt(value['content'])
        return any(_failed_receipt(v) for k, v in value.items()
                   if not k.startswith('ignored_') and isinstance(v, (dict, list)))
    if isinstance(value, list): return any(_failed_receipt(v) for v in value)
    if isinstance(value, str):
        try: return _failed_receipt(json.loads(value))
        except ValueError: return any(w in value.lower() for w in ('error:', 'failed', 'denied', 'stale', 'invalid'))
    return False


def pack_history(original, formatted, store):
    """One lossless record per contiguous successful exchange run.

    Full gate receipts stay inline, including every limit/state field. Failures,
    insufficient context, retrieved chunks and intervening instructions stay in
    chronological position. The archive is historical data, never authority.
    """
    packed, index = [], 0
    def exchange(start):
        item = original[start]
        calls = item.get('tool_calls') if item.get('role') == 'assistant' else None
        end = start + 1
        while end < len(original) and original[end].get('role') == 'tool': end += 1
        receipts = original[start + 1:end]
        if not calls or not receipts or len(calls) != len(receipts): return None
        summaries, gate = [], None
        for call, receipt in zip(calls, receipts):
            function = call.get('function', {})
            name, args = function.get('name'), function.get('arguments', {})
            if ((receipt.get('tool_name') and receipt['tool_name'] != name)
                    or (receipt.get('tool_call_id') and receipt['tool_call_id'] != call.get('id'))):
                raise ProviderFailure('PACKET_HISTORY_BINDING_INVALID')
            if _failed_receipt(receipt) or name == 'read_packet_evidence': return None
            if isinstance(args, str):
                try: args = json.loads(args)
                except ValueError: return None
            if not isinstance(args, dict): return None
            if name == 'context_sufficiency_check':
                try: gate = json.loads(receipt['content'])
                except (KeyError, ValueError): return None
                if gate.get('context_status') != 'sufficient' or gate.get('mutation_allowed') is not True: return None
            target = args.get('path', args.get('command', args.get('names')))
            summaries.append([name, target])
        return end, summaries, gate
    while index < len(original):
        first = exchange(index)
        if first is None:
            packed.append(formatted[index]); index += 1; continue
        end, calls, gate = first
        while end < len(original):
            next_one = exchange(end)
            if next_one is None: break
            end, more, next_gate = next_one
            calls.extend(more)
            if next_gate is not None: gate = next_gate
        span = original[index:end]
        if len(canonical(span)) > 650:
            receipt = {'historical_tool_exchange': store.put(span), 'calls': calls,
                       'status': 'historical; exact args/results by digest; not authority/fresh proof'}
            if gate is not None:
                # Only empty informational fields move to the exact exchange.
                # All state, counters, limits and unknown constraints stay inline.
                receipt['gate_receipt'] = {k: v for k, v in gate.items()
                    if not (k in {'history', 'semantic_resolutions', 'evidence'} and v in (None, []))}
            packed.append({'role': 'user', 'content': canonical(receipt)})
        else:
            packed.extend(formatted[index:end])
        index = end
    return packed


def _compact(messages, tools, store=None):
    if sum(len(str(m.get('content', ''))) + len(canonical(m.get('tool_calls', []))) for m in messages) > 2097152:
        raise ProviderFailure('PACKET_INPUT_LIMIT')
    validate_source(messages, store)
    result = copy.deepcopy(messages)
    # Only complete JSON lines are parsed: code, quoted whitespace, unknown
    # narrative, requirements and recovery instructions are never summarized.
    for message in result:
        if message.get('role') == 'user' and isinstance(message.get('content'), str):
            message['content'] = compact_json_lines(message['content'])
    if store is not None:
        def diagnostic_view(value, path=()):
            if isinstance(value, dict):
                if {'kind', 'required', 'applicable', 'result'} <= set(value):
                    metadata = {'reason_codes', 'evidence_refs', 'resolution_status', 'resolution_source', 'requested_from_node'}
                    return {'$at': True, 'view': {k: v for k, v in value.items() if k not in metadata and not
                            (k == 'actual_result' and value[k] == value.get('result'))}}
                output = {}
                for key, item in value.items():
                    current = path + (key,)
                    if key in {'subject_before', 'subject_after'} and isinstance(item, dict) and {'schema_version', 'paths', 'hash'} <= set(item):
                        output[key] = {'$at': True}
                    elif key == 'error' and isinstance(item, str) and 'Call log:' in item:
                        output[key] = {'$at': True, 'head': item.split('Call log:', 1)[0]}
                    elif (key.endswith('_hash') and isinstance(item, str) and re.fullmatch(r'[0-9a-f]{64}', item)):
                        output[key] = {'$at': True}
                    elif key in {'reason_codes', 'evidence_refs'} and len(canonical(item)) > len(canonical({'$at': list(current)})):
                        output[key] = {'$at': True}
                    else:
                        output[key] = diagnostic_view(item, current)
                return output
            if isinstance(value, list): return [diagnostic_view(v, path + (i,)) for i, v in enumerate(value)]
            return value
        def evidence_views(value):
            if isinstance(value, dict):
                output = {}
                for key, item in value.items():
                    if key in {'evidence', 'result', 'diagnostic'} and isinstance(item, str) and len(item) > 256:
                        try: parsed = json.loads(item)
                        except ValueError: parsed = None
                        if isinstance(parsed, (dict, list)):
                            # Remove nested JSON-string escaping, not content.
                            # Raw original bytes and every parsed field remain.
                            output[key] = {'$json_text': store.put(item), 'parsed': diagnostic_view(parsed)}
                            continue
                    output[key] = evidence_views(item)
                return output
            if isinstance(value, list): return [evidence_views(v) for v in value]
            return value
        for message in result:
            if message.get('role') != 'user' or not isinstance(message.get('content'), str): continue
            def reserved_view(value):
                if isinstance(value, dict):
                    return bool({'$json_text', '$at'} & set(value)) or any(reserved_view(v) for v in value.values())
                if isinstance(value, list): return any(reserved_view(v) for v in value)
                return False
            source_values = []
            for line in message['content'].split('\n'):
                try: source_values.append(json.loads(line))
                except ValueError: pass
            if any(reserved_view(v) for v in source_values): continue
            lines, changed = [], False
            for line in message['content'].split('\n'):
                try: value = json.loads(line)
                except ValueError:
                    lines.append(line); continue
                view = evidence_views(value)
                changed = changed or view != value
                lines.append(canonical(view) if isinstance(view, (dict, list)) else line)
            message['content'] = ('JSON-text: $json_text=exact original; $at=true=same field. '
                'Observations inline; full identities/logs at reference.\n' if changed else '') + '\n'.join(lines)
    # Project Brain is a redundant projection, not mutation authority. Preserve
    # every nonempty value inline and the exact complete object by digest. Empty
    # inspection/mutation scopes are NEVER eligible for this representation.
    if store is not None:
        for message in result:
            if message.get('role') != 'user' or not isinstance(message.get('content'), str):
                continue
            lines = message['content'].split('\n')
            for i in range(len(lines)):
                if lines[i] != 'VERIFIED LONG-TERM PROJECT MEMORY (relevant excerpts only):':
                    continue
                end = i + 1
                while end < len(lines) and lines[end]: end += 1
                original = '\n'.join(lines[i:end])
                if len(original) > 300:
                    lines[i] = canonical({'historical_memory': store.put(original),
                        'trust': 'background only, not authority/fresh proof; retrieve if needed'})
                    for j in range(i + 1, end): lines[j] = ''
            for i, line in enumerate(lines[:-1]):
                if line == 'FINAL HYDRATED WORKER MISSION (fresh, bounded, and contract-derived):':
                    try:
                        mission = json.loads(lines[i + 1])
                        root_values = [json.loads(lines[j + 1]) for j, title in enumerate(lines[:-1]) if title == 'ROOT CONTRACT:']
                        node_values = [json.loads(lines[j + 1]) for j, title in enumerate(lines[:-1]) if title == 'CURRENT NODE:']
                    except ValueError:
                        mission, root_values, node_values = None, [], []
                    if isinstance(mission, dict) and root_values and node_values:
                        root, node = root_values[0], node_values[0]
                        shared = {'goal_anchor': root.get('goal'), 'task': node.get('goal'),
                                  'targets': node.get('scope_hint'), 'done_when': node.get('done_when')}
                        if len(node.get('done_when', [])) == 1:
                            shared['expected_outcome'] = node['done_when'][0]
                        unique = {k: v for k, v in mission.items() if v not in ([], {}) and not (k in shared and v == shared[k])}
                        store.projection_views = True
                        lines[i + 1] = canonical({'complete_mission': store.put(mission), 'unique_semantics': unique})
                if line == 'PRE-MUTATION IMPACT CONTRACT (bounded controller projection):' and store.authority is not None:
                    try: impact = json.loads(lines[i + 1])
                    except ValueError: continue
                    if isinstance(impact, dict):
                        # Runtime still uses the full contract. Keep its scope,
                        # constraints and duties inline; detailed source evidence
                        # is immutable and available by digest, not discarded.
                        required = ('status', 'revision',
                                    'required_preservations', 'forbidden_or_out_of_scope',
                                    'verification_obligations', 'expected_relationship_changes')
                        view = {k: impact[k] for k in required if k in impact}
                        view['complete_impact'] = store.put(impact)
                        view['execution_authority'] = copy.deepcopy(store.authority)
                        lines[i + 1] = canonical(view)
                if line != 'PROJECT BRAIN PROJECTION (relevant core + verified state):':
                    continue
                try:
                    brain = json.loads(lines[i + 1])
                except ValueError:
                    continue
                if not isinstance(brain, dict):
                    continue
                def project(value):
                    if isinstance(value, dict):
                        return {k: project(v) for k, v in value.items() if v not in ([], {})
                                or any(word in k for word in ('scope', 'allowed', 'authorized', 'forbidden', 'permission'))}
                    if isinstance(value, list):
                        return [project(v) for v in value]
                    return value
                view = project(brain)
                # Current task and root goal are already in the immutable
                # mission/node sections; retain exact equality before sharing.
                values = []
                for other in lines:
                    try: values.append(json.loads(other))
                    except ValueError: pass
                current = view.get('current_task')
                if isinstance(current, dict) and any(isinstance(v, dict) and all(
                        v.get(k) == x for k, x in current.items() if k != 'id') for v in values):
                    view['current_task'] = {'id': current.get('id'), 'same_fields_as': 'CURRENT NODE'}
                if any(isinstance(v, dict) and v.get('goal_anchor') == view.get('root_goal_anchor') for v in values):
                    view['root_goal_anchor'] = {'same_field_as': 'FINAL HYDRATED WORKER MISSION.goal_anchor'}
                root = next((v for v in values if isinstance(v, dict) and 'source_requirement_ids' in v and 'requirements' in v), None)
                core = view.get('relevant_core', {})
                records = core.get('source_requirements', []) if isinstance(core, dict) else []
                # Only share a source ledger when each ID/text association is
                # independently identical to the inline root contract.
                pairs = dict(zip(root['source_requirement_ids'], root['requirements'])) if root and len(root['source_requirement_ids']) == len(root['requirements']) else {}
                if records and all(isinstance(r, dict) and pairs.get(r.get('requirement_id')) == r.get('text') for r in records):
                    unique = copy.deepcopy(view)
                    unique.pop('current_task', None)
                    unique.pop('root_goal_anchor', None)
                    unique_core = unique.get('relevant_core', {})
                    unique_core.pop('source_requirements', None)
                    product = unique_core.get('product_contract', {})
                    if isinstance(product, dict) and all(r in root['requirements'] for r in product.get('requirements', [])):
                        product.pop('requirements', None)
                        if not product: unique_core.pop('product_contract', None)
                    if not unique_core: unique.pop('relevant_core', None)
                    dependency_sets = [v for v in values if isinstance(v, list) and v and all(isinstance(row, dict) and 'task_id' in row for row in v)]
                    def represented(rows):
                        return all(any(all(other.get(k) == val for k, val in row.items())
                            for group in dependency_sets for dependency in group
                            for other in (dependency, dependency.get('integration_manifest') or {})) for row in rows)
                    verified = unique.get('verified_state', {})
                    for key in ('dependencies', 'verified_child_manifests', 'dependency_manifests'):
                        rows = verified.get(key)
                        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows) and represented(rows):
                            verified.pop(key)
                    if not verified: unique.pop('verified_state', None)
                    view = {'unique_semantics': unique}
                reference = store.put(brain)
                store.projection_views = True
                frame = {'complete_projection': reference}
                frame.update(view if 'unique_semantics' in view else {'nonempty_fields': view})
                lines[i + 1] = canonical(frame)
            message['content'] = '\n'.join(lines)
    # Exact duplicate JSON values are factored across structured sections, with
    # local named definitions. This is reversible, including empty scopes and
    # provenance. Definitions carry the original values, not paraphrases.
    for message in result:
        if message.get('role') != 'user' or not isinstance(message.get('content'), str):
            continue
        lines = message['content'].split('\n')
        objects = {}
        counts = {}
        dictionaries = {}
        reserved_source_keys = []
        visited = [0]
        def visit(value, depth=0):
            visited[0] += 1
            if visited[0] > 50000 or depth > 64:
                raise ProviderFailure('PACKET_STRUCTURE_LIMIT')
            raw = canonical(value)
            if isinstance(value, (dict, list, str)) and len(raw) > 30:
                counts[raw] = counts.get(raw, 0) + 1
            if isinstance(value, dict):
                if '$ref' in value or '$base' in value: reserved_source_keys.append(True)
                if len(raw) > 120:
                    dictionaries[raw] = value
                for item in value.values(): visit(item, depth + 1)
            elif isinstance(value, list):
                for item in value: visit(item, depth + 1)
        for i, line in enumerate(lines):
            try: value = json.loads(line)
            except ValueError: continue
            if isinstance(value, (dict, list)):
                objects[i] = value
                visit(value)
        candidates = {raw: 'D' + str(i) for i, (raw, n) in enumerate(counts.items())
                      if (n - 1) * len(raw) > n * 14 + 20}
        # Factor an exact object subset shared by richer projections. No key
        # may be overridden by $base; expansion is an exact disjoint union.
        bases = []
        for raw, value in list(dictionaries.items())[:128]:
            if any(len(other) > len(value) and all(k in other and other[k] == v for k, v in value.items())
                   for other in list(dictionaries.values())[:128]):
                if raw not in candidates: candidates[raw] = 'B' + str(len(bases))
                bases.append((raw, value))
        shared = {}
        pool = list(dictionaries.values())[:128]
        for i, first in enumerate(pool):
            for second in pool[i + 1:]:
                common = {k: v for k, v in first.items() if k in second and second[k] == v}
                raw = canonical(common)
                if len(common) >= 2 and len(raw) > 120:
                    shared[raw] = common
        for raw, value in sorted(shared.items(), key=lambda row: len(row[0]), reverse=True)[:32]:
            if raw not in candidates: candidates[raw] = 'C' + str(len(bases))
            if not any(existing == raw for existing, _ in bases): bases.append((raw, value))
        if reserved_source_keys:
            # Source JSON schemas may legitimately use these keys. Never
            # confuse their data with our local factoring notation.
            candidates, bases = {}, []
        def encode(value, skip=None):
            raw = canonical(value)
            if raw in candidates and raw != skip:
                return {'$ref': candidates[raw]}
            if isinstance(value, dict):
                matching = [(raw, base) for raw, base in bases if len(value) > len(base)
                    and all(k in value and value[k] == v for k, v in base.items())]
                if matching:
                    base_raw, base = max(matching, key=lambda row: len(row[0]))
                    return {'$base': candidates[base_raw], **{k: encode(v) for k, v in value.items() if k not in base}}
                return {k: encode(v) for k, v in value.items()}
            if isinstance(value, list): return [encode(v) for v in value]
            return value
        if candidates:
            definitions = {name: encode(json.loads(raw), raw) for raw, name in candidates.items()}
            encoded_objects = {i: encode(value) for i, value in objects.items()}
            required = set()
            def references(value):
                if isinstance(value, dict):
                    for key in ('$ref', '$base'):
                        if key in value:
                            name = value[key]
                            if name not in required:
                                required.add(name); references(definitions[name])
                    for key, item in value.items():
                        if key not in {'$ref', '$base'}: references(item)
                elif isinstance(value, list):
                    for item in value: references(item)
            for value in encoded_objects.values(): references(value)
            definitions = {name: value for name, value in definitions.items() if name in required}
            for i, value in encoded_objects.items(): lines[i] = canonical(value)
            lines.insert(0, 'Exact JSON: $ref=value; $base=disjoint object merge; no authority.\n' + canonical(definitions))
        message['content'] = '\n'.join(lines)
    # Archive complete successful runs, preserving full gate state inline.
    if store is not None:
        result = pack_history(messages, result, store)
    tools = compact_tools(tools)
    if store is not None and store._values and tools is not None:
        if not any(t.get('function', {}).get('name') == 'read_packet_evidence' for t in tools):
            tools.append(copy.deepcopy(EVIDENCE_TOOL))
    headings = {
        'GREENFIELD CREATION CONTEXT (controller assignment and current filesystem observation):': 'CREATION: controller assignment/current filesystem:',
        'PROJECT BRAIN PROJECTION (relevant core + verified state):': 'BRAIN: relevant core/verified state:',
        'FINAL HYDRATED WORKER MISSION (fresh, bounded, and contract-derived):': 'MISSION: fresh/bounded/contract-derived:',
        'PARENT (goal + short verified summary):': 'PARENT: goal/verified summary:',
        'RELEVANT PROJECT MEMORY:': 'PROJECT MEMORY:',
        'REPOSITORY HINTS:': 'REPOSITORY:',
        'DEPENDENCIES (verified summaries only):': 'DEPENDENCIES: verified summaries only:',
        'PROJECT INVARIANTS (canonical facts; extend, do not redefine):': 'INVARIANTS: canonical; extend, never redefine:',
        'FAILED DECOMPOSITIONS (do not paraphrase these boundaries):': 'FAILED DECOMPOSITIONS: preserve boundaries verbatim:',
        'PRE-MUTATION IMPACT CONTRACT (bounded controller projection):': 'IMPACT: bounded controller projection:',
        'The real filesystem is the shared source of truth. Inspect files with tools. Do not assume sibling chat history.': 'Filesystem is truth; inspect via tools, never assume sibling chat.',
    }
    for message in result:
        if message.get('role') == 'user' and isinstance(message.get('content'), str):
            message['content'] = '\n'.join(headings.get(line, line) for line in message['content'].split('\n'))
            message['content'] = text_macros(message['content'], store.workspace if store else None)
    if store is not None and store.obligations is not None:
        first = next((m for m in result if m.get('role') == 'user'), None)
        if first is not None:
            first['content'] += '\nASSIGNED OBLIGATIONS (exact):\n' + canonical(store.obligations)
    if store is not None and store.projection_views:
        first = next((m for m in result if m.get('role') == 'user'), None)
        if first is not None:
            first['content'] += ('\nSnapshots complete; identical root/node/dependency fields shared; unique constraints inline. '
                'Full detail/empties in snapshot.')
    for message in result:
        if message.get('role') == 'user' and isinstance(message.get('content'), str):
            message['content'] = compact_key_lines(message['content'])
    if store is not None:
        # References are session-local, complete and immutable by digest before
        # any provider dispatch. Corruption fails even when not yet retrieved.
        for digest in store._values:
            store.read(digest, 0)
    return result, tools


def compact(messages, tools, store=None):
    try:
        return _compact(messages, tools, store)
    except RecursionError:
        raise ProviderFailure('PACKET_STRUCTURE_LIMIT') from None
