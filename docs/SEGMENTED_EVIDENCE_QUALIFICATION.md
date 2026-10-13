# Qualification of segmented TRAIN evidence

This checkpoint connects separately governed collection and qualification. A
versioned consumer binds an exact frozen v18 qualification policy to an exact
v19 TRAIN capture plan and export. It does not change the old policy, make the
old v18 input format compatible, rewrite a deferred result or acquire authority
to trade. Auto-trading remains OFF.

The original hypotheses, prices, session indices, partitions, risk declarations
and uncertainty protocol remain intact. No Galactica trading rules, new agents,
dependencies, model changes, inference, execution, budget activation or capital
transfers are introduced.

## Inspected starting point and boundaries

The inspected starting checkpoint was `9fa244a`, with a clean working tree.
Existing implementations and fixtures were read before new files were created.

| Existing component | Verified capability | Preserved limitation |
| --- | --- | --- |
| Frozen trading hypotheses and original v2 research plans | Exact catalog/hypothesis/data identity and chronological TRAIN/VALIDATION/TEST/holdout ranges. | Specifications are unproven and retrospective availability remains assumed. |
| v18 qualification policy and result | Native continuity, reviewed simulation risk, separate cost/capacity assumptions, joint window/sample checks and a frozen future uncertainty design. | Its original single-chain input contract is pinned; existing results cannot be upgraded by editing it. |
| v19 TRAIN capture/export | Bounded returned-session opening windows, immutable raw/receipt/checkpoint retention, pure source replay, explicit full/partial/empty coverage. | Its `consumer_v18=INCOMPATIBLE_SEGMENTED_INPUT` marker remains unchanged. Retrieval success does not establish economic support or independent action coverage. |
| Decision Journal | Typed immutable source records, historical-prefix replay, conflicts, exact retries and recovery. | New bindings and qualifications need additive records rather than a parallel decision history. |

The new binding identifies both original source event IDs. The request selects
that binding and one exact aggregate-export event, with an explicit recording
clock and data cutoff. Source ownership, hypothesis revision, dataset, universe,
folds and declared TRAIN scope must match; a generic current profile or arbitrary
latest export cannot substitute for the registered evidence.

New contracts are `blackpod.segmented_evidence_qualification_binding.v1`,
`blackpod.segmented_evidence_qualification_request.v1` and
`blackpod.segmented_evidence_qualification.v1`, in
`contracts/segmented_evidence_qualification.py`. The pure consumer is
`segmented_evidence_qualification.py`; `segmented_evidence_qualification_journal.py`
adds binding and assessment replay through journal v20.

| Record fields | Meaning |
| --- | --- |
| Binding policy/capture-plan event IDs | Exact earlier immutable input/governance sources. |
| `calibration_source` | Fixed `VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY`; no ambiguous fallback to old quote chains. |
| Request binding/aggregate-export event IDs | Exact selected binding and already verified source export. |
| Recording clock and data cutoff | Explicit chronology for the new qualification; no implicit current/latest evidence selection. |
| Result reasons, continuity, calibration and risk | Replayed evidence/design findings and joint sample checks, separate from strategy returns. |
| Result provenance | Native source links, hashes, preserved old-marker status, ignored old input chains and separate coverage/authentication limitations. |
| Supersession links and disabled authority | New append-only revisions, with no execution or policy-changing permission. |

## Collection and qualification remain separate

Collection can succeed while qualification remains deferred. The v19 plan
freezes scope before its GETs. The new binding freezes the selected input method
and governance before this qualification; it can follow collection and is
explicitly retrospective. Neither freeze establishes blind historical
preregistration or historical point-in-time publication evidence.

The qualified consumer reads verified per-fold segmented extrema and coverage
from the selected v19 export. It does not concatenate independent pagination
chains into a fabricated old v18 request. The old policy's training chains and
old results remain visible; the new method explicitly records which input method
it uses and which original inputs it leaves unchanged.

New qualification events link their source events and methodology, retaining
compact source references. The existing segment events already retain raw quote
bodies and receipts. The consumer does not create a second raw corpus or select
favorable observations from it.

## Required evidence and design gates

Full admitted quote coverage is required for every originally planned TRAIN
symbol/session pair in each selected fold. A partial export or a terminal-empty
HTTP 200 chain retains its missing pairs and remains insufficient. Missing
profiles are not imputed from another fold, a later session or a different feed.

