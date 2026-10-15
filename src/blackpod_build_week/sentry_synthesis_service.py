"""Bounded local synthesis worker, with provider-free verification and recovery.

The immutable attempt ledger, not the mutable display state, owns retry and
budget admission. Interrupted roles are inspected, never resent by recovery.
"""
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import re
import stat
import threading
from zoneinfo import ZoneInfo

from .decision_journal_store import JournalStoreError, check_separate_root, _open_root
from .hashing import canonical_json_bytes, sha256_bytes
from .modeldock_config import ModelDockConfig
from .sentry_catalyst import clock, stamp, control as catalyst_control
from .sentry_catalyst_service import paths as catalyst_paths
from .sentry_synthesis import VERSION, AUTHORITY, current_packet, verify_packet, compose_report
from .sentry_synthesis_transport import (generate_role, read_role, write_json_once, _read,
    VERSION as TRANSPORT_VERSION, LEGACY_VERSION as LEGACY_TRANSPORT_VERSION)
from .shadow_station import read_state, atomic_state, service_lock
from .shadow_station_collection import _off, _pinned_view

CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v1'
VALIDATION_VERSION = 'blackpod.sentry_synthesis_validation.v2'
VALIDATION_PURPOSE = 'EXPLICIT_V2_VALIDATION'
VALIDATION_TRANSPORT_VERSION = 'blackpod.sentry_synthesis_transport.v2'
LA = ZoneInfo('America/Los_Angeles')
MAX_RUNS = 256
MAX_BYTES = 64 * 1024 * 1024
ERRORS = (ValueError, TypeError, KeyError, OSError, RuntimeError, JournalStoreError)


def utc_now():
    return datetime.now(timezone.utc)


def paths(config):
    root = Path(config['station_root']) / 'synthesis'
    for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    check_separate_root(root, catalyst_paths(config)[0])
    return root, root / 'runs'


def configuration(value):
    if not isinstance(value, dict) or set(value) != {'base_url', 'timeout_seconds', 'profile', 'provider', 'max_response_bytes', 'delivery_grace_seconds'}:
        raise ValueError('invalid synthesis ModelDock configuration')
    config = ModelDockConfig(**value)
    if config.timeout_seconds > 120 or config.delivery_grace_seconds > 10:
        raise ValueError('synthesis deadline exceeds bound')
    return config


def control(value):
    if not value:
        return {'schema_version': CONTROL_VERSION, 'enabled': False, 'modeldock': None}
    if set(value) != {'schema_version', 'enabled', 'modeldock'} or value['schema_version'] != CONTROL_VERSION or type(value['enabled']) is not bool:
        raise ValueError('invalid synthesis control')
    configuration(value['modeldock'])
    return value


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


def validation_directory(parent_report_id):
    if not isinstance(parent_report_id, str) or re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', parent_report_id) is None:
        raise ValueError('invalid validation source report identity')
    return sha256_bytes(canonical_json_bytes({'purpose': VALIDATION_PURPOSE,
        'parent_report_id': parent_report_id, 'transport_schema_version': VALIDATION_TRANSPORT_VERSION}))


