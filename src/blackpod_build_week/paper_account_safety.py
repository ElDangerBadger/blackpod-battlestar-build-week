"""Persistent PAPER desk binding and receipts shared across runtime folders.

This module performs no broker operations. Journal observations never become
capital authority. An installed book only restricts an independently confirmed
execution profile; unreconciled attempts cannot cause automatic resubmission.
"""
from __future__ import annotations
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

from .auto_trading_runtime import RuntimeLedger, TradingRuntimeError, _immutable, account_lock, profile_hash, read_json
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import atomic_write, read_regular


def account_state_root(account_id: str) -> Path:
    digest = sha256_bytes(canonical_json_bytes({"mode": "PAPER", "account_id": account_id}))
    return Path(__file__).resolve().parents[2] / "output" / "auto-trading-account-state" / digest


def export_runtime(root: Path) -> bytes:
    """Read a coherent verified ledger prefix and its immutable profiles."""
    ledger = RuntimeLedger(root)
    if not ledger.root.exists():
        events, profiles = [], {}
    else:
        # Read-only scans do not repair/create lock files.
        events = ledger.events()
        profiles = {}
        for event in events:
            if event["kind"] == "CONTROL" and event["payload"]["entries_enabled"]:
                digest = event["payload"]["profile_sha256"]
                profiles[digest] = read_json(ledger.root / "profiles" / (digest + ".json"))
        if ledger.events() != events:
            raise TradingRuntimeError("runtime changed during export; retry read")
    return canonical_json_bytes({"schema_version": "blackpod.runtime_export.v1", "events": events, "profiles": profiles})


def _event(events, event_id, event_type):
    event = next((event for event in events if event.event_id == event_id and event.event_type == event_type), None)
    if event is None:
        raise TradingRuntimeError("unknown verified journal binding")
    return event


def install_paper_book(journal_root, ownership_event_id, reconciliation_event_id=None, *, confirm_account_id):
    store = JournalStore(journal_root)
    events, _ = store.verified_contents()
    ownership = _event(events, ownership_event_id, "TRADING_DESK_OWNERSHIP_RECORDED")
    book = ownership.payload["ownership"]
    if book["mode"] != "PAPER" or book["account_id"] != confirm_account_id:
        raise TradingRuntimeError("paper book confirmation does not match account")
    related = [event for event in events if event.event_type == ownership.event_type
               and event.payload["ownership"]["account_id"] == confirm_account_id]
    if related[-1].event_id != ownership.event_id:
        raise TradingRuntimeError("cannot install superseded ownership")
    reconciliation = None
    if reconciliation_event_id:
        reconciliation = _event(events, reconciliation_event_id, "TRADING_EXECUTION_RECONCILED")
        packet = reconciliation.payload["reconciliation"]
        if packet["account_id"] != confirm_account_id or packet["ownership_event_id"] != ownership_event_id:
            raise TradingRuntimeError("reconciliation belongs to a different account or book")
    root = account_state_root(confirm_account_id)
    check_separate_root(root, store.root)
    ledger = RuntimeLedger(root)
    binding = {"schema_version": "blackpod.paper_book_binding.v1", "mode": "PAPER",
        "account_id": confirm_account_id, "journal_root": str(store.root),
        "ownership_event_id": ownership.event_id, "ownership_event_sha256": sha256_bytes(ownership.to_bytes()),
        "reconciliation_event_id": reconciliation.event_id if reconciliation else None,
        "reconciliation_event_sha256": sha256_bytes(reconciliation.to_bytes()) if reconciliation else None,
        "execution_authorized": False, "capital_policy_activated": False}
    with ledger.lock("book.lock"):
        path = root / "book.json"
        previous = read_json(path) if path.exists() else None
        if previous == binding:
            return {"written": False, "account_id": confirm_account_id, "execution_authorized": False}
        if previous is not None:
            prior = _event(events, previous["ownership_event_id"], ownership.event_type)
            if sha256_bytes(prior.to_bytes()) != previous["ownership_event_sha256"]:
                raise TradingRuntimeError("book replacement lost immutable ownership lineage")
            if (previous["ownership_event_id"] != ownership_event_id
                    and book["supersedes_event_id"] != previous["ownership_event_id"]):
                raise TradingRuntimeError("book change requires linked ownership supersession")
        changing_scope = previous is None or previous["ownership_event_id"] != ownership_event_id
        # A reconciliation refresh of the same scope may occur while exits run.
        # A scope change requires the independently held account worker lock.
        admission = account_lock({"mode": "PAPER", "account_id": confirm_account_id}) if changing_scope else nullcontext()
        with admission:
            _immutable(root / "book_bindings" / (sha256_bytes(canonical_json_bytes(binding)) + ".json"), canonical_json_bytes(binding))
            atomic_write(path, canonical_json_bytes(binding))
    return {"written": True, "account_id": confirm_account_id, "execution_authorized": False,
            "capital_policy_activated": False}


