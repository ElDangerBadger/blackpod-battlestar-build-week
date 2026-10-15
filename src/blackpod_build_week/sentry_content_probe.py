"""Explicit one-GET article-content observation after a reviewed synthesis pair.

This is neither a recurring collector nor synthesis input. Bodies remain private
untrusted evidence. Availability is not a subscription or licensing attestation.
"""
from contextlib import contextmanager
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import argparse
import fcntl
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import (
    JournalStoreError, _absolute_path, _check_existing_ancestors, _open_root,
    _open_child_directory, _publish_immutable, _read_regular as _read_descriptor,
    check_separate_root,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import (
    PaperCredentials, MAX_CREDENTIAL_BYTES, _credential_literal, _read_regular, parse_credentials,
)
from .sentry_catalyst import symbols, clock, stamp, control as catalyst_control
from .sentry_catalyst_service import paths as catalyst_paths
from .sentry_synthesis_service import paths as synthesis_paths, ledger, read_report
from .sentry_synthesis_transport import _read
from .shadow_station import read_state
from .shadow_station_collection import _off, _pinned_view
from .trading_historical_intake import parse_historical_json

VERSION = 'blackpod.sentry_content_probe.v1'
URL = 'https://data.alpaca.markets/v1beta1/news'
MAX_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 20
AUTHORITY = 'OBSERVATION_ONLY'
LIMITATIONS = [
    'ONE_BOUNDED_SAMPLE_NOT_COMPLETE_NEWS_OR_ENTITLEMENT_ATTESTATION',
    'CONTENT_OBSERVED_DOES_NOT_GUARANTEE_FULL_ARTICLE',
    'NO_CONTENT_OR_NO_ARTICLES_REMAINS_INCONCLUSIVE',
    'SUBSCRIPTION_AND_CONTENT_LICENSING_RIGHTS_UNKNOWN_NOT_REVIEWED',
    'UNTRUSTED_HTML_NOT_RENDERED_EXECUTED_OR_SENT_TO_MODELS',
    'NO_PAGINATION_RETRY_PAYWALL_FETCH_OR_PROVIDER_FALLBACK',
    'FROZEN_EXPERIMENT_AND_TRADING_AUTHORITY_UNCHANGED',
]
FILES = {'intent.json', 'response.bin', 'transport.json', 'report.json', 'outcome.json', 'staging', '.probe.lock'}
ERRORS = (ValueError, TypeError, KeyError, OSError, RuntimeError, JournalStoreError)


class ProbeError(ValueError):
    def __init__(self, code, http_status=None):
        self.code = code if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,90}', code) else 'PROBE_BLOCKED'
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


def utc_now():
    return datetime.now(timezone.utc)


def _validate_query(query):
    try:
        if (not isinstance(query, dict) or set(query) != {'symbols', 'start', 'end', 'limit', 'sort', 'include_content'}
                or type(query['limit']) is not int or query['limit'] != 3 or query['sort'] != 'desc'
                or query['include_content'] != 'true'
                or not timedelta(0) < clock(query['end']) - clock(query['start']) <= timedelta(hours=24)):
            raise ValueError()
        named = symbols(query['symbols'].split(','))
        if ','.join(named) != query['symbols']:
            raise ValueError()
        return dict(query)
    except ERRORS:
        raise ProbeError('QUERY_REFUSED') from None


def _sensitive(raw, credentials):
    key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
    if any(value.encode('utf-8') in raw for value in (key, secret)):
        raise ProbeError('SENSITIVE_RESPONSE_REFUSED')
    document = parse_historical_json(raw)
    def walk(value, depth=0):
        if depth > 16:
            raise ValueError('response nesting bound')
        if isinstance(value, str):
            return key in value or secret in value
        if isinstance(value, list):
            return any(walk(child, depth + 1) for child in value)
        if isinstance(value, dict):
            return any(walk(name, depth + 1) or walk(child, depth + 1) for name, child in value.items())
        return False
    if walk(document):
        raise ProbeError('SENSITIVE_RESPONSE_REFUSED')


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise ProbeError('REDIRECT_REFUSED', code)