def validation_metadata(value):
    if (not isinstance(value, dict) or set(value) != {'purpose', 'parent_report_id', 'parent_report_sha256', 'transport_schema_version'}
            or value['purpose'] != VALIDATION_PURPOSE
            or value['transport_schema_version'] != VALIDATION_TRANSPORT_VERSION
            or not isinstance(value['parent_report_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', value['parent_report_sha256']) is None):
        raise ValueError('invalid explicit validation linkage')
    validation_directory(value['parent_report_id'])
    return value


def load_attempt(directory):
    if set(os.listdir(directory)) - {'packet.json', 'run-intent.json', 'completion-clock.json', 'report.json', 'oracle', 'challenge', 'staging'}:
        raise ValueError('unexpected synthesis capsule file')
    packet = immutable_read(directory, 'packet.json')
    intent = immutable_read(directory, 'run-intent.json')
    fields = {'schema_version', 'context_id', 'packet_sha256', 'evidence_signature', 'reserved_at', 'modeldock'}
    if intent.get('schema_version') == VALIDATION_VERSION:
        expected_fields = fields | {'validation'}
        metadata = validation_metadata(intent.get('validation'))
        expected_directory = validation_directory(metadata['parent_report_id'])
    elif intent.get('schema_version') == VERSION:
        expected_fields, expected_directory = fields, packet['evidence_signature']
    else:
        raise ValueError('unsupported synthesis attempt schema')
    if (set(intent) != expected_fields or intent['context_id'] != packet['context_id']
            or intent['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet))
            or intent['evidence_signature'] != packet['evidence_signature']
            or directory.name != expected_directory or clock(intent['reserved_at']) < clock(packet['as_of'])):
        raise ValueError('synthesis attempt binding differs')
    return packet, intent, configuration(intent['modeldock'])


def abandoned_validation(directory, packet):
    """Identify a packet-only child without inventing a reservation or send."""
    for candidate in inventory(directory.parent):
        if candidate == directory or not (candidate / 'report.json').exists():
            continue
        report = immutable_read(candidate, 'report.json')
        identity = report.get('report_id')
        if (isinstance(identity, str) and re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}', identity)
                and directory.name == validation_directory(identity)
                and report.get('context') == packet):
            return True
    return False


def ledger(runs):
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
        packet, intent, modeldock = load_attempt(directory)
        entries.append((directory, packet, intent, modeldock))
    return sorted(entries, key=lambda row: (clock(row[2]['reserved_at']), row[0].name))


def due(now, entries, enabled):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware synthesis clock required')
    local = now.astimezone(LA)
    if not enabled:
        return False, 'PAUSED'
    if local.weekday() >= 5 or not 5 <= local.hour < 17:
        return False, 'OUTSIDE_MONITORING_HOURS'
    times = [clock(row[2]['reserved_at']) for row in entries]
    if times and max(times) > now:
        return False, 'CLOCK_BLOCKED'
    if sum(t.astimezone(LA).date() == local.date() for t in times) >= 4:
        return False, 'DAILY_BUDGET_EXHAUSTED'
    if times and now - max(times) < timedelta(hours=1):
        return False, 'WAITING_FOR_NEXT_SLOT'
    return True, 'DUE'


def retained_roles(directory, packet, modeldock):
    oracle = read_role('oracle', packet, directory / 'oracle', modeldock)
    challenge = (read_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'])
                 if oracle['status'] == 'ACCEPTED' else {'status': 'UNCERTAIN', 'response': None, 'failure_code': 'ORACLE_NOT_ACCEPTED'})
    return oracle, challenge


def read_report(directory, config):
    packet, intent, modeldock = load_attempt(directory)
    verify_packet(packet, config)
    metadata = verify_validation_link(directory, packet, intent, config)
    oracle, challenge = retained_roles(directory, packet, modeldock)
    completed = immutable_read(directory, 'completion-clock.json')
    if set(completed) != {'completed_at'} or clock(completed['completed_at']) < minimum_completion(directory, intent):
        raise ValueError('invalid synthesis completion clock')
    report = immutable_read(directory, 'report.json')
    if report != compose_report(packet, oracle, challenge, completed['completed_at'], **({'validation': metadata} if metadata else {})):
        raise ValueError('synthesis report does not replay')
    return report


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
    write_json_once(directory, 'report.json', report)
    return read_report(directory, config)


def validation_parent(config, parent_report_id):
    """Replay a terminal legacy failure; an accepted or uncertain role is ineligible."""
    validation_directory(parent_report_id)
    _, runs = paths(config)
    found = None
    for directory, packet, intent, modeldock in ledger(runs):
        if not (directory / 'report.json').exists():
            continue
        retained = immutable_read(directory, 'report.json')
        if retained.get('report_id') != parent_report_id:
            continue
        if found is not None or intent['schema_version'] != VERSION or 'validation' in intent:
            raise ValueError('validation source must be one original failure')
        report = read_report(directory, config)
        oracle = report['provenance']['oracle']
        if report['status'] not in {'FAILED', 'REJECTED'} or oracle['status'] not in {'FAILED', 'REJECTED'}:
            raise ValueError('validation source is not a terminal failed v1 Oracle delivery')
        role_intent = immutable_read(directory / 'oracle', 'intent.json')
        receipt = immutable_read(directory / 'oracle', 'receipt.json')
        if (report['status'] not in {'FAILED', 'REJECTED'} or oracle['status'] not in {'FAILED', 'REJECTED'}
                or role_intent['schema_version'] != LEGACY_TRANSPORT_VERSION
                or role_intent['wire_request']['response_format']['schema']['properties']['schema_version']['const']
                    != 'blackpod.sentry_oracle_draft.v1'
                or receipt['status'] != oracle['status'] or receipt['response'] is not None
                or receipt['provenance'] is not None or not receipt['failure_code']):
            raise ValueError('validation source is not a terminal failed v1 Oracle delivery')
        found = directory, packet, report
    if found is None:
        raise ValueError('validation source report not found')
    return found


def verify_validation_link(directory, packet, intent, config):
    if intent['schema_version'] != VALIDATION_VERSION:
        return None
    metadata = validation_metadata(intent['validation'])
    parent, original, report = validation_parent(config, metadata['parent_report_id'])
    if (sha256_bytes(canonical_json_bytes(report)) != metadata['parent_report_sha256']
            or original != packet or immutable_read(parent, 'packet.json') != immutable_read(directory, 'packet.json')):
        raise ValueError('validation differs from exact original evidence or parent')
    _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
    for role in ('oracle', 'challenge'):
        role_intent = directory / role / 'intent.json'
        if role_intent.exists() and immutable_read(directory / role, 'intent.json')['schema_version'] != VALIDATION_TRANSPORT_VERSION:
            raise ValueError('validation role did not reserve the v2 transport')
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


def validate_v2(config, source_report_id, *, now=None, client_factory=None):
    """Explicit single child validation of the exact retained legacy evidence.

    This is not ordinary source admission, an automatic retry, or an escape
    from the shared hourly/daily budget. A reserved child is never resent.
    """
    root, runs = paths(config)
    with service_lock(root):
        _off(Path(config['runtime_root']))
        verify(config)
        parent, packet, parent_report = validation_parent(config, source_report_id)
        original_hashes = capsule_hashes(parent)
        metadata = {'purpose': VALIDATION_PURPOSE, 'parent_report_id': source_report_id,
            'parent_report_sha256': sha256_bytes(canonical_json_bytes(parent_report)),
            'transport_schema_version': VALIDATION_TRANSPORT_VERSION}
        directory = runs / validation_directory(source_report_id)

        def gates():
            _off(Path(config['runtime_root']))
            _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
            verify_packet(packet, config)
            current = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
            if current['symbols'] != packet['watchlist'] or capsule_hashes(parent) != original_hashes:
                raise ValueError('validation source, watchlist or original capsule changed')
            checked_parent, checked_packet, checked_report = validation_parent(config, source_report_id)
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
        admitted, reason = due(now, entries, selected['enabled'])
        if not admitted:
            return {'status': reason, 'report_id': None, 'validation': metadata, 'authority': dict(AUTHORITY)}
        if TRANSPORT_VERSION != VALIDATION_TRANSPORT_VERSION:
            raise ValueError('explicit validation requires the fixed v2 transport')
        if len(inventory(runs)) >= MAX_RUNS or sum(p.stat().st_size for p in runs.rglob('*') if p.is_file()) > MAX_BYTES - 8 * 1024 * 1024:
            return {'status': 'ARCHIVE_REVIEW_REQUIRED', 'report_id': None, 'validation': metadata, 'authority': dict(AUTHORITY)}
        modeldock = configuration(selected['modeldock'])
        # Both originals are canonical; this publishes the identical retained
        # packet bytes and preserves its historical as_of, without a new view.
        write_json_once(directory, 'packet.json', packet)
        write_json_once(directory, 'run-intent.json', {'schema_version': VALIDATION_VERSION,
            'context_id': packet['context_id'], 'packet_sha256': sha256_bytes(canonical_json_bytes(packet)),
            'evidence_signature': packet['evidence_signature'], 'reserved_at': stamp(now),
            'modeldock': selected['modeldock'], 'validation': metadata})
        state = {'schema_version': VERSION, 'last_attempt_at': stamp(now), 'last_run': directory.name,
                 'last_result': 'ATTEMPT_STARTED'}
        atomic_state(root / 'state.json', state)
        try:
            oracle = generate_role('oracle', packet, directory / 'oracle', modeldock,
                off_check=gates, verify_source=lambda: verify_validation_link(directory, packet,
                    immutable_read(directory, 'run-intent.json'), config), client_factory=client_factory)
            if oracle['status'] == 'ACCEPTED':
                generate_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'],
                    off_check=gates, verify_source=lambda: verify_validation_link(directory, packet,
                        immutable_read(directory, 'run-intent.json'), config), client_factory=client_factory)
            gates()
            result = recover_attempt(directory, config)
            state['last_result'] = result['status']
            atomic_state(root / 'state.json', state)
            return result
        finally:
            gates()


