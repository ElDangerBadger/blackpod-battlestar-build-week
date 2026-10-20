"""Bounded local synthesis worker, with provider-free verification and recovery.

The immutable attempt ledger, not the mutable display state, owns retry and
budget admission. Interrupted roles are inspected, never resent by recovery.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
from zoneinfo import ZoneInfo

from .decision_journal_store import JournalStoreError, check_separate_root, _open_root
from .hashing import canonical_json_bytes, sha256_bytes
from .modeldock_config import ModelDockConfig
from .sentry_catalyst import CatalystStore, clock, stamp, control as catalyst_control
from .sentry_catalyst_service import paths as catalyst_paths
from .sentry_synthesis import VERSION, AUTHORITY, current_packet, verify_packet, compose_report
from .sentry_synthesis_transport import (generate_role, read_role, read_error_observation, read_local_contract_observation, write_json_once, _read,
    LEGACY_VERSION as LEGACY_TRANSPORT_VERSION)
from .shadow_station import read_state, atomic_state, service_lock
from .shadow_station_collection import _off, _pinned_view

CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v1'
SCHEDULE_CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v2'
ECONOMIC_CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v3'
ECONOMIC_ATTEMPT_VERSION = 'blackpod.sentry_synthesis_attempt.v2'
CODEX_CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v4'
CODEX_ATTEMPT_VERSION = 'blackpod.sentry_synthesis_attempt.v3'
CODEX_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v18'
ECONOMIC_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v15'
SCHEDULE_ATTEMPT_VERSION = 'blackpod.sentry_synthesis_scheduled_attempt.v1'
BACKGROUND_ATTEMPT_VERSIONS = frozenset({VERSION, SCHEDULE_ATTEMPT_VERSION, ECONOMIC_ATTEMPT_VERSION, CODEX_ATTEMPT_VERSION})
COMPARISON_ATTEMPT_VERSION = 'blackpod.sentry_synthesis_comparison.v1'
VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v2'
VALIDATION_PURPOSE = 'EXPLICIT_V2_VALIDATION'
VALIDATION_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v2'
DEADLINE_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v3'
DEADLINE_PURPOSE = 'EXPLICIT_DEADLINE_VALIDATION'
DEADLINE_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v3'
ERROR_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v4'
ERROR_PURPOSE = 'EXPLICIT_ERROR_CODE_DIAGNOSTIC'
ERROR_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v4'
RUNTIME_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v5'
RUNTIME_PURPOSE = 'EXPLICIT_RUNTIME_DIAGNOSTIC'
RUNTIME_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v5'
MODEL_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v6'
MODEL_PURPOSE = 'EXPLICIT_MODEL_SELECTION_VALIDATION'
MODEL_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v6'
OUTPUT_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v7'
OUTPUT_PURPOSE = 'EXPLICIT_OUTPUT_BUDGET_VALIDATION'
OUTPUT_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v7'
CONTRACT_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v8'
CONTRACT_PURPOSE = 'EXPLICIT_CONTRACT_VALIDATION'
CONTRACT_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v8'
TEXT_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v9'
TEXT_PURPOSE = 'EXPLICIT_TEXT_VALIDATION'
TEXT_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v9'
SYMBOL_VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v10'
SYMBOL_PURPOSE = 'EXPLICIT_SYMBOL_VALIDATION'
SYMBOL_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v10'
# Future background work uses the symbol-keyed contract. Historical attempts
# replay their reserved version; format acceptance never grants authority.
# The dated saved-packet v10 probe retained a connection failure, not model proof.
BACKGROUND_TRANSPORT_VERSION = SYMBOL_TRANSPORT_VERSION
MANUAL_SCOPE = 'MANUAL_RETAINED_EVIDENCE'
LA = ZoneInfo('America/Los_Angeles')
MAX_RUNS = 256
MAX_BYTES = 64 * 1024 * 1024
ERRORS = (ValueError, TypeError, KeyError, OSError, RuntimeError, JournalStoreError)


def utc_now():
    return datetime.now(timezone.utc)


@contextmanager
def awake_while_generating(modeldock):
    """Bound idle sleep while awake; this cannot wake a sleeping Mac."""
    process = None
    if Path('/usr/bin/caffeinate').exists():
        seconds = int(2 * (modeldock.timeout_seconds + modeldock.delivery_grace_seconds) + 30)
        process = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-s', '-t', str(seconds)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def paths(config):
    root = Path(config['station_root']) / 'synthesis'
    for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    check_separate_root(root, catalyst_paths(config)[0])
    return root, root / 'runs'


def configuration(value, *, allow_codex=False):
    if not isinstance(value, dict) or set(value) != {'base_url', 'timeout_seconds', 'profile', 'provider', 'max_response_bytes', 'delivery_grace_seconds'}:
        raise ValueError('invalid synthesis ModelDock configuration')
    if value.get('provider') == 'codex':
        if not allow_codex:
            raise ValueError('Codex requires an explicit versioned Sentry policy')
        from .sentry_modeldock_codex import SentryCodexConfig
        config = SentryCodexConfig(**value)
    else:
        config = ModelDockConfig(**value)
    if config.timeout_seconds > 900 or config.delivery_grace_seconds > 30:
        raise ValueError('synthesis deadline exceeds bound')
    return config


def analysis_settings(value):
    if (not isinstance(value,dict) or set(value) != {'prompt_version','include_article_content'}
            or value['prompt_version'] not in {'ECONOMIC_V3','ECONOMIC_V4'} or type(value['include_article_content']) is not bool):
        raise ValueError('invalid economic synthesis settings')
    return value


def codex_qualification(value, *, verify=False):
    """Bind a full-watchlist accepted proof; verification never invokes models."""
    fields = {'root', 'packet_sha256', 'oracle_receipt_sha256', 'challenge_receipt_sha256', 'watchlist'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('invalid Codex qualification binding')
    root = value['root']
    if (not isinstance(root, str) or not Path(root).is_absolute() or '..' in Path(root).parts
            or any(ord(c) < 32 for c in root)):
        raise ValueError('invalid Codex qualification root')
    for key in fields - {'root', 'watchlist'}:
        if not isinstance(value[key], str) or re.fullmatch('[0-9a-f]{64}', value[key]) is None:
            raise ValueError('invalid Codex qualification digest')
    watchlist = value['watchlist']
    if (not isinstance(watchlist, list) or len(watchlist) != 10
            or any(not isinstance(symbol, str) or re.fullmatch('[A-Z][A-Z0-9.-]{0,9}', symbol) is None for symbol in watchlist)
            or len(set(watchlist)) != len(watchlist)):
        raise ValueError('Codex qualification requires the complete ten-symbol watchlist')
    if verify:
        from .sentry_codex_validation import verify_qualification
        if verify_qualification(Path(root)) != value:
            raise ValueError('Codex qualification proof differs from its approved binding')
    return value


def codex_evidence_gate(config, packet, qualification):
    """Recheck OFF, frozen sources, exact evidence and accepted compatibility."""
    _off(Path(config['runtime_root']))
    _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
    verify_packet(packet, config)
    codex_qualification(qualification, verify=True)
    if packet['watchlist'] != qualification['watchlist']:
        raise ValueError('current Sentry watchlist differs from the qualified Codex watchlist')


def control(value):
    if not value:
        return {'schema_version': CONTROL_VERSION, 'enabled': False, 'modeldock': None}
    codex = value.get('schema_version') == CODEX_CONTROL_VERSION
    enhanced = value.get('schema_version') == ECONOMIC_CONTROL_VERSION or codex
    scheduled = value.get('schema_version') == SCHEDULE_CONTROL_VERSION or enhanced and 'schedule' in value
    expected = {'schema_version','enabled','modeldock'} | ({'schedule'} if scheduled else set()) | ({'analysis'} if enhanced else set()) | ({'qualification', 'monitoring'} if codex else set())
    if set(value) != expected or value['schema_version'] not in {CONTROL_VERSION,SCHEDULE_CONTROL_VERSION,ECONOMIC_CONTROL_VERSION,CODEX_CONTROL_VERSION} or type(value['enabled']) is not bool:
        raise ValueError('invalid synthesis control')
    dock = configuration(value['modeldock'], allow_codex=codex)
    if scheduled: schedule(value['schedule'])
    if enhanced: analysis_settings(value['analysis'])
    if codex:
        if dock.provider != 'codex' or value['analysis']['prompt_version'] != 'ECONOMIC_V4':
            raise ValueError('Codex Sentry requires the explicit economic V4 policy')
        if value['monitoring'] != ('FINITE_SCHEDULE' if scheduled else 'WEEKDAY_BOUNDED'):
            raise ValueError('Codex monitoring mode must be deliberate')
        codex_qualification(value['qualification'])
    return value


def schedule(value):
    """A finite experiment, never an implicit extension of weekday monitoring."""
    if (not isinstance(value, dict) or set(value) != {'id', 'slots', 'window_seconds'}
            or not isinstance(value['id'], str) or re.fullmatch('[a-z0-9-]{1,80}', value['id']) is None
            or type(value['window_seconds']) is not int or not 60 <= value['window_seconds'] <= 1800
            or not isinstance(value['slots'], list) or not 1 <= len(value['slots']) <= 4):
        raise ValueError('invalid finite synthesis schedule')
    times = [clock(t) for t in value['slots']]
    if (times != sorted(set(times)) or times[-1] - times[0] > timedelta(hours=48)
            or any(b - a < timedelta(hours=1) for a, b in zip(times, times[1:]))):
        raise ValueError('invalid synthesis slot spacing or duration')
    return value


def scheduled_due(now, entries, selected):
    """Reservation consumes a slot even after a crash or inference failure."""
    plan = schedule(selected['schedule'])
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware synthesis clock required')
    if not selected['enabled']:
        return False, 'PAUSED', None
    if any(clock(row[2]['reserved_at']) > now for row in entries):
        return False, 'CLOCK_BLOCKED', None
    claimed = {row[2]['schedule']['slot_at'] for row in entries
               if row[2]['schema_version'] in {SCHEDULE_ATTEMPT_VERSION, ECONOMIC_ATTEMPT_VERSION, CODEX_ATTEMPT_VERSION} and 'schedule' in row[2]
               and row[2]['schedule']['id'] == plan['id']}
    ordinary = [clock(row[2]['reserved_at']) for row in entries
                if row[2]['schema_version'] in BACKGROUND_ATTEMPT_VERSIONS]
    for slot in plan['slots']:
        start = clock(slot)
        if slot in claimed or now >= start + timedelta(seconds=plan['window_seconds']):
            continue
        if now < start:
            return False, 'WAITING_FOR_SCHEDULED_SLOT', slot
        if sum(t.astimezone(LA).date() == now.astimezone(LA).date() for t in ordinary) >= 4:
            return False, 'DAILY_BUDGET_EXHAUSTED', slot
        if ordinary and now - max(ordinary) < timedelta(hours=1):
            return False, 'WAITING_FOR_NEXT_SLOT', slot
        return True, 'DUE', slot
    return False, 'SCHEDULE_FINISHED', None


def immutable_read(root, name):
    descriptor = _open_root(root, create=False)
    try:
        value, raw = _read(descriptor, name)
        if raw != canonical_json_bytes(value):
            raise ValueError('noncanonical synthesis capsule')
        return value
    finally:
        os.close(descriptor)


def inventory(runs):
    if not os.path.lexists(runs):
        return []
    descriptor = _open_root(runs, create=False)
    try:
        names = os.listdir(descriptor)
        if len(names) > MAX_RUNS or any(re.fullmatch('[0-9a-f]{64}', n) is None for n in names):
            raise ValueError('invalid synthesis run inventory')
    finally:
        os.close(descriptor)
    # A symlink or external hardlink cannot evade the storage bound. Staging
    # publication links are validated by the descriptor-based capsule readers.
    total = 0
    for directory, subdirs, files in os.walk(runs, followlinks=False):
        for name in subdirs + files:
            info = os.lstat(Path(directory) / name)
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError('unsafe synthesis storage')
            total += info.st_size
            if total > MAX_BYTES:
                raise ValueError('synthesis archive review required')
    return [runs / name for name in names]


def validation_settings(*, deadline=False, error_diagnostic=False, runtime_diagnostic=False, model_selection=False, output_budget=False, contract_validation=False, text_validation=False, symbol_validation=False):
    if sum((deadline, error_diagnostic, runtime_diagnostic, model_selection, output_budget, contract_validation, text_validation, symbol_validation)) > 1:
        raise ValueError('validation purposes cannot be combined')
    if symbol_validation:
        return SYMBOL_PURPOSE, SYMBOL_TRANSPORT_VERSION, SYMBOL_VALIDATION_VERSION, True
    if text_validation:
        return TEXT_PURPOSE, TEXT_TRANSPORT_VERSION, TEXT_VALIDATION_VERSION, True
    if contract_validation:
        return CONTRACT_PURPOSE, CONTRACT_TRANSPORT_VERSION, CONTRACT_VALIDATION_VERSION, True
    if output_budget:
        return OUTPUT_PURPOSE, OUTPUT_TRANSPORT_VERSION, OUTPUT_VALIDATION_VERSION, True
    if model_selection:
        return MODEL_PURPOSE, MODEL_TRANSPORT_VERSION, MODEL_VALIDATION_VERSION, True
    if runtime_diagnostic:
        return RUNTIME_PURPOSE, RUNTIME_TRANSPORT_VERSION, RUNTIME_VALIDATION_VERSION, True
    if error_diagnostic:
        return ERROR_PURPOSE, ERROR_TRANSPORT_VERSION, ERROR_VALIDATION_VERSION, True
    if deadline:
        return DEADLINE_PURPOSE, DEADLINE_TRANSPORT_VERSION, DEADLINE_VALIDATION_VERSION, True
    return VALIDATION_PURPOSE, VALIDATION_TRANSPORT_VERSION, VALIDATION_VERSION, False


def validation_directory(parent_report_id, *, deadline=False, error_diagnostic=False, runtime_diagnostic=False, model_selection=False, output_budget=False, contract_validation=False, text_validation=False, symbol_validation=False):
    if not isinstance(parent_report_id, str) or re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', parent_report_id) is None:
        raise ValueError('invalid validation source report identity')
    purpose, transport_version, _, manual = validation_settings(deadline=deadline, error_diagnostic=error_diagnostic,
        runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
    identity = {'purpose': purpose,
        'parent_report_id': parent_report_id,
        'transport_schema_version': transport_version}
    if manual:
        identity['scope'] = MANUAL_SCOPE
    return sha256_bytes(canonical_json_bytes(identity))


def validation_metadata(value):
    if not isinstance(value, dict):
        raise ValueError('invalid explicit validation linkage')
    deadline = value.get('purpose') == DEADLINE_PURPOSE
    error_diagnostic = value.get('purpose') == ERROR_PURPOSE
    runtime_diagnostic = value.get('purpose') == RUNTIME_PURPOSE
    model_selection = value.get('purpose') == MODEL_PURPOSE
    output_budget = value.get('purpose') == OUTPUT_PURPOSE
    contract_validation = value.get('purpose') == CONTRACT_PURPOSE
    text_validation = value.get('purpose') == TEXT_PURPOSE
    symbol_validation = value.get('purpose') == SYMBOL_PURPOSE
    purpose, transport_version, _, manual = validation_settings(deadline=deadline, error_diagnostic=error_diagnostic,
        runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
    fields = {'purpose', 'parent_report_id', 'parent_report_sha256', 'transport_schema_version'} | ({'scope'} if manual else set())
    if (set(value) != fields
            or value['purpose'] != purpose or value['transport_schema_version'] != transport_version
            or manual and value['scope'] != MANUAL_SCOPE
            or not isinstance(value['parent_report_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', value['parent_report_sha256']) is None):
        raise ValueError('invalid explicit validation linkage')
    validation_directory(value['parent_report_id'], deadline=deadline, error_diagnostic=error_diagnostic,
        runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
    return value


def load_attempt(directory):
    if set(os.listdir(directory)) - {'packet.json', 'run-intent.json', 'completion-clock.json', 'report.json', 'oracle', 'challenge', 'staging'}:
        raise ValueError('unexpected synthesis capsule file')
    packet = immutable_read(directory, 'packet.json')
    intent = immutable_read(directory, 'run-intent.json')
    fields = {'schema_version', 'context_id', 'packet_sha256', 'evidence_signature', 'reserved_at', 'modeldock'}
    if intent.get('schema_version') in {VALIDATION_VERSION, DEADLINE_VALIDATION_VERSION, ERROR_VALIDATION_VERSION, RUNTIME_VALIDATION_VERSION, MODEL_VALIDATION_VERSION, OUTPUT_VALIDATION_VERSION, CONTRACT_VALIDATION_VERSION, TEXT_VALIDATION_VERSION, SYMBOL_VALIDATION_VERSION}:
        expected_fields = fields | {'validation'}
        metadata = validation_metadata(intent.get('validation'))
        deadline = intent['schema_version'] == DEADLINE_VALIDATION_VERSION
        error_diagnostic = intent['schema_version'] == ERROR_VALIDATION_VERSION
        runtime_diagnostic = intent['schema_version'] == RUNTIME_VALIDATION_VERSION
        model_selection = intent['schema_version'] == MODEL_VALIDATION_VERSION
        output_budget = intent['schema_version'] == OUTPUT_VALIDATION_VERSION
        contract_validation = intent['schema_version'] == CONTRACT_VALIDATION_VERSION
        text_validation = intent['schema_version'] == TEXT_VALIDATION_VERSION
        symbol_validation = intent['schema_version'] == SYMBOL_VALIDATION_VERSION
        if metadata['purpose'] != validation_settings(deadline=deadline, error_diagnostic=error_diagnostic,
                runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)[0]:
            raise ValueError('validation schema and purpose differ')
        expected_directory = validation_directory(metadata['parent_report_id'], deadline=deadline, error_diagnostic=error_diagnostic,
            runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
    elif intent.get('schema_version') == COMPARISON_ATTEMPT_VERSION:
        expected_fields = fields | {'comparison'}
        comparison = intent.get('comparison')
        if (not isinstance(comparison,dict) or set(comparison) != {'experiment_id','fixture_id','model_id','transport_version','attempt'}
                or comparison['experiment_id'] != 'sentry-economic-20261018'
                or comparison['transport_version'] not in {'blackpod.sentry_synthesis_transport.v11','blackpod.sentry_synthesis_transport.v12','blackpod.sentry_synthesis_transport.v13','blackpod.sentry_synthesis_transport.v14','blackpod.sentry_synthesis_transport.v15','blackpod.sentry_synthesis_transport.v16','blackpod.sentry_synthesis_transport.v17'}
                or type(comparison['attempt']) is not int or not 0 <= comparison['attempt'] <= 1
                or any(not isinstance(comparison[k],str) or not comparison[k] for k in ('fixture_id','model_id'))):
            raise ValueError('invalid explicit comparison reservation')
        expected_directory = sha256_bytes(canonical_json_bytes({'packet_sha256':intent['packet_sha256'],'comparison':comparison}))
    elif intent.get('schema_version') in {ECONOMIC_ATTEMPT_VERSION, CODEX_ATTEMPT_VERSION}:
        codex = intent['schema_version'] == CODEX_ATTEMPT_VERSION
        expected_fields = fields | {'analysis'} | ({'schedule'} if 'schedule' in intent else set()) | ({'transport_version', 'qualification'} if codex else set())
        analysis_settings(intent['analysis'])
        if codex:
            codex_qualification(intent['qualification'])
            if (intent['transport_version'] != CODEX_TRANSPORT_VERSION
                    or intent['analysis']['prompt_version'] != 'ECONOMIC_V4'
                    or intent['modeldock'].get('provider') != 'codex'
                    or packet['watchlist'] != intent['qualification']['watchlist']):
                raise ValueError('Codex attempt differs from its versioned qualified policy')
        expected_directory = packet['evidence_signature']
        if 'schedule' in intent:
            binding = intent['schedule']
            if not isinstance(binding,dict) or set(binding) != {'id','slot_at','window_seconds'}:
                raise ValueError('invalid economic scheduled attempt')
            schedule({'id':binding['id'],'slots':[binding['slot_at']],'window_seconds':binding['window_seconds']})
            if not clock(binding['slot_at']) <= clock(intent['reserved_at']) < clock(binding['slot_at'])+timedelta(seconds=binding['window_seconds']):
                raise ValueError('economic reservation outside its slot')
        if intent['analysis']['include_article_content'] != (packet['schema_version'] == 'blackpod.sentry_synthesis.v2'):
            raise ValueError('economic content mode differs from retained packet')
    elif intent.get('schema_version') == SCHEDULE_ATTEMPT_VERSION:
        expected_fields, expected_directory = fields | {'schedule'}, packet['evidence_signature']
        binding = intent.get('schedule')
        if not isinstance(binding, dict) or set(binding) != {'id', 'slot_at', 'window_seconds'}:
            raise ValueError('invalid scheduled attempt binding')
        schedule({'id': binding['id'], 'slots': [binding['slot_at']], 'window_seconds': binding['window_seconds']})
        reserved = clock(intent['reserved_at'])
        if not clock(binding['slot_at']) <= reserved < clock(binding['slot_at']) + timedelta(seconds=binding['window_seconds']):
            raise ValueError('scheduled reservation outside its slot')
    elif intent.get('schema_version') == VERSION:
        expected_fields, expected_directory = fields, packet['evidence_signature']
    else:
        raise ValueError('unsupported synthesis attempt schema')
    if (set(intent) != expected_fields or intent['context_id'] != packet['context_id']
            or intent['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet))
            or intent['evidence_signature'] != packet['evidence_signature']
            or directory.name != expected_directory or clock(intent['reserved_at']) < clock(packet['as_of'])):
        raise ValueError('synthesis attempt binding differs')
    modeldock = configuration(intent['modeldock'], allow_codex=intent['schema_version'] == CODEX_ATTEMPT_VERSION)
    if intent['schema_version'] == VALIDATION_VERSION and (modeldock.timeout_seconds > 120 or modeldock.delivery_grace_seconds > 10):
        raise ValueError('legacy v2 validation deadline exceeds its bound')
    if intent['schema_version'] in {DEADLINE_VALIDATION_VERSION, ERROR_VALIDATION_VERSION, RUNTIME_VALIDATION_VERSION, MODEL_VALIDATION_VERSION, OUTPUT_VALIDATION_VERSION, CONTRACT_VALIDATION_VERSION, TEXT_VALIDATION_VERSION, SYMBOL_VALIDATION_VERSION} and (modeldock.timeout_seconds != 900 or modeldock.delivery_grace_seconds != 30):
        raise ValueError('explicit deadline validation requires exactly 900 seconds plus 30 seconds grace')
    return packet, intent, modeldock


def abandoned_validation(directory, packet):
    """Identify a packet-only child without inventing a reservation or send."""
    for candidate in inventory(directory.parent):
        if candidate == directory or not (candidate / 'report.json').exists():
            continue
        report = immutable_read(candidate, 'report.json')
        identity = report.get('report_id')
        if (isinstance(identity, str) and re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', identity)
                and directory.name in {validation_directory(identity), validation_directory(identity, deadline=True),
                                       validation_directory(identity, error_diagnostic=True),
                                       validation_directory(identity, runtime_diagnostic=True),
                                       validation_directory(identity, model_selection=True),
                                       validation_directory(identity, output_budget=True),
                                       validation_directory(identity, contract_validation=True),
                                       validation_directory(identity, text_validation=True),
                                       validation_directory(identity, symbol_validation=True)}
                and report.get('context') == packet):
            return True
    return False


def ledger(runs, *, _context=None):
    entries = []
    for directory in inventory(runs):
        if not (directory / 'run-intent.json').exists():
            # Packet publication precedes the reservation. No role may exist
            # yet. Retain this abandoned packet without inventing a send time
            # or blocking unrelated future evidence forever.
            if set(os.listdir(directory)) - {'packet.json', 'staging'}:
                raise ValueError('unreserved synthesis capsule contains work')
            if (directory / 'packet.json').exists():
                packet = immutable_read(directory, 'packet.json')
                if directory.name != packet['evidence_signature'] and not abandoned_validation(directory, packet):
                    raise ValueError('abandoned synthesis identity differs')
            if (directory / 'staging').exists():
                for file in (directory / 'staging').iterdir():
                    if re.fullmatch(r'\.publish-[0-9a-f]{32}\.tmp', file.name) is None:
                        raise ValueError('unexpected abandoned staging file')
                    info = file.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        packet_path = directory / 'packet.json'
                        if not packet_path.exists() or not os.path.samestat(info, packet_path.stat()) or info.st_nlink != 2:
                            raise ValueError('unsafe abandoned staging link')
            continue
        packet, intent, modeldock = (_context.attempt(directory) if _context is not None else load_attempt(directory))
        entries.append((directory, packet, intent, modeldock))
    return sorted(entries, key=lambda row: (clock(row[2]['reserved_at']), row[0].name))


class _ReplayContext:
    """One operation's verified snapshot, never a cross-request trust cache.

    The original filesystem and source checks run at first read of every
    distinct item. Repeated ancestry references reuse those verified bytes.
    A later operation constructs a fresh context and detects later tampering.
    No dispatch, role delivery or OFF check relies on this memoization.
    """
    def __init__(self, config, *, source=None, entries=None):
        self.config = deepcopy(config)
        self._source = source
        self._entries = entries
        self.attempts = {}
        self.documents = {}
        self.packets = set()
        self.roles = {}
        self.reports = {}
        self.active = set()
        if entries is not None:
            self.attempts.update((directory, (packet, intent, dock)) for directory, packet, intent, dock in entries)

    def check(self, config):
        if config != self.config:
            raise ValueError('replay context belongs to another operation configuration')

    @property
    def source(self):
        if self._source is None:
            self._source = CatalystStore(catalyst_paths(self.config)[1]).verified_records()
        return self._source

    def entries(self):
        if self._entries is None:
            self._entries = ledger(paths(self.config)[1], _context=self)
        return self._entries

    def attempt(self, directory):
        if directory not in self.attempts:
            self.attempts[directory] = load_attempt(directory)
        return self.attempts[directory]

    def document(self, directory, name):
        identity = directory, name
        if identity not in self.documents:
            self.documents[identity] = immutable_read(directory, name)
        return deepcopy(self.documents[identity])

    def packet(self, packet):
        identity = sha256_bytes(canonical_json_bytes(packet))
        if identity not in self.packets:
            verify_packet(packet, self.config, verified_source=self.source)
            self.packets.add(identity)

    def retained(self, directory, packet, dock):
        if directory not in self.roles:
            self.roles[directory] = retained_roles(directory, packet, dock)
        return deepcopy(self.roles[directory])


def due(now, entries, enabled, *, manual_retained=False):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware synthesis clock required')
    local = now.astimezone(LA)
    if not enabled:
        return False, 'PAUSED'
    times = [clock(row[2]['reserved_at']) for row in entries]
    if times and max(times) > now:
        return False, 'CLOCK_BLOCKED'
    if manual_retained:
        return True, 'DUE'
    if local.weekday() >= 5 or not 5 <= local.hour < 17:
        return False, 'OUTSIDE_MONITORING_HOURS'
    # The ordinary monitoring budget has its own ledger projection. Existing
    # explicit diagnostic records are retained unchanged and do not consume it.
    times = [clock(row[2]['reserved_at']) for row in entries if row[2]['schema_version'] in BACKGROUND_ATTEMPT_VERSIONS]
    if sum(t.astimezone(LA).date() == local.date() for t in times) >= 4:
        return False, 'DAILY_BUDGET_EXHAUSTED'
    if times and now - max(times) < timedelta(hours=1):
        return False, 'WAITING_FOR_NEXT_SLOT'
    return True, 'DUE'


def retained_roles(directory, packet, modeldock):
    intent = immutable_read(directory, 'run-intent.json')
    if intent['schema_version'] == CODEX_ATTEMPT_VERSION:
        version = intent['transport_version']
    elif intent['schema_version'] == ECONOMIC_ATTEMPT_VERSION:
        version = 'blackpod.sentry_synthesis_transport.v16' if intent['analysis']['prompt_version']=='ECONOMIC_V4' else ECONOMIC_TRANSPORT_VERSION
    elif 'comparison' in intent:
        version = intent['comparison']['transport_version']
    elif 'validation' in intent:
        version = intent['validation']['transport_schema_version']
    elif (directory / 'oracle/intent.json').exists():
        version = immutable_read(directory / 'oracle', 'intent.json')['schema_version']
    elif (directory / 'report.json').exists():
        original = immutable_read(directory, 'report.json')['provenance']['oracle']['request_id']
        candidates = []
        for candidate in (LEGACY_TRANSPORT_VERSION, VALIDATION_TRANSPORT_VERSION, DEADLINE_TRANSPORT_VERSION, ERROR_TRANSPORT_VERSION, RUNTIME_TRANSPORT_VERSION, MODEL_TRANSPORT_VERSION, OUTPUT_TRANSPORT_VERSION, CONTRACT_TRANSPORT_VERSION, TEXT_TRANSPORT_VERSION, SYMBOL_TRANSPORT_VERSION):
            try:
                result = read_role('oracle', packet, directory / 'oracle', modeldock, version=candidate)
                if result['request_id'] == original:
                    candidates.append(candidate)
            except ERRORS:
                continue
        if len(candidates) != 1:
            raise ValueError('unreserved historical role version cannot be established')
        version = candidates[0]
    else:
        version = BACKGROUND_TRANSPORT_VERSION
    oracle = read_role('oracle', packet, directory / 'oracle', modeldock, version=version)
    if oracle['status'] != 'ACCEPTED' and os.path.lexists(directory / 'challenge'):
        raise ValueError('challenge work exists without an accepted original Oracle draft')
    challenge = (read_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'], version=version)
                 if oracle['status'] == 'ACCEPTED' else {'status': 'UNCERTAIN', 'response': None, 'failure_code': 'ORACLE_NOT_ACCEPTED'})
    return oracle, challenge


def read_report(directory, config, *, _source=None, _context=None):
    context = _context or _ReplayContext(config, source=_source)
    context.check(config)
    if directory in context.reports:
        return deepcopy(context.reports[directory])
    if directory in context.active:
        raise ValueError('cyclic synthesis validation ancestry')
    context.active.add(directory)
    try:
        packet, intent, modeldock = context.attempt(directory)
        context.packet(packet)
        metadata = verify_validation_link(directory, packet, intent, config, _context=context)
        oracle, challenge = context.retained(directory, packet, modeldock)
        completed = context.document(directory, 'completion-clock.json')
        if set(completed) != {'completed_at'} or clock(completed['completed_at']) < minimum_completion(directory, intent):
            raise ValueError('invalid synthesis completion clock')
        report = context.document(directory, 'report.json')
        if report != compose_report(packet, oracle, challenge, completed['completed_at'], **({'validation': metadata} if metadata else {})):
            raise ValueError('synthesis report does not replay')
        context.reports[directory] = deepcopy(report)
        return report
    finally:
        context.active.remove(directory)


def minimum_completion(directory, intent):
    clocks = [clock(intent['reserved_at'])]
    for role in ('oracle', 'challenge'):
        if (directory / role / 'receipt.json').exists():
            clocks.append(clock(immutable_read(directory / role, 'receipt.json')['finished_at']))
    return max(clocks)


def recover_attempt(directory, config, now=None):
    """No client construction or inference, even if a role was never reserved."""
    _off(Path(config['runtime_root']))
    packet, intent, modeldock = load_attempt(directory)
    if intent['schema_version'] == CODEX_ATTEMPT_VERSION:
        codex_evidence_gate(config, packet, intent['qualification'])
    verify_packet(packet, config)
    metadata = verify_validation_link(directory, packet, intent, config)
    if (directory / 'report.json').exists():
        return read_report(directory, config)
    oracle, challenge = retained_roles(directory, packet, modeldock)
    if not (directory / 'completion-clock.json').exists():
        completed_at = now or utc_now()
        if completed_at < minimum_completion(directory, intent):
            raise ValueError('completion clock precedes retained model delivery')
        write_json_once(directory, 'completion-clock.json', {'completed_at': stamp(completed_at)})
    completed = immutable_read(directory, 'completion-clock.json')['completed_at']
    report = compose_report(packet, oracle, challenge, completed, **({'validation': metadata} if metadata else {}))
    _off(Path(config['runtime_root']))
    verify_packet(packet, config)
    if intent['schema_version'] == CODEX_ATTEMPT_VERSION:
        codex_evidence_gate(config, packet, intent['qualification'])
    write_json_once(directory, 'report.json', report)
    return read_report(directory, config)


def validation_parent(config, parent_report_id, *, deadline=False, error_diagnostic=False, runtime_diagnostic=False, model_selection=False, output_budget=False, contract_validation=False, text_validation=False, symbol_validation=False, _source=None, _context=None):
    """Replay a terminal legacy failure; an accepted or uncertain role is ineligible."""
    validation_directory(parent_report_id)
    _, runs = paths(config)
    context = _context or _ReplayContext(config, source=_source)
    context.check(config)
    found = None
    for directory, packet, intent, modeldock in context.entries():
        if not (directory / 'report.json').exists():
            continue
        retained = context.document(directory, 'report.json')
        if retained.get('report_id') != parent_report_id:
            continue
        if found is not None:
            raise ValueError('validation source identity is duplicated')
        if symbol_validation:
            if intent['schema_version'] != VERSION or 'validation' in intent:
                raise ValueError('symbol validation source must be a terminal v9 background attempt')
        elif text_validation:
            if intent['schema_version'] != CONTRACT_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != CONTRACT_PURPOSE:
                raise ValueError('text validation source must be the terminal v8 contract validation')
        elif contract_validation:
            if intent['schema_version'] != OUTPUT_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != OUTPUT_PURPOSE:
                raise ValueError('contract validation source must be the terminal v7 output budget validation')
        elif output_budget:
            if intent['schema_version'] != MODEL_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != MODEL_PURPOSE:
                raise ValueError('output budget validation source must be the terminal v6 model validation')
        elif model_selection:
            if intent['schema_version'] != RUNTIME_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != RUNTIME_PURPOSE:
                raise ValueError('model validation source must be the terminal v5 runtime diagnostic')
        elif runtime_diagnostic:
            if intent['schema_version'] != ERROR_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != ERROR_PURPOSE:
                raise ValueError('runtime diagnostic source must be the terminal v4 error diagnostic')
        elif error_diagnostic:
            if intent['schema_version'] != DEADLINE_VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != DEADLINE_PURPOSE:
                raise ValueError('error diagnostic source must be the terminal v3 deadline validation')
        elif deadline:
            if intent['schema_version'] != VALIDATION_VERSION or intent.get('validation', {}).get('purpose') != VALIDATION_PURPOSE:
                raise ValueError('deadline validation source must be the terminal v2 validation')
        elif intent['schema_version'] != VERSION or 'validation' in intent:
            raise ValueError('validation source must be one original failure')
        report = read_report(directory, config, _context=context)
        oracle = report['provenance']['oracle']
        if report['status'] not in {'FAILED', 'REJECTED'} or oracle['status'] not in {'FAILED', 'REJECTED'}:
            raise ValueError('validation source is not a terminal failed Oracle delivery')
        role_intent = immutable_read(directory / 'oracle', 'intent.json')
        receipt = immutable_read(directory / 'oracle', 'receipt.json')
        if (report['status'] not in {'FAILED', 'REJECTED'} or oracle['status'] not in {'FAILED', 'REJECTED'}
                or role_intent['schema_version'] != (TEXT_TRANSPORT_VERSION if symbol_validation else CONTRACT_TRANSPORT_VERSION if text_validation else OUTPUT_TRANSPORT_VERSION if contract_validation else MODEL_TRANSPORT_VERSION if output_budget else RUNTIME_TRANSPORT_VERSION if model_selection else ERROR_TRANSPORT_VERSION if runtime_diagnostic else DEADLINE_TRANSPORT_VERSION if error_diagnostic else VALIDATION_TRANSPORT_VERSION if deadline else LEGACY_TRANSPORT_VERSION)
                or role_intent['wire_request']['response_format']['schema']['properties']['schema_version']['const']
                    != ('blackpod.sentry_oracle_draft.v2' if deadline or error_diagnostic or runtime_diagnostic or model_selection or output_budget or contract_validation or text_validation or symbol_validation else 'blackpod.sentry_oracle_draft.v1')
                or receipt['status'] != oracle['status'] or receipt['response'] is not None
                or receipt['provenance'] is not None or not receipt['failure_code']
                or deadline and receipt['failure_code'] != 'MODELDOCK_HTTP_504'
                or (error_diagnostic or runtime_diagnostic or model_selection or output_budget) and receipt['failure_code'] != 'MODELDOCK_HTTP_500'
                or (contract_validation or text_validation or symbol_validation) and (report['status'] != 'REJECTED' or oracle['status'] != 'REJECTED'
                    or receipt['failure_code'] != 'MODELDOCK_NARRATIVE_SCHEMA_INVALID'
                    or role_intent['wire_request']['max_tokens'] != 4096)):
            raise ValueError('validation source is not the required terminal failed delivery')
        if runtime_diagnostic or model_selection or output_budget:
            observation = read_error_observation('oracle', packet, directory / 'oracle', modeldock)
            if (observation is None or observation['status'] != 'AVAILABLE'
                    or observation['http_status'] != 500 or observation['code'] != 'STRUCTURED_OUTPUT_INVALID'):
                raise ValueError('runtime diagnostic requires a verified STRUCTURED_OUTPUT_INVALID observation')
            if model_selection or output_budget:
                diagnostic = observation.get('validation_diagnostic')
                if (observation['schema_version'] != 'blackpod.sentry_http_error_observation.v2'
                        or not isinstance(diagnostic, dict)
                        or diagnostic.get('schema') != 'modeldock.structured-validation-diagnostic.v1'
                        or diagnostic.get('stage') != 'RESULT_VALIDATION'
                        or diagnostic.get('reason') != 'JSON_SYNTAX'
                        or type(diagnostic.get('generated_token_count')) is not int
                        or diagnostic['generated_token_count'] != 2500
                        or diagnostic.get('generated_token_count_source') != 'native'
                        or diagnostic.get('stop_reason') != 'length'
                        or diagnostic.get('stop_reason_source') != 'native'
                        or role_intent['wire_request']['max_tokens'] != 2500):
                    raise ValueError('validation requires verified native JSON_SYNTAX at the original 2500-token limit')
        if symbol_validation:
            observation = read_local_contract_observation('oracle', packet, directory / 'oracle', modeldock)
            if (observation is None
                    or observation['schema_version'] != 'blackpod.sentry_local_contract_observation.v2'
                    or observation['stage'] != 'HOST_RESPONSE_CONTRACT'
                    or observation['reason'] != 'DUPLICATE_SYMBOL'
                    or modeldock.timeout_seconds != 900 or modeldock.delivery_grace_seconds != 30):
                raise ValueError('symbol validation requires a verified original v9 DUPLICATE_SYMBOL rejection')
        if text_validation:
            observation = read_local_contract_observation('oracle', packet, directory / 'oracle', modeldock)
            if (observation is None
                    or observation['schema_version'] != 'blackpod.sentry_local_contract_observation.v1'
                    or observation['stage'] != 'HOST_RESPONSE_CONTRACT'
                    or observation['reason'] != 'TEXT_FORMAT'):
                raise ValueError('text validation requires a verified original TEXT_FORMAT observation')
        found = directory, packet, report
    if found is None:
        raise ValueError('validation source report not found')
    return found


def verify_validation_link(directory, packet, intent, config, *, _source=None, _context=None):
    if intent['schema_version'] not in {VALIDATION_VERSION, DEADLINE_VALIDATION_VERSION, ERROR_VALIDATION_VERSION, RUNTIME_VALIDATION_VERSION, MODEL_VALIDATION_VERSION, OUTPUT_VALIDATION_VERSION, CONTRACT_VALIDATION_VERSION, TEXT_VALIDATION_VERSION, SYMBOL_VALIDATION_VERSION}:
        return None
    metadata = validation_metadata(intent['validation'])
    deadline = intent['schema_version'] == DEADLINE_VALIDATION_VERSION
    error_diagnostic = intent['schema_version'] == ERROR_VALIDATION_VERSION
    runtime_diagnostic = intent['schema_version'] == RUNTIME_VALIDATION_VERSION
    model_selection = intent['schema_version'] == MODEL_VALIDATION_VERSION
    output_budget = intent['schema_version'] == OUTPUT_VALIDATION_VERSION
    contract_validation = intent['schema_version'] == CONTRACT_VALIDATION_VERSION
    text_validation = intent['schema_version'] == TEXT_VALIDATION_VERSION
    symbol_validation = intent['schema_version'] == SYMBOL_VALIDATION_VERSION
    parent, original, report = validation_parent(config, metadata['parent_report_id'], deadline=deadline, error_diagnostic=error_diagnostic,
        runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation, _source=_source, _context=_context)
    if (sha256_bytes(canonical_json_bytes(report)) != metadata['parent_report_sha256']
            or original != packet or immutable_read(parent, 'packet.json') != immutable_read(directory, 'packet.json')):
        raise ValueError('validation differs from exact original evidence or parent')
    _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
    for role in ('oracle', 'challenge'):
        role_intent = directory / role / 'intent.json'
        if role_intent.exists() and immutable_read(directory / role, 'intent.json')['schema_version'] != metadata['transport_schema_version']:
            raise ValueError('validation role did not reserve its required transport version')
    return metadata


def capsule_hashes(directory):
    """Detect any alteration of the original capsule during the explicit attempt."""
    result = {}
    for item in directory.rglob('*'):
        relative = str(item.relative_to(directory))
        info = item.lstat()
        if stat.S_ISDIR(info.st_mode):
            result[relative] = None
        elif stat.S_ISREG(info.st_mode):
            result[relative] = sha256_bytes(item.read_bytes())
        else:
            raise ValueError('unsafe original validation source')
    return result


def validation_chain_hashes(directory, config):
    result = {}
    while True:
        if directory in result or len(result) >= 9:
            raise ValueError('invalid validation ancestry')
        result[directory] = capsule_hashes(directory)
        _, intent, _ = load_attempt(directory)
        if intent['schema_version'] not in {VALIDATION_VERSION, DEADLINE_VALIDATION_VERSION, ERROR_VALIDATION_VERSION, RUNTIME_VALIDATION_VERSION, MODEL_VALIDATION_VERSION, OUTPUT_VALIDATION_VERSION, CONTRACT_VALIDATION_VERSION, TEXT_VALIDATION_VERSION, SYMBOL_VALIDATION_VERSION}:
            return result
        directory, _, _ = validation_parent(config, intent['validation']['parent_report_id'],
            deadline=intent['schema_version'] == DEADLINE_VALIDATION_VERSION,
            error_diagnostic=intent['schema_version'] == ERROR_VALIDATION_VERSION,
            runtime_diagnostic=intent['schema_version'] == RUNTIME_VALIDATION_VERSION,
            model_selection=intent['schema_version'] == MODEL_VALIDATION_VERSION,
            output_budget=intent['schema_version'] == OUTPUT_VALIDATION_VERSION,
            contract_validation=intent['schema_version'] == CONTRACT_VALIDATION_VERSION,
            text_validation=intent['schema_version'] == TEXT_VALIDATION_VERSION,
            symbol_validation=intent['schema_version'] == SYMBOL_VALIDATION_VERSION)


def _validate(config, source_report_id, *, now=None, client_factory=None, deadline=False, error_diagnostic=False, runtime_diagnostic=False, model_selection=False, output_budget=False, contract_validation=False, text_validation=False, symbol_validation=False):
    """Explicit single child validation of the exact retained legacy evidence.

    Explicit manual scope has a user-authorized schedule allowance separate
    from ordinary source admission. A reserved child is never resent; pause,
    clock, serialization, storage, OFF and source gates still apply.
    """
    root, runs = paths(config)
    purpose, transport_version, intent_version, manual = validation_settings(deadline=deadline, error_diagnostic=error_diagnostic,
        runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
    with service_lock(root):
        _off(Path(config['runtime_root']))
        verify(config)
        parent, packet, parent_report = validation_parent(config, source_report_id, deadline=deadline, error_diagnostic=error_diagnostic,
            runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
        original_hashes = validation_chain_hashes(parent, config)
        metadata = {'purpose': purpose, 'parent_report_id': source_report_id,
            'parent_report_sha256': sha256_bytes(canonical_json_bytes(parent_report)),
            'transport_schema_version': transport_version}
        if manual:
            metadata['scope'] = MANUAL_SCOPE
        directory = runs / validation_directory(source_report_id, deadline=deadline, error_diagnostic=error_diagnostic,
            runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)

        def gates():
            _off(Path(config['runtime_root']))
            _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
            verify_packet(packet, config)
            current = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
            if current['symbols'] != packet['watchlist'] or validation_chain_hashes(parent, config) != original_hashes:
                raise ValueError('validation source, watchlist or original capsule changed')
            checked_parent, checked_packet, checked_report = validation_parent(config, source_report_id, deadline=deadline, error_diagnostic=error_diagnostic,
                runtime_diagnostic=runtime_diagnostic, model_selection=model_selection, output_budget=output_budget, contract_validation=contract_validation, text_validation=text_validation, symbol_validation=symbol_validation)
            if checked_parent != parent or checked_packet != packet or checked_report != parent_report:
                raise ValueError('validation parent changed')

        gates()
        if directory.exists():
            if not (directory / 'run-intent.json').exists():
                gates()
                return {'status': 'UNCERTAIN', 'report_id': None, 'validation': metadata, 'authority': dict(AUTHORITY)}
            result = recover_attempt(directory, config)
            gates()
            return result
        selected = control(read_state(root / 'control.json'))
        entries = ledger(runs)
        now = now or utc_now()
        admitted, reason = due(now, entries, selected['enabled'], manual_retained=manual)
        if not admitted:
            return {'status': reason, 'report_id': None, 'validation': metadata, 'authority': dict(AUTHORITY)}
        if len(inventory(runs)) >= MAX_RUNS or sum(p.stat().st_size for p in runs.rglob('*') if p.is_file()) > MAX_BYTES - 8 * 1024 * 1024:
            return {'status': 'ARCHIVE_REVIEW_REQUIRED', 'report_id': None, 'validation': metadata, 'authority': dict(AUTHORITY)}
        modeldock = configuration(selected['modeldock'])
        if not manual and (modeldock.timeout_seconds > 120 or modeldock.delivery_grace_seconds > 10):
            raise ValueError('legacy v2 validation requires its original bounded deadline')
        if manual and (modeldock.timeout_seconds != 900 or modeldock.delivery_grace_seconds != 30):
            raise ValueError('explicit deadline validation requires exactly 900 seconds plus 30 seconds grace')
        # Both originals are canonical; this publishes the identical retained
        # packet bytes and preserves its historical as_of, without a new view.
        write_json_once(directory, 'packet.json', packet)
        write_json_once(directory, 'run-intent.json', {'schema_version': intent_version,
            'context_id': packet['context_id'], 'packet_sha256': sha256_bytes(canonical_json_bytes(packet)),
            'evidence_signature': packet['evidence_signature'], 'reserved_at': stamp(now),
            'modeldock': selected['modeldock'], 'validation': metadata})
        state = {'schema_version': VERSION, 'last_attempt_at': stamp(now), 'last_run': directory.name,
                 'last_result': 'ATTEMPT_STARTED'}
        atomic_state(root / 'state.json', state)
        try:
            oracle = generate_role('oracle', packet, directory / 'oracle', modeldock,
                off_check=gates, verify_source=lambda: verify_validation_link(directory, packet,
                    immutable_read(directory, 'run-intent.json'), config), client_factory=client_factory,
                    version=metadata['transport_schema_version'])
            if oracle['status'] == 'ACCEPTED':
                generate_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'],
                    off_check=gates, verify_source=lambda: verify_validation_link(directory, packet,
                        immutable_read(directory, 'run-intent.json'), config), client_factory=client_factory,
                        version=metadata['transport_schema_version'])
            gates()
            result = recover_attempt(directory, config)
            state['last_result'] = result['status']
            atomic_state(root / 'state.json', state)
            return result
        finally:
            gates()


def validate_v2(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory)


def validate_deadline(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, deadline=True)


def validate_error(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, error_diagnostic=True)


def validate_runtime(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, runtime_diagnostic=True)


def validate_model(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, model_selection=True)


def validate_output_budget(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, output_budget=True)


def validate_contract(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, contract_validation=True)


def validate_text(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, text_validation=True)


def validate_symbols(config, source_report_id, *, now=None, client_factory=None):
    return _validate(config, source_report_id, now=now, client_factory=client_factory, symbol_validation=True)


def cycle(config, *, now=None, client_factory=None):
    live_clock = now is None
    root, runs = paths(config)
    with service_lock(root):
        selected = control(read_state(root / 'control.json'))
        codex = selected['schema_version'] == CODEX_CONTROL_VERSION
        entries = ledger(runs)
        now = now or utc_now()
        scheduled = 'schedule' in selected
        slot = None
        if scheduled:
            admitted, reason, slot = scheduled_due(now, entries, selected)
        else:
            admitted, reason = due(now, entries, selected['enabled'])
        if not admitted:
            return reason
        _off(Path(config['runtime_root']))
        verify(config)  # No new inference alongside an unverifiable archive.
        # Archive replay can be expensive. Live admission must use the clock
        # after it finishes, never reserve an expired slot with an older time.
        if live_clock:
            now = utc_now()
            if scheduled:
                admitted, reason, slot = scheduled_due(now, entries, selected)
            else:
                admitted, reason = due(now, entries, selected['enabled'])
            if not admitted:
                return reason
        packet = current_packet(config, as_of=now, **({'include_content':selected['analysis']['include_article_content']} if 'analysis' in selected else {}))
        if codex:
            codex_evidence_gate(config, packet, selected['qualification'])
        if (now - clock(packet['quality']['latest_capture_at'])).total_seconds() > 600:
            return 'SOURCE_CAPTURE_STALE'
        if not packet['selection']['selected_headline_count']:
            return 'NO_HEADLINE_EVIDENCE'
        if (runs / packet['evidence_signature']).exists():
            return 'NO_NEW_HEADLINE_EVIDENCE'
        if len(inventory(runs)) >= MAX_RUNS or sum(p.stat().st_size for p in runs.rglob('*') if p.is_file()) > MAX_BYTES - 8 * 1024 * 1024:
            return 'ARCHIVE_REVIEW_REQUIRED'
        directory = runs / packet['evidence_signature']
        modeldock = configuration(selected['modeldock'], allow_codex=codex)
        write_json_once(directory, 'packet.json', packet)
        intent = {'schema_version': CODEX_ATTEMPT_VERSION if codex else ECONOMIC_ATTEMPT_VERSION if 'analysis' in selected else SCHEDULE_ATTEMPT_VERSION if scheduled else VERSION, 'context_id': packet['context_id'],
            'packet_sha256': sha256_bytes(canonical_json_bytes(packet)), 'evidence_signature': packet['evidence_signature'],
            'reserved_at': stamp(now), 'modeldock': selected['modeldock']}
        if scheduled:
            intent['schedule'] = {'id': selected['schedule']['id'], 'slot_at': slot,
                                  'window_seconds': selected['schedule']['window_seconds']}
        if 'analysis' in selected:
            intent['analysis'] = selected['analysis']
        if codex:
            intent.update(transport_version=CODEX_TRANSPORT_VERSION, qualification=selected['qualification'])
        write_json_once(directory, 'run-intent.json', intent)
        transport_version = CODEX_TRANSPORT_VERSION if codex else ('blackpod.sentry_synthesis_transport.v16' if selected.get('analysis',{}).get('prompt_version')=='ECONOMIC_V4' else ECONOMIC_TRANSPORT_VERSION) if 'analysis' in selected else BACKGROUND_TRANSPORT_VERSION
        state = {'schema_version': VERSION, 'last_attempt_at': stamp(now), 'last_run': directory.name,
                 'last_result': 'ATTEMPT_STARTED'}
        atomic_state(root / 'state.json', state)  # The durable run intent already consumed budget.
        try:
            def gate():
                _off(Path(config['runtime_root']))
                if codex:
                    if control(read_state(root / 'control.json')) != selected:
                        raise ValueError('Codex Sentry control changed during the reserved attempt')
                    codex_evidence_gate(config, packet, selected['qualification'])
            source = lambda: verify_packet(packet, config)
            with awake_while_generating(modeldock):
                oracle = generate_role('oracle', packet, directory / 'oracle', modeldock,
                    off_check=gate, verify_source=source, client_factory=client_factory, version=transport_version)
                if codex:
                    gate()
                if oracle['status'] == 'ACCEPTED':
                    generate_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'],
                        off_check=gate, verify_source=source, client_factory=client_factory, version=transport_version)
                    if codex:
                        gate()
            report = recover_attempt(directory, config)
            state['last_result'] = report['status']
        except ERRORS:
            state['last_result'] = 'SOURCE_OR_OFF_BLOCKED'
        atomic_state(root / 'state.json', state)
        return state['last_result']


def verify(config):
    _, runs = paths(config)
    context = _ReplayContext(config)
    source = context.source
    entries = context.entries()
    orphans = [directory for directory in inventory(runs) if not (directory / 'run-intent.json').exists()]
    for directory in orphans:
        if (directory / 'packet.json').exists():
            context.packet(immutable_read(directory, 'packet.json'))
    complete = uncertain = 0
    dispositions = {}
    for directory, packet, intent, modeldock in entries:
        if (directory / 'report.json').exists():
            report = read_report(directory, config, _context=context)
            dispositions[report['status']] = dispositions.get(report['status'], 0) + 1
            complete += 1
        else:
            context.packet(packet)
            verify_validation_link(directory, packet, intent, config, _context=context)
            context.retained(directory, packet, modeldock)
            uncertain += 1
    return {'status': 'VERIFIED', 'attempt_count': len(entries), 'report_count': complete,
            'incomplete_attempt_count': uncertain, 'abandoned_pre_reservation_count': len(orphans),
            'report_dispositions': dispositions}


def role_diagnostics(directory, report, *, _context=None):
    """Read closed, receipt-bound failure categories without exposing model text."""
    _, _, dock = (_context.attempt(directory) if _context is not None else load_attempt(directory))
    result = {}
    for role in ('oracle', 'challenge'):
        if _context is not None and not os.path.lexists(directory / role / 'local-contract-error.json'):
            # The context has already verified the original role. There is no
            # diagnostic to attach; a symlink still counts as present and is
            # rejected by the original safe reader rather than skipped.
            continue
        observation = read_local_contract_observation(role, report['context'], directory / role, dock,
            **({'draft': report['draft']} if role == 'challenge' else {}))
        if observation is not None:
            result[role] = {key: observation[key] for key in ('stage', 'reason', 'rule', 'field') if key in observation}
    return result


def status(config, now=None):
    now = now or utc_now()
    value = {'schema_version': VERSION, 'status': 'NOT_GENERATED', 'report': None, 'auto_trading': 'UNVERIFIED',
             'operational': {'enabled': False}, 'authority': dict(AUTHORITY)}
    try:
        _off(Path(config['runtime_root']))
        value['auto_trading'] = 'OFF'
        root, runs = paths(config)
        selected = control(read_state(root / 'control.json'))
        entries = ledger(runs)
        replay = _ReplayContext(config, entries=entries)
        orphan_count = len(inventory(runs)) - len(entries)
        state = read_state(root / 'state.json')
        health = read_state(root / 'health.json')
        heartbeat = health.get('heartbeat_at')
        scheduled = 'schedule' in selected
        slot = None
        if scheduled:
            _, reason, slot = scheduled_due(now, entries, selected)
        else:
            _, reason = due(now, entries, selected['enabled'])
        today = now.astimezone(LA).date()
        background = [row for row in entries if row[2]['schema_version'] in BACKGROUND_ATTEMPT_VERSIONS]
        health_bound = 300
        processing = False
        if entries and heartbeat:
            directory, _, intent, dock = entries[-1]
            reserved = clock(intent['reserved_at'])
            delivery_bound = 2 * (dock.timeout_seconds + dock.delivery_grace_seconds) + 30
            processing = (not (directory / 'report.json').exists()
                and state.get('last_result') == 'ATTEMPT_STARTED' and state.get('last_run') == directory.name
                and clock(heartbeat) >= reserved - timedelta(seconds=30)
                and 0 <= (now - reserved).total_seconds() < delivery_bound)
            if processing:
                health_bound = max(300, delivery_bound)
        heartbeat_age = (now-clock(heartbeat)).total_seconds() if heartbeat else None
        value['operational'] = {'enabled': selected['enabled'], 'reason': reason,
            # Liveness only: a long bounded delivery does not prove progress.
            'worker_healthy': bool(heartbeat_age is not None and 0 <= heartbeat_age < health_bound),
            'heartbeat_age_seconds': heartbeat_age, 'worker_health_bound_seconds': health_bound,
            'awaiting_retained_completion': processing,
            'abandoned_pre_reservation_count': orphan_count,
            'attempt_count_today': sum(clock(row[2]['reserved_at']).astimezone(LA).date() == today for row in entries),
            'background_attempt_count_today': sum(clock(row[2]['reserved_at']).astimezone(LA).date() == today for row in background),
            'manual_attempt_count_today': sum(row[2]['schema_version'] not in BACKGROUND_ATTEMPT_VERSIONS and clock(row[2]['reserved_at']).astimezone(LA).date() == today for row in entries),
            'last_attempt_at': entries[-1][2]['reserved_at'] if entries else None,
            'next_eligible_at': stamp(clock(background[-1][2]['reserved_at']) + timedelta(hours=1)) if background and reason == 'WAITING_FOR_NEXT_SLOT' else None,
            'last_result': state.get('last_result', 'NOT_RUN')}
        if selected['schema_version'] == CODEX_CONTROL_VERSION:
            codex_qualification(selected['qualification'], verify=True)
            _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
            value['operational']['provider_policy'] = {'provider': 'codex', 'engine': 'codex-app-server',
                'prompt_version': 'ECONOMIC_V4', 'transport_version': CODEX_TRANSPORT_VERSION,
                'monitoring': selected['monitoring'], 'qualification': selected['qualification']}
        value['operational']['last_check_result'] = health.get('last_check_result', 'NOT_CHECKED')
        if scheduled:
            plan = selected['schedule']
            claimed = {row[2]['schedule']['slot_at']: row[0].name for row in entries
                       if row[2]['schema_version'] in {SCHEDULE_ATTEMPT_VERSION, ECONOMIC_ATTEMPT_VERSION, CODEX_ATTEMPT_VERSION} and 'schedule' in row[2]
                       and row[2]['schedule']['id'] == plan['id']}
            value['operational']['schedule'] = {'id': plan['id'], 'slots': [
                {'slot_at': t, 'run_id': claimed.get(t), 'status': 'RESERVED' if t in claimed else
                 'MISSED_NO_ATTEMPT' if now >= clock(t) + timedelta(seconds=plan['window_seconds']) else 'PENDING'}
                for t in plan['slots']]}
            value['operational']['next_eligible_at'] = slot
        packet = current_packet(config, as_of=now, verified_source=replay.source, **({'include_content':selected['analysis']['include_article_content']} if 'analysis' in selected else {}))
        if selected['schema_version'] == CODEX_CONTROL_VERSION and packet['watchlist'] != selected['qualification']['watchlist']:
            raise ValueError('current watchlist differs from qualified Codex policy')
        value['current_source_head'] = packet['source']['head_sha256']
        # Current observations are separate from the preserved model input.
        if packet['quality'].get('market_feed') in {'sip', 'delayed_sip'}:
            captured_at = packet['quality']['latest_capture_at']
            age = (now - clock(captured_at)).total_seconds()
            value['current_market_context'] = {
                'status': 'FRESH' if 0 <= age <= 600 else 'STALE',
                'captured_at': captured_at,
                'market_feed': packet['quality']['market_feed'],
                'feed_delay_seconds': packet['quality']['feed_delay_seconds'],
                'contexts': [row['data'] for row in packet['evidence'] if row['kind'] == 'PRICE_CONTEXT'],
            }
        for directory, _, retained_intent, _ in reversed(entries):
            # Controlled study subsets (including explicitly authored stress
            # cases) must not replace the operational market brief.
            if retained_intent['schema_version'] == COMPARISON_ATTEMPT_VERSION:
                continue
            if (directory / 'report.json').exists():
                report = read_report(directory, config, _context=replay)
                value.update(status=report['status'], report=report,
                    brief_age_seconds=int((now-clock(report['context']['as_of'])).total_seconds()),
                    newer_evidence_available=report['context']['source']['head_sha256'] != packet['source']['head_sha256'])
                value['role_diagnostics'] = role_diagnostics(directory, report, _context=replay)
                if (report.get('draft') or {}).get('schema_version') in {'blackpod.sentry_oracle_draft.v4', 'blackpod.sentry_oracle_draft.v5'}:
                    from .sentry_narrative_evaluation import intake_quality
                    value['intake_quality'] = intake_quality(report['context'],report['draft'],report['challenge'])
                break
        if (any(row[2]['schema_version'] != COMPARISON_ATTEMPT_VERSION for row in entries) or orphan_count) and not value['report']:
            value['status'] = 'UNCERTAIN'
        _off(Path(config['runtime_root']))
    except ERRORS:
        value.update(status='UNAVAILABLE', report=None, auto_trading='UNVERIFIED')
        value.pop('current_market_context', None)
        value.pop('role_diagnostics', None)
    # An additive read-only attachment. It cannot alter the original report,
    # invoke generation, or make an evaluation failure look like approval.
    from .sentry_narrative_evaluation import evaluation_status
    value['narrative_evaluation'] = evaluation_status(config, value['report'])
    return value


def worker(config, stop):
    root, _ = paths(config)
    while not stop.is_set():
        try:
            atomic_state(root / 'health.json', {'schema_version': VERSION, 'heartbeat_at': stamp(utc_now())})
            result = cycle(config)
            atomic_state(root / 'health.json', {'schema_version': VERSION,
                'heartbeat_at': stamp(utc_now()), 'last_check_result': result})
        except ERRORS:
            # Failures cannot stop the independent pilot or Sentry collector.
            try:
                atomic_state(root / 'health.json', {'schema_version': VERSION,
                    'heartbeat_at': stamp(utc_now()), 'last_check_result': 'SOURCE_OR_OFF_BLOCKED'})
            except ERRORS:
                pass
        stop.wait(30)


def start_worker(config, stop):
    thread = threading.Thread(target=worker, args=(config, stop), name='sentry-synthesis', daemon=True)
    thread.start()
    return thread


def main(argv=None):
    from .shadow_station import load_config
    parser = argparse.ArgumentParser(description='Observation-only local Sentry → Oracle synthesis')
    parser.add_argument('command', choices=['configure', 'generate', 'recover', 'status', 'verify', 'validate-v2', 'validate-deadline', 'validate-error', 'validate-runtime', 'validate-model', 'validate-output-budget', 'validate-contract', 'validate-text', 'validate-symbols'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--enabled', action='store_true')
    parser.add_argument('--modeldock-base-url')
    parser.add_argument('--modeldock-timeout-seconds', type=float)
    parser.add_argument('--modeldock-delivery-grace-seconds', type=float, default=30)
    parser.add_argument('--modeldock-profile', default='default')
    parser.add_argument('--modeldock-provider', choices=['mlx', 'codex'], default='mlx')
    parser.add_argument('--codex-validation-root', type=Path, help='Verified accepted full-watchlist compatibility capsule for Codex configure only')
    parser.add_argument('--weekday-monitoring', action='store_true', help='Explicitly select existing bounded weekday monitoring for Codex configure')
    parser.add_argument('--source-report-id')
    parser.add_argument('--schedule', type=Path, help='Finite schedule JSON for configure only')
    parser.add_argument('--economic-prompt', action='store_true', help='Configure versioned economic reasoning')
    parser.add_argument('--economic-prompt-version', choices=['ECONOMIC_V3','ECONOMIC_V4'])
    parser.add_argument('--include-article-content', action='store_true', help='Supply retained provider article text to the economic prompt')
    args = parser.parse_args(argv)
    if args.schedule is not None and args.command != 'configure':
        parser.error('--schedule is only valid for configure')
    if (args.codex_validation_root is not None or args.weekday_monitoring or args.modeldock_provider != 'mlx') and args.command != 'configure':
        parser.error('provider policy is only valid for configure')
    if args.modeldock_provider == 'codex':
        if not args.economic_prompt or args.economic_prompt_version != 'ECONOMIC_V4' or args.codex_validation_root is None:
            parser.error('Codex configure requires economic V4 and an accepted --codex-validation-root')
        if args.weekday_monitoring == (args.schedule is not None):
            parser.error('Codex configure requires exactly one of --weekday-monitoring or --schedule')
    elif args.codex_validation_root is not None or args.weekday_monitoring:
        parser.error('Codex qualification and deliberate monitoring apply only to provider codex')
    if (args.economic_prompt or args.include_article_content or args.economic_prompt_version) and args.command != 'configure':
        parser.error('economic settings are only valid for configure')
    if args.economic_prompt_version and not args.economic_prompt:
        parser.error('--economic-prompt-version requires --economic-prompt')
    if args.include_article_content and not args.economic_prompt:
        parser.error('--include-article-content requires --economic-prompt')
    if args.command in {'validate-v2', 'validate-deadline', 'validate-error', 'validate-runtime', 'validate-model', 'validate-output-budget', 'validate-contract', 'validate-text', 'validate-symbols'} and not args.source_report_id:
        parser.error('explicit validation requires --source-report-id identifying its terminal failed source')
    if args.command not in {'validate-v2', 'validate-deadline', 'validate-error', 'validate-runtime', 'validate-model', 'validate-output-budget', 'validate-contract', 'validate-text', 'validate-symbols'} and args.source_report_id is not None:
        parser.error('--source-report-id is only valid for explicit validation')
    try:
        config = load_config(args.config)
        root, runs = paths(config)
        if args.command == 'configure':
            dock = configuration({'base_url':args.modeldock_base_url, 'timeout_seconds':args.modeldock_timeout_seconds,
                'profile':args.modeldock_profile, 'provider':args.modeldock_provider,
                'max_response_bytes':1024 * 1024, 'delivery_grace_seconds':args.modeldock_delivery_grace_seconds},
                allow_codex=args.modeldock_provider == 'codex')
            document = {'schema_version': CONTROL_VERSION, 'enabled': args.enabled,
                'modeldock': {key: getattr(dock, key) for key in ('base_url', 'timeout_seconds', 'profile', 'provider', 'max_response_bytes', 'delivery_grace_seconds')}}
            if args.schedule is not None:
                document.update(schema_version=SCHEDULE_CONTROL_VERSION, schedule=read_state(args.schedule))
            if args.economic_prompt:
                document.update(schema_version=ECONOMIC_CONTROL_VERSION,
                    analysis={'prompt_version':args.economic_prompt_version or 'ECONOMIC_V3','include_article_content':args.include_article_content})
            if args.modeldock_provider == 'codex':
                from .sentry_codex_validation import verify_qualification
                qualified = verify_qualification(args.codex_validation_root)
                document.update(schema_version=CODEX_CONTROL_VERSION, qualification=qualified,
                    monitoring='FINITE_SCHEDULE' if args.schedule is not None else 'WEEKDAY_BOUNDED')
            control(document)
            _off(Path(config['runtime_root']))
            with service_lock(root):
                if args.modeldock_provider == 'codex':
                    packet = current_packet(config, include_content=args.include_article_content)
                    codex_evidence_gate(config, packet, document['qualification'])
                    verify(config)
                atomic_state(root / 'control.json', document)
            result = document
        elif args.command == 'generate':
            result = {'status': cycle(config)}
        elif args.command == 'validate-v2':
            result = validate_v2(config, args.source_report_id)
        elif args.command == 'validate-deadline':
            result = validate_deadline(config, args.source_report_id)
        elif args.command == 'validate-error':
            result = validate_error(config, args.source_report_id)
        elif args.command == 'validate-runtime':
            result = validate_runtime(config, args.source_report_id)
        elif args.command == 'validate-model':
            result = validate_model(config, args.source_report_id)
        elif args.command == 'validate-output-budget':
            result = validate_output_budget(config, args.source_report_id)
        elif args.command == 'validate-contract':
            result = validate_contract(config, args.source_report_id)
        elif args.command == 'validate-text':
            result = validate_text(config, args.source_report_id)
        elif args.command == 'validate-symbols':
            result = validate_symbols(config, args.source_report_id)
        elif args.command == 'recover':
            with service_lock(root):
                reports = [recover_attempt(row[0], config)['report_id'] for row in ledger(runs)]
                result = {**verify(config), 'status': 'RECOVERED', 'reports': reports}
        elif args.command == 'verify':
            result = verify(config)
        else:
            result = status(config)
        print(json.dumps(result, sort_keys=True))
        return 0
    except ERRORS:
        print(json.dumps({'status': 'BLOCKED', 'authority': 'OBSERVATION_ONLY'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
