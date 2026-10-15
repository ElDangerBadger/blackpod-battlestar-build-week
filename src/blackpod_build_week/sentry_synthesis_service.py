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
from .sentry_catalyst import clock, stamp
from .sentry_catalyst_service import paths as catalyst_paths
from .sentry_synthesis import VERSION, AUTHORITY, current_packet, verify_packet, compose_report
from .sentry_synthesis_transport import generate_role, read_role, write_json_once, _read
from .shadow_station import read_state, atomic_state, service_lock
from .shadow_station_collection import _off

CONTROL_VERSION = 'blackpod.sentry_synthesis_control.v1'
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


def load_attempt(directory):
    if set(os.listdir(directory)) - {'packet.json', 'run-intent.json', 'completion-clock.json', 'report.json', 'oracle', 'challenge', 'staging'}:
        raise ValueError('unexpected synthesis capsule file')
    packet = immutable_read(directory, 'packet.json')
    intent = immutable_read(directory, 'run-intent.json')
    if (set(intent) != {'schema_version', 'context_id', 'packet_sha256', 'evidence_signature', 'reserved_at', 'modeldock'}
            or intent['schema_version'] != VERSION or intent['context_id'] != packet['context_id']
            or intent['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet))
            or intent['evidence_signature'] != packet['evidence_signature']
            or directory.name != packet['evidence_signature'] or clock(intent['reserved_at']) < clock(packet['as_of'])):
        raise ValueError('synthesis attempt binding differs')
    return packet, intent, configuration(intent['modeldock'])


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
                if directory.name != packet['evidence_signature']:
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
    oracle, challenge = retained_roles(directory, packet, modeldock)
    completed = immutable_read(directory, 'completion-clock.json')
    if set(completed) != {'completed_at'} or clock(completed['completed_at']) < minimum_completion(directory, intent):
        raise ValueError('invalid synthesis completion clock')
    report = immutable_read(directory, 'report.json')
    if report != compose_report(packet, oracle, challenge, completed['completed_at']):
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
    if (directory / 'report.json').exists():
        return read_report(directory, config)
    oracle, challenge = retained_roles(directory, packet, modeldock)
    if not (directory / 'completion-clock.json').exists():
        completed_at = now or utc_now()
        if completed_at < minimum_completion(directory, intent):
            raise ValueError('completion clock precedes retained model delivery')
        write_json_once(directory, 'completion-clock.json', {'completed_at': stamp(completed_at)})
    completed = immutable_read(directory, 'completion-clock.json')['completed_at']
    report = compose_report(packet, oracle, challenge, completed)
    _off(Path(config['runtime_root']))
    verify_packet(packet, config)
    write_json_once(directory, 'report.json', report)
    return read_report(directory, config)


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
    for directory, packet, _, modeldock in entries:
        verify_packet(packet, config)
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
    parser.add_argument('command', choices=['configure', 'generate', 'recover', 'status', 'verify'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--enabled', action='store_true')
    parser.add_argument('--modeldock-base-url')
    parser.add_argument('--modeldock-timeout-seconds', type=float)
    parser.add_argument('--modeldock-profile', default='default')
    args = parser.parse_args(argv)
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
