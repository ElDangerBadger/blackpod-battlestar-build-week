"""Closed retained Invesco QQQ source metadata; no coverage or trading authority."""
from .decision_journal import _object, _identifier, _enum
from .historical_intake import historical_date
from .investment_review import _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference

VERSION = "blackpod.qqq_distribution_inventory.v1"
PROFILE = "INVESCO_QQQ_DISTRIBUTIONS_JSON_V1"
URL = "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/distribution?idType=cusip&productType=ETF"
PRODUCT_URL = "https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html"
RESOURCE_TEMPLATE = "https://dng-api.invesco.com/cache/v1/accounts/{locale}/shareclasses/{id}/distribution?idType={uniqueIdentifier}&productType=ETF"
AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_DISCOVERY_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 16384


def _constant(row, key, expected):
    if type(row[key]) is not type(expected) or row[key] != expected:
        raise ContractValidationError(key + " differs from the frozen QQQ source profile")


def _inventory(value):
    row = _object(value, {"schema_version", "inventory_id", "recorded_at", "profile", "evidence_scope", "publisher", "source_url", "captured_at", "body_evidence", "receipt_evidence", "discovery_evidence", "declared_coverage", "auto_trading_enabled", "authority"}, "QQQ distribution inventory")
    for key, expected in (("schema_version", VERSION), ("profile", PROFILE), ("publisher", "INVESCO"), ("source_url", URL)):
        _constant(row, key, expected)
    row["inventory_id"] = _identifier(row["inventory_id"], "inventory_id")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    for key in ("recorded_at", "captured_at"):
        row[key] = accounting_timestamp(row[key], key)
    if parse_rfc3339(row["captured_at"], "capture clock") > parse_rfc3339(row["recorded_at"], "inventory clock"):
        raise ContractValidationError("inventory cannot precede its retained capture")
    for key, maximum in (("body_evidence", MAX_BODY_BYTES), ("receipt_evidence", MAX_RECEIPT_BYTES), ("discovery_evidence", MAX_DISCOVERY_BYTES)):
        row[key] = evidence_reference(row[key], key)
        if not 0 < row[key]["size_bytes"] <= maximum:
            raise ContractValidationError(key + " exceeds the bounded source profile")
    refs = [row[key] for key in ("body_evidence", "receipt_evidence", "discovery_evidence")]
    if len({ref["path"] for ref in refs}) != 3 or len({ref["sha256"] for ref in refs}) != 3:
        raise ContractValidationError("QQQ source leaves require distinct paths and hashes")
    coverage = _object(row["declared_coverage"], {"symbols", "action_types", "effective_start", "effective_end", "completeness"}, "QQQ declared scope")
    for key, expected in (("symbols", ["QQQ"]), ("action_types", ["cash_dividends"]), ("completeness", "UNKNOWN")):
        _constant(coverage, key, expected)
    for key in ("effective_start", "effective_end"):
        coverage[key] = historical_date(coverage[key], key)
    if coverage["effective_start"] > coverage["effective_end"]:
        raise ContractValidationError("QQQ declared scope dates are reversed")
    row["declared_coverage"] = coverage
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


class QQQDistributionInventory(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_inventory)


def evidence_references(inventory):
    inventory = inventory if isinstance(inventory, QQQDistributionInventory) else QQQDistributionInventory.from_mapping(inventory)
    return [inventory.body_evidence, inventory.receipt_evidence, inventory.discovery_evidence]
