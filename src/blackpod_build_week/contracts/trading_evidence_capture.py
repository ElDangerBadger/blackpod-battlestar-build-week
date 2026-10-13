"""Closed local receipts for read-only retained research evidence."""
from .decision_journal import _hash, _object, _string
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument

CAPTURE_RECEIPT_VERSION = "blackpod.trading_evidence_capture.v1"
CAPTURE_URLS = frozenset({"https://data.alpaca.markets/v1/corporate-actions",
                          "https://data.alpaca.markets/v2/stocks/quotes"})


def validate_capture_receipt(value):
    row = _object(value, {"schema_version", "method", "url", "query", "captured_at", "status", "body_sha256", "size_bytes"}, "research capture receipt")
    if row["schema_version"] != CAPTURE_RECEIPT_VERSION or row["method"] != "GET" or not isinstance(row["url"], str) or row["url"] not in CAPTURE_URLS:
        raise ContractValidationError("research capture requires versioned GET to an allowed data endpoint")
    if type(row["status"]) is not int or not 200 <= row["status"] <= 599:
        raise ContractValidationError("capture status must be an exact HTTP status integer")
    if type(row["size_bytes"]) is not int or not 0 <= row["size_bytes"] <= 64 * 1024 * 1024:
        raise ContractValidationError("capture body size must be a bounded integer")
    row["body_sha256"] = _hash(row["body_sha256"], "body_sha256")
    row["captured_at"] = accounting_timestamp(row["captured_at"], "captured_at")
    if not isinstance(row["query"], dict) or not 1 <= len(row["query"]) <= 16:
        raise ContractValidationError("capture query must be a bounded explicit object")
    for key, item in row["query"].items():
        _string(key, "query key", 64)
        if not isinstance(item, str) and type(item) is not int:
            raise ContractValidationError("capture query values must be exact strings or integers")
        if isinstance(item, str):
            _string(item, "query value", 4096)
    return row


class CaptureReceipt(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(validate_capture_receipt)