def _remaining_timeout(response, remaining):
    current = response
    candidates = [current]
    for name in ('fp', 'raw', '_sock'):
        current = getattr(current, name, None)
        if current is None:
            break
        candidates.append(current)
    for candidate in reversed(candidates):
        setter = getattr(candidate, 'settimeout', None)
        if callable(setter):
            setter(max(0.001, remaining))
            break


def content_get(query, credentials):
    """Exactly one fixed-host GET. No redirects, pagination, proxies or retries."""
    query = _validate_query(query)
    if not isinstance(credentials, PaperCredentials):
        raise ProbeError('CREDENTIALS_REFUSED')
    try:
        key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
        url = URL + '?' + urlencode(sorted(query.items()))
        request = Request(url, method='GET', headers={'APCA-API-KEY-ID': key,
            'APCA-API-SECRET-KEY': secret, 'Accept': 'application/json'})
        opener = build_opener(ProxyHandler({}), _NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
        deadline = time.monotonic() + TIMEOUT_SECONDS
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() != url:
                raise ProbeError('REDIRECT_REFUSED')
            if type(response.status) is not int or response.status != 200:
                raise ProbeError('HTTP_ERROR', response.status)
            declared = getattr(response, 'headers', {}).get('Content-Length')
            if declared is not None and (not isinstance(declared, str) or not declared.isdigit() or not 0 < int(declared) <= MAX_BYTES):
                raise ProbeError('RESPONSE_SIZE_REFUSED')
            parts, size = [], 0
            reader = getattr(response, 'read1', response.read)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProbeError('TIMEOUT')
                _remaining_timeout(response, remaining)
                part = reader(min(65536, MAX_BYTES + 1 - size))
                if not isinstance(part, bytes):
                    raise ProbeError('RESPONSE_REFUSED')
                if not part:
                    break
                parts.append(part); size += len(part)
                if size > MAX_BYTES:
                    raise ProbeError('RESPONSE_TOO_LARGE')
            raw = b''.join(parts)
            if not raw or (declared is not None and int(declared) != len(raw)):
                raise ProbeError('RESPONSE_SIZE_REFUSED')
        _sensitive(raw, credentials)
        receipt = {'schema_version': VERSION, 'method': 'GET', 'url': URL, 'query': query,
                   'captured_at': stamp(utc_now()), 'status': 200,
                   'body_sha256': sha256_bytes(raw), 'size_bytes': len(raw)}
        return raw, receipt
    except ProbeError:
        raise
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise ProbeError('HTTP_ERROR', status) from None
    except (TimeoutError, socket.timeout):
        raise ProbeError('TIMEOUT') from None
    except URLError:
        raise ProbeError('URL_ERROR') from None
    except (OSError, HTTPException):
        raise ProbeError('TRANSPORT_ERROR') from None
    except ERRORS:
        raise ProbeError('INPUT_OR_RESPONSE_REFUSED') from None


def _paths(config, destination):
    output = _absolute_path(Path(destination))
    _check_existing_ancestors(output)
    protected = [Path(config[key]) for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root')]
    protected += [Path(config['station_root']), catalyst_paths(config)[0], synthesis_paths(config)[0], Path(config['credentials_file']).parent]
    repo = Path(config['repo_root'])
    if output.parent != repo / 'output':
        raise ProbeError('OUTPUT_SCOPE_REFUSED')
    protected += [repo / name for name in ('src', 'tests', 'fixtures', 'examples', 'macos', '.git', 'missions')]
    for source in protected:
        check_separate_root(output, source)
    return output


def _review(config, reviewed_report_id, *, require_current_watchlist=True):
    if not isinstance(reviewed_report_id, str) or re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', reviewed_report_id) is None:
        raise ProbeError('REVIEW_ID_REFUSED')
    _, runs = synthesis_paths(config)
    found = None
    for directory, _, _, _ in ledger(runs):
        if not (directory / 'report.json').exists():
            continue
        report = read_report(directory, config)
        if report['report_id'] == reviewed_report_id:
            if (report['status'] != 'CHALLENGED_INTERPRETATION'
                    or any(report['provenance'][role]['status'] != 'ACCEPTED' for role in ('oracle', 'challenge'))):
                raise ProbeError('REVIEW_PAIR_NOT_ACCEPTED')
            if found is not None:
                raise ProbeError('REVIEW_ID_CONFLICT')
            named = symbols(report['context']['watchlist'])
            found = {'reviewed_report_id': reviewed_report_id, 'context_id': report['context']['context_id'],
                     'report_sha256': sha256_bytes(canonical_json_bytes(report)), 'watchlist': named}
    if found is None:
        raise ProbeError('REVIEW_NOT_FOUND')
    if require_current_watchlist:
        selected = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
        if selected['symbols'] != found['watchlist']:
            raise ProbeError('WATCHLIST_DIFFERS_FROM_REVIEW')
    return found


def _frozen(config):
    # Journal replay compares all nine current implementation files with their
    # immutable registration evidence. This reads neither providers nor orders.
    return _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])['journal']


