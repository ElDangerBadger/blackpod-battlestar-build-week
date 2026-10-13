"""Explicit runtime adapter for pinned Galactica Navigator Trickle.

Importing this module is offline. Only ``run_guarded_navigator`` imports native
runtime modules, constructs an Alpaca client, or starts its data stream. The
facade preserves native mandate/entry/exit rules while restricting account-wide
broker operations to an explicitly owned TRADING symbol set.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata as distribution_metadata
import os
import re
import secrets
import sys
import threading
import types
from contextlib import nullcontext
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .contracts.mission_request import parse_rfc3339

NATIVE_SOURCE_FILES = (
    "blackwell_navigator_trickle.py", "execution/__init__.py", "execution/audit.py",
    "execution/bias_contract.py", "execution/broker.py", "execution/config.py", "execution/indicators.py",
    "execution/loggers.py", "execution/mandate_gate.py", "mandate/enforcer.py",
    "setup/setup_manager.py", "setup/bar_aggregator.py",
)
NATIVE_RUNTIME_DEPENDENCIES = {"alpaca-py": "0.42.0", "pandas": "2.3.1"}
_TERMINAL = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})


class TradingAdapterError(ValueError):
    """A required account, ownership, control, or runtime fact is unverified."""


def _get(value: object, field: str, default=None):
    return value.get(field, default) if isinstance(value, Mapping) else getattr(value, field, default)


def _text(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else ""


def _decimal(value: object, field: str, *, positive=False, nonnegative=False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise TradingAdapterError(field + " is not a finite numeric value")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TradingAdapterError(field + " is not a finite numeric value") from exc
    if not number.is_finite() or (positive and number <= 0) or (nonnegative and number < 0):
        raise TradingAdapterError(field + " is outside the required numeric range")
    return number


def _symbols(values: object, field: str, *, nonempty=False) -> frozenset[str]:
    if not isinstance(values, list) or (nonempty and not values):
        raise TradingAdapterError(field + " must be a list")
    if any(not isinstance(item, str) or not item or item != item.strip().upper() or len(item) > 64 for item in values):
        raise TradingAdapterError(field + " requires explicit uppercase symbols")
    if len(set(values)) != len(values):
        raise TradingAdapterError(field + " contains duplicate symbols")
    return frozenset(values)


class GuardedTradingBroker:
    """Alpaca-backed native Broker facade with explicit ownership and entry gates.

    A process-local lock serializes check/submission. The runtime controller must
    enforce a single worker/account. Orders from other processes remain visible
    through broker open-order checks; external concurrent submissions cannot be
    made atomic with this facade. Any pending order blocks risk increases.
    """

    def __init__(self, native_broker, runtime_profile: Mapping[str, Any], switch_reader: Callable[[], object],
                 receipt_callback: Callable[[dict], None] | None = None, *, open_orders_reader=None,
                 now: Callable[[], datetime] | None = None, mandate_checker=None, submission_admission=None,
                 persistent_gate=None, restored_inflight=None):
        self._native = native_broker
        self._profile = dict(runtime_profile)
        self._owned = _symbols(self._profile.get("symbols"), "symbols", nonempty=True)
        self._protected = _symbols(self._profile.get("protected_symbols"), "protected_symbols")
        if self._owned & self._protected:
            raise TradingAdapterError("TRADING and protected INVESTMENT symbols must be disjoint")
        if self._profile.get("account_scope") not in {"DEDICATED_TRADING", "SHARED_DISJOINT"}:
            raise TradingAdapterError("explicit account_scope is required")
        if self._profile["account_scope"] == "DEDICATED_TRADING" and self._protected:
            raise TradingAdapterError("dedicated TRADING account cannot declare protected holdings")
        if self._profile.get("mode") not in {"PAPER", "LIVE"}:
            raise TradingAdapterError("explicit PAPER or LIVE mode is required")
        if not isinstance(self._profile.get("account_id"), str) or not self._profile["account_id"]:
            raise TradingAdapterError("explicit account_id is required")
        if bool(getattr(native_broker, "dry_run", True)) or getattr(native_broker, "client", None) is None:
            raise TradingAdapterError("guard requires an explicitly executable native broker")
        self._budget = _decimal(self._profile.get("trading_budget_usd"), "trading_budget_usd", positive=True)
        self._gross_cap = _decimal(self._profile.get("max_account_gross_usd"), "max_account_gross_usd", positive=True)
        self._order_cap = _decimal(self._profile.get("max_order_notional_usd"), "max_order_notional_usd", positive=True)
        self._price_buffer = _decimal(self._profile.get("price_buffer_fraction"), "price_buffer_fraction", positive=True)
        if self._price_buffer > 1:
            raise TradingAdapterError("price_buffer_fraction must not exceed 1")
        self._price_age = self._profile.get("price_max_age_seconds")
        if type(self._price_age) is not int or self._price_age <= 0:
            raise TradingAdapterError("price_max_age_seconds must be positive integer")
        if not isinstance(self._profile.get("capital_authorization_id"), str) or not self._profile["capital_authorization_id"]:
            raise TradingAdapterError("fixed capital authorization identity is required")
        self._expires = parse_rfc3339(self._profile.get("authorization_expires_at"), "authorization_expires_at")
        self._switch_reader = switch_reader
        self._receipts = receipt_callback
        self._orders_reader = open_orders_reader or native_broker.client.get_orders
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.mandate_checker = mandate_checker
        self._submission_admission = submission_admission or nullcontext
        if not callable(self._submission_admission):
            raise TradingAdapterError("submission_admission must be a context factory")
        self._lock = threading.RLock()
        self._prices: dict[str, tuple[Decimal, datetime]] = {}
        self._inflight: dict[str, dict] = {}
        self._ambiguous = False
        self._ambiguous_symbols = set()
        self._persistent_gate = persistent_gate
        if persistent_gate is not None and not callable(persistent_gate):
            raise TradingAdapterError("persistent_gate must be callable")
        if restored_inflight is not None:
            if not isinstance(restored_inflight, list): raise TradingAdapterError("restored_inflight must be a list")
            for item in restored_inflight:
                if not isinstance(item, Mapping) or set(item) != {"order_id", "symbol", "side", "qty", "prior_qty"}:
                    raise TradingAdapterError("restored inflight observation has missing or unknown fields")
                identity = item["order_id"]
                if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", identity) or identity in self._inflight:
                    raise TradingAdapterError("restored broker order identity is invalid or duplicated")
                self._assert_owned(item["symbol"])
                if item["side"] not in {"buy", "sell", "close"}: raise TradingAdapterError("restored order side is unsupported")
                qty = _decimal(item["qty"], "restored qty", positive=True)
                prior = _decimal(item["prior_qty"], "restored prior_qty")
                if item["side"] == "close" and (prior == 0 or qty > abs(prior)):
                    raise TradingAdapterError("restored close exceeds its recorded position")
                self._inflight[identity] = {"symbol": item["symbol"], "side": item["side"], "qty": qty, "prior_qty": prior}
        self.dry_run = False

    @property
    def session_id(self):
        return getattr(self._native, "session_id", "unknown")

    @session_id.setter
    def session_id(self, value):
        self._native.session_id = value

    @property
    def orders_logger(self):
        return getattr(self._native, "orders_logger", None)

    @orders_logger.setter
    def orders_logger(self, value):
        self._native.orders_logger = value

    def _enabled(self) -> bool:
        try:
            state = self._switch_reader()
            return isinstance(state, Mapping) and state.get("entries_enabled") is True
        except Exception:
            return False

    def _receipt(self, symbol: str, side: str, qty: object, outcome: str, reason: str, order_id=None,
                 *, attempt=None, client_order_id=None):
        if self._receipts is not None:
            self._receipts({"schema_version": "blackpod.trading_execution_receipt.v2",
                            "recorded_at": self._now().isoformat(), "profile_id": self._profile.get("profile_id"),
                            "domain": "TRADING", "account_mode": self._profile["mode"], "symbol": symbol,
                            "side": side, "qty": str(qty), "outcome": outcome, "reason_code": reason,
                            "order_id": order_id, "capital_authorization_id": self._profile["capital_authorization_id"],
                            "account_id": self._profile["account_id"], "attempt_id": attempt["attempt_id"] if attempt else None,
                            "prior_qty": attempt["prior_qty"] if attempt else None, "client_order_id": client_order_id})

    def _mark_ambiguous(self, symbol):
        self._ambiguous = True
        self._ambiguous_symbols.add(symbol)

    def _ambiguous_for(self, symbol):
        return self._ambiguous and (not self._ambiguous_symbols or symbol in self._ambiguous_symbols)

    def _persistent_check(self, symbol, risk_increase):
        if self._persistent_gate is not None:
            try: permitted = self._persistent_gate(symbol, risk_increase)
            except Exception: permitted = False
            if permitted is not True: raise TradingAdapterError("PERSISTENT_EXECUTION_BARRIER")

    def _deny(self, symbol, side, qty, reason):
        self._receipt(symbol, side, qty, "BLOCKED", reason)
        return {"ok": False, "skipped": True, "reason": reason, "order_id": None}

    def _assert_owned(self, symbol):
        if not isinstance(symbol, str) or symbol not in self._owned or symbol in self._protected:
            raise TradingAdapterError("SYMBOL_NOT_OWNED_BY_TRADING")

    def observe_bar(self, symbol: str, close: object, timestamp: object) -> None:
        """Retain a source timestamp; stale/future/malformed bars cannot price entries."""
        self._assert_owned(symbol)
        price = _decimal(close, "bar.close", positive=True)
        if isinstance(timestamp, str):
            stamp = parse_rfc3339(timestamp, "bar.timestamp")
        elif isinstance(timestamp, datetime) and timestamp.tzinfo is not None:
            stamp = timestamp.astimezone(timezone.utc)
        else:
            raise TradingAdapterError("bar timestamp must be timezone aware")
        with self._lock:
            if symbol not in self._prices or stamp >= self._prices[symbol][1]:
                self._prices[symbol] = price, stamp

    def _price(self, symbol):
        if symbol not in self._prices:
            raise TradingAdapterError("CURRENT_PRICE_UNVERIFIED")
        price, stamp = self._prices[symbol]
        age = (self._now() - stamp).total_seconds()
        if age < 0 or age > self._price_age:
            raise TradingAdapterError("CURRENT_PRICE_STALE_OR_FUTURE")
        return price * (1 + self._price_buffer)

    def _account(self):
        account = self._native.client.get_account()
        if str(_get(account, "id", "")) != self._profile["account_id"]:
            raise TradingAdapterError("ACCOUNT_ID_MISMATCH")
        if _text(_get(account, "status")).upper() != "ACTIVE" or _get(account, "trading_blocked") is not False:
            raise TradingAdapterError("ACCOUNT_TRADING_STATUS_UNVERIFIED")
        _decimal(_get(account, "equity"), "account.equity", positive=True)
        _decimal(_get(account, "cash"), "account.cash", nonnegative=True)
        return account

    def _account_identity(self):
        # Even protective reductions must target the explicitly authorized account.
        account = self._native.client.get_account()
        if str(_get(account, "id", "")) != self._profile["account_id"]:
            raise TradingAdapterError("ACCOUNT_ID_MISMATCH")
        if _text(_get(account, "status")).upper() != "ACTIVE" or _get(account, "trading_blocked") is not False:
            raise TradingAdapterError("ACCOUNT_TRADING_STATUS_UNVERIFIED")

    def _positions(self):
        raw = self._native.client.get_all_positions()
        if not isinstance(raw, list):
            raise TradingAdapterError("POSITIONS_UNVERIFIED")
        result = {}
        for position in raw:
            symbol = _get(position, "symbol")
            if not isinstance(symbol, str) or not symbol or symbol != symbol.strip().upper() or symbol in result:
                raise TradingAdapterError("POSITION_SYMBOL_UNVERIFIED")
            qty = _decimal(_get(position, "qty"), "position.qty")
            result[symbol] = (qty, position)
        return result

    def _orders(self):
        raw = self._orders_reader()
        if not isinstance(raw, list) or len(raw) >= 500:
            raise TradingAdapterError("OPEN_ORDERS_INCOMPLETE")
        result = []
        ids = set()
        def add(order):
            identity, symbol = _get(order, "id"), _get(order, "symbol")
            status = _text(_get(order, "status")).lower()
            if identity is None or not isinstance(symbol, str) or not symbol or symbol != symbol.strip().upper() or not status:
                raise TradingAdapterError("OPEN_ORDER_METADATA_UNVERIFIED")
            if status in _TERMINAL:
                raise TradingAdapterError("OPEN_ORDER_QUERY_NOT_OPEN_ONLY")
            if str(identity) in ids:
                raise TradingAdapterError("DUPLICATE_OPEN_ORDER")
            ids.add(str(identity)); result.append(order)
            legs = _get(order, "legs")
            if legs is not None:
                if not isinstance(legs, list): raise TradingAdapterError("OPEN_ORDER_LEGS_UNVERIFIED")
                for leg in legs: add(leg)
        for item in raw: add(item)
        return result

    def _reconcile_inflight(self):
        for identity in list(self._inflight):
            info = self._native.client.get_order_by_id(identity)
            if str(_get(info, "id", "")) != identity:
                raise TradingAdapterError("INFLIGHT_ORDER_ID_MISMATCH")
            status = _text(_get(info, "status")).lower()
            if not status:
                raise TradingAdapterError("INFLIGHT_ORDER_STATUS_UNVERIFIED")
            if status in _TERMINAL:
                if status == "replaced":
                    self._mark_ambiguous(self._inflight[identity]["symbol"])
                    continue
                pending = self._inflight[identity]
                filled = _decimal(_get(info, "filled_qty"), "order.filled_qty", nonnegative=True)
                if filled > pending["qty"] or (status == "filled" and filled != pending["qty"]):
                    raise TradingAdapterError("INFLIGHT_FILLED_QUANTITY_UNVERIFIED")
                before = pending["prior_qty"]
                if pending["side"] == "buy": expected = before + filled
                elif pending["side"] == "sell": expected = before - filled
                else: expected = before - filled if before > 0 else before + filled
                actual = self._positions().get(pending["symbol"], (Decimal(0), None))[0]
                if actual != expected:
                    # Order status and position endpoints can update separately.
                    # Keep the reservation until the recorded fill is reflected.
                    continue
                del self._inflight[identity]

    def account_equity(self):
        # Preserve full account equity semantics; never fabricate a desk budget.
        return float(_decimal(_get(self._account(), "equity"), "account.equity", positive=True))

    def positions(self):
        return {symbol: float(qty) for symbol, (qty, _) in self._positions().items() if symbol in self._owned and qty != 0}

    def position_info(self, symbol):
        self._assert_owned(symbol)
        position = self._positions().get(symbol)
        if position is None: return None
        qty, item = position
        return {"symbol": symbol, "qty": float(qty), "avg_entry_price": float(_decimal(_get(item, "avg_entry_price"), "avg_entry_price", nonnegative=True)),
                "unrealized_plpc": float(_decimal(_get(item, "unrealized_plpc"), "unrealized_plpc"))}

    def order_info(self, order_id=None):
        return self._native.order_info(order_id)

    def minutes_to_close(self):
        return self._native.minutes_to_close()

    def _pending_symbol(self, symbol, orders):
        return any(_get(order, "symbol") == symbol for order in orders) or any(info["symbol"] == symbol for info in self._inflight.values())

    def _increase_gate(self, symbol, side, qty, positions, orders):
        if not self._enabled(): raise TradingAdapterError("AUTO_TRADING_OFF_OR_CONTROL_UNVERIFIED")
        if self._now() >= self._expires: raise TradingAdapterError("CAPITAL_AUTHORIZATION_EXPIRED")
        if self._ambiguous or self._inflight: raise TradingAdapterError("PRIOR_SUBMISSION_NOT_RECONCILED")
        if orders: raise TradingAdapterError("OPEN_ORDERS_BLOCK_INCREASE")
        if side != "buy": raise TradingAdapterError("NEW_SHORTS_DISABLED")
        if positions.get(symbol, (Decimal(0), None))[0] < 0: raise TradingAdapterError("CROSSING_SHORT_POSITION_DISABLED")
        if set(positions) - self._owned - self._protected: raise TradingAdapterError("UNCLASSIFIED_ACCOUNT_POSITIONS")
        if self.mandate_checker is None: raise TradingAdapterError("NATIVE_MANDATE_GATE_NOT_CONNECTED")
        gate = self.mandate_checker(symbol, side)
        if not (_get(gate, "ok") is True and _get(gate, "mandate_ok") is True):
            raise TradingAdapterError("NATIVE_MANDATE_GATE_REJECTED")
        account = self._account()
        trading, consolidated = Decimal(0), Decimal(0)
        for sym, (held, position) in positions.items():
            if held < 0: raise TradingAdapterError("CONSOLIDATED_SHORT_RISK_UNSUPPORTED")
            market_value = _decimal(_get(position, "market_value"), "position.market_value", nonnegative=True)
            current_price = _decimal(_get(position, "current_price"), "position.current_price", positive=True)
            # Prefer the larger supplied valuation; do not reduce existing exposure.
            value = max(market_value, held * current_price)
            consolidated += value
            if sym in self._owned: trading += value
        notional = qty * self._price(symbol)
        if notional > self._order_cap: raise TradingAdapterError("ORDER_NOTIONAL_CAP_EXCEEDED")
        if trading + notional > self._budget: raise TradingAdapterError("TRADING_DOLLAR_BUDGET_EXCEEDED")
        if consolidated + notional > self._gross_cap: raise TradingAdapterError("CONSOLIDATED_GROSS_CAP_EXCEEDED")
        if notional > _decimal(_get(account, "cash"), "account.cash", nonnegative=True):
            raise TradingAdapterError("CASH_RESERVE_INSUFFICIENT")
        # Re-read persisted control at the last practical moment before submission.
        if not self._enabled(): raise TradingAdapterError("AUTO_TRADING_CHANGED_BEFORE_SUBMISSION")

    def _submitted(self, result, symbol, side, qty, prior_qty, attempt):
        identity = result.get("order_id") if isinstance(result, dict) else None
        client_id = result.get("client_order_id") if isinstance(result, dict) else None
        valid_id = lambda value: isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", value) and value != "DRY-RUN"
        identity = identity if valid_id(identity) else None
        client_id = client_id if valid_id(client_id) else None
        if isinstance(result, dict) and result.get("ok") is True and identity is not None:
            self._inflight[identity] = {"symbol": symbol, "side": side, "qty": Decimal(qty), "prior_qty": prior_qty}
            try:
                self._receipt(symbol, side, qty, "SUBMITTED", "NATIVE_ORDER_ACCEPTED", identity,
                              attempt=attempt, client_order_id=client_id)
            except Exception:
                self._mark_ambiguous(symbol)
                self._receipt(symbol, side, qty, "AMBIGUOUS", "RESULT_RECEIPT_PERSISTENCE_UNVERIFIED", identity,
                              attempt=attempt, client_order_id=client_id)
                raise
            return result
        if isinstance(result, dict) and result.get("ok") is False and result.get("skipped") is True:
            self._receipt(symbol, side, qty, "BLOCKED", "NATIVE_PRECHECK_BLOCKED", attempt=attempt)
            return result
        self._mark_ambiguous(symbol)
        self._receipt(symbol, side, qty, "AMBIGUOUS", "BROKER_ACCEPTANCE_UNVERIFIED", identity,
                      attempt=attempt, client_order_id=client_id)
        return {"ok": False, "error": True, "reason": "BROKER_ACCEPTANCE_UNVERIFIED", "order_id": identity}

    def _execute_attempt(self, symbol, side, qty, prior_qty, admission_reason, mutation):
        attempt = {"attempt_id": "attempt-" + secrets.token_hex(16), "prior_qty": str(prior_qty)}
        # The complete original intent is durable before any broker mutation.
        # Audit failures propagate and cannot fall through to submission.
        self._receipt(symbol, side, qty, "ATTEMPT", admission_reason, attempt=attempt)
        try:
            result = mutation()
        except Exception:
            self._mark_ambiguous(symbol)
            self._receipt(symbol, side, qty, "AMBIGUOUS", "SUBMISSION_EXCEPTION_REQUIRES_RECONCILIATION", attempt=attempt)
            return {"ok": False, "error": True, "reason": "SUBMISSION_EXCEPTION_REQUIRES_RECONCILIATION", "order_id": None}
        return self._submitted(result, symbol, side, qty, prior_qty, attempt)

    def submit_market(self, symbol, side, qty, tif="day", *, reason="-"):
        with self._lock, self._submission_admission():
            try:
                self._assert_owned(symbol)
                if side not in {"buy", "sell"} or type(qty) is not int or qty <= 0 or tif != "day":
                    raise TradingAdapterError("UNSUPPORTED_ORDER_PARAMETERS")
                self._enabled()  # Every order observes the persistent switch.
                self._account_identity()
                self._reconcile_inflight()
                positions, orders = self._positions(), self._orders()
                held = positions.get(symbol, (Decimal(0), None))[0]
                reduction = (held > 0 and side == "sell" and qty <= held) or (held < 0 and side == "buy" and qty <= -held)
                if self._ambiguous_for(symbol) or self._pending_symbol(symbol, orders):
                    raise TradingAdapterError("SYMBOL_ORDER_ALREADY_PENDING")
                if not reduction: self._increase_gate(symbol, side, Decimal(qty), positions, orders)
                self._persistent_check(symbol, not reduction)
            except TradingAdapterError as exc:
                return self._deny(symbol, side, qty, str(exc))
            except Exception:
                return self._deny(symbol, side, qty, "BROKER_OR_AUDIT_DATA_UNVERIFIED")
            return self._execute_attempt(symbol, side, qty, held, "REDUCTION" if reduction else "RISK_INCREASE",
                lambda: self._native.submit_market(symbol, side, qty, tif=tif, reason=reason))

    def close_position(self, symbol, *, reason="-"):
        with self._lock, self._submission_admission():
            try:
                self._assert_owned(symbol)
                self._enabled()
                self._account_identity()
                self._reconcile_inflight()
                positions, orders = self._positions(), self._orders()
                held = positions.get(symbol, (Decimal(0), None))[0]
                if held == 0: raise TradingAdapterError("NO_OWNED_POSITION_TO_CLOSE")
                if self._ambiguous_for(symbol) or self._pending_symbol(symbol, orders):
                    raise TradingAdapterError("SYMBOL_ORDER_ALREADY_PENDING")
                self._persistent_check(symbol, False)
            except TradingAdapterError as exc: return self._deny(symbol, "close", "-", str(exc))
            except Exception: return self._deny(symbol, "close", "-", "BROKER_OR_AUDIT_DATA_UNVERIFIED")
            return self._execute_attempt(symbol, "close", abs(held), held, "OWNED_REDUCTION",
                lambda: self._native.close_position(symbol, reason=reason))

    def flatten_all(self):
        # Never delegate native close_all_positions(cancel_orders=True).
        return {symbol: self.close_position(symbol, reason="owned_trading_flatten") for symbol in sorted(self.positions())}

    def safe_to_stop(self):
        with self._lock:
            try:
                self._reconcile_inflight()
                orders = self._orders()
                owned_pending = any(_get(order, "symbol") in self._owned for order in orders)
                return not self._ambiguous and not self.positions() and not owned_pending and not self._inflight
            except Exception:
                return False


def validate_runtime_environment(profile: Mapping[str, Any]) -> None:
    """Require environment-only credentials and exact declared paper/live mode."""
    for key in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        value = os.environ.get(key)
        if not isinstance(value, str) or not value.strip():
            raise TradingAdapterError("runtime requires environment Alpaca credentials")
    expected = "true" if profile.get("mode") == "PAPER" else "false" if profile.get("mode") == "LIVE" else None
    if expected is None or os.environ.get("ALPACA_PAPER") != expected:
        raise TradingAdapterError("ALPACA_PAPER must explicitly match declared profile mode (true/false)")


def validate_runtime_dependencies() -> None:
    """Inspect installed distribution metadata without importing its code."""
    for package, expected in NATIVE_RUNTIME_DEPENDENCIES.items():
        try:
            installed = distribution_metadata.version(package)
        except distribution_metadata.PackageNotFoundError:
            raise TradingAdapterError("runtime dependency is unavailable: " + package) from None
        if installed != expected:
            raise TradingAdapterError("runtime dependency pin mismatch: " + package)


async def run_guarded_navigator(runtime_profile: Mapping[str, Any], switch_reader: Callable[[], object], receipt_callback=None,
                                *, submission_admission=None, persistent_gate=None, restored_inflight=None):
    """Explicit executable integration. Supervisor verifies pins and ON confirmation.

    The optional native YAML credential loader is never called. Frozen input paths
    are supplied directly. Call only from the isolated supervised worker process.
    """
    if runtime_profile.get("mode") != "PAPER":
        raise TradingAdapterError("funded activation requires a separately governed execution path")
    initial = switch_reader()
    if not isinstance(initial, Mapping) or initial.get("entries_enabled") is not True:
        raise TradingAdapterError("explicit verified runtime ON is required before native import")
    validate_runtime_environment(runtime_profile)
    from .auto_trading_runtime import validate_profile
    runtime_profile = validate_profile(dict(runtime_profile))
    validate_runtime_dependencies()
    if not os.path.samefile(runtime_profile["python_executable"], sys.executable):
        raise TradingAdapterError("runtime interpreter does not match the validated profile")
    root = Path(runtime_profile["galactica_root"]).resolve(strict=True)
    for prefix in ("execution", "setup", "mandate", "blackwell_navigator_trickle"):
        for name, module in tuple(sys.modules.items()):
            if name == prefix or name.startswith(prefix + "."):
                origin = getattr(module, "__file__", None)
                if origin is None or not Path(origin).resolve().is_relative_to(root):
                    raise TradingAdapterError("native runtime import namespace is already occupied")
    sys.path.insert(0, str(root))
    # Pin namespace packages before Python can choose an installed regular
    # package named setup/mandate instead of Galactica's namespace directories.
    for package in ("setup", "mandate"):
        if package in sys.modules: continue
        directory = root / package
        initializer = directory / "__init__.py"
        if initializer.exists():
            spec = importlib.util.spec_from_file_location(package, initializer, submodule_search_locations=[str(directory)])
            if spec is None or spec.loader is None: raise TradingAdapterError("native package cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[package] = module
            spec.loader.exec_module(module)
        else:
            module = types.ModuleType(package)
            module.__path__ = [str(directory)]
            module.__package__ = package
            sys.modules[package] = module
    native = importlib.import_module("blackwell_navigator_trickle")
    configuration = importlib.import_module("execution.config")
    for relative in NATIVE_SOURCE_FILES:
        name = relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        module = sys.modules.get(name)
        if module is None:
            raise TradingAdapterError("native runtime import closure is incomplete")
        origin = getattr(module, "__file__", None)
        if origin is None or Path(origin).resolve() != root / relative:
            raise TradingAdapterError("native runtime import origin mismatch")
    requests = importlib.import_module("alpaca.trading.requests")
    enums = importlib.import_module("alpaca.trading.enums")
    settings = dict(runtime_profile["native_settings"])
    forbidden = {"key_id", "secret_key", "symbols", "bias_csv", "mandate_path", "dry_run", "paper", "startup_plan", "recruits_yaml", "max_recruits", "senate_overwrite"}
    if forbidden & set(settings): raise TradingAdapterError("native_settings contains a reserved override")
    cfg = configuration.ExecutionConfig(
        symbols=list(runtime_profile["symbols"]), bias_csv=Path(runtime_profile["frozen_inputs"]["bias_csv"]["path"]),
        mandate_path=Path(runtime_profile["frozen_inputs"]["mandate_path"]["path"]),
        key_id=os.environ["APCA_API_KEY_ID"], secret_key=os.environ["APCA_API_SECRET_KEY"],
        paper=runtime_profile["mode"] == "PAPER", dry_run=False, startup_plan=False,
        recruits_yaml=None, max_recruits=0, senate_overwrite=False, **settings,
    )
    native_broker_class = native.Broker
    guardian = None
    def build_broker(config):
        nonlocal guardian
        if config.paper != (runtime_profile["mode"] == "PAPER") or config.dry_run:
            raise TradingAdapterError("native account mode mismatch")
        broker = native_broker_class(config)
        query = requests.GetOrdersRequest(status=enums.QueryOrderStatus.OPEN, limit=500, nested=True)
        guardian = GuardedTradingBroker(broker, runtime_profile, switch_reader, receipt_callback,
                                       open_orders_reader=lambda: broker.client.get_orders(filter=query),
                                       submission_admission=submission_admission, persistent_gate=persistent_gate,
                                       restored_inflight=restored_inflight)
        return guardian
    native.Broker = build_broker
    try: nav = native.NavigatorTrickle(cfg)
    finally: native.Broker = native_broker_class
    assert guardian is not None
    guardian.mandate_checker = lambda symbol, side: nav.mandate_gate.check_entry(symbol, side, nav.trade_counts)
    nav.mandate_gate.refresh()
    guardian._account()
    guardian._orders()
    if receipt_callback is not None:
        receipt_callback({"state": "RUNNING", "kind": "WORKER_STATUS"})
    original_on_bar = nav.on_bar
    async def guarded_bar(bar):
        try: guardian.observe_bar(_get(bar, "symbol"), _get(bar, "close"), _get(bar, "timestamp"))
        except Exception:
            # Native protective exits may continue; the missing price blocks entries.
            with guardian._lock:
                guardian._prices.pop(_get(bar, "symbol"), None)
        await original_on_bar(bar)
    nav.on_bar = guarded_bar
    loop = asyncio.get_running_loop()
    # Native handler would stop a worker with unprotected positions. Only permit
    # interruption after broker-confirmed flatness; switch OFF retains exits.
    def request_safe_stop():
        if guardian.safe_to_stop():
            nav._stop.set()
            if nav.stream is not None: nav.stream.stop()
    import signal
    for signum in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(signum, request_safe_stop)
        except NotImplementedError: pass
    async def control_watchdog():
        draining = False
        while not nav._stop.is_set():
            enabled = guardian._enabled()
            if not enabled:
                if guardian.safe_to_stop():
                    request_safe_stop(); return
                if not draining and receipt_callback is not None:
                    receipt_callback({"state": "DRAINING", "kind": "WORKER_STATUS"})
                draining = True
            else:
                draining = False
            await asyncio.sleep(1)
    watcher = asyncio.create_task(control_watchdog())
    try:
        await nav.run()
    finally:
        watcher.cancel()
        try: await watcher
        except asyncio.CancelledError: pass
    if not guardian.safe_to_stop():
        raise TradingAdapterError("RUNTIME_STOPPED_WITH_UNRESOLVED_OWNED_RISK")
    return {"status": "STOPPED", "domain": "TRADING", "owned_positions_flat": True}
