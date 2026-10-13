"""Explicit fixed-GET TRAIN capture with immutable, resumable local attempts.

Importing this module is offline. Credentials remain in memory; neither broker
endpoints nor account/order APIs are available. A terminal provider page means
pagination completeness, never coverage or usable economic evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
from http.client import HTTPException
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from .contracts.mission_request import normalize_rfc3339, parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_evidence_capture import CaptureReceipt
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import PaperCredentials, _credential_literal
from .sentry_history_cache import _directory, read_regular
from .trading_cost_intake import QUOTES_URL, _nanos, _number, _query
from .trading_historical_intake import parse_historical_json

_START_SCHEMA = "blackpod.train_market_capture_attempt_started.v1"
_FINISH_SCHEMA = "blackpod.train_market_capture_attempt_completed.v1"
_INDEX_SCHEMA = "blackpod.train_market_capture_source_index.v1"
SNAPSHOT_SCHEMA = "blackpod.train_market_capture_snapshot.v1"
_START_NAME = re.compile(r"attempt-([0-9]{6})\.started\.v1\.json\Z")
_FINISH_NAME = re.compile(r"attempt-([0-9]{6})\.completed\.v1\.json\Z")
_STAGE_NAME = re.compile(r"\.capture-stage-[a-f0-9]{32}-(.+)\Z")
_FAILURES = frozenset({"HTTP_ERROR", "REDIRECT_REFUSED", "TIMEOUT", "URL_ERROR", "TRANSPORT_ERROR", "RESPONSE_TOO_LARGE",
    "INVALID_RESPONSE", "SENSITIVE_RESPONSE_REFUSED", "INTERRUPTED", "SEGMENT_PAGE_LIMIT", "SEGMENT_ROW_LIMIT",
    "SEGMENT_BYTE_LIMIT", "CAPTURE_BYTE_LIMIT", "TOTAL_REQUEST_LIMIT", "ENDPOINT_REFUSED"})


class CaptureError(ValueError):
    """A sanitized capture input, durable state or publication failure."""


class CaptureTransportError(Exception):
    def __init__(self, code, http_status=None):
        self.code = code if code in _FAILURES else "TRANSPORT_ERROR"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


@dataclass(frozen=True, repr=False)
class MarketResponse:
    status: int
    body: bytes


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise CaptureTransportError("REDIRECT_REFUSED", code)


def market_get(query, credentials, timeout=20, max_response_bytes=8 * 1024 * 1024):
    """Only the fixed Alpaca historical-quotes GET, with verified TLS."""
    try:
        if not isinstance(credentials, PaperCredentials):
            raise ValueError()
        key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
        symbols = query.get("symbols", "").split(",") if isinstance(query, dict) else []
        _query(query, symbols)
        if symbols != sorted(set(symbols)) or not symbols or any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", value) for value in symbols):
            raise ValueError()
        if type(timeout) not in {int, float} or not 0 < timeout <= 60 or type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 8 * 1024 * 1024:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise CaptureTransportError("ENDPOINT_REFUSED") from None
    url = QUOTES_URL + "?" + urlencode(sorted(query.items()))
    request = Request(url, headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}, method="GET")
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise CaptureTransportError("REDIRECT_REFUSED")
            if type(response.status) is not int or response.status != 200:
                raise CaptureTransportError("HTTP_ERROR", response.status)
            chunks, size = [], 0
            reader = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() > deadline:
                    raise CaptureTransportError("TIMEOUT")
                part = reader(min(65536, max_response_bytes + 1 - size))
                if not isinstance(part, bytes):
                    raise CaptureTransportError("INVALID_RESPONSE")
                if not part:
                    break
                chunks.append(part); size += len(part)
                if size > max_response_bytes:
                    raise CaptureTransportError("RESPONSE_TOO_LARGE", response.status)
            return MarketResponse(200, b"".join(chunks))
    except CaptureTransportError:
        raise
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise CaptureTransportError("HTTP_ERROR", status) from None
    except (TimeoutError, socket.timeout):
        raise CaptureTransportError("TIMEOUT") from None
    except URLError:
        raise CaptureTransportError("URL_ERROR") from None
    except (OSError, HTTPException):
        raise CaptureTransportError("TRANSPORT_ERROR") from None


_NETWORK_TRANSPORT = market_get


def _ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _safe_root(output_root):
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    root = Path(output_root).absolute()
    if ".." in root.parts or root == Path(root.anchor):
        raise CaptureError("unsafe capture output path")
    _check_existing_ancestors(root)
    _reject_source_storage(root)
    package = Path(__file__).absolute().parents[2]
    for ancestor in (root, *root.parents):
        if ancestor.name in {"src", "tests", "fixtures", ".git"}:
            raise CaptureError("capture output overlaps source storage")
        if any(os.path.lexists(ancestor / marker) for marker in (".journal.lock", "ledger.lock", "worker.lock", "blackwell_navigator_trickle.py")):
            raise CaptureError("capture output overlaps protected storage")
        if os.path.lexists(ancestor / ".git"):
            if ancestor != package or root == ancestor or root.relative_to(ancestor).parts[0] != "output":
                raise CaptureError("capture output overlaps a repository source tree")
    return root


def _regular_info(path, *, allow_stage=False):
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink not in ({1, 2} if allow_stage else {1}):
        raise CaptureError("capture contains an unsafe source file")
    return value


def _recover_stages(root):
    for directory, subdirs, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        if len(names) + len(subdirs) > 10000:
            raise CaptureError("capture directory exceeds its file bound")
        for name in subdirs:
            if not stat.S_ISDIR((parent / name).lstat().st_mode):
                raise CaptureError("capture contains an unsafe source directory")
        # Resolve our two-link publication window before regular-file checks.
        for name in sorted(names, key=lambda value: _STAGE_NAME.fullmatch(value) is None):
            match = _STAGE_NAME.fullmatch(name)
            if match is None:
                _regular_info(parent / name)
                continue
            info = _regular_info(parent / name, allow_stage=True)
            target = parent / match[1]
            if info.st_nlink == 2:
                other = _regular_info(target, allow_stage=True)
                if (other.st_dev, other.st_ino) != (info.st_dev, info.st_ino):
                    raise CaptureError("capture staging link is inconsistent")
            descriptor = _directory(parent)
            try:
                os.unlink(name, dir_fd=descriptor); os.fsync(descriptor)
            finally:
                os.close(descriptor)


@contextmanager
def _lock(root, *, create):
    descriptor = _directory(root, create=create)
    lock = None
    try:
        lock = os.open(".capture.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=descriptor)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024:
            raise CaptureError("capture lock is unsafe")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CaptureError("capture lock is busy") from None
        _recover_stages(root)
        yield
    finally:
        if lock is not None:
            os.close(lock)
        os.close(descriptor)


def _immutable(path, raw):
    parent = _directory(path.parent, create=True)
    stage = ".capture-stage-" + uuid.uuid4().hex + "-" + path.name
    descriptor = None
    try:
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        position = 0
        while position < len(raw):
            written = os.write(descriptor, raw[position:])
            if not written:
                raise CaptureError("capture publication did not complete")
            position += written
        os.fsync(descriptor); os.close(descriptor); descriptor = None
        try:
            os.link(stage, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            if read_regular(path, max_bytes=max(len(raw), 1)) != raw:
                raise CaptureError("immutable capture identity conflicts with existing bytes")
        os.unlink(stage, dir_fd=parent); os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(stage, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def _load_object(path):
    try:
        raw = read_regular(path, max_bytes=1024 * 1024)
        value = parse_strict_json_object_bytes(raw)
        if canonical_json_bytes(value) != raw:
            raise CaptureError("capture checkpoint serialization changed")
        return value
    except (ValueError, OSError, RecursionError):
        raise CaptureError("capture checkpoint cannot be verified") from None


def _inputs(plan, root, source_blobs, *, initialize, credentials=None):
    from .contracts.train_market_evidence import TrainMarketCapturePlan
    from .train_market_evidence import validate_capture_inputs
    plan = TrainMarketCapturePlan.from_mapping(plan.to_dict() if hasattr(plan, "to_dict") else plan)
    index_path = root / "source_evidence/index.v1.json"
    if index_path.exists():
        index = _load_object(index_path)
        if set(index) != {"schema_version", "capture_plan_sha256", "evidence"} or index["schema_version"] != _INDEX_SCHEMA or index["capture_plan_sha256"] != sha256_bytes(plan.to_bytes()):
            raise CaptureError("capture source index differs from the frozen plan")
        loaded = {}
        from .contracts.decision_journal import _evidence
        refs = _evidence(index["evidence"])
        for ref in refs:
            raw = read_regular(root / "source_evidence" / ref["path"], max_bytes=64 * 1024 * 1024)
            if sha256_bytes(raw) != ref["sha256"] or len(raw) != ref["size_bytes"]:
                raise CaptureError("capture source snapshot differs in hash or size")
            loaded[ref["sha256"]] = raw
        if source_blobs is not None:
            for digest, raw in loaded.items():
                if source_blobs.get(digest) != raw:
                    raise CaptureError("provided capture sources differ from their immutable snapshot")
        source_blobs = loaded
    elif source_blobs is None or not initialize:
        raise CaptureError("first capture requires verified frozen source evidence")
    material = validate_capture_inputs(plan, source_blobs)
    if credentials is not None:
        _check_sensitive(plan.to_bytes(), credentials)
        for raw in material["evidence"].values():
            if any(value.encode() in raw for value in (credentials.key_id, credentials.secret_key)):
                raise CaptureError("sensitive source snapshot refused")
    if not index_path.exists():
        evidence = material["evidence"]
        index = {"schema_version": _INDEX_SCHEMA, "capture_plan_sha256": sha256_bytes(plan.to_bytes()),
                 "evidence": [_ref(path, raw) for path, raw in sorted(evidence.items())]}
        for path, raw in evidence.items():
            _immutable(root / "source_evidence" / path, raw)
        _immutable(index_path, canonical_json_bytes(index))
    plan_path = root / "capture-plan.v1.json"
    if initialize:
        _immutable(plan_path, plan.to_bytes())
    elif read_regular(plan_path, max_bytes=1024 * 1024) != plan.to_bytes():
        raise CaptureError("capture source plan differs from the immutable original")
    return plan


def _check_sensitive(raw, credentials):
    values = (credentials.key_id, credentials.secret_key)
    if any(value.encode() in raw for value in values):
        raise CaptureTransportError("SENSITIVE_RESPONSE_REFUSED")
    try:
        parsed = parse_historical_json(raw)
    except (ValueError, RecursionError):
        raise CaptureTransportError("INVALID_RESPONSE") from None
    pending = [parsed]
    while pending:
        value = pending.pop()
        if isinstance(value, str) and any(secret in value for secret in values):
            raise CaptureTransportError("SENSITIVE_RESPONSE_REFUSED")
        elif isinstance(value, dict):
            pending.extend(value.keys()); pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def _native_page(raw, query, previous_pair, signatures, seen_tokens):
    value = parse_historical_json(raw)
    if not isinstance(value, dict) or set(value) != {"quotes", "next_page_token"} or not isinstance(value["quotes"], dict):
        raise CaptureError("native capture response is invalid")
    universe = query["symbols"].split(",")
    start, end = _query(query, universe)
    if any(symbol not in universe for symbol in value["quotes"]):
        raise CaptureError("native capture has an undeclared symbol")
    token = value["next_page_token"]
    if token is not None and (not isinstance(token, str) or not 1 <= len(token) <= 2048 or token in seen_tokens):
        raise CaptureError("native capture pagination is malformed or cyclic")
    count = 0
    for symbol in sorted(value["quotes"]):
        rows = value["quotes"][symbol]
        if not isinstance(rows, list): raise CaptureError("native capture quote rows are invalid")
        for row in rows:
            count += 1
            if not isinstance(row, dict) or set(row) != {"t", "bp", "bs", "bx", "ap", "as", "ax", "c", "z"}:
                raise CaptureError("native capture quote fields are invalid")
            stamp = _nanos(row["t"], "capture quote time")
            pair = (symbol, stamp)
            if not start <= stamp <= end or (previous_pair is not None and pair < previous_pair):
                raise CaptureError("native capture quote chronology is invalid")
            if pair != previous_pair:
                signatures.clear()
            for field in ("bx", "ax"):
                if not isinstance(row[field], str) or not 1 <= len(row[field]) <= 16 or row[field].strip() != row[field]:
                    raise CaptureError("native capture exchange is invalid")
            if not isinstance(row["z"], str) or row["z"] not in {"A", "B", "C"}:
                raise CaptureError("native capture tape is invalid")
            conditions = row["c"]
            if not isinstance(conditions, list) or len(conditions) > 16 or any(not isinstance(item, str) or not 1 <= len(item) <= 16 or item.strip() != item for item in conditions) or len(set(conditions)) != len(conditions):
                raise CaptureError("native capture conditions are invalid")
            signature = (_number(row["bp"], "capture bid"), _number(row["ap"], "capture ask"),
                _number(row["bs"], "capture bid size", integer=True), _number(row["as"], "capture ask size", integer=True),
                row["bx"], row["ax"], tuple(conditions), row["z"])
            if signature in signatures:
                raise CaptureError("native capture quote duplicate is invalid")
            signatures.add(signature); previous_pair = pair
    if count > query["limit"]:
        raise CaptureError("native capture quote page exceeds the query limit")
    return token, count, previous_pair


def _new_states(plan):
    return {segment["segment_id"]: {"segment": segment, "pages": [], "status": "NOT_STARTED", "failure": None,
        "next_token": None, "rows": 0, "bytes": 0, "last_pair": None, "signatures": set(), "tokens": set()}
        for segment in plan.segments}


def _finish(root, started, outcome, completed_at, *, body_ref=None, receipt_ref=None, failure=None, rows=0, token=None):
    if parse_rfc3339(completed_at, "completion clock") < parse_rfc3339(started["started_at"], "attempt clock"):
        raise CaptureError("capture completion clock moved backwards")
    value = {"schema_version": _FINISH_SCHEMA, "sequence": started["sequence"], "capture_id": started["capture_id"],
        "capture_plan_sha256": started["capture_plan_sha256"], "segment_id": started["segment_id"],
        "started_sha256": sha256_bytes(canonical_json_bytes(started)), "outcome": outcome, "completed_at": completed_at,
        "body_evidence": body_ref, "receipt_evidence": receipt_ref, "failure": failure,
        "native_row_count": rows, "next_page_token": token}
    _immutable(root / ("attempts/attempt-%06d.completed.v1.json" % started["sequence"]), canonical_json_bytes(value))
    return value


def _load(plan, root, recovery_at):
    states, checkpoints, evidence = _new_states(plan), [], {}
    attempt_root = root / "attempts"
    names = sorted(os.listdir(attempt_root)) if attempt_root.exists() else []
    starts, finishes = {}, {}
    for name in names:
        start, finish = _START_NAME.fullmatch(name), _FINISH_NAME.fullmatch(name)
        if start: starts[int(start[1])] = name
        elif finish: finishes[int(finish[1])] = name
        else: raise CaptureError("capture has an unknown attempt checkpoint")
    if sorted(starts) != list(range(1, len(starts) + 1)) or set(finishes) - set(starts) or len(starts) > plan.limits["max_total_requests"]:
        raise CaptureError("capture attempt sequence is inconsistent")
    previous, latest_clock = None, plan.created_at
    for sequence in sorted(starts):
        start_path = "attempts/" + starts[sequence]
        started = _load_object(root / start_path)
        expected_fields = {"schema_version", "sequence", "capture_id", "capture_plan_sha256", "segment_id", "query", "started_at", "previous_completed_sha256"}
        if (set(started) != expected_fields or started["schema_version"] != _START_SCHEMA or type(started["sequence"]) is not int or started["sequence"] != sequence
                or started["capture_id"] != plan.capture_id or started["capture_plan_sha256"] != sha256_bytes(plan.to_bytes())
                or started["previous_completed_sha256"] != previous or started["segment_id"] not in states):
            raise CaptureError("capture attempt differs from its frozen checkpoint chain")
        state = states[started["segment_id"]]
        query = dict(state["segment"]["query"])
        if state["next_token"] is not None: query["page_token"] = state["next_token"]
        unfinished = next((segment["segment_id"] for segment in plan.segments if states[segment["segment_id"]]["status"] != "COMPLETE"), None)
        if started["query"] != query or state["status"] == "COMPLETE" or unfinished != started["segment_id"]:
            raise CaptureError("capture attempt changed its segment or pagination cursor")
        if parse_rfc3339(started["started_at"], "attempt clock") < parse_rfc3339(latest_clock, "prior capture clock"):
            raise CaptureError("capture attempt clock moved backwards")
        evidence[start_path] = canonical_json_bytes(started)
        body_path, receipt_path = "source/attempt-%06d.body.raw" % sequence, "source/attempt-%06d.receipt.v1.json" % sequence
        if sequence not in finishes:
            if sequence != len(starts): raise CaptureError("capture is missing a nonterminal attempt checkpoint")
            if (root / body_path).exists() and (root / receipt_path).exists():
                body = read_regular(root / body_path, max_bytes=plan.limits["max_response_bytes"])
                receipt = CaptureReceipt.from_bytes(read_regular(root / receipt_path, max_bytes=65536))
                if (receipt.query != query or receipt.status != 200 or receipt.url != QUOTES_URL
                        or receipt.body_sha256 != sha256_bytes(body) or receipt.size_bytes != len(body)):
                    raise CaptureError("interrupted capture source pair cannot be verified")
                token, count, _ = _native_page(body, query, state["last_pair"], set(state["signatures"]), set(state["tokens"]))
                completed = _finish(root, started, "PAGE_RETAINED", receipt.captured_at,
                    body_ref=_ref(body_path, body), receipt_ref=_ref(receipt_path, receipt.to_bytes()), rows=count, token=token)
            else:
                completed = _finish(root, started, "INTERRUPTED", recovery_at, failure={"code": "INTERRUPTED", "http_status": None})
        else:
            completed = _load_object(root / ("attempts/" + finishes[sequence]))
        finish_path = "attempts/attempt-%06d.completed.v1.json" % sequence
        if (set(completed) != {"schema_version", "sequence", "capture_id", "capture_plan_sha256", "segment_id", "started_sha256", "outcome", "completed_at", "body_evidence", "receipt_evidence", "failure", "native_row_count", "next_page_token"}
                or completed["schema_version"] != _FINISH_SCHEMA or type(completed["sequence"]) is not int or completed["sequence"] != sequence
                or completed["capture_id"] != plan.capture_id or completed["capture_plan_sha256"] != started["capture_plan_sha256"]
                or completed["segment_id"] != started["segment_id"] or completed["started_sha256"] != sha256_bytes(canonical_json_bytes(started))
                or type(completed["native_row_count"]) is not int or completed["native_row_count"] < 0
                or parse_rfc3339(completed["completed_at"], "completion clock") < parse_rfc3339(started["started_at"], "attempt clock")):
            raise CaptureError("capture completion checkpoint is inconsistent")
        if completed["outcome"] == "PAGE_RETAINED":
            if completed["failure"] is not None:
                raise CaptureError("successful page has contradictory failure metadata")
            body_ref, receipt_ref = completed["body_evidence"], completed["receipt_evidence"]
            if body_ref["path"] != body_path or receipt_ref["path"] != receipt_path:
                raise CaptureError("capture source identity changed")
            body = read_regular(root / body_path, max_bytes=plan.limits["max_response_bytes"])
            receipt_raw = read_regular(root / receipt_path, max_bytes=65536)
            if body_ref != _ref(body_path, body) or receipt_ref != _ref(receipt_path, receipt_raw):
                raise CaptureError("capture source body or receipt differs in hash or size")
            receipt = CaptureReceipt.from_bytes(receipt_raw)
            if (receipt.query != query or receipt.status != 200 or receipt.url != QUOTES_URL or receipt.body_sha256 != body_ref["sha256"]
                    or receipt.size_bytes != len(body) or receipt.captured_at != completed["completed_at"]):
                raise CaptureError("capture receipt differs from its exact request and completion")
            token, count, last_pair = _native_page(body, query, state["last_pair"], state["signatures"], state["tokens"])
            if token != completed["next_page_token"] or count != completed["native_row_count"]:
                raise CaptureError("capture checkpoint differs from its native response replay")
            state["next_token"], state["last_pair"] = token, last_pair
            if token is not None: state["tokens"].add(token)
            state["pages"].append({"body_evidence": body_ref, "receipt_evidence": receipt_ref})
            state["rows"] += count; state["bytes"] += len(body) + len(receipt_raw)
            state["status"], state["failure"] = ("COMPLETE" if token is None else "INCOMPLETE"), None
            evidence[body_path], evidence[receipt_path] = body, receipt_raw
            if len(state["pages"]) > plan.limits["max_pages_per_segment"] or state["rows"] > plan.limits["max_rows_per_segment"] or state["bytes"] > plan.limits["max_segment_bytes"]:
                raise CaptureError("retained capture exceeds its frozen segment bounds")
        elif completed["outcome"] in {"FAILED", "INTERRUPTED"}:
            failure = completed["failure"]
            if (not isinstance(failure, dict) or set(failure) != {"code", "http_status"} or failure["code"] not in _FAILURES
                    or (failure["http_status"] is not None and (type(failure["http_status"]) is not int or not 100 <= failure["http_status"] <= 599))
                    or completed["body_evidence"] is not None or completed["receipt_evidence"] is not None
                    or completed["native_row_count"] != 0 or completed["next_page_token"] is not None
                    or (completed["outcome"] == "INTERRUPTED" and failure != {"code": "INTERRUPTED", "http_status": None})):
                raise CaptureError("capture failure checkpoint contains unsafe or contradictory metadata")
            state["status"], state["failure"] = "UNAVAILABLE", failure
        else:
            raise CaptureError("capture completion outcome is invalid")
        finish_raw = canonical_json_bytes(completed)
        evidence[finish_path] = finish_raw; previous = sha256_bytes(finish_raw)
        latest_clock = completed["completed_at"]
        checkpoints.extend((_ref(start_path, evidence[start_path]), _ref(finish_path, finish_raw)))
    source_root = root / "source"
    orphan_bytes = 0
    if source_root.exists():
        expected = {path.split("/", 1)[1] for path in evidence if path.startswith("source/")}
        for name in os.listdir(source_root):
            if name not in expected:
                # A lone published body from an interrupted attempt is retained
                # as an opaque orphan for audit, never imported as a page.
                if not re.fullmatch(r"attempt-[0-9]{6}\.(?:body\.raw|receipt\.v1\.json)", name):
                    raise CaptureError("capture contains an unknown source artifact")
                index = int(name[8:14])
                if index not in starts: raise CaptureError("capture orphan has no preceding attempt")
                # Without a bound source pair there is no authenticated page
                # digest. Keep the orphan on disk, but never export its content
                # or import it into source history. Account for its disk size.
                info = _regular_info(source_root / name)
                if info.st_size > plan.limits["max_response_bytes"]:
                    raise CaptureError("capture orphan exceeds its response bound")
                orphan_bytes += info.st_size
    index = _load_object(root / "source_evidence/index.v1.json")
    index_raw = canonical_json_bytes(index)
    evidence["source_evidence/index.v1.json"] = index_raw
    checkpoints.append(_ref("source_evidence/index.v1.json", index_raw))
    for ref in index["evidence"]:
        path = "source_evidence/" + ref["path"]
        evidence[path] = read_regular(root / path, max_bytes=64 * 1024 * 1024)
        checkpoints.append(_ref(path, evidence[path]))
    evidence["capture-plan.v1.json"] = plan.to_bytes()
    retained = sum(map(len, evidence.values()))
    if retained + orphan_bytes > plan.limits["max_capture_bytes"]:
        raise CaptureError("capture exceeds its frozen combined byte bound")
    return states, evidence, checkpoints, len(starts), previous, retained


def _disk_bytes(root):
    return sum(_regular_info(Path(directory) / name).st_size for directory, _, names in os.walk(root, followlinks=False)
               for name in names if name != ".capture.lock")


def _limited(state, plan, attempts, retained):
    if len(state["pages"]) >= plan.limits["max_pages_per_segment"]: return "SEGMENT_PAGE_LIMIT"
    if state["rows"] >= plan.limits["max_rows_per_segment"]: return "SEGMENT_ROW_LIMIT"
    if state["bytes"] + 16384 >= plan.limits["max_segment_bytes"]: return "SEGMENT_BYTE_LIMIT"
    if retained + 16384 >= plan.limits["max_capture_bytes"]: return "CAPTURE_BYTE_LIMIT"
    if attempts >= plan.limits["max_total_requests"]: return "TOTAL_REQUEST_LIMIT"
    return None


def capture_train_quotes(plan, output_root, credentials, *, source_blobs=None, request_budget=None,
                         transport=market_get, clock=utc_now, sleeper=time.sleep):
    """Capture only frozen TRAIN segments; explicit invocations bound retries."""
    root = _safe_root(output_root)
    with _lock(root, create=True):
        if not isinstance(credentials, PaperCredentials):
            raise CaptureError("capture requires explicit literal credentials in memory")
        _credential_literal(credentials.key_id); _credential_literal(credentials.secret_key)
        plan = _inputs(plan, root, source_blobs, initialize=True, credentials=credentials)
        if plan.evidence_scope == "SYNTHETIC_FIXTURE_ONLY" and transport is _NETWORK_TRANSPORT:
            raise CaptureError("synthetic capture cannot contact a provider")
        budget = plan.limits["max_requests_per_invocation"] if request_budget is None else request_budget
        if type(budget) is not int or not 0 <= budget <= plan.limits["max_requests_per_invocation"]:
            raise CaptureError("request budget exceeds the frozen invocation bound")
        now = normalize_rfc3339(clock(), "capture clock")
        if parse_rfc3339(now, "capture clock") < parse_rfc3339(plan.created_at, "plan freeze"):
            raise CaptureError("capture cannot predate its frozen plan")
        requests, stop = 0, None
        prior_clock = now
        while True:
            states, retained_evidence, _, attempts, previous, retained = _load(plan, root, now)
            state = next((states[segment["segment_id"]] for segment in plan.segments if states[segment["segment_id"]]["status"] != "COMPLETE"), None)
            if state is None: break
            disk_bytes = _disk_bytes(root)
            stop = _limited(state, plan, attempts, disk_bytes)
            if stop is not None or requests >= budget:
                stop = stop or "INVOCATION_REQUEST_BUDGET"
                break
            if requests or attempts:
                sleeper(plan.limits["min_request_interval_ms"] / 1000)
            now = normalize_rfc3339(clock(), "capture clock")
            latest_completed = (parse_strict_json_object_bytes(retained_evidence["attempts/attempt-%06d.completed.v1.json" % attempts])["completed_at"]
                                if attempts else plan.created_at)
            if parse_rfc3339(now, "attempt clock") < max(parse_rfc3339(value, "prior capture clock") for value in (plan.created_at, prior_clock, latest_completed)):
                raise CaptureError("capture attempt clock moved backwards before request")
            prior_clock = now
            query = dict(state["segment"]["query"])
            if state["next_token"] is not None: query["page_token"] = state["next_token"]
            sequence = attempts + 1
            started = {"schema_version": _START_SCHEMA, "sequence": sequence, "capture_id": plan.capture_id,
                "capture_plan_sha256": sha256_bytes(plan.to_bytes()), "segment_id": state["segment"]["segment_id"],
                "query": query, "started_at": now, "previous_completed_sha256": previous}
            _immutable(root / ("attempts/attempt-%06d.started.v1.json" % sequence), canonical_json_bytes(started))
            requests += 1
            response_limit = min(plan.limits["max_response_bytes"], plan.limits["max_segment_bytes"] - state["bytes"] - 16384,
                                 plan.limits["max_capture_bytes"] - disk_bytes - 16384)
            try:
                response = transport(query, credentials, timeout=plan.limits["timeout_seconds"], max_response_bytes=response_limit)
                if not isinstance(response, MarketResponse) or type(response.status) is not int or response.status != 200:
                    raise CaptureTransportError("HTTP_ERROR", getattr(response, "status", None))
                if not isinstance(response.body, bytes): raise CaptureTransportError("INVALID_RESPONSE")
                if len(response.body) > response_limit: raise CaptureTransportError("RESPONSE_TOO_LARGE", 200)
                _check_sensitive(response.body, credentials)
                try:
                    token, count, _ = _native_page(response.body, query, state["last_pair"], set(state["signatures"]), set(state["tokens"]))
                except (ValueError, TypeError, RecursionError):
                    raise CaptureTransportError("INVALID_RESPONSE") from None
                if state["rows"] + count > plan.limits["max_rows_per_segment"]:
                    raise CaptureTransportError("SEGMENT_ROW_LIMIT")
                now = normalize_rfc3339(clock(), "receipt clock")
                if parse_rfc3339(now, "receipt clock") < parse_rfc3339(started["started_at"], "attempt clock"):
                    raise CaptureError("capture receipt clock moved backwards")
                receipt = CaptureReceipt.from_mapping({"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
                    "url": QUOTES_URL, "query": query, "captured_at": now, "status": 200,
                    "body_sha256": sha256_bytes(response.body), "size_bytes": len(response.body)})
            except CaptureTransportError as exc:
                now = normalize_rfc3339(clock(), "failure clock")
                _finish(root, started, "FAILED", now, failure={"code": exc.code, "http_status": exc.http_status})
                stop = exc.code; break
            except CaptureError:
                raise
            except (OSError, HTTPException, ValueError, TypeError):
                now = normalize_rfc3339(clock(), "failure clock")
                _finish(root, started, "FAILED", now, failure={"code": "TRANSPORT_ERROR", "http_status": None})
                stop = "TRANSPORT_ERROR"; break
            # Publication failures preserve ATTEMPT_STARTED for offline
            # recovery; they never rewrite a persisted response as failure.
            body_path, receipt_path = "source/attempt-%06d.body.raw" % sequence, "source/attempt-%06d.receipt.v1.json" % sequence
            try:
                _immutable(root / body_path, response.body)
                _immutable(root / receipt_path, receipt.to_bytes())
                _finish(root, started, "PAGE_RETAINED", now, body_ref=_ref(body_path, response.body), receipt_ref=_ref(receipt_path, receipt.to_bytes()), rows=count, token=token)
                prior_clock = now
            except (OSError, ValueError):
                raise CaptureError("capture publication interrupted; verify durable recovery") from None
        states, _, _, attempts, _, retained = _load(plan, root, normalize_rfc3339(clock(), "final capture clock"))
        complete = sum(state["status"] == "COMPLETE" for state in states.values())
        return {"capture_id": plan.capture_id, "requests_this_invocation": requests, "attempt_count": attempts,
            "complete_segment_count": complete, "segment_count": len(states), "pagination_complete": complete == len(states),
            "coverage_verified": False, "stop_reason": stop, "retained_bytes": retained,
            "orders_submitted": 0, "auto_trading_enabled": False}


def read_capture(plan, output_root, *, exported_at):
    """Verify and recover durable local sources without any provider call."""
    root = _safe_root(output_root)
    exported_at = normalize_rfc3339(exported_at, "capture export clock")
    with _lock(root, create=False):
        plan = _inputs(plan, root, None, initialize=False)
        states, evidence, checkpoints, attempts, _, retained = _load(plan, root, exported_at)
        if any(parse_rfc3339(_load_object(root / ref["path"])["completed_at"], "completion") > parse_rfc3339(exported_at, "export")
               for ref in checkpoints if ref["path"].endswith("completed.v1.json")):
            raise CaptureError("capture export cannot predate its retained attempts")
        snapshot = {"schema_version": SNAPSHOT_SCHEMA, "capture_plan_evidence": _ref("capture-plan.v1.json", plan.to_bytes()),
            "capture_id": plan.capture_id, "exported_at": exported_at,
            "segments": [{"segment_id": segment["segment_id"], "pages": states[segment["segment_id"]]["pages"],
                "status": states[segment["segment_id"]]["status"],
                "failure": states[segment["segment_id"]]["failure"] or
                    ({"code": _limited(states[segment["segment_id"]], plan, attempts, retained), "http_status": None}
                     if states[segment["segment_id"]]["status"] != "COMPLETE" and _limited(states[segment["segment_id"]], plan, attempts, retained) else None)}
                for segment in plan.segments],
            "attempt_count": attempts, "retained_bytes": retained, "checkpoint_evidence": checkpoints,
            "auto_trading_enabled": False, "authority": plan.authority}
        return {"snapshot": snapshot, "evidence": evidence}


def validate_capture_snapshot(plan, snapshot, blobs):
    """Pure semantic replay of an exported capture audit, without filesystem I/O.

    Hashes alone do not prove that a snapshot's counters, source statuses or
    checkpoint sequence describe the retained attempts. Every claim here is
    reconstructed from the original immutable records and native page bodies.
    """
    from .contracts.decision_journal import _evidence
    from .contracts.train_market_evidence import TrainMarketCapturePlan, TrainMarketCaptureSnapshot
    from .train_market_evidence import validate_capture_inputs
    plan = TrainMarketCapturePlan.from_mapping(plan.to_dict() if hasattr(plan, "to_dict") else plan)
    snapshot = TrainMarketCaptureSnapshot.from_mapping(snapshot.to_dict() if hasattr(snapshot, "to_dict") else snapshot)
    exported = parse_rfc3339(snapshot.exported_at, "snapshot export")
    if snapshot.capture_id != plan.capture_id or exported < parse_rfc3339(plan.created_at, "plan freeze"):
        raise CaptureError("capture audit identity or export clock differs from its frozen plan")
    evidence = {}

    def retain(ref):
        ref = _evidence([ref])[0]
        raw = blobs.get(ref["sha256"])
        if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
            raise CaptureError("capture audit evidence differs in hash or size")
        if ref["path"] in evidence and evidence[ref["path"]] != raw:
            raise CaptureError("capture audit source path conflicts")
        evidence[ref["path"]] = raw
        return raw

    def record(ref):
        raw = retain(ref)
        value = parse_strict_json_object_bytes(raw)
        if canonical_json_bytes(value) != raw:
            raise CaptureError("capture audit checkpoint serialization changed")
        return value

    if snapshot.capture_plan_evidence["path"] != "capture-plan.v1.json" or retain(snapshot.capture_plan_evidence) != plan.to_bytes():
        raise CaptureError("capture audit must bind its exact persisted plan")
    by_path = {ref["path"]: ref for ref in snapshot.checkpoint_evidence}
    if "source_evidence/index.v1.json" not in by_path:
        raise CaptureError("capture audit is missing its frozen source index")
    index = record(by_path["source_evidence/index.v1.json"])
    if (set(index) != {"schema_version", "capture_plan_sha256", "evidence"} or index["schema_version"] != _INDEX_SCHEMA
            or index["capture_plan_sha256"] != sha256_bytes(plan.to_bytes())):
        raise CaptureError("capture audit source index differs from its frozen plan")
    original_refs = _evidence(index["evidence"])
    source_blobs, source_paths = {}, {"source_evidence/index.v1.json"}
    for ref in original_refs:
        alias = {**ref, "path": "source_evidence/" + ref["path"]}
        if by_path.get(alias["path"]) != alias:
            raise CaptureError("capture audit source index has a missing or changed leaf")
        source_blobs[ref["sha256"]] = retain(alias)
        source_paths.add(alias["path"])
    context = validate_capture_inputs(plan, source_blobs)
    if original_refs != [_ref(path, raw) for path, raw in sorted(context["evidence"].items())]:
        raise CaptureError("capture audit source snapshot differs from its required original closure")
    starts, finishes = {}, {}
    for path, ref in by_path.items():
        if path in source_paths:
            continue
        if not path.startswith("attempts/"):
            raise CaptureError("capture audit contains an unknown checkpoint source")
        start, finish = _START_NAME.fullmatch(path[9:]), _FINISH_NAME.fullmatch(path[9:])
        if start: starts[int(start[1])] = ref
        elif finish: finishes[int(finish[1])] = ref
        else: raise CaptureError("capture audit contains an unknown attempt checkpoint")
    if (sorted(starts) != list(range(1, len(starts) + 1)) or set(starts) != set(finishes)
            or snapshot.attempt_count != len(starts) or len(starts) > plan.limits["max_total_requests"]):
        raise CaptureError("capture audit attempt count or checkpoint sequence is inconsistent")
    states = _new_states(plan)
    previous, latest = None, plan.created_at
    for sequence in sorted(starts):
        started, completed = record(starts[sequence]), record(finishes[sequence])
        if (set(started) != {"schema_version", "sequence", "capture_id", "capture_plan_sha256", "segment_id", "query", "started_at", "previous_completed_sha256"}
                or started["schema_version"] != _START_SCHEMA or type(started["sequence"]) is not int or started["sequence"] != sequence
                or started["capture_id"] != plan.capture_id or started["capture_plan_sha256"] != sha256_bytes(plan.to_bytes())
                or started["previous_completed_sha256"] != previous or started["segment_id"] not in states):
            raise CaptureError("capture audit attempt differs from the frozen checkpoint chain")
        state = states[started["segment_id"]]
        expected_query = dict(state["segment"]["query"])
        if state["next_token"] is not None: expected_query["page_token"] = state["next_token"]
        unfinished = next((segment["segment_id"] for segment in plan.segments if states[segment["segment_id"]]["status"] != "COMPLETE"), None)
        if started["segment_id"] != unfinished or state["status"] == "COMPLETE" or started["query"] != expected_query:
            raise CaptureError("capture audit attempt changed its original segment cursor")
        start_clock = parse_rfc3339(started["started_at"], "attempt clock")
        if not parse_rfc3339(latest, "prior completion") <= start_clock <= exported:
            raise CaptureError("capture audit attempt clock is inconsistent")
        if (set(completed) != {"schema_version", "sequence", "capture_id", "capture_plan_sha256", "segment_id", "started_sha256", "outcome", "completed_at", "body_evidence", "receipt_evidence", "failure", "native_row_count", "next_page_token"}
                or completed["schema_version"] != _FINISH_SCHEMA or type(completed["sequence"]) is not int or completed["sequence"] != sequence
                or completed["capture_id"] != plan.capture_id or completed["capture_plan_sha256"] != started["capture_plan_sha256"]
                or completed["segment_id"] != started["segment_id"] or completed["started_sha256"] != starts[sequence]["sha256"]
                or type(completed["native_row_count"]) is not int or completed["native_row_count"] < 0):
            raise CaptureError("capture audit completion differs from its original attempt")
        completion_clock = parse_rfc3339(completed["completed_at"], "completion clock")
        if not start_clock <= completion_clock <= exported:
            raise CaptureError("capture audit completion clock is inconsistent")
        if completed["outcome"] == "PAGE_RETAINED":
            if completed["failure"] is not None:
                raise CaptureError("capture audit page has a contradictory failure")
            body_ref, receipt_ref = completed["body_evidence"], completed["receipt_evidence"]
            body, receipt_raw = retain(body_ref), retain(receipt_ref)
            if (body_ref["path"] != "source/attempt-%06d.body.raw" % sequence
                    or receipt_ref["path"] != "source/attempt-%06d.receipt.v1.json" % sequence
                    or len(body) > plan.limits["max_response_bytes"] or len(receipt_raw) > 65536):
                raise CaptureError("capture audit page changes its source identity or bound")
            receipt = CaptureReceipt.from_bytes(receipt_raw)
            if (receipt.to_bytes() != receipt_raw or receipt.method != "GET" or receipt.url != QUOTES_URL or receipt.status != 200
                    or receipt.query != expected_query or receipt.body_sha256 != body_ref["sha256"]
                    or receipt.size_bytes != len(body) or receipt.captured_at != completed["completed_at"]
                    or _nanos(expected_query["end"], "query end") > _nanos(receipt.captured_at, "capture receipt")):
                raise CaptureError("capture audit receipt differs from exact native request or body")
            token, count, pair = _native_page(body, expected_query, state["last_pair"], state["signatures"], state["tokens"])
            if token != completed["next_page_token"] or count != completed["native_row_count"]:
                raise CaptureError("capture audit page counters differ from native response replay")
            state["pages"].append({"body_evidence": body_ref, "receipt_evidence": receipt_ref})
            state["rows"] += count; state["bytes"] += len(body) + len(receipt_raw)
            if (len(state["pages"]) > plan.limits["max_pages_per_segment"] or state["rows"] > plan.limits["max_rows_per_segment"]
                    or state["bytes"] > plan.limits["max_segment_bytes"]):
                raise CaptureError("capture audit page exceeds the frozen segment bounds")
            state["next_token"], state["last_pair"] = token, pair
            if token is not None: state["tokens"].add(token)
            state["status"], state["failure"] = ("COMPLETE" if token is None else "INCOMPLETE"), None
        elif completed["outcome"] in {"FAILED", "INTERRUPTED"}:
            failure = completed["failure"]
            if (not isinstance(failure, dict) or set(failure) != {"code", "http_status"} or failure["code"] not in _FAILURES
                    or (failure["http_status"] is not None and (type(failure["http_status"]) is not int or not 100 <= failure["http_status"] <= 599))
                    or completed["body_evidence"] is not None or completed["receipt_evidence"] is not None
                    or completed["native_row_count"] != 0 or completed["next_page_token"] is not None
                    or (completed["outcome"] == "INTERRUPTED" and failure != {"code": "INTERRUPTED", "http_status": None})):
                raise CaptureError("capture audit failure disposition is inconsistent")
            state["status"], state["failure"] = "UNAVAILABLE", failure
        else:
            raise CaptureError("capture audit has an unknown completion outcome")
        previous, latest = finishes[sequence]["sha256"], completed["completed_at"]
    retained = sum(map(len, evidence.values()))
    if retained != snapshot.retained_bytes or retained > plan.limits["max_capture_bytes"]:
        raise CaptureError("capture audit retained-byte count differs from exact verified evidence")
    expected_segments = []
    for segment in plan.segments:
        state = states[segment["segment_id"]]
        failure = state["failure"]
        limit = _limited(state, plan, len(starts), retained)
        if failure is None and state["status"] != "COMPLETE" and limit:
            failure = {"code": limit, "http_status": None}
        expected_segments.append({"segment_id": segment["segment_id"], "pages": state["pages"], "status": state["status"], "failure": failure})
    if snapshot.segments != expected_segments:
        raise CaptureError("capture audit segment status, page identity or failure differs from checkpoint replay")
    return {"snapshot": snapshot.to_dict(), "evidence": evidence}
