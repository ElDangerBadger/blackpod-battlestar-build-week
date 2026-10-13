"""Append-only v19 market-evidence plans, raw segments and compact exports."""
from .contracts.decision_journal import JournalEvent
from .contracts.train_market_evidence import JOURNAL_VERSION, PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE
from .train_market_evidence import plan_context, segment_context, export_context, implementation_evidence, refs
from .hashing import sha256_bytes
from .trading_research_journal import identity


def _event(context, event_type):
    document = context["plan"] if event_type == PLAN_TYPE else context["request"]
    key = "capture_id" if event_type == PLAN_TYPE else "export_id"
    kind = {PLAN_TYPE: "TRAIN_MARKET_CAPTURE_PLAN", SEGMENT_TYPE: "TRAIN_MARKET_CAPTURE_SEGMENT", EXPORT_TYPE: "TRAIN_MARKET_CAPTURE_EXPORT"}[event_type]
    identities = {"decision_id": context["parent"].decision_id, "event_type": event_type, key: getattr(document, key)}
    source = {"kind": kind, key: getattr(document, key), "source_sha256": sha256_bytes(document.to_bytes())}
    if event_type == SEGMENT_TYPE: source["segment_id"] = document.segment_id; identities["segment_id"] = document.segment_id
    payload = {"plan": document.to_dict()} if event_type == PLAN_TYPE else {"request": document.to_dict(), "result": context["result"]}
    return JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING", "event_id": identity("journal-event", identities),
        "decision_id": context["parent"].decision_id, "event_type": event_type, "recorded_at": getattr(document, "created_at" if event_type == PLAN_TYPE else "exported_at"),
        "source": source, "evidence": refs(context["evidence"]), "payload": {**payload, "links": context["links"], "implementation_evidence": refs(implementation_evidence())}})


def capture_plan_material(plan, events, blobs):
    context = plan_context(plan, events, blobs)
    return {"event": _event(context, PLAN_TYPE), "evidence": context["evidence"]}

def segment_material(request, events, blobs):
    context = segment_context(request, events, blobs)
    return {"event": _event(context, SEGMENT_TYPE), "evidence": context["evidence"], "result": context["result"]}

def export_material(request, events, blobs):
    context = export_context(request, events, blobs)
    return {"event": _event(context, EXPORT_TYPE), "evidence": context["evidence"], "result": context["result"]}

def validate_train_market_event(event, previous, blobs):
    field = "plan" if event.event_type == PLAN_TYPE else "request"
    builder = {PLAN_TYPE: capture_plan_material, SEGMENT_TYPE: segment_material, EXPORT_TYPE: export_material}[event.event_type]
    if builder(event.payload[field], previous, blobs)["event"].to_bytes() != event.to_bytes(): raise ValueError("TRAIN export differs from exact frozen source replay")