def _verify_frozen(config, before, *, current=None):
    """Allow later legitimate appends, while verifying the original prefix."""
    current = _frozen(config) if current is None else current
    if current == before:
        return current
    count = before.get('event_count')
    if (type(count) is not int or count < 1 or type(current.get('event_count')) is not int
            or current['event_count'] < count):
        raise ProbeError('FROZEN_PREFIX_REFUSED')
    entry = Path(config['experiment_root']) / 'entries' / f'{count:08d}.json'
    if sha256_bytes(_read_regular(entry, 64 * 1024 * 1024)) != before.get('last_entry_sha256'):
        raise ProbeError('FROZEN_PREFIX_REFUSED')
    return current


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ProbeError('HASH_REFUSED')
    return value


def _validate_intent(intent):
    if (not isinstance(intent, dict) or set(intent) != {'schema_version', 'reviewed_report_id', 'context_id', 'report_sha256',
        'watchlist', 'query', 'reserved_at', 'frozen_before', 'authority'}
            or intent['schema_version'] != VERSION or intent['authority'] != AUTHORITY):
        raise ProbeError('INTENT_REFUSED')
    _digest(intent['report_sha256'])
    if re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', intent['reviewed_report_id']) is None:
        raise ProbeError('REVIEW_ID_REFUSED')
    if not isinstance(intent['context_id'], str) or not 1 <= len(intent['context_id']) <= 256:
        raise ProbeError('CONTEXT_REFUSED')
    named = symbols(intent['watchlist'])
    query = _validate_query(intent['query'])
    if (query['symbols'] != ','.join(named) or clock(query['end']) != clock(intent['reserved_at'])
            or clock(query['end']) - clock(query['start']) != timedelta(hours=24)
            or not isinstance(intent['frozen_before'], dict)):
        raise ProbeError('INTENT_QUERY_REFUSED')
    return intent


def _receipt(raw, receipt, intent):
    if (not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES or not isinstance(receipt, dict)
            or set(receipt) != {'schema_version', 'method', 'url', 'query', 'captured_at', 'status', 'body_sha256', 'size_bytes'}
            or receipt['schema_version'] != VERSION or receipt['method'] != 'GET' or receipt['url'] != URL
            or type(receipt['status']) is not int or receipt['status'] != 200
            or receipt['query'] != intent['query'] or receipt['body_sha256'] != sha256_bytes(raw)
            or type(receipt['size_bytes']) is not int or receipt['size_bytes'] != len(raw)
            or clock(receipt['captured_at']) < clock(intent['reserved_at'])):
        raise ProbeError('TRANSPORT_RECEIPT_REFUSED')
    _validate_query(receipt['query'])
    return receipt