Observed spread extrema retain their native values. Slippage, proportional and
per-fill fees, daily-volume participation and simulation sizing come from
separately retained, exact policy assumptions/review. They are not estimated from
positive returns or invented when absent. Native quote-size units are not
converted into guaranteed executable depth.

The new consumer preserves the policy's native action continuity evidence and
review. It cannot infer independent effective-date coverage from quote
completeness. A separately supplied export coverage review must match the
original source scope and continuity context. Source/reviewer labels remain
unauthenticated declarations. That export packet remains separately recorded;
`export_continuity_packet_applied_to_native_windows` stays false. It cannot
upgrade inherited native continuity windows. Clearing missing native coverage
requires new native intake and qualification-policy records, with their own
retained independent support. Missing coverage remains unresolved.

The same pre-signal feature, entry, holding/exit and matched-control boundary
masks apply. Qualified sampling is the intersection of comparable continuity,
positive feasible known-close sizing and declared training-capacity proxies.
Minimum samples count distinct jointly eligible source-session dates per fold,
not symbols or raw TEST length. An insufficient sample does not justify lowering
its frozen minimum.

The future uncertainty/stability design remains frozen and unexecuted. This
checkpoint computes no new strategy return, confidence interval, p-value,
statistical significance or economic support. Readiness for a qualified shadow
study design is distinct from support for a trading hypothesis and permission to
execute an order.

## Governed lifecycle and audit

The binding is a strict research-only record. It cannot change the original
qualification policy or capture plan and has all authorization, capital
activation, execution and policy-change flags disabled. Exact references and
source revisions are retained. A later change uses a new linked binding;
historical records remain readable.

Each qualification request selects one binding and aggregate export. Its
result states readiness/deferment, reasons, source identities, cost provenance,
continuity, joint sizing/sample checks and methodological limitations. Corrected
or later assessments append new IDs and explicit supersession links. Identical
retries reconstruct their original prefix and write nothing; changed content
under an existing identity conflicts.

The new journal version replays its typed inputs and selected earlier source
records on read and locked append. Earlier v18 and v19 parsing, calculation
files and source pins are unchanged. A supported collection state cannot silently
override an old gate or promote a strategy. Realized trade P&L remains null for
these unexecuted records.

## Controlled offline cases

The example preserves the original synthetic source history and its native
calculations. New authored quote bodies copy unchanged original quote rows into
per-session TRAIN windows. They are explicitly synthetic and contact no
provider; no real credential source is read.

Cases demonstrate:

- Full segmented coverage and complete declared toy sources can qualify the
  original one-session reversal design within the narrowly declared scope.
- Partial and terminal-empty coverage defer and retain all missing pairs.
- The original three-session continuation design has too few joint dates under
  the same frozen eight-date minimum and defers.
- Inactive proposed policies, missing cost assumptions and missing independent
  continuity evidence remain deferred despite complete quotes.

Both hypotheses remain unchanged. Their different data/design readiness does
not rank profitability, select a winner or establish a generalizable edge.
Toy fees, capacity, reviewer declarations and uncertainty parameters are not
validated choices for real markets.

The authored v19 sources use the original contract's optional operational-audit
packet as `null`: raw native-shaped segment pages are still independently
replayed, while `CAPTURE_OPERATION_AUDIT_NOT_SELECTED` remains explicit. These
fixtures do not claim to have performed real acquisition. Actual runner-backed
exports retain their own snapshot/checkpoint audit and are reported separately.

## Runnable offline commands

The example creates one mixed-version journal with seven cases. It preserves
the original twenty-two v18 fixture events, adds new separately scoped source
records and appends new v20 bindings/assessments. Source prices, hypotheses and
the eight-date uncertainty minimum are unchanged.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_example \
  --output-root output/segmented-evidence-qualification-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli verify \
  --journal-root output/segmented-evidence-qualification-example/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli assess \
  --request output/segmented-evidence-qualification-example/input/full-reversal.request.json \
  --journal-root output/segmented-evidence-qualification-example/journal \
  --output output/segmented-evidence-qualification-example/reports/full-reversal-reassessment.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli record \
  --request output/segmented-evidence-qualification-example/input/full-reversal.request.json \
  --journal-root output/segmented-evidence-qualification-example/journal
