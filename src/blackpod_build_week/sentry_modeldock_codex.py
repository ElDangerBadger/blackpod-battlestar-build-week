"""Explicit Sentry-only ModelDock/Codex delivery, never a generic provider policy.

The loopback appliance may dispatch to Codex cloud under its existing login.
This adapter neither logs in, selects a model nor changes ModelDock. All calls
are one-shot; the owning Sentry ledger reserves attempts before constructing it.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
import time
from collections.abc import Mapping
import urllib.error

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .modeldock_client import (
    HttpResponse, ModelDockCallResult, ModelDockClient, ModelDockClientError,
    ModelDockFailure, ModelDockTransportTimeout, UrlLibTransport, _ProtocolIssue,
    _content_length, _safe_token,
)
from .modeldock_config import ModelDockConfig, ModelDockConfigurationError

MAX_RETAINED_RESPONSE_BYTES = 512 * 1024
ENVELOPE_FIELDS = frozenset({'status', 'request_type', 'profile', 'provider',
    'model', 'content', 'data', 'metadata', 'trace_id', 'mocked'})
META_FIELDS = frozenset({'engine', 'codex_model', 'codex_thread_id', 'codex_turn_id',
    'generated_token_count', 'generated_token_count_source', 'stop_reason',
    'stop_reason_source', 'max_tokens_enforced', 'streaming_mode',
    'prefill_cache_supported', 'execution_provenance', 'structured_output',
    'blackpod_correlation'})
PROJECTED_META_FIELDS = META_FIELDS | {'execution_provenance_sha256'}


@dataclass(frozen=True, slots=True)
class SentryCodexConfig(ModelDockConfig):
    """Opt-in configuration; base ModelDockConfig remains MLX-only."""

    provider: str = 'codex'

    def __post_init__(self):
        if self.provider != 'codex':
            raise ModelDockConfigurationError('Sentry Codex provider must be exactly codex')
        checked = ModelDockConfig(self.base_url, self.timeout_seconds,
            profile=self.profile, model=self.model, provider='mlx',
            max_response_bytes=self.max_response_bytes,
            delivery_grace_seconds=self.delivery_grace_seconds)
        if checked.timeout_seconds > 900 or checked.delivery_grace_seconds > 30:
            raise ModelDockConfigurationError('Sentry Codex deadline exceeds 900 seconds plus 30 seconds grace')
        for name in ('base_url', 'timeout_seconds', 'profile', 'model',
                     'max_response_bytes', 'delivery_grace_seconds'):
            object.__setattr__(self, name, getattr(checked, name))


def _known(value, *, source, expected=None):
    if (not isinstance(value, dict) or set(value) != {'status', 'value', 'source'}
            or value['status'] != 'known' or value['source'] != source
            or expected is not None and (value['value'] != expected or type(value['value']) is not type(expected))):
        raise ValueError('Codex execution observation differs')
    return value['value']


def _unavailable(value):
    if value != {'status': 'unavailable', 'reason': 'native_telemetry_not_observed'}:
        raise ValueError('Codex unavailable telemetry differs')


def _basic(envelope, *, projected):
    if (not isinstance(envelope, dict) or set(envelope) != ENVELOPE_FIELDS
            or envelope['status'] != 'ok' or envelope['request_type'] != 'text.generate'
            or envelope['provider'] != 'codex' or envelope['mocked'] is not False
            or envelope['data'] != {}):
        raise ValueError('Codex envelope differs')
    for name in ('profile', 'model', 'trace_id'):
        _safe_token(envelope[name], name)
    metadata = envelope['metadata']
    if (not isinstance(metadata, dict)
            or set(metadata) != (PROJECTED_META_FIELDS if projected else META_FIELDS)
            or metadata['engine'] != 'codex-app-server'
            or metadata['structured_output'] != {'mode': 'json_schema', 'validated': True}
            or metadata['structured_output']['validated'] is not True
            or metadata['max_tokens_enforced'] is not False
            or metadata['prefill_cache_supported'] is not False
            or metadata['streaming_mode'] != 'buffered'
            or metadata['stop_reason'] != 'unknown'
            or metadata['stop_reason_source'] != 'unavailable'):
        raise ValueError('Codex metadata differs')
    for name in ('codex_model', 'codex_thread_id', 'codex_turn_id'):
        _safe_token(metadata[name], name)
    count = metadata['generated_token_count']
    if not ((type(count) is int and count >= 0 and metadata['generated_token_count_source'] == 'native')
            or (count is None and metadata['generated_token_count_source'] == 'unavailable')):
        raise ValueError('Codex optional native usage differs')
    correlation = metadata['blackpod_correlation']
    if (not isinstance(correlation, dict)
            or set(correlation) != {'mission_id', 'request_id', 'symbol', 'run_mode'}
            or correlation['run_mode'] != 'LIVE'):
        raise ValueError('Codex correlation differs')
    for name, value in correlation.items():
        _safe_token(value, name)
    if not isinstance(envelope['content'], str) or not envelope['content'].strip():
        raise ValueError('Codex structured answer missing')
    return metadata


def _execution_projection(execution, envelope):
    metadata = envelope['metadata']
    if (not isinstance(execution, dict)
            or execution.get('schema') != 'modeldock.execution-provenance.v1'
            or execution.get('request_id') != envelope['trace_id']):
        raise ValueError('Codex execution trace differs')
    _safe_token(execution['execution_id'], 'execution_id')
    start = _known(execution['started_at'], source='execution_boundary')
    finish = _known(execution['completed_at'], source='execution_boundary')
    if parse_rfc3339(start, 'Codex started') > parse_rfc3339(finish, 'Codex completed'):
        raise ValueError('Codex execution clocks reversed')
    environment = execution['environment']
    _known(environment['operation'], source='dispatch', expected='text.generate')
    _known(environment['model']['resolved_model'], source='codex_thread_start', expected=metadata['codex_model'])
    for name, value in (('provider', 'codex'), ('engine', 'codex-app-server'),
                        ('implementation', 'providers.codex.CodexProvider')):
        _known(environment['runtime'][name], source='dispatch', expected=value)
    _known(environment['execution_kind'], source='provider_result', expected='inference')
    completion = execution['completion']
    if not isinstance(completion, dict) or set(completion) != {'generated_token_count', 'finish_reason'}:
        raise ValueError('Codex completion fields differ')
    _unavailable(completion['finish_reason'])
    if metadata['generated_token_count'] is None:
        _unavailable(completion['generated_token_count'])
    else:
        _known(completion['generated_token_count'], source='native', expected=metadata['generated_token_count'])
    # Retain only validated public proof. The complete response is retained by
    # the owning transport; its full execution object is bound separately below.
    return copy.deepcopy({
        'schema': execution['schema'], 'execution_id': execution['execution_id'],
        'request_id': execution['request_id'], 'started_at': execution['started_at'],
        'completed_at': execution['completed_at'],
        'environment': {'operation': environment['operation'],
            'model': {'resolved_model': environment['model']['resolved_model']},
            'runtime': {key: environment['runtime'][key] for key in ('provider', 'engine', 'implementation')},
            'execution_kind': environment['execution_kind']},
        'completion': completion})


def codex_projection(original):
    """Project validated public Codex proof, without copying arbitrary metadata."""
    try:
        metadata = _basic(original, projected=False)
        execution = _execution_projection(metadata['execution_provenance'], original)
        projected = copy.deepcopy(original)
        projected['metadata']['execution_provenance'] = execution
        projected['metadata']['execution_provenance_sha256'] = sha256_bytes(
            canonical_json_bytes(metadata['execution_provenance']))
        return projected
    except (KeyError, TypeError, _ProtocolIssue) as exc:
        raise ValueError('Codex projection failed strict validation') from None


def validate_projection(envelope, wire, *, started_at, observed_at):
    """Verify a retained public projection offline; return untouched JSON content."""
    try:
        metadata = _basic(envelope, projected=True)
        if len(canonical_json_bytes(envelope)) > MAX_RETAINED_RESPONSE_BYTES:
            raise ValueError('Codex retained projection exceeds bound')
        identity = metadata['execution_provenance_sha256']
        if (not isinstance(identity, str) or len(identity) != 64
                or any(c not in '0123456789abcdef' for c in identity)):
            raise ValueError('Codex execution identity invalid')
        execution = metadata['execution_provenance']
        if _execution_projection(execution, envelope) != execution:
            raise ValueError('Codex retained proof contains unsupported fields')
        if (envelope['profile'] != wire['profile']
                or metadata['blackpod_correlation'] != wire['metadata']['blackpod_correlation']):
            raise ValueError('Codex retained correlation differs')
        start = parse_rfc3339(started_at, 'host started')
        observed = parse_rfc3339(observed_at, 'host observed')
        if not (start <= parse_rfc3339(execution['started_at']['value'], 'provider started')
                <= parse_rfc3339(execution['completed_at']['value'], 'provider completed') <= observed):
            raise ValueError('Codex execution outside host delivery')
        return parse_strict_json_object_bytes(envelope['content'].encode('utf-8'))
    except (KeyError, TypeError, _ProtocolIssue):
        raise ValueError('Codex retained projection failed strict validation') from None


class CodexSentryClient(ModelDockClient):
    """One serial, bounded Sentry request through the selected Codex provider."""

    def __init__(self, config, *, transport=None, readiness_transport=None,
                 monotonic=time.monotonic, now=None, before_post=None):
        if not isinstance(config, SentryCodexConfig):
            raise ModelDockConfigurationError('Codex Sentry requires explicit SentryCodexConfig')
        super().__init__(config, transport=transport, monotonic=monotonic, now=now)
        # Readiness does not traverse Sentry's POST raw-capture adapter.
        self.readiness_transport = readiness_transport or UrlLibTransport(monotonic=monotonic)
        self.before_post = before_post

    def _readiness(self, deadline):
        values = []
        for path in ('health', 'stats', 'models/active'):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex readiness deadline elapsed')
            response = self.readiness_transport.request(method='GET',
                url=self.config.base_url + '/api/v1/' + path,
                headers={'Accept': 'application/json'}, body=None,
                timeout_seconds=min(5.0, remaining), max_response_bytes=65536)
            self._http(response, limit=65536)
            values.append(parse_strict_json_object_bytes(response.body))
        health, stats, active = values
        model = active['model']
        if (health.get('ready') is not True or health.get('state') != 'READY'
                or health.get('provider_available') is not True
                or type(stats.get('active_compute')) is not int or stats['active_compute'] != 0
                or type(stats.get('active_requests')) is not int or stats['active_requests'] != 0
                or model.get('provider') != 'codex' or model.get('engine') != 'codex-app-server'
                or model.get('status') != 'ACTIVE' or model.get('availability') != 'PROVIDER_MANAGED'
                or model.get('structured_output') != {'mode': 'json_schema', 'supported': True, 'reason': None}
                or model['structured_output']['supported'] is not True
                or active.get('active_model') != model.get('name')
                or stats.get('current_model') != model.get('name')
                or stats.get('configured_model') != model.get('name')):
            raise ValueError('Codex must be selected ready and idle')
        return _safe_token(model['name'], 'active_model')

    @staticmethod
    def _http(response, *, limit):
        if (not isinstance(response, HttpResponse) or type(response.status) is not int
                or not 100 <= response.status <= 599 or type(response.complete) is not bool
                or not isinstance(response.headers, Mapping) or not isinstance(response.body, bytes)):
            raise ValueError('Codex bounded HTTP contract differs')
        if response.status != 200:
            raise _ProtocolIssue('http_status', 'ModelDockHttpError', 'ModelDock returned an HTTP failure')
        declared = _content_length(response.headers)
        if (len(response.body) > limit or not response.complete
                or declared is not None and declared != len(response.body)):
            raise ValueError('Codex response is incomplete or exceeds retained bound')

    def generate_text(self, request_payload, *, mission_id, request_id, symbol,
                      run_mode, content_validator=None, content_requires_correlation=True):
        start = self._monotonic()
        started_at = self._now().astimezone(UTC).isoformat().replace('+00:00', 'Z')
        deadline = start + self.config.delivery_timeout_seconds
        raw_hash = size = None
        delivery = {'schema_version': 'blackpod.modeldock_delivery.v1', 'phase': 'REQUEST_VALIDATION',
            'http_status': None, 'automatic_retry_allowed': False, 'server_completion': 'UNKNOWN'}
        try:
            if run_mode != 'LIVE':
                raise ValueError('Codex Sentry only supports explicit LIVE delivery')
            wire, correlation, _ = self._validate_request(request_payload,
                mission_id=mission_id, request_id=request_id, symbol=symbol, run_mode='LIVE')
            if wire['response_format'].get('type') != 'json_schema':
                raise ValueError('Codex Sentry requires a JSON schema')
            request_bytes = canonical_json_bytes(wire)
            delivery['phase'] = 'READINESS'
            alias = self._readiness(deadline)
            if self.before_post is not None:
                self.before_post()
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex deadline elapsed before POST')
            delivery['phase'] = 'TRANSPORT'
            response = self.transport.request(method='POST',
                url=self.config.endpoint('/text/generate'),
                headers={'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8',
                    'X-ModelDock-Client': 'BlackPod-Sentry'}, body=request_bytes,
                timeout_seconds=remaining,
                max_response_bytes=min(self.config.max_response_bytes, MAX_RETAINED_RESPONSE_BYTES))
            if isinstance(response, HttpResponse) and isinstance(response.body, bytes):
                size, raw_hash = len(response.body), sha256_bytes(response.body)
                delivery['http_status'] = response.status
            self._http(response, limit=min(self.config.max_response_bytes, MAX_RETAINED_RESPONSE_BYTES))
            original = parse_strict_json_object_bytes(response.body)
            projection = codex_projection(original)
            observed_at = self._now().astimezone(UTC).isoformat().replace('+00:00', 'Z')
            parsed = validate_projection(projection, wire, started_at=started_at, observed_at=observed_at)
            if projection['model'] != alias:
                raise ValueError('Codex model route changed after readiness')
            if content_requires_correlation and any(parsed.get(key) != correlation[key]
                    for key in ('mission_id', 'request_id', 'symbol')):
                raise ValueError('Codex content correlation differs')
            if content_validator is None:
                raise ValueError('Sentry requires an explicit host content validator')
            try:
                validated = content_validator(parsed)
            except Exception:
                raise _ProtocolIssue('narrative_schema_invalid', 'ModelDockNarrativeValidationError',
                    'ModelDock content failed the original Sentry host contract') from None
            if self._monotonic() > deadline:
                raise TimeoutError('Codex validation exceeded total delivery deadline')
            projected_bytes = canonical_json_bytes(projection)
            delivery.update(phase='COMPLETE', server_completion='VALIDATED_RESPONSE_RECEIVED')
            return ModelDockCallResult(request_bytes=request_bytes, request_sha256=sha256_bytes(request_bytes),
                raw_response_sha256=raw_hash, response_byte_size=size,
                safe_response=MappingProxyType(copy.deepcopy(projection)), safe_response_bytes=projected_bytes,
                provider='codex', model=projection['model'], model_revision=None,
                trace_id=projection['trace_id'], mocked=False,
                latency_ms=max(0, self._monotonic()-start)*1000, started_at=started_at,
                observed_at=observed_at, parsed_content=validated, delivery=MappingProxyType(delivery))
        except ModelDockClientError:
            raise
        except Exception as exc:
            code = exc.code if isinstance(exc, _ProtocolIssue) else (
                'timeout' if isinstance(exc, (TimeoutError, ModelDockTransportTimeout))
                or isinstance(getattr(exc, 'reason', None), TimeoutError) else
                'connection_failure' if isinstance(exc, (OSError, urllib.error.URLError)) else 'codex_validation_failed')
            raise ModelDockClientError(ModelDockFailure(code=code,
                error_type='ModelDockCodexError', message='Sentry Codex request failed; no automatic resend is allowed',
                resumable=False, latency_ms=max(0, self._monotonic()-start)*1000,
                started_at=started_at, observed_at=self._now().astimezone(UTC).isoformat().replace('+00:00', 'Z'),
                raw_response_sha256=raw_hash, response_byte_size=size, delivery=MappingProxyType(delivery))) from None