def cycle(config, *, now=None, client_factory=None):
    root, runs = paths(config)
    with service_lock(root):
        selected = control(read_state(root / 'control.json'))
        entries = ledger(runs)
        now = now or utc_now()
        admitted, reason = due(now, entries, selected['enabled'])
        if not admitted:
            return reason
        _off(Path(config['runtime_root']))
        verify(config)  # No new inference alongside an unverifiable archive.
        packet = current_packet(config, as_of=now)
        if (now - clock(packet['quality']['latest_capture_at'])).total_seconds() > 600:
            return 'SOURCE_CAPTURE_STALE'
        if not packet['selection']['selected_headline_count']:
            return 'NO_HEADLINE_EVIDENCE'
        if (runs / packet['evidence_signature']).exists():
            return 'NO_NEW_HEADLINE_EVIDENCE'
        if len(inventory(runs)) >= MAX_RUNS or sum(p.stat().st_size for p in runs.rglob('*') if p.is_file()) > MAX_BYTES - 8 * 1024 * 1024:
            return 'ARCHIVE_REVIEW_REQUIRED'
        directory = runs / packet['evidence_signature']
        modeldock = configuration(selected['modeldock'])
        write_json_once(directory, 'packet.json', packet)
        write_json_once(directory, 'run-intent.json', {'schema_version': VERSION, 'context_id': packet['context_id'],
            'packet_sha256': sha256_bytes(canonical_json_bytes(packet)), 'evidence_signature': packet['evidence_signature'],
            'reserved_at': stamp(now), 'modeldock': selected['modeldock']})
        state = {'schema_version': VERSION, 'last_attempt_at': stamp(now), 'last_run': directory.name,
                 'last_result': 'ATTEMPT_STARTED'}
        atomic_state(root / 'state.json', state)  # The durable run intent already consumed budget.
        try:
            gate = lambda: _off(Path(config['runtime_root']))
            source = lambda: verify_packet(packet, config)
            oracle = generate_role('oracle', packet, directory / 'oracle', modeldock,
                off_check=gate, verify_source=source, client_factory=client_factory)
            if oracle['status'] == 'ACCEPTED':
                generate_role('challenge', packet, directory / 'challenge', modeldock, draft=oracle['response'],
                    off_check=gate, verify_source=source, client_factory=client_factory)
            report = recover_attempt(directory, config)
            state['last_result'] = report['status']
        except ERRORS:
            state['last_result'] = 'SOURCE_OR_OFF_BLOCKED'
        atomic_state(root / 'state.json', state)
        return state['last_result']