```

The final command is an identical record retry and writes no new event. `assess`
writes an immutable report outside the journal; it does not append history.
The manifest identifies exact binding, source export and qualification IDs.

`prepare` accepts exact existing policy/capture-plan event IDs, a new binding ID
and explicit recording clock. It validates compatibility and writes a strict
binding without calculating or appending a qualification. `register --binding`
explicitly appends the immutable method selection. `show --event-id` reads an
exact binding or assessment; `verify` checks the entire mixed-version chain.

These six ordinary consumer commands are offline. Market acquisition remains
the separate explicitly authorized v19 `capture` operation with its frozen
scope and bounds. No consumer command reads API credentials, calls a provider,
starts inference or connects a broker. Invalid references, scope, chronology,
identity, altered evidence or unsafe output reject with exit 2. Successful
qualification or an auditable deferral returns JSON and exit 0.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_segmented_evidence_qualification_example -q
```

The example's exact retry verifies its immutable prefix and avoids republishing
all source events. Its new batch adapter validates the entire remaining suffix
under one writer lock before publishing immutable entries. Commits remain per
event: interruption can leave a valid prefix and unreferenced evidence, rather
than an all-or-nothing transaction. An exact retry appends the remaining suffix
without rewriting that prefix. It cannot erase or replace a different existing
history. The checkpoint validation report lists the actual final results and
remaining real-data gaps.

## Bounded collection and publication adapters

Two explicit opt-in performance adapters support the larger real corpus. The
original pinned capture runner and `JournalStore.append` remain unchanged.

| Explicit flag | Scope and verification |
| --- | --- |
| `train_market_evidence_cli capture --verified-invocation-cache` | Retains a fully verified in-memory view only within one locked invocation. Full replay still occurs at entry/exit; every new response and checkpoint is checked. No persistent validation cache, request-scope or provider-endpoint change. |
| `train_market_evidence_cli export --batched-journal-append` | Replays the full existing journal and validates the complete proposed segment/aggregate suffix before publishing. Each entry/evidence object remains immutable and interruption recovers by exact-prefix retry. |

Both flags default to disabled, preserving the ordinary existing paths. The
batch adapter permits at most 4,096 candidate events and 768 MiB of distinct
supplied evidence per call. Existing 64 MiB object limits, per-segment quote/page
limits, 512 MiB capture limit, 4,096 lifetime requests and bounded invocation
requests remain unchanged. The consumer commands use no collection cache and
acquire no provider authority from either flag.

Measured full-corpus replay also exposed repeated whole-document decoding for
scalar journal attributes. The shared immutable document now derives canonical
bytes for each field from its original frozen document. Attribute reads still
return fresh defensive values; canonical event bytes, validation and schemas
remain unchanged. Legacy objects missing the derived cache reconstruct it from
their original bytes. Pickled state retains only the canonical byte slot;
legacy/interim states rebuild the immutable cache from those bytes. Compatibility
tests cover defensive mutation, serialization and old cached-object recovery.
This performance change grants no authority and does not bypass any source replay.

Full semantic replay remains expensive for the real quote corpus. These adapters
do not introduce a persistent trusted verification cache or a live latency
guarantee; every required native source check remains active. Operational
profiling is a separate prerequisite before connecting this offline path to
live orchestration.

## Real evidence and readiness

The real QQQ/SPY plan retains TRAIN indices 0–227, 228 returned sessions and
456 planned symbol/session pairs. Capture progress must report the actual
completed chains and missing pairs, rather than borrowing the old holdout sample
at index 759. Default per-invocation and lifetime limits remain frozen; explicit
resumption creates new immutable snapshots/exports while old partial records
remain intact.

The checkpoint validation report records the actual collection counts and exact
source/consumer results. Even complete real quote coverage cannot manufacture
independent effective-date support, applicable real fees/slippage, authenticated
human approval or an approved simulation-risk declaration. Those prerequisites
remain separate from data acquisition and software test results.

The completed real export admits all 456 planned QQQ/SPY TRAIN symbol/session
pairs. It retains every native observation, including rows outside its admitted
profile. Observed maximum opening-window spreads remain unclipped and exceed the
existing 1,000-bps cost-component bound. These source findings require independent
review; complete coverage does not make them an applicable execution-cost model.
The validation report records exact counts, maxima, source identities and the
separate consumer outcome.

The next milestone follows the remaining evidence: retain independently justified
coverage and cost/capacity assumptions, review the retained wide-spread source
observations and obtain an explicit review of simulation risk, then evaluate the
frozen uncertainty/stability procedure in a separately
governed shadow study. The final holdout stays withheld and auto-trading stays OFF.
