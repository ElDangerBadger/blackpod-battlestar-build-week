"""One-shot saved-evidence qualification for explicitly enabled Codex Sentry.

The existing Sentry role ledger owns delivery and replay. This module supplies
no orders, policy changes, retries, output repair or alternate inference route.
"""
from pathlib import Path
import argparse
import os

from .contracts.mission_request import parse_rfc3339
from .decision_journal_store import _open_root, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_synthesis_transport import (
    CODEX_ECONOMIC_VERSION, _read, write_json_once, generate_role, read_role,
)
from .sentry_modeldock_codex import SentryCodexConfig

VERSION = 'blackpod.sentry_codex_qualification.v1'
FOLLOWUP_VERSION = 'blackpod.sentry_codex_challenge_followup.v1'
CONFIG_FIELDS = ('base_url', 'timeout_seconds', 'profile', 'provider',
                 'max_response_bytes', 'delivery_grace_seconds')


def _document(root, name):
    descriptor = _open_root(root, create=False)
    try:
        value, raw = _read(descriptor, name)
        if raw != canonical_json_bytes(value):
            raise ValueError('noncanonical Codex qualification document')
        return value
    finally:
        os.close(descriptor)


def _basis(root):
    packet = _document(root, 'packet.json')
    plan = _document(root, 'validation.json')
    expected = {'schema_version', 'transport_version', 'packet_sha256',
                'modeldock', 'watchlist', 'reserved_at'}
    if (set(plan) != expected or plan['schema_version'] != VERSION
            or plan['transport_version'] != CODEX_ECONOMIC_VERSION
            or plan['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet))
            or plan['watchlist'] != packet['watchlist']
            or len(packet['watchlist']) != 10 or len(set(packet['watchlist'])) != 10
            or set(plan['modeldock']) != set(CONFIG_FIELDS)):
        raise ValueError('full-watchlist Codex qualification binding differs')
    if parse_rfc3339(plan['reserved_at'], 'qualification reservation') < parse_rfc3339(packet['as_of'], 'packet as_of'):
        raise ValueError('qualification precedes saved evidence')
    dock = SentryCodexConfig(**plan['modeldock'])
    return packet, plan, dock


def verify_qualification(root):
    """Replay accepted original/explicitly linked roles without a transport."""
    root = Path(os.path.abspath(root))
    packet, plan, dock = _basis(root)
    oracle = read_role('oracle', packet, root / 'oracle', dock, version=CODEX_ECONOMIC_VERSION)
    if oracle['status'] != 'ACCEPTED':
        raise ValueError('full-watchlist Oracle qualification is not accepted')
    original_challenge = read_role('challenge', packet, root / 'challenge', dock,
                                   draft=oracle['response'], version=CODEX_ECONOMIC_VERSION)
    challenge_root = _challenge_root(root, plan)
    challenge = (original_challenge if challenge_root == root / 'challenge' else
                 read_role('challenge', packet, challenge_root, dock,
                           draft=oracle['response'], version=CODEX_ECONOMIC_VERSION))
    if challenge['status'] != 'ACCEPTED':
        raise ValueError('full-watchlist challenge qualification is not accepted')
    for role, result in (('oracle', oracle), ('challenge', challenge)):
        intent = _document(root / role if role == 'oracle' else challenge_root, 'intent.json')
        if (intent['schema_version'] != CODEX_ECONOMIC_VERSION
                or parse_rfc3339(intent['reserved_at'], 'role reservation') < parse_rfc3339(plan['reserved_at'], 'qualification reservation')):
            raise ValueError('qualified role differs from reserved provider version')
        if role == 'challenge' and challenge_root != root / 'challenge':
            link = _document(root, 'challenge-followup.json')
            if parse_rfc3339(intent['reserved_at'], 'follow-up intent') < parse_rfc3339(link['reserved_at'], 'follow-up approval binding'):
                raise ValueError('follow-up role predates its explicit link')
    if parse_rfc3339(challenge['provenance']['started_at'], 'challenge start') < parse_rfc3339(oracle['provenance']['observed_at'], 'Oracle completion'):
        raise ValueError('qualified challenge precedes original Oracle completion')
    return {'root': str(root), 'packet_sha256': plan['packet_sha256'],
            'oracle_receipt_sha256': oracle['receipt_sha256'],
            'challenge_receipt_sha256': challenge['receipt_sha256'],
            'watchlist': list(packet['watchlist'])}


def _challenge_root(root, plan):
    """Select only an explicitly linked follow-up; never infer a retry path."""
    if not (root / 'challenge-followup.json').exists():
        return root / 'challenge'
    link = _document(root, 'challenge-followup.json')
    fields = {'schema_version', 'packet_sha256', 'original_challenge_receipt_sha256',
              'approval_sha256', 'reserved_at', 'role_directory'}
    original = _document(root / 'challenge', 'receipt.json')
    approval = _document(root, 'challenge-followup-approval.json')
    if (set(link) != fields or link['schema_version'] != FOLLOWUP_VERSION
            or link['packet_sha256'] != plan['packet_sha256']
            or link['role_directory'] != 'challenge-followup-001'
            or original['status'] not in {'FAILED', 'REJECTED'}
            or link['original_challenge_receipt_sha256'] != sha256_bytes(canonical_json_bytes(original))
            or link['approval_sha256'] != sha256_bytes(canonical_json_bytes(approval))
            or type(approval.get('max_additional_requests')) is not int
            or approval.get('automatic_resends') is not False
            or approval != {'schema_version': FOLLOWUP_VERSION, 'authority': 'HUMAN_USER',
                'answer': 'Approve one linked challenge request', 'max_additional_requests': 1,
                'automatic_resends': False, 'packet_sha256': plan['packet_sha256'],
                'original_challenge_receipt_sha256': link['original_challenge_receipt_sha256']}):
        raise ValueError('explicit challenge follow-up binding differs')
    if parse_rfc3339(link['reserved_at'], 'follow-up reservation') < parse_rfc3339(original['finished_at'], 'original challenge completion'):
        raise ValueError('follow-up predates original challenge failure')
    return root / link['role_directory']


def capture_challenge(config, root, *, now=None, client_factory=None):
    """One explicitly approved linked request; original failure stays immutable.

    The human approval is supplied outside this function. Calling this command
    without that exact retained approval cannot send or create a follow-up.
    """
    from .sentry_synthesis import verify_packet
    from .sentry_catalyst import control as catalyst_control, stamp
    from .sentry_catalyst_service import paths as catalyst_paths
    from .sentry_synthesis_service import utc_now
    from .shadow_station import read_state, service_lock
    from .shadow_station_collection import _off, _pinned_view

    root = Path(os.path.abspath(root))
    for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root', 'station_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    packet, plan, dock = _basis(root)

    def gate():
        _off(Path(config['runtime_root']))
        _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
        selected = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
        if selected['symbols'] != packet['watchlist']:
            raise ValueError('follow-up watchlist changed')

    def source():
        verify_packet(packet, config)

    gate(); source()
    with service_lock(root):
        if (root / 'challenge-followup.json').exists():
            return verify_qualification(root)
        if os.path.lexists(root / 'challenge-followup-001'):
            raise ValueError('unlinked follow-up evidence cannot be adopted or resent')
        approval = _document(root, 'challenge-followup-approval.json')
        original = read_role('oracle', packet, root / 'oracle', dock, version=CODEX_ECONOMIC_VERSION)
        failed = read_role('challenge', packet, root / 'challenge', dock,
                           draft=original['response'], version=CODEX_ECONOMIC_VERSION)
        if original['status'] != 'ACCEPTED' or failed['status'] not in {'FAILED', 'REJECTED'}:
            raise ValueError('follow-up requires the accepted Oracle and terminal original challenge')
        # Bind before dispatch. Verification checks exact approval fields and
        # the original failed receipt, not a claim that no earlier POST occurred.
        original_receipt = _document(root / 'challenge', 'receipt.json')
        link = {'schema_version': FOLLOWUP_VERSION, 'packet_sha256': plan['packet_sha256'],
                'original_challenge_receipt_sha256': sha256_bytes(canonical_json_bytes(original_receipt)),
                'approval_sha256': sha256_bytes(canonical_json_bytes(approval)),
                'reserved_at': stamp(now or utc_now()), 'role_directory': 'challenge-followup-001'}
        expected = {'schema_version': FOLLOWUP_VERSION, 'authority': 'HUMAN_USER',
                    'answer': 'Approve one linked challenge request', 'max_additional_requests': 1,
                    'automatic_resends': False, 'packet_sha256': plan['packet_sha256'],
                    'original_challenge_receipt_sha256': link['original_challenge_receipt_sha256']}
        if (approval != expected or type(approval.get('max_additional_requests')) is not int
                or approval.get('automatic_resends') is not False):
            raise ValueError('one-request human follow-up approval is required')
        if plan['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet)) or len(packet['watchlist']) != 10:
            raise ValueError('follow-up packet differs from original full-watchlist validation')
        write_json_once(root, 'challenge-followup.json', link)
        destination = _challenge_root(root, plan)
        kwargs = {'off_check': gate, 'verify_source': source, 'client_factory': client_factory,
                  'version': CODEX_ECONOMIC_VERSION}
        if now is not None:
            kwargs['now'] = lambda: now
        generate_role('challenge', packet, destination, dock, draft=original['response'], **kwargs)
        gate(); source()
        return verify_qualification(root)


def capture(config, packet, root, dock, *, client_factory=None, now=None):
    """Reserve once, then at most one Oracle and one gated challenge request."""
    from .sentry_synthesis import verify_packet
    from .sentry_catalyst import control as catalyst_control, stamp
    from .sentry_catalyst_service import paths as catalyst_paths
    from .sentry_synthesis_service import utc_now
    from .shadow_station import read_state, service_lock
    from .shadow_station_collection import _off, _pinned_view

    if not isinstance(dock, SentryCodexConfig):
        raise ValueError('qualification requires explicit Sentry Codex policy')
    root = Path(os.path.abspath(root))
    for key in ('experiment_root', 'runtime_root', 'historical_root', 'ui_root', 'station_root'):
        check_separate_root(root, Path(config[key]))
    check_separate_root(root, Path(config['credentials_file']).parent)
    selected = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
    if len(packet['watchlist']) != 10 or packet['watchlist'] != selected['symbols']:
        raise ValueError('qualification must use the unchanged full current watchlist')

    def gate():
        _off(Path(config['runtime_root']))
        _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
        current = catalyst_control(read_state(catalyst_paths(config)[0] / 'control.json'))
        if current['symbols'] != packet['watchlist']:
            raise ValueError('qualification watchlist changed')

    def source():
        verify_packet(packet, config)

    gate(); source()
    # A new invocation never continues a partially delivered qualification. It
    # can only inspect the existing proof, including interrupted reservations.
    with service_lock(root):
        if (root / 'validation.json').exists():
            previous = _document(root, 'validation.json')
            if (previous['packet_sha256'] != sha256_bytes(canonical_json_bytes(packet))
                    or previous['modeldock'] != {key: getattr(dock, key) for key in CONFIG_FIELDS}):
                raise ValueError('qualification retry conflicts with original packet or provider configuration')
            return verify_qualification(root)
        if any((root / name).exists() for name in ('packet.json', 'oracle', 'challenge')):
            raise ValueError('incomplete qualification reservation requires review; no resend')
        reserved = now or utc_now()
        plan = {'schema_version': VERSION, 'transport_version': CODEX_ECONOMIC_VERSION,
                'packet_sha256': sha256_bytes(canonical_json_bytes(packet)),
                'modeldock': {key: getattr(dock, key) for key in CONFIG_FIELDS},
                'watchlist': list(packet['watchlist']), 'reserved_at': stamp(reserved)}
        write_json_once(root, 'packet.json', packet)
        write_json_once(root, 'validation.json', plan)
        kwargs = {'client_factory': client_factory, 'off_check': gate,
                  'verify_source': source, 'version': CODEX_ECONOMIC_VERSION}
        if now is not None:
            kwargs['now'] = lambda: now
        oracle = generate_role('oracle', packet, root / 'oracle', dock, **kwargs)
        if oracle['status'] == 'ACCEPTED':
            generate_role('challenge', packet, root / 'challenge', dock,
                          draft=oracle['response'], **kwargs)
        gate(); source()
        return verify_qualification(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['capture', 'verify', 'capture-challenge'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--modeldock-base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            result = verify_qualification(args.root)
        elif args.command == 'capture-challenge':
            if args.config is None:
                parser.error('capture-challenge requires --config and retained explicit human approval')
            from .shadow_station import load_config
            result = capture_challenge(load_config(args.config), args.root)
        else:
            if args.config is None or args.packet is None:
                parser.error('capture requires --config and --packet')
            from .shadow_station import load_config
            from .contracts.mission_request import parse_strict_json_object_bytes
            packet = parse_strict_json_object_bytes(args.packet.read_bytes())
            dock = SentryCodexConfig(base_url=args.modeldock_base_url,
                                    timeout_seconds=900, provider='codex')
            result = capture(load_config(args.config), packet, args.root, dock)
        # Hashes and public identities only; never print supplied article text.
        print(canonical_json_bytes({'status': 'QUALIFIED', 'qualification': result,
                                    'auto_trading': 'NOT_CHECKED' if args.command == 'verify' else 'OFF',
                                    'execution_authority': False}).decode())
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print('{"status":"NOT_QUALIFIED","details":"Inspect retained local evidence; no automatic retry"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