def project(raw, receipt, intent):
    """Pure metadata projection; no article, headline, summary or HTML body text."""
    _validate_intent(intent); _receipt(raw, receipt, intent)
    document = parse_historical_json(raw)
    if not isinstance(document, dict) or set(document) - {'news', 'next_page_token'} or not isinstance(document.get('news'), list) or len(document['news']) > 3:
        raise ProbeError('NEWS_RESPONSE_REFUSED')
    token = document.get('next_page_token')
    if token is not None and (not isinstance(token, str) or not 0 < len(token) <= 2048):
        raise ProbeError('PAGINATION_METADATA_REFUSED')
    articles, seen = [], set()
    for article in document['news']:
        if not isinstance(article, dict):
            raise ProbeError('ARTICLE_REFUSED')
        identity = article.get('id')
        if (isinstance(identity, bool) or not isinstance(identity, (int, Decimal))
                or isinstance(identity, Decimal) and (not identity.is_finite() or identity != identity.to_integral_value())
                or not 0 <= identity <= 10 ** 30):
            raise ProbeError('ARTICLE_ID_REFUSED')
        identity = str(int(identity))
        if identity in seen:
            raise ProbeError('ARTICLE_ID_REFUSED')
        seen.add(identity)
        source = article.get('source')
        if not isinstance(source, str) or not 0 < len(source) <= 200 or any(ord(c) < 32 for c in source):
            raise ProbeError('ARTICLE_SOURCE_REFUSED')
        published, updated = clock(article['created_at']), clock(article['updated_at'])
        if published > updated or updated > clock(receipt['captured_at']) + timedelta(seconds=5):
            raise ProbeError('ARTICLE_CLOCK_REFUSED')
        named = article.get('symbols')
        if not isinstance(named, list) or len(named) > 1000 or any(not isinstance(s, str) for s in named):
            raise ProbeError('ARTICLE_SYMBOLS_REFUSED')
        matched = sorted(set(named) & set(intent['watchlist']))
        if not matched:
            raise ProbeError('ARTICLE_SCOPE_REFUSED')
        body, summary = article.get('content'), article.get('summary')
        content_is_string = isinstance(body, str)
        content_bytes = body.encode('utf-8') if content_is_string else None
        articles.append({'provider_id': str(identity), 'source': source, 'published_at': stamp(published),
            'updated_at': stamp(updated), 'matched_symbols': matched, 'content_field_present': 'content' in article,
            'content_is_string': content_is_string, 'content_present': content_is_string and bool(body.strip()),
            'content_bytes': len(content_bytes) if content_bytes is not None else 0,
            'content_sha256': sha256_bytes(content_bytes) if content_bytes is not None else None,
            'summary_bytes': len(summary.encode('utf-8')) if isinstance(summary, str) else 0})
    count = sum(row['content_present'] for row in articles)
    result = {'schema_version': VERSION, 'status': 'CONTENT_OBSERVED' if count else 'NO_CONTENT_IN_SAMPLE' if articles else 'NO_ARTICLES',
        'reviewed_report_id': intent['reviewed_report_id'], 'context_id': intent['context_id'],
        'reviewed_report_sha256': intent['report_sha256'], 'watchlist': list(intent['watchlist']), 'query': dict(intent['query']),
        'captured_at': receipt['captured_at'], 'response_sha256': receipt['body_sha256'],
        'response_size_bytes': len(raw), 'article_count': len(articles), 'content_observed_count': count,
        'pagination_available': token is not None, 'articles': articles, 'licensing_rights': 'UNKNOWN_NOT_REVIEWED',
        'entitlement_scope': 'OBSERVED_RESPONSE_ONLY_NOT_SUBSCRIPTION_ATTESTATION',
        'authority': AUTHORITY, 'limitations': list(LIMITATIONS)}
    result['report_id'] = 'sentry-content-probe-' + sha256_bytes(canonical_json_bytes(result))
    return result


