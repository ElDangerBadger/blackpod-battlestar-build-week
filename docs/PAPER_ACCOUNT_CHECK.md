# Galactica paper account confirmation

## Confirmed source — 2026-10-12

The intended original source is **`/Users/nikolai/buried_treasure/api_keys.yaml`**,
using `alpaca.key_id` and `alpaca.secret_key`. Those values differ from both
previously tested `.env` pairs. The YAML pair successfully authenticated:
account ACTIVE, trading not blocked, zero positions and zero open orders at
capture. All four paper GET requests returned HTTP 200; no orders were submitted.
The earlier 401 responses apply to the different environment-file pairs, not
this working YAML pair. A different project directory was not an API restriction.

The original Galactica Stream resolves that home YAML path, whereas Trickle's
nested config module resolves a different, absent YAML path. No legacy runtime
or credential file was changed. The repeatable checker now supports the exact
`GALACTICA_YAML` format through the existing PyYAML dependency.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.paper_account_probe \
  --credential-source /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML \
  --output-root output/auto-trading-paper-check
```

Successful private evidence is
`output/auto-trading-paper-check/paper-probe-49bff8bc5b531f14779cfb5abbb5015de199e273e6c2150e6dc31e21d4ed8733.json`.
The requested next burst proceeded after this confirmation; see
[paper reconciliation and ownership](TRADING_RECONCILIATION.md). Auto-trading
remains OFF, and account authentication does not authorize execution.

The requested check uses authenticated GET requests only against the fixed
Alpaca paper host. It does not import Galactica, run inference, stream market
data, submit/cancel orders, reset the paper account, change credentials or
activate the trading toggle. No new dependency is required.

## Initial real check

Two existing credential sources were tested on 2026-10-11:

| Source | Credential names | Result |
| --- | --- | --- |
| `/Users/nikolai/BlackPod-Versions/blackpod_galactica/navigator.env` | `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`; `ALPACA_PAPER=true` | GET `/v2/account` returned HTTP 401 |
| `/Users/nikolai/buried_treasure/.env` | `ALPACA_KEY_ID_PAPER`, `ALPACA_SECRET_KEY_PAPER`, `ALPACA_BASE_URL_PAPER` | GET `/v2/account` returned HTTP 401 |

The HTTP response rejected authentication; the reason the credentials are no
longer accepted is unverified. No account, position or order snapshot was
successfully retrieved. Failed authentication does not prove the paper account
does not exist. The initial attempt summary is retained privately under
`output/auto-trading-paper-check/initial-authentication-results.json`.

**Auto-trading stayed OFF; zero orders were submitted.** The user made the next
reconciliation burst conditional on confirmation, so that implementation had
not begun at this initial failed check. The user initially selected refreshing the paper keys in
`/Users/nikolai/buried_treasure/.env` for the next check. Keys should remain in
that local file and must not be pasted into chat or copied into reports.

### Endpoint recheck — 2026-10-12

Verified that the configured base `https://paper-api.alpaca.markets/v2` results
in GET `https://paper-api.alpaca.markets/v2/account`. The checker stores the
origin without `/v2` and concatenates its explicit `/v2/account` path exactly
once; there is no missing or duplicated version segment. Its authentication
headers are `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`.

Fresh GET checks of both existing sources again returned HTTP 401. Only the
account request was made for each source; later book/clock requests did not
run after failed authentication. This verifies the endpoint and the rejected
authentication attempts, not whether the individual key or secret is invalid.
No execution or order was submitted, and confirmation remains pending.

Private recheck evidence:

- `output/auto-trading-paper-check/paper-probe-915d037b5ce0048c67d9a0ee01b719c5d23d94ab6307f8a2f57fc8b8d5f4192b.json`
- `output/auto-trading-paper-check/paper-probe-ca3f0730c3d997749e35807ce42cf3bab184068e29ba68bb18b329b6e8e94163.json`

