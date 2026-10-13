# Retained native sources for offline shadow analysis

These are byte-exact source snapshots from the existing Galactica checkout.
`shadow_galactica_analysis.py` accepts their explicit SHA-256 fingerprints:

| Snapshot | Original source | Use |
|---|---|---|
| `spyglass.py` | `spyglass.py` | Calls the existing pure `analyze_structure` function on retained daily OHLCV. |
| `brigade_debrief.py` | `scripts/brigade_debrief.py` | Calls the existing `parse_log` function on an explicitly supplied historical transcript. |
| `blackwell_brigade.py` | `agents/blackwell_brigade.py` | Retains the selected producer source fingerprint; never imports or invokes its inference functions. |

The module checks source bytes before loading the first two snapshots in isolated
namespaces. Existing pandas and NumPy are imported lazily. Their versions and the
Python major/minor version are retained and must match for exact replay.

Synthetic test bars and the synthetic Brigade transcript are constructed by
`tests/test_shadow_galactica_analysis.py`. They are not historical predictions,
current Brigade opinions, broker activity, or trading performance.

Spyglass returns heuristic structures computed after the supplied history is
available. Swing detection uses right-hand bars. Its `confirmed` field is not a
forecast probability or proof that an order should be placed. The separate
`blackpod.shadow_spyglass_challenge.v1` recency screen uses the original market
capture time and a fixed 30-calendar-day lookback, retaining all excluded older
facts and their source times. It changes no live strategy policy.

Historical Brigade imports retain original opinions, disagreement, partial rows,
member coverage and date precision. Original model identity and producer-source
relationships remain declared and unverified. Fresh Brigade generation remains
deferred pending governed forecast and inference inputs; the adapter creates no
new opinions. All execution and capital authority remains disabled.
