"""Explicit provider/model assignments; no automatic model substitution."""
from dataclasses import asdict, fields, replace
import json
from pathlib import Path
import re

from hivo.agent_roles import AGENT_ROLES, IMPLEMENTATION_ROLES
from hivo.providers import ModelSelection, ProviderClient, ProviderFailure, parse_reference

WORKER_ROLES = IMPLEMENTATION_ROLES
ROLE_NAMES = AGENT_ROLES


def role_key(value):
    key = re.sub(r'[^a-z0-9]', '', str(value).lower())
    key = {'worker': 'builder', 'qualityreview': 'quality'}.get(key, key)
    aliases = {re.sub(r'[^a-z0-9]', '', role): role for role in ROLE_NAMES}
    if key not in aliases:
        raise ProviderFailure('UNASSIGNED_AGENT_ROLE')
    return aliases[key]


class RoutingConfig:
    def __init__(self, orchestrator, worker, *, overrides=None, request_budget=40):
        self.orchestrator, self.worker = orchestrator, worker
        if not isinstance(orchestrator, ModelSelection) or not isinstance(worker, ModelSelection):
            raise ProviderFailure('INVALID_MODEL_SELECTION')
        self.overrides = {}
        for key, value in (overrides or {}).items():
            normalized = role_key(key)
            if normalized in self.overrides:
                raise ProviderFailure('DUPLICATE_ROLE_OVERRIDE')
            self.overrides[normalized] = value
        if any(not isinstance(v, ModelSelection) for v in self.overrides.values()):
            raise ProviderFailure('INVALID_ROLE_OVERRIDE')
        if type(request_budget) is not int or not 1 <= request_budget <= 1000:
            raise ProviderFailure('INVALID_REQUEST_BUDGET')
        self.request_budget = request_budget

    def selection(self, role):
        key = role_key(role)
        return self.overrides.get(key, self.worker if key in WORKER_ROLES else self.orchestrator)

    def to_dict(self):
        return {'version': 1, 'orchestrator': asdict(self.orchestrator), 'worker': asdict(self.worker),
                'roles': {role: asdict(spec) for role, spec in self.overrides.items()}, 'request_budget': self.request_budget}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) - {'version', 'orchestrator', 'worker', 'roles', 'request_budget'} or value.get('version') != 1:
            raise ProviderFailure('INVALID_ROUTING_CONFIG')
        allowed = {f.name for f in fields(ModelSelection)}
        def spec(data):
            if not isinstance(data, dict) or set(data) - allowed:
                raise ProviderFailure('CONFIG_CONTAINS_UNSUPPORTED_OR_SECRET_FIELDS')
            try:
                return ModelSelection(**data)
            except (TypeError, ValueError):
                raise ProviderFailure('INVALID_MODEL_SELECTION') from None
        roles = value.get('roles', {})
        if not isinstance(roles, dict):
            raise ProviderFailure('INVALID_ROLE_OVERRIDE')
        return cls(spec(value.get('orchestrator')), spec(value.get('worker')),
                   overrides={k: spec(v) for k, v in roles.items()}, request_budget=value.get('request_budget', 40))

    @classmethod
    def load(cls, path):
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8-sig')))
        except (OSError, ValueError):
            raise ProviderFailure('UNREADABLE_ROUTING_CONFIG') from None


class RoutingPolicy:
    """Compatibility for existing context/temperature/metrics consumers."""
    def __init__(self, config): self.config = config
    @property
    def model_name(self): return self.config.worker.model
    def context_window(self, role): return self.config.selection(role).context
    def temperature(self, role): return 0.1 if role_key(role) in {'builder', 'repairer'} else 0.0
    def role_models(self): return {role: self.config.selection(role).reference for role in ROLE_NAMES}
    def validate(self, requested=None):
        if requested is not None and requested not in {s.model for s in self.selections()}:
            raise ValueError('explicit model override is outside the configured routing contract')
        return requested or self.config.worker.model
    def selections(self): return set(self.config.selection(role) for role in ROLE_NAMES)


class RoleRouter:
    def __init__(self, config, client=None):
        self.config = config
        self.client = client or ProviderClient(request_budget=config.request_budget)
        self.infos = {}
        self.qualified = False
        self.events = []
        self.active_role = None
        self.safety_guard = None

    def prepare(self):
        for role in ROLE_NAMES:
            spec = self.config.selection(role)
            if spec not in self.infos:
                self.infos[spec] = self.client.inspect(spec)
            self.client.validate_assignment(spec, self.infos[spec], needs_tools=role in WORKER_ROLES)
        return self.infos

    def chat(self, role, messages, *, tools=None, response_format=None, temperature=0.0, model_override=None, provider_retries=None):
        if not self.qualified:
            raise ProviderFailure('MODEL_CONFIGURATION_NOT_PREFLIGHTED')
        key = role_key(role)
        spec = self.config.selection(key)
        if model_override is not None and model_override not in {spec.model, spec.reference}:
            raise ProviderFailure('MODEL_OVERRIDE_VIOLATES_ROLE_ASSIGNMENT')
        self.active_role = key
        if self.safety_guard: self.safety_guard(spec)
        event = {'role': key, 'provider': spec.provider, 'model': spec.model, 'context': spec.context}
        self.events.append(event)
        request_spec = replace(spec, retries=min(spec.retries, max(0, int(provider_retries)))) if provider_retries is not None else spec
        try:
            result = self.client.chat(request_spec, self.infos[spec], messages, tools=tools,
                                      response_format=response_format, temperature=temperature)
        except ProviderFailure as exc:
            event.update(status='failed', code=exc.code, diagnostics=self.client.last_failure_diagnostics)
            raise
        if self.safety_guard: self.safety_guard(spec)
        event.update(status='completed', finish_reason=self.client.last_diagnostics.get('finish_reason'))
        return result
