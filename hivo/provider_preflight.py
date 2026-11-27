"""Provider-specific qualification with the existing controller memory floor."""
from dataclasses import replace
import json
import shutil
from pathlib import Path
import uuid

from hivo import host_preflight as host
from hivo.model_routing import ROLE_NAMES, WORKER_ROLES
from hivo.providers import ProviderFailure


def resource_guard(_selection=None, *, sampler=None):
    snapshot = host._safe_resource_snapshot(sampler or host.sample_resources, 'provider_guard', set())
    if snapshot.get('available_system_ram_bytes') is None:
        raise ProviderFailure('CONTROLLER_MEMORY_TELEMETRY_UNAVAILABLE')
    reason = host._resource_blocker(snapshot)
    if reason:
        raise ProviderFailure(reason[0])
    return snapshot


def qualify(router, workspace, *, resource_sampler=None, host_runner=None):
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ProviderFailure('WORKSPACE_UNUSABLE')
    folder = workspace / '.agent_evidence' / 'provider-preflight' / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    report = {'passed': False, 'status': 'FAIL', 'models': [], 'failure_reason': None,
              'scope': 'Provider/model qualification, not application acceptance'}
    router.qualified = False
    guard = lambda selection=None: resource_guard(selection, sampler=resource_sampler)
    try:
        if shutil.disk_usage(workspace).free < host.MIN_FREE_DISK_BYTES:
            raise ProviderFailure('INSUFFICIENT_DISK_SPACE')
        report['resources_before'] = guard()
        router.client._catalogs.clear()
        router.infos.clear()
        router.prepare()
        for index, (selection, info) in enumerate(router.infos.items()):
            item = {'provider': selection.provider, 'model': selection.model,
                    'context': selection.context, 'execution': 'local' if selection.provider == 'ollama' else 'remote',
                    'capabilities': sorted(info.capabilities), 'passed': False}
            report['models'].append(item)
            router.client.authenticate(selection)
            if selection.provider == 'ollama':
                try:
                    ps = router.client._json(router.client.get(selection.base_url + '/api/ps', timeout=5))
                except ProviderFailure:
                    raise
                except (OSError, TimeoutError):
                    raise ProviderFailure('PROVIDER_UNREACHABLE') from None
                loaded = ps.get('models', [])
                if not isinstance(loaded, list) or any(not isinstance(m, dict) for m in loaded):
                    raise ProviderFailure('INVALID_RESIDENCY_METADATA')
                selected_names = {s.model for s in router.infos if s.provider == 'ollama'}
                if any(m.get('name') not in selected_names for m in loaded):
                    raise ProviderFailure('UNSELECTED_LOCAL_MODEL_RESIDENT')
                resident = any(m.get('name') == selection.model for m in loaded)
                available = guard().get('available_system_ram_bytes')
                # Disk weight size is only a conservative cold-load estimate.
                # Residency is not charged twice; real post-load checks remain.
                if not resident and available is not None and info.size_bytes > 0 and available < info.size_bytes + host.MIN_AVAILABLE_MEMORY_BYTES:
                    raise ProviderFailure('INSUFFICIENT_COLD_LOAD_HEADROOM_ESTIMATE')
                local_folder = folder / ('local-' + str(index))
                local_folder.mkdir()
                def canary(model, prompt, timeout, base_url):
                    guard(selection)
                    tiny = replace(selection, max_output=min(64, selection.max_output), retries=0,
                                   timeout=min(timeout, selection.timeout))
                    message = router.client.chat(tiny, info, [{'role': 'user', 'content': prompt}])
                    guard(selection)
                    return {'status_code': 200, 'body': {'message': message}}
                local = (host_runner or host.run_host_preflight)(
                    local_folder, selection.model, selection.base_url,
                    model_catalog_loader=lambda _url: [selection.model], canary_call=canary,
                    resource_sampler=resource_sampler)
                item['host_preflight'] = local
                if not local.get('passed'):
                    raise ProviderFailure((local.get('report') or {}).get('failure_reason') or 'LOCAL_HOST_PREFLIGHT_FAILED')
            guard(selection)
            tiny = replace(selection, max_output=min(256, selection.max_output), retries=0)
            schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                      'required': ['ok'], 'additionalProperties': False}
            answer = router.client.chat(tiny, info, [{'role': 'user', 'content': 'Return exactly {"ok":true}.'}], response_format=schema)
            try:
                parsed = json.loads(answer['content'])
            except (ValueError, TypeError):
                raise ProviderFailure('STRUCTURED_CANARY_FAILED') from None
            if parsed != {'ok': True} or type(parsed.get('ok')) is not bool:
                raise ProviderFailure('STRUCTURED_CANARY_FAILED')
            item['structured_canary'] = True
            needs_tools = any(role in WORKER_ROLES and router.config.selection(role) == selection for role in ROLE_NAMES)
            if needs_tools:
                tool = {'type': 'function', 'function': {'name': 'hivo_capability_probe',
                        'description': 'Report readiness without executing any action.', 'parameters': schema}}
                answer = router.client.chat(tiny, info, [{'role': 'user', 'content': 'Call hivo_capability_probe with ok=true. Do not reply with prose.'}], tools=[tool])
                calls = answer.get('tool_calls', [])
                if len(calls) != 1 or calls[0]['function']['name'] != 'hivo_capability_probe' or calls[0]['function']['arguments'] != {'ok': True}:
                    raise ProviderFailure('TOOL_CANARY_FAILED')
                item['tool_canary'] = True
            item['passed'] = True
            guard(selection)
        report['resources_after'] = guard()
        router.safety_guard = guard
        router.qualified = True
        report.update(passed=True, status='PASS')
    except ProviderFailure as exc:
        report['failure_reason'] = exc.code
        report['http_status'] = exc.status
    except KeyboardInterrupt:
        report['failure_reason'] = 'PREFLIGHT_CANCELLED'
    except (OSError, ValueError, TypeError, KeyError):
        report['failure_reason'] = 'PROVIDER_QUALIFICATION_UNAVAILABLE'
    finally:
        (folder / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return report


def format_report(report):
    lines = ['HIVO PROVIDER PREFLIGHT: ' + report['status']]
    for item in report.get('models', []):
        lines.append(f"{item['provider']}:{item['model']} | {item['execution']} | context {item['context']} | "
                     + ('PASS' if item['passed'] else 'NOT QUALIFIED'))
    if not report['passed']:
        lines.append('Failure: ' + str(report.get('failure_reason')))
        lines.append('No workflow started.')
    return '\n'.join(lines)