def verify(config):
    _, runs = paths(config)
    entries = ledger(runs)
    orphans = [directory for directory in inventory(runs) if not (directory / 'run-intent.json').exists()]
    for directory in orphans:
        if (directory / 'packet.json').exists():
            verify_packet(immutable_read(directory, 'packet.json'), config)
    complete = uncertain = 0
    dispositions = {}
    for directory, packet, intent, modeldock in entries:
        verify_packet(packet, config)
        verify_validation_link(directory, packet, intent, config)
        retained_roles(directory, packet, modeldock)
        if (directory / 'report.json').exists():
            report = read_report(directory, config)
            dispositions[report['status']] = dispositions.get(report['status'], 0) + 1
            complete += 1
        else:
            uncertain += 1
    return {'status': 'VERIFIED', 'attempt_count': len(entries), 'report_count': complete,
            'incomplete_attempt_count': uncertain, 'abandoned_pre_reservation_count': len(orphans),
            'report_dispositions': dispositions}


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
        orphan_count = len(inventory(runs)) - len(entries)
        state = read_state(root / 'state.json')
        heartbeat = read_state(root / 'health.json').get('heartbeat_at')
        _, reason = due(now, entries, selected['enabled'])
        today = now.astimezone(LA).date()
        value['operational'] = {'enabled': selected['enabled'], 'reason': reason,
            # Covers two bounded model deliveries plus the idle check delay.
            'worker_healthy': bool(heartbeat and 0 <= (now-clock(heartbeat)).total_seconds() < 300),
            'abandoned_pre_reservation_count': orphan_count,
            'attempt_count_today': sum(clock(row[2]['reserved_at']).astimezone(LA).date() == today for row in entries),
            'last_attempt_at': entries[-1][2]['reserved_at'] if entries else None,
            'next_eligible_at': stamp(clock(entries[-1][2]['reserved_at']) + timedelta(hours=1)) if entries and reason == 'WAITING_FOR_NEXT_SLOT' else None,
            'last_result': state.get('last_result', 'NOT_RUN')}
        packet = current_packet(config, as_of=now)
        value['current_source_head'] = packet['source']['head_sha256']
        for directory, _, _, _ in reversed(entries):
            if (directory / 'report.json').exists():
                report = read_report(directory, config)
                value.update(status=report['status'], report=report,
                    brief_age_seconds=int((now-clock(report['context']['as_of'])).total_seconds()),
                    newer_evidence_available=report['context']['source']['head_sha256'] != packet['source']['head_sha256'])
                break
        if (entries or orphan_count) and not value['report']:
            value['status'] = 'UNCERTAIN'
        _off(Path(config['runtime_root']))
    except ERRORS:
        value.update(status='UNAVAILABLE', report=None, auto_trading='UNVERIFIED')
    return value


