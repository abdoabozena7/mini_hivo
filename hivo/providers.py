"""Provider boundaries, exact selections and capability records; no tool execution.

Secrets are resolved only at the HTTP boundary. Errors intentionally contain
codes/statuses, never raw provider bodies, request headers or reasoning text.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import json
import os
import re
import time
from urllib.parse import urlsplit

from hivo import http_client


class ProviderFailure(RuntimeError):
    def __init__(self, code, *, status=None):
        self.code, self.status = code, status
        super().__init__(code + (f' (HTTP {status})' if status is not None else ''))


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str
    endpoint: str = ''
    auth_env: str = 'OPENROUTER_API_KEY'
    context: int = 4096
    max_output: int = 1024
    reasoning: str | None = None
    timeout: float = 30.0
    retries: int = 0
    min_interval: float = 0.0
    free_only: bool = True
    keep_alive: str = '5m'

    def __post_init__(self):
        if type(self.free_only) is not bool or not isinstance(self.keep_alive, str) or not re.fullmatch(r'0|[0-9]{1,3}[smh]', self.keep_alive):
            raise ProviderFailure('INVALID_BILLING_RESIDENCY_POLICY')
        if self.provider not in {'ollama', 'openrouter'}:
            raise ProviderFailure('UNKNOWN_PROVIDER')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,254}', self.model) or self.model.startswith('sk-'):
            raise ProviderFailure('INVALID_MODEL_ID')
        if type(self.context) is not int or not 512 <= self.context <= 1000000:
            raise ProviderFailure('INVALID_CONTEXT_BUDGET')
        if type(self.max_output) is not int or not 1 <= self.max_output < self.context:
            raise ProviderFailure('INVALID_OUTPUT_BUDGET')
        if (type(self.retries) is not int or not 0 <= self.retries <= 2
                or type(self.timeout) not in {int, float} or not 1 <= self.timeout <= 180):
            raise ProviderFailure('INVALID_RETRY_TIMEOUT_POLICY')
        if (self.reasoning not in {None, 'default', 'off', 'low', 'medium', 'high'}
                or type(self.min_interval) not in {int, float} or not 0 <= self.min_interval <= 10):
            raise ProviderFailure('INVALID_REASONING_RATE_POLICY')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,100}', self.auth_env):
            raise ProviderFailure('INVALID_SECRET_REFERENCE')
        try:
            parsed = urlsplit(self.base_url)
        except ValueError:
            raise ProviderFailure('UNSAFE_ENDPOINT') from None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProviderFailure('UNSAFE_ENDPOINT')
        if self.provider == 'openrouter' and self.base_url != 'https://openrouter.ai/api/v1':
            raise ProviderFailure('UNAPPROVED_CREDENTIAL_ENDPOINT')
        if self.provider == 'ollama' and (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'localhost', '127.0.0.1', '::1'}):
            raise ProviderFailure('OLLAMA_ENDPOINT_MUST_BE_LOCAL')

    @property
    def base_url(self):
        return (self.endpoint or ('http://127.0.0.1:11434' if self.provider == 'ollama'
                                  else 'https://openrouter.ai/api/v1')).rstrip('/')

    @property
    def reference(self):
        return self.provider + ':' + self.model


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model: str
    capabilities: frozenset[str]
    context: int | None
    thinking_values: tuple = ()
    zero_pricing: bool = False
    size_bytes: int = 0
    remote: bool = False
    evidence: str = 'provider_metadata_only'


def _zero_pricing(pricing):
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= set(pricing):
        return False
    try:
        values = [Decimal(str(value)) for value in pricing.values()]
        return all(v.is_finite() and v == 0 for v in values)
    except (InvalidOperation, ValueError, TypeError):
        return False


def parse_reference(value, **settings):
    provider, separator, model = str(value).partition(':')
    if not separator:
        raise ProviderFailure('MODEL_REFERENCE_REQUIRES_PROVIDER')
    return ModelSelection(provider, model, **settings)


def _normalize_tools(message, offered):
    calls = message.get('tool_calls') or []
    if not isinstance(calls, list) or len(calls) > 8:
        raise ProviderFailure('INVALID_TOOL_CALLS')
    names = {x['function']['name'] for x in offered or [] if isinstance(x, dict) and isinstance(x.get('function'), dict)}
    result = []
    for call in calls:
        function = call.get('function') if isinstance(call, dict) else None
        if not isinstance(function, dict) or function.get('name') not in names:
            raise ProviderFailure('TOOL_NOT_OFFERED')
        args = function.get('arguments')
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                raise ProviderFailure('MALFORMED_TOOL_ARGUMENTS') from None
        if not isinstance(args, dict):
            raise ProviderFailure('TOOL_ARGUMENTS_MUST_BE_OBJECT')
        normalized = {'type': 'function', 'function': {'name': function['name'], 'arguments': args}}
        if isinstance(call.get('id'), str):
            normalized['id'] = call['id']
        result.append(normalized)
    return result


def openai_messages(messages):
    """Translate existing tool_name receipts into exact OpenAI call identities."""
    result, pending = [], []
    for index, original in enumerate(messages):
        message = copy.deepcopy(original)
        message.pop('thinking', None)
        message.pop('reasoning', None)
        images = message.pop('images', None)
        if images:
            message['content'] = [{'type': 'text', 'text': str(message.get('content') or '')}] + [
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + image}} for image in images]
        if message.get('role') == 'assistant' and message.get('tool_calls'):
            for ordinal, call in enumerate(message['tool_calls']):
                call['id'] = call.get('id') or f'call_{index}_{ordinal}'
                call['type'] = 'function'
                if isinstance(call['function'].get('arguments'), dict):
                    call['function']['arguments'] = json.dumps(call['function']['arguments'], ensure_ascii=False)
                pending.append((call['function']['name'], call['id']))
        if message.get('role') == 'tool':
            name = message.pop('tool_name', None) or message.pop('name', None)
            identity = message.get('tool_call_id')
            matched = next((x for x in pending if (x[1] == identity if identity else x[0] == name)), None)
            if matched is None:
                raise ProviderFailure('UNBOUND_TOOL_RESULT')
            message['tool_call_id'] = matched[1]
            pending.remove(matched)
        result.append(message)
    return result


class ProviderClient:
    def __init__(self, *, get=None, post=None, environ=None, sleep=time.sleep,
                 cloud_catalog_authorized=False, cloud_inference_authorized=False,
                 paid_authorized=False, request_budget=40):
        self.get = get or http_client.get_json
        self.post = post or http_client.post_json
        self.environ = os.environ if environ is None else environ
        self.sleep = sleep
        self.cloud_catalog_authorized = cloud_catalog_authorized
        self.cloud_inference_authorized = cloud_inference_authorized
        self.paid_authorized = paid_authorized
        self.request_budget = request_budget
        if type(request_budget) is not int or not 1 <= request_budget <= 1000:
            raise ProviderFailure('INVALID_REQUEST_BUDGET')
        self.requests = 0
        self.last_request_at = 0.0
        self.last_diagnostics = {}
        self.last_failure_diagnostics = {}
        self.blocked = False
        self._catalogs = {}

    def _headers(self, selection, *, inference=False):
        if selection.provider != 'openrouter':
            return {}
        if not (self.cloud_inference_authorized if inference else self.cloud_catalog_authorized):
            raise ProviderFailure('CLOUD_INFERENCE_APPROVAL_REQUIRED' if inference else 'CLOUD_CATALOG_APPROVAL_REQUIRED')
        key = self.environ.get(selection.auth_env)
        if not key:
            raise ProviderFailure('MISSING_API_KEY')
        return {'Authorization': 'Bearer ' + key}

    def _json(self, response):
        if response.status_code != 200:
            code = {401: 'AUTHENTICATION_FAILED', 402: 'CREDIT_OR_BILLING_LIMIT', 404: 'MODEL_OR_ENDPOINT_UNAVAILABLE',
                    429: 'RATE_LIMITED'}.get(response.status_code, 'PROVIDER_HTTP_ERROR')
            raise ProviderFailure(code, status=response.status_code)
        try:
            body = response.json()
        except (ValueError, TypeError):
            raise ProviderFailure('MALFORMED_PROVIDER_RESPONSE') from None
        if not isinstance(body, dict) or body.get('error'):
            raise ProviderFailure('PROVIDER_ERROR_ENVELOPE')
        return body

    def authenticate(self, selection):
        if selection.provider == 'ollama':
            return {'authentication': 'local_endpoint'}
        try:
            body = self._json(self.get(selection.base_url + '/key', timeout=10, headers=self._headers(selection)))
        except ProviderFailure:
            raise
        except (OSError, TimeoutError):
            raise ProviderFailure('PROVIDER_UNREACHABLE') from None
        if not isinstance(body.get('data'), dict):
            raise ProviderFailure('INVALID_AUTHENTICATION_RESPONSE')
        return {'authenticated': True, 'free_tier_reported': body['data'].get('is_free_tier') is True}

    def catalog(self, provider, *, endpoint='', auth_env='OPENROUTER_API_KEY', refresh=False):
        # Temporary ID is only an endpoint configuration carrier, never sent.
        selection = ModelSelection(provider, 'catalog', endpoint=endpoint, auth_env=auth_env)
        headers = self._headers(selection)
        cache_key = (provider, selection.base_url, auth_env)
        if refresh:
            self._catalogs.pop(cache_key, None)
        if cache_key in self._catalogs:
            return copy.deepcopy(self._catalogs[cache_key])
        try:
            body = self._json(self.get(selection.base_url + ('/api/tags' if provider == 'ollama' else '/models'),
                                       timeout=10, headers=headers))
        except ProviderFailure:
            raise
        except (OSError, TimeoutError):
            raise ProviderFailure('PROVIDER_UNREACHABLE') from None
        values = body.get('models' if provider == 'ollama' else 'data')
        if not isinstance(values, list):
            raise ProviderFailure('INVALID_MODEL_CATALOG')
        result = [item for item in values if isinstance(item, dict) and isinstance(item.get('name' if provider == 'ollama' else 'id'), str)]
        self._catalogs[cache_key] = copy.deepcopy(result)
        return result

    def inspect(self, selection):
        rows = self.catalog(selection.provider, endpoint=selection.endpoint, auth_env=selection.auth_env)
        row = next((r for r in rows if r.get('name' if selection.provider == 'ollama' else 'id') == selection.model), None)
        if row is None:
            raise ProviderFailure('SELECTED_MODEL_UNAVAILABLE')
        if selection.provider == 'ollama':
            try:
                data = self._json(self.post(selection.base_url + '/api/show', timeout=10, payload={'model': selection.model}))
            except ProviderFailure:
                raise
            except (OSError, TimeoutError):
                raise ProviderFailure('PROVIDER_UNREACHABLE') from None
            capabilities = data.get('capabilities', [])
            metadata, thinking = data.get('model_info', {}), data.get('thinking') or {}
            size = row.get('size') or 0
            if (not isinstance(capabilities, list) or any(not isinstance(x, str) for x in capabilities)
                    or not isinstance(metadata, dict) or not isinstance(thinking, dict)
                    or not isinstance(thinking.get('values', []), list)
                    or type(size) is not int or size < 0):
                raise ProviderFailure('INVALID_CAPABILITY_METADATA')
            caps = frozenset(capabilities)
            contexts = [v for k, v in metadata.items() if k.endswith('.context_length') and type(v) is int]
            return ModelInfo('ollama', selection.model, caps, min(contexts) if contexts else None,
                             tuple(thinking.get('values', [])), size_bytes=size,
                             remote=bool(data.get('remote_model') or data.get('remote_host')))
        parameters, architecture = row.get('supported_parameters') or [], row.get('architecture') or {}
        if (not isinstance(parameters, list) or any(not isinstance(x, str) for x in parameters)
                or not isinstance(architecture, dict) or not isinstance(architecture.get('input_modalities', []), list)):
            raise ProviderFailure('INVALID_CAPABILITY_METADATA')
        params = set(parameters)
        caps = {'completion'}
        if 'tools' in params: caps.add('tools')
        if 'response_format' in params: caps.add('json')
        if 'structured_outputs' in params: caps.update({'json', 'schema'})
        if 'reasoning' in params: caps.add('thinking')
        if 'image' in architecture.get('input_modalities', []): caps.add('vision')
        return ModelInfo('openrouter', selection.model, frozenset(caps), row.get('context_length'),
                         zero_pricing=_zero_pricing(row.get('pricing')), remote=True)

    def validate_assignment(self, selection, info, *, needs_tools=False, needs_json=True):
        if info.model != selection.model or info.provider != selection.provider:
            raise ProviderFailure('CAPABILITY_IDENTITY_MISMATCH')
        if 'completion' not in info.capabilities or (needs_tools and 'tools' not in info.capabilities):
            raise ProviderFailure('REQUIRED_CAPABILITY_UNAVAILABLE')
        if type(info.context) is not int or info.context <= 0 or selection.context > info.context:
            raise ProviderFailure('CONTEXT_CAPABILITY_UNVERIFIED')
        if selection.provider == 'openrouter':
            if needs_json and 'json' not in info.capabilities:
                raise ProviderFailure('STRUCTURED_OUTPUT_UNSUPPORTED')
            if selection.free_only:
                if not selection.model.endswith(':free') or selection.model in {'openrouter/auto', 'openrouter/free'} or not info.zero_pricing:
                    raise ProviderFailure('FREE_ONLY_POLICY_VIOLATION')
            elif not self.paid_authorized:
                raise ProviderFailure('PAID_INFERENCE_APPROVAL_REQUIRED')
        elif info.remote:
            raise ProviderFailure('OLLAMA_REMOTE_ALIAS_REQUIRES_SEPARATE_CLOUD_POLICY')
        if selection.reasoning not in {None, 'default'}:
            if selection.provider == 'ollama':
                wanted = False if selection.reasoning == 'off' else selection.reasoning
                if not any(type(x) is type(wanted) and x == wanted for x in info.thinking_values):
                    raise ProviderFailure('REASONING_CONTROL_UNSUPPORTED')
            elif 'thinking' not in info.capabilities:
                raise ProviderFailure('REASONING_CONTROL_UNSUPPORTED')

    def chat(self, selection, info, messages, *, tools=None, response_format=None, temperature=0.0):
        self.last_failure_diagnostics = {}
        self.validate_assignment(selection, info, needs_tools=bool(tools), needs_json=response_format is not None)
        if self.blocked or self.requests >= self.request_budget:
            raise ProviderFailure('PROVIDER_REQUEST_BUDGET_EXHAUSTED')
        if any(m.get('images') or isinstance(m.get('content'), list) for m in messages) and 'vision' not in info.capabilities:
            raise ProviderFailure('VISION_CAPABILITY_UNAVAILABLE')
        estimate = (len(json.dumps({'messages': messages, 'tools': tools, 'format': response_format}, ensure_ascii=False)) + 2) // 3
        if estimate + selection.max_output > selection.context:
            self.last_failure_diagnostics = {'estimated_input_tokens': estimate, 'context': selection.context,
                                             'reserved_output_tokens': selection.max_output,
                                             'message_chars': len(json.dumps(messages)),
                                             'tool_schema_chars': len(json.dumps(tools or []))}
            raise ProviderFailure('CONTEXT_BUDGET_EXCEEDED')
        headers = self._headers(selection, inference=True)
        if selection.provider == 'ollama':
            payload = {'model': selection.model, 'messages': copy.deepcopy(messages), 'stream': False, 'keep_alive': selection.keep_alive,
                       'options': {'num_ctx': selection.context, 'num_predict': selection.max_output, 'temperature': temperature, 'seed': 0}}
            if tools: payload['tools'] = copy.deepcopy(tools)
            if response_format is not None: payload['format'] = response_format
            if selection.reasoning not in {None, 'default'}:
                payload['think'] = False if selection.reasoning == 'off' else selection.reasoning
            path = '/api/chat'
        else:
            payload = {'model': selection.model, 'messages': openai_messages(messages), 'stream': False,
                       'max_tokens': selection.max_output, 'temperature': temperature,
                       'provider': {'allow_fallbacks': False, 'require_parameters': True}}
            if selection.free_only:
                payload['provider']['max_price'] = {'prompt': 0, 'completion': 0, 'request': 0, 'image': 0}
            if tools: payload['tools'] = copy.deepcopy(tools)
            if response_format is not None:
                payload['response_format'] = ({'type': 'json_schema', 'json_schema': {'name': 'hivo_contract', 'strict': True, 'schema': response_format}}
                                              if 'schema' in info.capabilities else {'type': 'json_object'})
            if selection.reasoning not in {None, 'default'}:
                payload['reasoning'] = {'enabled': False} if selection.reasoning == 'off' else {'effort': selection.reasoning}
            path = '/chat/completions'
        for attempt in range(selection.retries + 1):
            if self.requests >= self.request_budget:
                raise ProviderFailure('PROVIDER_REQUEST_BUDGET_EXHAUSTED')
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < selection.min_interval: self.sleep(selection.min_interval - elapsed)
            self.requests += 1
            self.last_request_at = time.monotonic()
            try:
                response = self.post(selection.base_url + path, timeout=selection.timeout, payload=copy.deepcopy(payload), headers=headers)
                body = self._json(response)
                break
            except (OSError, TimeoutError):
                if attempt >= selection.retries:
                    raise ProviderFailure('PROVIDER_UNREACHABLE') from None
            except ProviderFailure as exc:
                if exc.status not in {429, 500, 502, 503, 504} or attempt >= selection.retries:
                    raise
                retry_after = getattr(response, 'headers', {}).get('Retry-After', '1')
                try: delay = float(retry_after)
                except (TypeError, ValueError): delay = 1.0
                if delay > 2 or delay < 0:
                    raise ProviderFailure('RATE_LIMIT_RETRY_DEFERRED', status=exc.status) from None
                self.sleep(delay)
        if body.get('model') != selection.model:
            self.blocked = True
            raise ProviderFailure('RESPONSE_MODEL_IDENTITY_MISMATCH')
        if selection.provider == 'ollama':
            finish = body.get('done_reason')
            if body.get('done') is not True or finish not in {'stop', 'tool_calls'}:
                raise ProviderFailure('TRUNCATED_OR_INCOMPLETE_RESPONSE')
            message = body.get('message')
            usage = {'input_tokens': body.get('prompt_eval_count'), 'output_tokens': body.get('eval_count')}
        else:
            choices = body.get('choices')
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ProviderFailure('INVALID_RESPONSE_CHOICES')
            finish = choices[0].get('finish_reason')
            if finish not in {'stop', 'tool_calls'}:
                raise ProviderFailure('TRUNCATED_OR_INCOMPLETE_RESPONSE')
            message = choices[0].get('message')
            usage = body.get('usage') or {}
            if not isinstance(usage, dict):
                raise ProviderFailure('INVALID_USAGE_ENVELOPE')
            if selection.free_only and 'cost' in usage:
                try: zero_cost = Decimal(str(usage['cost'])).is_finite() and Decimal(str(usage['cost'])) == 0
                except (InvalidOperation, TypeError, ValueError): zero_cost = False
                if not zero_cost:
                    self.blocked = True
                    raise ProviderFailure('REPORTED_COST_VIOLATES_FREE_POLICY')
        if not isinstance(message, dict) or message.get('role') != 'assistant' or not isinstance(message.get('content') or '', str):
            raise ProviderFailure('INVALID_ASSISTANT_MESSAGE')
        calls = _normalize_tools(message, tools)
        if selection.provider == 'openrouter' and calls and any(not c.get('id') for c in calls):
            raise ProviderFailure('INVALID_CLOUD_TOOL_CALL_ID')
        if calls and message.get('reasoning_details'):
            raise ProviderFailure('UNSUPPORTED_REASONING_TOOL_CONTINUATION_STATE')
        if selection.reasoning == 'off' and (message.get('thinking') or message.get('reasoning') or message.get('reasoning_details')):
            raise ProviderFailure('REASONING_OFF_NOT_HONORED')
        content = message.get('content') or ''
        if not content.strip() and not calls:
            raise ProviderFailure('EMPTY_FINAL_RESPONSE')
        self.last_diagnostics = {'provider': selection.provider, 'model': selection.model, 'finish_reason': finish,
                                 'reasoning_present': bool(message.get('thinking') or message.get('reasoning') or message.get('reasoning_details')),
                                 'content_chars': len(content), 'tool_calls': len(calls),
                                 'usage': {k: usage[k] for k in ('input_tokens', 'output_tokens', 'prompt_tokens', 'completion_tokens', 'cost')
                                           if k in usage and type(usage[k]) in {int, float} and 0 <= usage[k] < 10**15}}
        return {'role': 'assistant', 'content': content, **({'tool_calls': calls} if calls else {})}
