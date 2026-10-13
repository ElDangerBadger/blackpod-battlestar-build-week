"""Explicit execution controls. Separate from the offline journal CLI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .auto_trading_runtime import (
    disable_trading, enable_trading, profile_hash, read_json, runtime_status,
    source_manifest, validate_profile,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guarded Galactica/Alpaca TRADING control; default OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("source-manifest", help="read source hashes without importing Galactica")
    manifest.add_argument("--galactica-root", type=Path, required=True)
    validate = commands.add_parser("validate-profile", help="offline pins, ownership and fixed-budget checks")
    validate.add_argument("--profile", type=Path, required=True)
    status = commands.add_parser("status", help="read entry gate and worker state; no broker calls")
    status.add_argument("--runtime-root", type=Path, required=True)
    for name in ("enable", "disable"):
        action = commands.add_parser(name, help="start explicit executor" if name == "enable" else "close entries and retain exits")
        action.add_argument("--runtime-root", type=Path, required=True)
        action.add_argument("--action-id", required=True)
        action.add_argument("--operator-id", required=True)
        if name == "enable":
            action.add_argument("--profile", type=Path, required=True)
            action.add_argument("--confirm-profile-sha256", required=True)
            action.add_argument("--confirm-account-id", required=True)
            action.add_argument("--confirm-mode", choices=("PAPER", "LIVE"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "source-manifest":
            output = {"source_hashes": source_manifest(args.galactica_root), "broker_calls": 0}
        elif args.command == "validate-profile":
            profile = validate_profile(read_json(args.profile))
            output = {"profile_sha256": profile_hash(profile), "profile_id": profile["profile_id"],
                "mode": profile["mode"], "validation_scope": "LOCAL_STRUCTURE_AND_FILE_PINS",
                "broker_calls": 0, "account_identity_verified": False,
                "capital_authorization_authenticated": False, "entries_enabled": False}
        elif args.command == "status":
            output = runtime_status(args.runtime_root)
        elif args.command == "disable":
            output = disable_trading(args.runtime_root, action_id=args.action_id, operator_id=args.operator_id)
        else:
            output = enable_trading(args.runtime_root, read_json(args.profile), action_id=args.action_id,
                operator_id=args.operator_id, confirm_profile_sha256=args.confirm_profile_sha256,
                confirm_account_id=args.confirm_account_id, confirm_mode=args.confirm_mode)
        print(json.dumps({"command": args.command, **output}, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError):
        # Generic runtime errors are deliberate: no potentially sensitive API
        # or environment values are copied to the operator console.
        print("auto-trading: control rejected; check profile, pins and runtime state", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
