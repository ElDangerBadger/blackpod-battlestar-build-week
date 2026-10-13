"""Invocation-local capture state with full replay at both locked boundaries.

This additive runner writes the original immutable checkpoint format. It never
trusts a cache across invocations, widens a frozen limit, or bypasses native page
validation. The pinned v19 runner remains unchanged and verifies its output.
"""
import time
from http.client import HTTPException

from . import train_market_capture as original
from .contracts.mission_request import normalize_rfc3339, parse_rfc3339
from .contracts.trading_evidence_capture import CaptureReceipt
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import PaperCredentials, _credential_literal
from .trading_cost_intake import QUOTES_URL

METHOD_VERSION = "blackpod.invocation_local_train_capture.v2"


def capture_train_quotes_incremental(plan, output_root, credentials, *, source_blobs=None,
        request_budget=None, transport=original.market_get, clock=original.utc_now,
        sleeper=time.sleep):
    """Use locked, verified temporary state; replay the entire durable result.

    Every invocation revalidates original source proof and all retained native
    pages. Every new page goes through the original native validator before
    publication. All state is discarded on exit. A final full replay rejects
    external tampering; interrupted publication recovers via the original reader.
    """
    root = original._safe_root(output_root)
    with original._lock(root, create=True):
        if not isinstance(credentials, PaperCredentials):
            raise original.CaptureError("capture requires explicit literal credentials in memory")
        _credential_literal(credentials.key_id)
        _credential_literal(credentials.secret_key)
        plan = original._inputs(plan, root, source_blobs, initialize=True, credentials=credentials)
        if plan.evidence_scope == "SYNTHETIC_FIXTURE_ONLY" and transport is original._NETWORK_TRANSPORT:
            raise original.CaptureError("synthetic capture cannot contact a provider")
        budget = plan.limits["max_requests_per_invocation"] if request_budget is None else request_budget
        if type(budget) is not int or not 0 <= budget <= plan.limits["max_requests_per_invocation"]:
            raise original.CaptureError("request budget exceeds the frozen invocation bound")
        now = normalize_rfc3339(clock(), "capture clock")
        if parse_rfc3339(now, "capture clock") < parse_rfc3339(plan.created_at, "plan freeze"):
            raise original.CaptureError("capture cannot predate its frozen plan")
        states, retained_evidence, _, attempts, previous, _ = original._load(plan, root, now)
        latest_completed = (original.parse_strict_json_object_bytes(
            retained_evidence["attempts/attempt-%06d.completed.v1.json" % attempts])["completed_at"]
            if attempts else plan.created_at)
        # Native history remains on disk and in the journal; only cursor state
        # is needed inside this invocation. No body corpus is held as a cache.
        del retained_evidence
        requests, stop, prior_clock = 0, None, now
        while True:
            state = next((states[segment["segment_id"]] for segment in plan.segments
                if states[segment["segment_id"]]["status"] != "COMPLETE"), None)
            if state is None:
                break
            disk_bytes = original._disk_bytes(root)
            stop = original._limited(state, plan, attempts, disk_bytes)
            if stop is not None or requests >= budget:
                stop = stop or "INVOCATION_REQUEST_BUDGET"
                break
            if requests or attempts:
                sleeper(plan.limits["min_request_interval_ms"] / 1000)
            now = normalize_rfc3339(clock(), "capture clock")
            if parse_rfc3339(now, "attempt clock") < max(parse_rfc3339(value, "prior capture clock")
                    for value in (plan.created_at, prior_clock, latest_completed)):
                raise original.CaptureError("capture attempt clock moved backwards before request")
            prior_clock = now
            query = dict(state["segment"]["query"])
            if state["next_token"] is not None:
                query["page_token"] = state["next_token"]
            sequence = attempts + 1
            started = {"schema_version": original._START_SCHEMA, "sequence": sequence,
                "capture_id": plan.capture_id, "capture_plan_sha256": sha256_bytes(plan.to_bytes()),
                "segment_id": state["segment"]["segment_id"], "query": query,
                "started_at": now, "previous_completed_sha256": previous}
            original._immutable(root / ("attempts/attempt-%06d.started.v1.json" % sequence),
                canonical_json_bytes(started))
            requests += 1
            response_limit = min(plan.limits["max_response_bytes"],
                plan.limits["max_segment_bytes"] - state["bytes"] - 16384,
                plan.limits["max_capture_bytes"] - disk_bytes - 16384)
            try:
                response = transport(query, credentials, timeout=plan.limits["timeout_seconds"],
                    max_response_bytes=response_limit)
                if not isinstance(response, original.MarketResponse) or type(response.status) is not int or response.status != 200:
                    raise original.CaptureTransportError("HTTP_ERROR", getattr(response, "status", None))
                if not isinstance(response.body, bytes):
                    raise original.CaptureTransportError("INVALID_RESPONSE")
                if len(response.body) > response_limit:
                    raise original.CaptureTransportError("RESPONSE_TOO_LARGE", 200)
                original._check_sensitive(response.body, credentials)
                signatures, tokens = set(state["signatures"]), set(state["tokens"])
                try:
                    token, count, last_pair = original._native_page(
                        response.body, query, state["last_pair"], signatures, tokens)
                except (ValueError, TypeError, RecursionError):
                    raise original.CaptureTransportError("INVALID_RESPONSE") from None
                if state["rows"] + count > plan.limits["max_rows_per_segment"]:
                    raise original.CaptureTransportError("SEGMENT_ROW_LIMIT")
                now = normalize_rfc3339(clock(), "receipt clock")
                if parse_rfc3339(now, "receipt clock") < parse_rfc3339(started["started_at"], "attempt clock"):
                    raise original.CaptureError("capture receipt clock moved backwards")
                receipt = CaptureReceipt.from_mapping({"schema_version": "blackpod.trading_evidence_capture.v1",
                    "method": "GET", "url": QUOTES_URL, "query": query, "captured_at": now, "status": 200,
                    "body_sha256": sha256_bytes(response.body), "size_bytes": len(response.body)})
            except original.CaptureTransportError as exc:
                now = normalize_rfc3339(clock(), "failure clock")
                original._finish(root, started, "FAILED", now,
                    failure={"code": exc.code, "http_status": exc.http_status})
                stop = exc.code
                break
            except original.CaptureError:
                raise
            except (OSError, HTTPException, ValueError, TypeError):
                now = normalize_rfc3339(clock(), "failure clock")
                original._finish(root, started, "FAILED", now,
                    failure={"code": "TRANSPORT_ERROR", "http_status": None})
                stop = "TRANSPORT_ERROR"
                break
            body_path = "source/attempt-%06d.body.raw" % sequence
            receipt_path = "source/attempt-%06d.receipt.v1.json" % sequence
            body_ref = original._ref(body_path, response.body)
            receipt_ref = original._ref(receipt_path, receipt.to_bytes())
            try:
                original._immutable(root / body_path, response.body)
                original._immutable(root / receipt_path, receipt.to_bytes())
                completed = original._finish(root, started, "PAGE_RETAINED", now,
                    body_ref=body_ref, receipt_ref=receipt_ref, rows=count, token=token)
            except (OSError, ValueError):
                raise original.CaptureError("capture publication interrupted; verify durable recovery") from None
            # Advance only after immutable raw bytes and checkpoint publication.
            attempts = sequence
            previous = sha256_bytes(canonical_json_bytes(completed))
            latest_completed = prior_clock = now
            state["next_token"], state["last_pair"] = token, last_pair
            state["signatures"], state["tokens"] = signatures, tokens
            if token is not None:
                state["tokens"].add(token)
            state["pages"].append({"body_evidence": body_ref, "receipt_evidence": receipt_ref})
            state["rows"] += count
            state["bytes"] += len(response.body) + len(receipt.to_bytes())
            state["status"], state["failure"] = ("COMPLETE" if token is None else "INCOMPLETE"), None
        states, _, _, attempts, _, retained = original._load(plan, root,
            normalize_rfc3339(clock(), "final capture clock"))
        complete = sum(state["status"] == "COMPLETE" for state in states.values())
        return {"capture_id": plan.capture_id, "requests_this_invocation": requests,
            "attempt_count": attempts, "complete_segment_count": complete, "segment_count": len(states),
            "pagination_complete": complete == len(states), "coverage_verified": False,
            "stop_reason": stop, "retained_bytes": retained, "orders_submitted": 0,
            "auto_trading_enabled": False, "runner_method_version": METHOD_VERSION}
