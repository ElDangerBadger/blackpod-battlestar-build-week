"""Explicit offline baseline export; never appends or starts a worker."""
import argparse
import json
from pathlib import Path

from .decision_journal_store import JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes
from .research_baseline import COHORTS, baseline_from_journal


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only research coverage baseline, with no trading authority")
    parser.add_argument("--journal-root", type=Path, required=True)
    parser.add_argument("--cohort", choices=sorted(COHORTS), required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        check_separate_root(args.output.parent, args.journal_root)
        result = baseline_from_journal(args.journal_root, cohort=args.cohort, as_of=args.as_of)
        _write(args.output, canonical_json_bytes(result), [args.journal_root])
        print(json.dumps({"report_id": result["report_id"], "output": str(args.output.absolute()),
            "verification": result["verification"], "auto_trading_enabled": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