class PaperSessionSafety:
    """Shared durable admission ledger; no inference, submissions or retries."""
    def __init__(self, profile: dict, control: dict):
        if profile["mode"] != "PAPER":
            raise TradingRuntimeError("paper safety cannot bind a funded profile")
        self.profile, self.session_id = profile, control["session_id"]
        if set(profile["symbols"]) & set(profile["protected_symbols"]):
            raise TradingRuntimeError("paper desk scopes overlap")
        self.ledger = RuntimeLedger(account_state_root(profile["account_id"]))
        self._book()  # Missing/changed declaration fails before native imports.
        digest = profile_hash(profile)
        with self.ledger.lock("account-registration.lock"):
            self.ledger.recover()
            _immutable(self.ledger.root / "profiles" / (digest + ".json"), canonical_json_bytes(profile))
            action_id = "account-" + sha256_bytes(canonical_json_bytes({"session_id": self.session_id, "profile": digest}))
            if not any(event["kind"] == "CONTROL" and event["payload"]["action_id"] == action_id for event in self.ledger.events()):
                self.ledger.append("CONTROL", {**control, "action_id": action_id})

    def _book(self, *, allow_superseded=False):
        binding = read_json(self.ledger.root / "book.json")
        if (binding.get("schema_version") != "blackpod.paper_book_binding.v1"
                or binding.get("mode") != "PAPER" or binding.get("account_id") != self.profile["account_id"]
                or binding.get("execution_authorized") is not False or binding.get("capital_policy_activated") is not False):
            raise TradingRuntimeError("paper ownership binding is invalid")
        store = JournalStore(Path(binding["journal_root"]))
        events, blobs = store.verified_contents()
        ownership = _event(events, binding["ownership_event_id"], "TRADING_DESK_OWNERSHIP_RECORDED")
        if sha256_bytes(ownership.to_bytes()) != binding["ownership_event_sha256"]:
            raise TradingRuntimeError("installed paper ownership hash changed")
        related = [event for event in events if event.event_type == ownership.event_type
                   and event.payload["ownership"]["account_id"] == self.profile["account_id"]]
        if related[-1].event_id != ownership.event_id and not allow_superseded:
            raise TradingRuntimeError("installed paper ownership is superseded")
        value = ownership.payload["ownership"]
        if (set(self.profile["symbols"]) != set(value["desks"]["TRADING"])
                or set(value["desks"]["INVESTMENT"]) != set(self.profile["protected_symbols"])):
            raise TradingRuntimeError("profile does not respect declared desk ownership")
        return binding, events, blobs

    def _resolved_receipts(self, binding, events, blobs):
        if not binding.get("reconciliation_event_id"):
            return set()
        event = _event(events, binding["reconciliation_event_id"], "TRADING_EXECUTION_RECONCILED")
        if sha256_bytes(event.to_bytes()) != binding["reconciliation_event_sha256"]:
            raise TradingRuntimeError("installed reconciliation hash changed")
        value = event.payload["reconciliation"]
        if (value["account_id"] != self.profile["account_id"] or value["ownership_event_id"] != binding["ownership_event_id"]):
            raise TradingRuntimeError("installed reconciliation does not match paper book")
        if event.payload["result"]["restart_barrier"]["entries_blocked"]:
            return set()
        reference = value["runtime_evidence"]
        if reference is None:
            return set()
        from .trading_reconciliation import parse_runtime_capture
        capture = parse_runtime_capture(blobs[reference["sha256"]])
        retained = capture["events"]
        current = self.ledger.events()
        if len(retained) > len(current) or retained != current[:len(retained)]:
            raise TradingRuntimeError("reconciliation is not a prefix of this account ledger")
        return {item["event_sha256"] for item in retained if item["kind"] == "BROKER_GUARD"}

    def state(self, *, allow_superseded=False):
        binding, events, blobs = self._book(allow_superseded=allow_superseded)
        resolved = self._resolved_receipts(binding, events, blobs)
        from .trading_reconciliation import durable_restart_barrier
        capture = read_json_capture(export_runtime(self.ledger.root))
        # Keep controls/profiles and discard only already reconciled guard facts;
        # the pure parser needs the intact hash chain, so use full attempt results
        # and compare each attempt's exact original event hash below.
        result = durable_restart_barrier(capture, account_id=self.profile["account_id"])
        symbols = {item["event_sha256"]: item["payload"].get("symbol") for item in capture["events"]
                   if item["kind"] == "BROKER_GUARD"}
        unresolved = [{**item, "symbol": symbols.get(item["attempt_sha256"])}
                      for item in result["unresolved_attempts"] if item["attempt_sha256"] not in resolved]
        return {"entries_blocked": bool(unresolved), "unresolved_attempts": unresolved,
                "automatic_resubmission_enabled": False}

    def permit_mutation(self, symbol: str, risk_increase: bool) -> bool:
        try:
            if not risk_increase:
                # Passive declarations cannot remove an active worker's exits.
                # Scope changes become operational only when installed while
                # the account worker lock is free, after the verified handoff.
                binding, events, _ = self._book(allow_superseded=True)
                installed = _event(events, binding["ownership_event_id"], "TRADING_DESK_OWNERSHIP_RECORDED")
                if symbol not in installed.payload["ownership"]["desks"]["TRADING"]:
                    return False
            state = self.state(allow_superseded=not risk_increase)
            if risk_increase:
                return not state["entries_blocked"]
            # Known accepted IDs are restored and checked by the native facade.
            # Unknown acceptance on this symbol must never cause a duplicate exit.
            return not any(item.get("order_id") is None and item.get("symbol", symbol) == symbol
                           for item in state["unresolved_attempts"])
        except (ValueError, OSError, KeyError, TypeError, JournalStoreError):
            return False

    def record_receipt(self, payload: dict):
        self.ledger.append("BROKER_GUARD", payload)

    def restored_inflight(self):
        binding, events, blobs = self._book()
        resolved = self._resolved_receipts(binding, events, blobs)
        attempts, results = {}, {}
        for event in self.ledger.events():
            if event["kind"] != "BROKER_GUARD":
                continue
            payload = event["payload"]
            if payload.get("schema_version") != "blackpod.trading_execution_receipt.v2":
                continue
            if payload["outcome"] == "ATTEMPT":
                if event["event_sha256"] not in resolved:
                    attempts[payload["attempt_id"]] = payload
            elif payload["outcome"] in {"SUBMITTED", "AMBIGUOUS"} and payload.get("order_id"):
                original = attempts.get(payload["attempt_id"])
                if original:
                    results[payload["order_id"]] = {"order_id": payload["order_id"], "symbol": original["symbol"],
                        "side": original["side"], "qty": original["qty"], "prior_qty": original["prior_qty"]}
        return list(results.values())


def read_json_capture(raw):
    from .trading_reconciliation import parse_runtime_capture
    return parse_runtime_capture(raw)