@contextmanager
def _directory(destination, *, create, lock):
    root = _open_root(destination, create=create)
    staging = descriptor = None
    try:
        metadata = os.fstat(root)
        if metadata.st_mode & 0o077 or metadata.st_uid != os.getuid():
            raise ProbeError('PRIVATE_OUTPUT_REQUIRED')
        if set(os.listdir(root)) - FILES:
            raise ProbeError('UNEXPECTED_PROBE_FILE')
        if lock:
            descriptor = os.open('.probe.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=root)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ProbeError('UNSAFE_PROBE_LOCK')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProbeError('PROBE_BUSY') from None
        elif '.probe.lock' in os.listdir(root):
            body, info = _read_descriptor(root, '.probe.lock')
            if body or info.st_nlink != 1:
                raise ProbeError('UNSAFE_PROBE_LOCK')
        if create or 'staging' in os.listdir(root):
            staging = _open_child_directory(root, 'staging', create=create)
            inventory = []
            for name in os.listdir(root):
                if name != 'staging':
                    info = os.stat(name, dir_fd=root, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise ProbeError('UNSAFE_PROBE_FILE')
                    inventory.append(info)
            pending = []
            for name in os.listdir(staging):
                if re.fullmatch(r'\.publish-[0-9a-f]{32}\.tmp', name) is None:
                    raise ProbeError('UNEXPECTED_STAGING_FILE')
                info = os.stat(name, dir_fd=staging, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise ProbeError('UNSAFE_STAGING_LINK')
                inventory.append(info); pending.append((name, info))
            internal = Counter((info.st_dev, info.st_ino) for info in inventory)
            for name, info in pending:
                if info.st_nlink != internal[(info.st_dev, info.st_ino)]:
                    raise ProbeError('UNSAFE_STAGING_LINK')
                _read_descriptor(staging, name)  # Read only fully accounted local files.
        yield root, staging
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if staging is not None:
            os.close(staging)
        os.close(root)


def _publish(root, staging, name, value):
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ProbeError('PROBE_FILE_SIZE_REFUSED')
    _publish_immutable(staging, root, name, raw)


def _read_json(root, name):
    value, raw = _read(root, name)
    if raw != canonical_json_bytes(value):
        raise ProbeError('NONCANONICAL_PROBE_JSON')
    return value, raw


def _result(status, *, intent=None, report=None, outcome=None, provider_calls=0, verified=False):
    return {'schema_version': VERSION, 'status': status, 'report': report,
        'report_id': report['report_id'] if report else None,
        'reviewed_report_id': intent['reviewed_report_id'] if intent else None,
        'context_id': intent['context_id'] if intent else None,
        'provider_calls': provider_calls, 'original_provider_calls': outcome['provider_calls'] if outcome else None,
        'failure_code': outcome['failure_code'] if outcome else None,
        'http_status': outcome['http_status'] if outcome else None,
        'verification_status': 'VERIFIED' if verified else 'NOT_COMPLETE',
        'authority': AUTHORITY}


def _verify(config, root):
    names = set(os.listdir(root))
    if 'intent.json' not in names:
        if names - {'staging', '.probe.lock'}:
            raise ProbeError('PROBE_WITHOUT_INTENT')
        return _result('NOT_RUN')
    intent, intent_raw = _read_json(root, 'intent.json')
    _validate_intent(intent)
    _verify_frozen(config, intent['frozen_before'])
    bound = _review(config, intent['reviewed_report_id'], require_current_watchlist=False)
    if any(bound[key] != intent[key] for key in ('reviewed_report_id', 'context_id', 'report_sha256', 'watchlist')):
        raise ProbeError('REVIEW_BINDING_DIFFERS')
    if 'response.bin' in names:
        _, raw = _read(root, 'response.bin')
        if len(raw) > MAX_BYTES:
            raise ProbeError('PROBE_FILE_SIZE_REFUSED')
    else:
        raw = None
    receipt = _read_json(root, 'transport.json')[0] if 'transport.json' in names else None
    if raw is not None and receipt is not None:
        _receipt(raw, receipt, intent)
    if 'outcome.json' not in names:
        if 'report.json' in names and (raw is None or receipt is None):
            raise ProbeError('REPORT_WITHOUT_RESPONSE')
        return _result('UNCERTAIN', intent=intent)
    outcome, _ = _read_json(root, 'outcome.json')
    if (set(outcome) != {'schema_version', 'status', 'intent_sha256', 'finished_at', 'provider_calls',
                         'failure_code', 'http_status', 'report_sha256', 'frozen_after'}
            or outcome['schema_version'] != VERSION or outcome['intent_sha256'] != sha256_bytes(intent_raw)
            or clock(outcome['finished_at']) < clock(intent['reserved_at'])
            or type(outcome['provider_calls']) is not int or outcome['provider_calls'] not in (0, 1)):
        raise ProbeError('OUTCOME_REFUSED')
    if outcome['status'] == 'SUCCEEDED':
        if (raw is None or receipt is None or 'report.json' not in names or outcome['failure_code'] is not None
                or outcome['http_status'] is not None or outcome['provider_calls'] != 1
                or not isinstance(outcome['frozen_after'], dict)
                or clock(outcome['finished_at']) < clock(receipt['captured_at'])):
            raise ProbeError('SUCCESS_RECEIPT_REFUSED')
        _verify_frozen(config, outcome['frozen_after'])
        before, after = intent['frozen_before'], outcome['frozen_after']
        if before != after and (type(before.get('event_count')) is not int or type(after.get('event_count')) is not int
                               or after['event_count'] < before['event_count']):
            raise ProbeError('FROZEN_PREFIX_REFUSED')
        report, report_raw = _read_json(root, 'report.json')
        if report != project(raw, receipt, intent) or sha256_bytes(report_raw) != outcome['report_sha256']:
            raise ProbeError('REPORT_REPLAY_DIFFERS')
        return _result(report['status'], intent=intent, report=report, outcome=outcome, verified=True)
    if (outcome['status'] != 'FAILED' or outcome['report_sha256'] is not None or 'report.json' in names
            or not isinstance(outcome['failure_code'], str) or re.fullmatch(r'[A-Z][A-Z0-9_]{0,90}', outcome['failure_code']) is None
            or outcome['http_status'] is not None and (type(outcome['http_status']) is not int or not 100 <= outcome['http_status'] <= 599)):
        raise ProbeError('FAILURE_RECEIPT_REFUSED')
    return _result('FAILED', intent=intent, outcome=outcome, verified=True)


def verify(config, destination):
    """Provider-free integrity/replay verification; never reads credentials."""
    try:
        output = _paths(config, destination)
        _off(Path(config['runtime_root']))
        if not os.path.lexists(output):
            return _result('NOT_RUN')
        with _directory(output, create=False, lock=False) as (root, _):
            result = _verify(config, root)
        _off(Path(config['runtime_root']))
        return result
    except ProbeError:
        raise
    except ERRORS:
        raise ProbeError('VERIFICATION_BLOCKED') from None


def status(config, destination):
    try:
        return verify(config, destination)
    except ProbeError as exc:
        result = _result('UNAVAILABLE')
        result.update(failure_code=exc.code, http_status=exc.http_status)
        return result


def capture(config, destination, reviewed_report_id, *, getter=content_get, now=utc_now):
    """One explicitly reviewed sample. A retained intent is never resent."""
    try:
        output = _paths(config, destination)
        _off(Path(config['runtime_root']))
        bound = _review(config, reviewed_report_id)
        before = _frozen(config)
        with _directory(output, create=True, lock=True) as (root, staging):
            if 'intent.json' in os.listdir(root):
                intent = _read_json(root, 'intent.json')[0]
                if intent['reviewed_report_id'] != reviewed_report_id:
                    raise ProbeError('REVIEW_ID_CONFLICT')
                result = _verify(config, root)
                _off(Path(config['runtime_root']))
                return result
            if set(os.listdir(root)) - {'staging', '.probe.lock'}:
                raise ProbeError('PROBE_WITHOUT_INTENT')
            reserved = now()
            if not isinstance(reserved, datetime) or reserved.tzinfo is None or reserved.utcoffset() is None:
                raise ProbeError('CLOCK_REFUSED')
            intent = {'schema_version': VERSION, **bound,
                'query': {'symbols': ','.join(bound['watchlist']), 'start': stamp(reserved-timedelta(hours=24)),
                          'end': stamp(reserved), 'limit': 3, 'sort': 'desc', 'include_content': 'true'},
                'reserved_at': stamp(reserved), 'frozen_before': before, 'authority': AUTHORITY}
            _validate_intent(intent)
            _publish(root, staging, 'intent.json', intent)
            attempted, report, receipt, failure_code, http_status, after = 0, None, None, None, None, None
            try:
                credentials = parse_credentials(_read_regular(Path(config['credentials_file']), MAX_CREDENTIAL_BYTES), config['credential_format'])
                attempted = 1
                raw, receipt = getter(intent['query'], credentials)
                if not isinstance(raw, bytes):
                    raise ProbeError('RESPONSE_REFUSED')
                _sensitive(raw, credentials)
                _receipt(raw, receipt, intent)
                _publish(root, staging, 'response.bin', raw)
                _publish(root, staging, 'transport.json', receipt)
                report = project(raw, receipt, intent)
            except ProbeError as exc:
                failure_code, http_status = exc.code, exc.http_status
                report = None
            except ERRORS:
                failure_code, report = 'INPUT_OR_CAPTURE_BLOCKED', None
            finally:
                try:
                    _off(Path(config['runtime_root']))
                    after = _frozen(config)
                    reviewed_after = _review(config, reviewed_report_id)
                    _verify_frozen(config, before, current=after)
                    if reviewed_after != bound:
                        raise ProbeError('PRESERVATION_GATE_FAILED')
                except ERRORS:
                    failure_code, report, http_status = 'PRESERVATION_OR_OFF_GATE_FAILED', None, None
            finished = stamp(now())
            if clock(finished) < clock(intent['reserved_at']) or receipt and clock(finished) < clock(receipt['captured_at']):
                raise ProbeError('CLOCK_REFUSED')
            if report is not None:
                _publish(root, staging, 'report.json', report)
            outcome = {'schema_version': VERSION, 'status': 'SUCCEEDED' if report is not None else 'FAILED',
                'intent_sha256': sha256_bytes(canonical_json_bytes(intent)), 'finished_at': finished,
                'provider_calls': attempted, 'failure_code': failure_code, 'http_status': http_status,
                'report_sha256': sha256_bytes(canonical_json_bytes(report)) if report is not None else None, 'frozen_after': after}
            _publish(root, staging, 'outcome.json', outcome)
            if failure_code == 'PRESERVATION_OR_OFF_GATE_FAILED':
                # Preserve the observation and truthful terminal failure even
                # when the final gates prevent source-verified publication.
                return _result('FAILED', intent=intent, outcome=outcome, provider_calls=attempted)
            result = _verify(config, root)
            _off(Path(config['runtime_root']))
            result['provider_calls'] = attempted
            return result
    except ProbeError:
        raise
    except ERRORS:
        raise ProbeError('CAPTURE_BLOCKED') from None


def main(argv=None):
    from .shadow_station import load_config
    parser = argparse.ArgumentParser(description='Explicit one-GET article-content sample; never runs models or trades')
    parser.add_argument('command', choices=('capture', 'verify', 'status'))
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewed-report-id')
    args = parser.parse_args(argv)
    if args.command == 'capture' and not args.reviewed_report_id:
        parser.error('capture requires --reviewed-report-id identifying the reviewed accepted pair')
    try:
        config = load_config(args.config)
        result = capture(config, args.output, args.reviewed_report_id) if args.command == 'capture' else verify(config, args.output) if args.command == 'verify' else status(config, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] not in {'FAILED', 'UNCERTAIN', 'UNAVAILABLE'} else 2
    except ProbeError as exc:
        print(json.dumps({'schema_version': VERSION, 'status': 'BLOCKED', 'failure_code': exc.code,
                          'http_status': exc.http_status, 'provider_calls': None, 'authority': AUTHORITY}, sort_keys=True))
        return 2
    except ERRORS:
        print(json.dumps({'schema_version': VERSION, 'status': 'BLOCKED', 'failure_code': 'INPUT_REFUSED',
                          'provider_calls': None, 'authority': AUTHORITY}, sort_keys=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
