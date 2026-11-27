"""Interactive/CLI model configuration; consent before any cloud access."""
from dataclasses import replace
import argparse
from pathlib import Path
import sys

from hivo.model_routing import RoutingConfig, ROLE_NAMES, role_key
from hivo.providers import ModelSelection, ProviderFailure, parse_reference, _zero_pricing

MODEL_SETTING_NAMES = frozenset({'worker_context', 'worker_output', 'orchestrator_context',
    'orchestrator_output', 'worker_thinking', 'ollama_url', 'model_request_budget'})


class ModelSettingAction(argparse.Action):
    """Track explicit parser assignments, including values equal to defaults."""
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        provided = set(getattr(namespace, 'model_options_provided', ()))
        provided.add(self.dest)
        namespace.model_options_provided = frozenset(provided)


def supplied_model_settings(args):
    provided = getattr(args, 'model_options_provided', None)
    if provided is None:
        # Embedders: properties actually supplied are explicit. A namespace
        # filled with defaults can explicitly mark its provenance as empty.
        return MODEL_SETTING_NAMES.intersection(vars(args))
    if (not isinstance(provided, (set, frozenset, list, tuple))
            or not all(isinstance(name, str) for name in provided)
            or not set(provided) <= MODEL_SETTING_NAMES):
        raise ProviderFailure('INVALID_MODEL_OPTION_PROVENANCE')
    return frozenset(provided)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown/invalid argument values may be accidentally pasted secrets.
        self.exit(2, 'Invalid CLI configuration. Run --help; argument values are not echoed.\n')


def _choose_model(client, role, *, context, output, reasoning, input_fn, print_fn):
    options = []
    for provider in ['ollama', 'openrouter']:
        if provider == 'openrouter' and not client.cloud_catalog_authorized:
            continue
        try:
            rows = client.catalog(provider)
        except ProviderFailure as exc:
            print_fn(provider + ': ' + exc.code)
            continue
        for row in rows:
            name = row['name' if provider == 'ollama' else 'id']
            if provider == 'openrouter' and (not name.endswith(':free') or not _zero_pricing(row.get('pricing'))):
                continue
            spec = ModelSelection(provider, name, context=context, max_output=output,
                                  reasoning=reasoning)
            try:
                info = client.inspect(spec)
                client.validate_assignment(spec, info, needs_tools=role == 'worker')
            except ProviderFailure as exc:
                print_fn(spec.reference + ' | unavailable for role: ' + exc.code)
                continue
            options.append(spec)
            weight = f' | weight files approximately {info.size_bytes / 2**30:.2f} GiB' if provider == 'ollama' else ' | strict free-only'
            print_fn(f'{len(options)}. {spec.reference}{weight} | metadata compatible; canaries pending')
    if not options:
        raise ProviderFailure('NO_COMPATIBLE_MODEL_CHOICES')
    raw = input_fn(f'Select {role} model number: ').strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(options):
        raise ProviderFailure('INVALID_MODEL_CHOICE')
    return options[int(raw) - 1]


