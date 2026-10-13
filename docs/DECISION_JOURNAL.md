# Passive Decision Journal and two-desk foundation

Burst 1 adds an explicit offline journal. It reads verified canonical mission
histories and retains their evidence in a separate directory. It does not run
stages, call market providers, start inference, submit orders, change existing
decision policies, activate capital allocation, or update the Cabin. No new
dependencies are required.

BlackPod is one operation with two independently governed desks: `TRADING`
(short-horizon trading and position management) and `INVESTMENT` (long-horizon
investing and portfolio management). `CAPITAL_ALLOCATION` is separate oversight
of desk capital budgets/transfers under consolidated account risk. It is not a
third trading desk. `UNCLASSIFIED` is an explicit historical-import state; the
journal never infers a desk from a ticker, native component name, or approval.

See [the implementation validation record](DECISION_JOURNAL_VALIDATION.md) for
changed files, exact executed commands, test results and archived-history coverage.

## Contracts and authority

The next implemented burst adds `blackpod.investment_hypothesis.v1` and journal
event v2 for source-bound shadow research drafts. Existing v1 meanings and
serialized records remain unchanged. See
[the hypothesis commands and semantics](INVESTMENT_HYPOTHESES.md).
Journal event v3 then adds [linked challenge and outcome review](INVESTMENT_REVIEW.md)
without changing v1/v2 records or granting decision/execution authority.

Strict versioned contracts live in `contracts/decision_journal.py`:

| Contract | Purpose |
| --- | --- |
| `blackpod.decision_journal_event.v1` | Immutable mission, evaluation, or policy event |
| `blackpod.decision_journal_evaluation.v1` | Explicit externally supplied evaluation linked to a decision |
| `blackpod.capital_policy_proposal.v1` | Inactive initial capital split |
| `blackpod.decision_journal_entry.v1` | Storage envelope with sequence and predecessor/event hashes |

Factories reject unknown/missing fields, duplicate JSON keys, non-finite numbers,
ambiguous paths, unsupported enums/versions, and incorrect nested types. Values
are held as immutable canonical bytes; exposed mappings are defensive copies.

Forecasts, recommendations, authorizations, and executable orders remain distinct.
Mission events summarize native dispositions and operator approval scope; their
retained source artifacts remain authoritative for detailed forecasts,
recommendations, model/agent provenance, warnings, and evidence timestamps.
The journal does not manufacture forecast objects or orders from narrative text.

`PROCEED` means eligible for operator review. `SHADOW_APPROVED` authorizes only
`NAVIGATOR_SHADOW_HANDOFF`. A validated plan records `SHADOW_ONLY`; all other
current mission revisions record `NOT_EXECUTED`. Neither permits realized trade
P&L, including a misleading value of zero. A trade evaluation is rejected for
both states. A supplied counterfactual evaluation can state its method in the
conclusion but cannot report realized trade P&L.

Historical hypotheses, expectations, investment horizons, confidence
probabilities, and evaluations are recorded as `NOT_RECORDED`, even where native
artifacts contain rule-derived confidence or qualitative descriptions. Later
evaluations append separate events; the original historical record stays intact.
An evaluation's immutable chain position binds the imported mission context used
at first append. A retry preserves that context even after later mission growth.

Known-domain imports require `--domain` and a nonblank
`--classification-reason`. This records an importer's classification, not original
desk authority. A decision cannot be relabeled on retry. There is no reclassification
or policy activation command in this burst.

## Storage and recovery

```text
<journal-root>/
  .journal.lock
  entries/00000001.json
  entries/00000002.json
  evidence/<full-sha256>
  staging/.publish-<random-id>.tmp  # only possible after interruption
```

Each verified mission revision produces one event. The decision ID derives from
mission ID, request ID, and LIVE/REPLAY mode. The event ID derives from decision
ID, event type, and source revision (or explicit evaluation ID). Source location
and export wall-clock time are excluded so moving unchanged evidence does not
change identity. Identical retry is a no-op; the same logical identity with
different content is a conflict. Domain and classification reason participate
in content and therefore cannot change under an existing identity.

Mission `recorded_at` preserves the source revision's `observed_at`; it is not
the time the offline export ran. Other native evidence timestamps are retained
verbatim. The journal makes no claim that acquisition time is provider event
time, that stage timestamps are chronological, or that a historical artifact
represents present market conditions.

The source loader validates strict mission contracts, request correlation,
every revision and predecessor hash, current-head equality, artifact hashes/sizes,
and artifact/provenance continuity. Stable before/after captures detect source
changes. Only declared artifacts, request bytes, and immutable revision snapshots
are copied. The mutable `mission_snapshot.json` pointer is checked but not stored
as an immutable event reference. Supplemental unreferenced artifacts are excluded.

Retained evidence is addressed by SHA-256 and preserves original mission bytes.
Evaluation and capital-policy submissions are validated and retained in normalized
canonical JSON. Journal verification works after the source tree becomes
unavailable. It verifies all retained blobs, the entry chain, identities,
source projections, contiguous imported revisions, and evaluation linkage.