The exact-URL/GET transport assertion and configured-origin validation tests
were rerun: **2 passed**. No production code or configuration change was needed.

## Repeatable check

After refreshed keys are saved, run:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.paper_account_probe \
  --credential-source /Users/nikolai/buried_treasure/.env \
  --credential-format PAPER_ENV \
  --output-root output/auto-trading-paper-check
```

For Galactica's direct Navigator environment format instead:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.paper_account_probe \
  --credential-source /Users/nikolai/BlackPod-Versions/blackpod_galactica/navigator.env \
  --credential-format NAVIGATOR_ENV \
  --output-root output/auto-trading-paper-check
```

The checker parses the explicitly selected file without sourcing shell code.
It uses credentials only in memory and refuses redirects and funded-account
hosts. It never uses Galactica's broken legacy dotenv helper or changes its
`NAV_DRY_RUN` setting. Confirmation requires a valid active account response,
supported balances, positions, a bounded open-order response, and a clock
response. An optional exact expected account ID can bind a known account.

Successful capture remains sequential and is not an atomic account snapshot.
It does not classify holdings into desks, grant capital authority, prove native
runtime readiness or authorize execution. Private evidence records source
paths, capture times, safe response fields and status; it contains no API keys.
Authentication failure records no fabricated empty portfolio.

## Files and validation

Added `src/blackpod_build_week/paper_account_probe.py` and
`tests/test_paper_account_probe.py`, this runbook, and a link from
`docs/AUTO_TRADING.md`. No trading, ModelDock, mission or database interfaces
were changed. The checker has no execution activation path.

The tests use fake transports and temporary credential fixtures. They cover
fixed-host GET requests, redirect/proxy refusal, literal environment formats,
sanitized authentication failures, incomplete and malformed broker responses,
retained prior account proof after partial failure, expected-account mismatch,
private immutable evidence, unsafe paths, bounded input and capture timestamps.

The two actual network checks were executed with:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 \
  /private/tmp/blackpod-paper-readonly-probe.py
# HTTP 401 from Galactica navigator.env

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 \
  /private/tmp/blackpod-paper-readonly-probe.py --paper-key-source
# HTTP 401 from the documented paper-specific .env
```

The first sandboxed network attempt could not connect; the authenticated
GET checks above ran with the approved network permission. Both selected
files also passed the new checker's local literal-format validation without
network access. No credential values were printed or written to evidence.

Offline test command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_paper_account_probe test_auto_trading_runtime \
  test_galactica_trading_adapter test_trading_automation -q

git diff --check
```

Final result: **102 tests passed in 0.715 seconds** — 20 new probe tests and
82 existing trading-control/adapter regressions. `git diff --check` passed.
These are offline fixture tests, not successful real account authentication.
The selected paper credential file had not changed at the final metadata
check; the real account remained unconfirmed and the next burst remained
conditional on refreshed credentials and successful authentication.

The selected existing interpreter is sufficient for this REST check. The
Galactica executor's separate pinned dependencies, ownership, limits, frozen
inputs and explicit activation confirmation are still required before it can
be started. See [Auto-trading controls](AUTO_TRADING.md).

The later source investigation also located
`/Users/nikolai/BlackPod-Versions/BlackPod_Quorum/venv/bin/python` with installed
alpaca-py 0.42.0 and pandas 2.3.1, matching Galactica's pinned versions. This
metadata check did not start a native executor or broker stream.

The fixed paper endpoint and GET account interface follow Alpaca's
[paper environment documentation](https://docs.alpaca.markets/us/docs/paper-trading)
and [GET Account reference](https://docs.alpaca.markets/us/reference/getaccount-1).

## Next-burst gate

Successful YAML authentication satisfied the user's next-burst condition.
The [reconciliation burst](TRADING_RECONCILIATION.md) now preserves order/fill
identity, partial and cancelled fills, replacement chains, unresolved submission
barriers and append-only links. It never automatically retries an uncertain
broker result. Realized P&L remains null pending attributable closed lots and fees.