def configure(args, client, *, interactive=None, input_fn=input, print_fn=print):
    interactive = sys.stdin.isatty() if interactive is None else interactive
    legacy = getattr(args, 'model', None)
    file = getattr(args, 'model_config', None)
    orchestrator = getattr(args, 'orchestrator_model', None)
    worker = getattr(args, 'worker_model', None)
    if sum(bool(x) for x in [legacy, file, orchestrator or worker]) > 1:
        raise ProviderFailure('CONFLICTING_MODEL_CONFIGURATION')
    if file:
        if supplied_model_settings(args):
            raise ProviderFailure('CONFIG_FILE_AND_CLI_SETTING_CONFLICT')
        config = RoutingConfig.load(file)
    elif legacy:
        spec = ModelSelection('ollama', legacy, endpoint=getattr(args, 'ollama_url', '') or '',
            context=getattr(args, 'worker_context', 4096), max_output=getattr(args, 'worker_output', 1024),
            reasoning=getattr(args, 'worker_thinking', None))
        config = RoutingConfig(spec, spec, request_budget=getattr(args, 'model_request_budget', 40))
    elif orchestrator or worker:
        if not orchestrator or not worker:
            raise ProviderFailure('BOTH_MODEL_GROUPS_MUST_BE_EXPLICIT')
        first = parse_reference(orchestrator, context=getattr(args, 'orchestrator_context', 16384),
                                max_output=getattr(args, 'orchestrator_output', 4096))
        second = parse_reference(worker, context=getattr(args, 'worker_context', 4096),
                                 max_output=getattr(args, 'worker_output', 1024),
                                 reasoning=getattr(args, 'worker_thinking', None))
        if first.provider == 'ollama': first = replace(first, endpoint=getattr(args, 'ollama_url', '') or '')
        if second.provider == 'ollama': second = replace(second, endpoint=getattr(args, 'ollama_url', '') or '')
        config = RoutingConfig(first, second, request_budget=getattr(args, 'model_request_budget', 40))
    elif interactive:
        if client.environ.get('OPENROUTER_API_KEY'):
            client.cloud_catalog_authorized = input_fn('Read configured OpenRouter catalogue (no inference)? [y/N] ').strip().lower() == 'y'
        else:
            print_fn('OpenRouter not configured: set OPENROUTER_API_KEY in this process to enable cloud choices.')
        first = _choose_model(client, 'orchestrator', context=getattr(args, 'orchestrator_context', 16384),
            output=getattr(args, 'orchestrator_output', 4096), reasoning=None, input_fn=input_fn, print_fn=print_fn)
        second = _choose_model(client, 'worker', context=getattr(args, 'worker_context', 4096),
            output=getattr(args, 'worker_output', 1024), reasoning=getattr(args, 'worker_thinking', None), input_fn=input_fn, print_fn=print_fn)
        config = RoutingConfig(first, second, request_budget=getattr(args, 'model_request_budget', 40))
    else:
        raise ProviderFailure('EXPLICIT_MODEL_CONFIGURATION_REQUIRED')
    for item in getattr(args, 'role_model', None) or []:
        role, separator, reference = item.partition('=')
        if not separator: raise ProviderFailure('INVALID_ROLE_OVERRIDE')
        base = config.selection(role)
        spec = parse_reference(reference, context=base.context, max_output=base.max_output, reasoning=base.reasoning)
        config.overrides[role_key(role)] = spec
    print_fn('Model configuration (capabilities require fresh preflight):')
    print_fn('Orchestrator: ' + config.orchestrator.reference + f' | context {config.orchestrator.context}')
    print_fn('Worker: ' + config.worker.reference + f' | context {config.worker.context}')
    for role, spec in config.overrides.items(): print_fn(f'Override {role}: {spec.reference}')
    print_fn(f'Model request budget for this session: {config.request_budget}; local weights use host RAM; cloud quotas may reject requests.')
    remote = any(config.selection(role).provider == 'openrouter' for role in ROLE_NAMES)
    paid = any(config.selection(role).provider == 'openrouter' and not config.selection(role).free_only for role in ROLE_NAMES)
    client.paid_authorized = bool(getattr(args, 'allow_paid_inference', False))
    if paid and not client.paid_authorized:
        raise ProviderFailure('PAID_INFERENCE_APPROVAL_REQUIRED')
    confirmed = bool(getattr(args, 'confirm_models', False))
    if interactive and not confirmed:
        confirmed = input_fn('Confirm this configuration and its provider preflight? [y/N] ').strip().lower() == 'y'
    if not confirmed and (interactive or remote):
        raise ProviderFailure('MODEL_CONFIGURATION_NOT_CONFIRMED')
    if remote:
        approved = (interactive and confirmed or bool(getattr(args, 'approve_free_cloud', False))
                    or confirmed and client.paid_authorized)
        if not approved:
            raise ProviderFailure('CLOUD_INFERENCE_APPROVAL_REQUIRED')
        client.cloud_catalog_authorized = client.cloud_inference_authorized = True
    client.request_budget = config.request_budget
    return config


def choose_workflow(args, *, input_fn=input, print_fn=print):
    if args.prompt_file or '--mode' in sys.argv or not sys.stdin.isatty():
        return
    modes = ['auto', 'baseline', 'recursive', 'current_recursive', 'decomposition_first_recursive']
    print_fn('Mini Hivo workflow:')
    for index, mode in enumerate(modes, 1): print_fn(f'{index}. {mode}')
    value = input_fn('Select workflow number: ').strip()
    if not value.isdigit() or not 1 <= int(value) <= len(modes):
        raise ProviderFailure('INVALID_WORKFLOW_CHOICE')
    args.mode = modes[int(value) - 1]