Writes use a single-writer advisory lock, anchored no-follow directory access,
fsynced temporary files, and exclusive immutable publication. Symlink traversal,
external hardlinks, unexpected files, missing evidence, and overwritten/conflicting
entries fail closed. Committed files are read-only; this is an accident-prevention
measure, not protection against a privileged actor.

Evidence is published before its referencing entry. A crash before entry
publication can leave verified orphan evidence; retry reuses it. A crash after
entry publication is recognized as an identical retry. Recognized staging files
are verified and cleaned only during a subsequent append under the writer lock.
`verify` is read-only and reports orphan counts. There is no mutable head/index
and no automatic repair of corrupt committed evidence or chain gaps. Fix the
storage fault, preserve the damaged tree for review, and restore a trusted backup
when committed history fails verification. Do not delete a conflicting event to
make a retry pass.

Retain the entire journal tree together, including referenced evidence. Export it
to separately controlled backup storage and test verification after restoration.
No retention/deletion service or off-host anchor is introduced. Hashes detect
damage against a trusted root; a full privileged rewrite of the chain is outside
this local-store guarantee. The implementation is for local POSIX filesystems
with advisory locking, fsync and hardlink publication; network filesystems and
Windows are not validated deployment targets.

## Runnable offline example

Run from the checkout with the existing environment. The committed source is an
initialized REPLAY fixture; no stage is run. The example journal is outside all
source mission roots. Re-running the same commands is idempotent.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/decision_journal/missions/mission-journal-example \
  --journal-root output/decision-journal-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/decision-journal-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal propose-capital-policy \
  --journal-root output/decision-journal-example \
  --proposal examples/capital_policy.proposed.v1.json
```

The export output includes `decision_id`. To append an evaluation, this example
reads that identity from the verified journal and creates a separate supplied
evaluation file. It does not modify the source mission or a journal entry.

```sh
.venv/bin/python3.11 - <<'PY'
from pathlib import Path
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes
event = next(e for e in JournalStore(Path('output/decision-journal-example')).events()
             if e.event_type == 'MISSION_SNAPSHOT_RECORDED')
Path('output/decision-journal-evaluation.json').write_bytes(canonical_json_bytes({
    'schema_version': 'blackpod.decision_journal_evaluation.v1',
    'evaluation_id': 'offline-process-review-001',
    'decision_id': event.decision_id,
    'recorded_at': '2026-10-12T00:00:00Z',
    'evaluator': 'offline-example-reviewer',
    'evaluation_type': 'PROCESS',
    'conclusion': 'Initialized fixture has no Governor disposition or execution authorization.',
    'outcome_status': 'OBSERVED',
    'realized_trade_pnl': None,
}))
PY

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal append-evaluation \
  --journal-root output/decision-journal-example \
  --evaluation output/decision-journal-evaluation.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/decision-journal-example
```

The standalone equivalent is
`python -m blackpod_build_week.decision_journal_cli <command> ...`.
All commands emit JSON on success and return 0. Validation, conflict, integrity,
or persistence failures print an error to stderr and return 2. Argument errors
also return 2. An export can commit a verified prefix before an I/O interruption;
retry the same request to continue, rather than changing identities or deleting
the prefix. Verification never creates a missing journal.

## Initial capital policy

`examples/capital_policy.proposed.v1.json` specifies:

- TRADING: 50% of account equity; INVESTMENT: 50%.
- Status: `PROPOSED`; allocation basis: `ACCOUNT_EQUITY`.
- `INITIAL_ALLOCATION_ONLY`: no perpetual 50/50 rebalance rule.
- Activation, capital transfers, and automated reallocation: disabled.
- Consolidated account risk and explicit authorization for subsequent changes:
  required.

Recording this proposal does not establish actual desk balances, evaluate account
risk, grant budget authority, or move funds. Later evidence-based adjustments
need a separately implemented and authorized governance process. This burst
rejects an activated proposal, another split, or automatic rebalance semantics.

## Offline tests and limits

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_decision_journal*.py' -v
```

Tests cover strict contracts, canonical fixture projection, native SHADOW scope,
non-execution/P&L rules, deterministic retry and conflicts, retained evidence,
tampering, path safety, concurrency, interrupted writes and CLI behavior.
CLI tests deny network connections and subprocess producer calls. Archived real
LIVE/REPLAY verification is separate evidence and is not represented as a live
provider, inference, trading or performance test.

This burst does not implement automatic outcome acquisition, capital activation,
order/fill joins, portfolio accounting, investment hypothesis generation, causal
validation, human authentication, journal signatures, or a performance evaluator.
Evaluations are explicit supplied observations and conclusions; journal validation
checks structure and linkage, not economic truth. Source-bound, explicitly
supplied shadow hypotheses and fixed evaluation plans are now implemented in
[Burst 2](INVESTMENT_HYPOTHESES.md). Automatic hypothesis origination and outcome
evaluation remain future work.