def worker(config, stop):
    root, _ = paths(config)
    while not stop.is_set():
        try:
            atomic_state(root / 'health.json', {'schema_version': VERSION, 'heartbeat_at': stamp(utc_now())})
            cycle(config)
        except ERRORS:
            # Failures cannot stop the independent pilot or Sentry collector.
            pass
        stop.wait(30)


def start_worker(config, stop):
    thread = threading.Thread(target=worker, args=(config, stop), name='sentry-synthesis', daemon=True)
    thread.start()
    return thread


def main(argv=None):
    from .shadow_station import load_config
    parser = argparse.ArgumentParser(description='Observation-only local Sentry → Oracle synthesis')
    parser.add_argument('command', choices=['configure', 'generate', 'recover', 'status', 'verify', 'validate-v2'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--enabled', action='store_true')
    parser.add_argument('--modeldock-base-url')
    parser.add_argument('--modeldock-timeout-seconds', type=float)
    parser.add_argument('--modeldock-profile', default='default')
    parser.add_argument('--source-report-id')
    args = parser.parse_args(argv)
    if args.command == 'validate-v2' and not args.source_report_id:
        parser.error('validate-v2 requires --source-report-id identifying the original terminal v1 failure')
    if args.command != 'validate-v2' and args.source_report_id is not None:
        parser.error('--source-report-id is only valid for validate-v2')
    try:
        config = load_config(args.config)
        root, runs = paths(config)
        if args.command == 'configure':
            dock = ModelDockConfig(args.modeldock_base_url, args.modeldock_timeout_seconds,
                profile=args.modeldock_profile, delivery_grace_seconds=5)
            document = {'schema_version': CONTROL_VERSION, 'enabled': args.enabled,
                'modeldock': {key: getattr(dock, key) for key in ('base_url', 'timeout_seconds', 'profile', 'provider', 'max_response_bytes', 'delivery_grace_seconds')}}
            control(document)
            _off(Path(config['runtime_root']))
            with service_lock(root):
                atomic_state(root / 'control.json', document)
            result = document
        elif args.command == 'generate':
            result = {'status': cycle(config)}
        elif args.command == 'validate-v2':
            result = validate_v2(config, args.source_report_id)
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
