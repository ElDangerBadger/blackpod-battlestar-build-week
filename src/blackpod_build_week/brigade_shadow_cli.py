"""Explicit shadow assessment, retained replay and opt-in local text capture."""
import argparse
from html import escape
import json
import os
from pathlib import Path
import sys

from .contracts.brigade_shadow import BrigadeShadowRequest
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write, load_evidence
from .forecast_journal import assess_brigade_shadow, build_brigade_shadow_event, evidence_for_brigade_shadow
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError


def build_parser():
    parser = argparse.ArgumentParser(description="Brigade SHADOW recommendations; never execution or activation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("assess", "record", "generate", "recover"):
        sub = commands.add_parser(name)
        sub.add_argument("--journal-root", type=Path, required=True)
        sub.add_argument("--request", type=Path, required=True)
        sub.add_argument("--evidence-root", type=Path)
        if name in {"generate", "recover"}:
            sub.add_argument("--output-directory", type=Path, required=True)
        if name == "generate":
            sub.add_argument("--modeldock-shadow", action="store_true", required=True)
            sub.add_argument("--modeldock-base-url")
            sub.add_argument("--modeldock-timeout-seconds", type=float)
            sub.add_argument("--modeldock-delivery-grace-seconds", type=float)
    for name in ("show", "render"):
        sub = commands.add_parser(name)
        sub.add_argument("--journal-root", type=Path, required=True)
        sub.add_argument("--event-id", required=True)
        if name == "render":
            sub.add_argument("--output", type=Path, required=True)
    return parser


def render_brigade_review(event):
    if event.event_type != "BRIGADE_SHADOW_ANALYSIS_RECORDED":
        raise ValueError("a Brigade report requires a verified shadow analysis")
    request, packet = event.payload["request"], event.payload["analysis"]
    text = lambda value: escape(str(value), quote=True)
    structured_evidence = ""
    if request.get("response_contract") is not None:
        transcripts = ''.join('<details><summary>' + text(row["request"]["symbol"]) + ' · ' + text(row["request"]["member"]) +
            '</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + text(row["response_text"] if row["response_text"] is not None else row["error_code"]) + '</pre></details>'
            for row in packet["response_transcripts"])
        structured_evidence = '<section><h2>Versioned structured response evidence</h2><p>' + text(request["response_contract"]) + \
            '. Each typed response binds its member and symbol. Confidence remains a heuristic label. Strict validation rejects malformed content without repairs or legacy-label fallback; invalid native defaults remain evidence and contribute no vote.</p>' + transcripts + '</section>'
    rows = []
    for row in packet["forecast_result"]["rows"]:
        rows.append('<tr><td>' + text(row["symbol"]) + '</td><td>' + text(row["source_date"]) + '<small>' + text(row["source_time_precision"]) + '</small></td><td>'
            + text(row["horizon_count"]) + ' · ' + text(row["horizon_unit"] or 'unit unverified') + '<small>' + text(row["target_at"]) + '</small></td><td>' + text(row["q10"]) + ' / ' + text(row["q50"]) + ' / ' + text(row["q90"]) + '<small>' + text(row["units"] or 'Units unverified') + '</small>'
            + '</td><td>' + text(row["gate"]) + '<small>' + text(', '.join(row["reason_codes"])) + '</small></td></tr>')
    members = []
    for symbol in packet["symbols"]:
        opinions = {opinion["member"]: opinion for opinion in symbol["opinions"]}
        for coverage in symbol["member_coverage"]:
            opinion = opinions.get(coverage["member"], {})
            members.append('<tr><td>' + text(symbol["symbol"]) + '</td><td>' + text(coverage["member"]) + '</td><td>' + text(coverage["status"]) + '</td><td>'
                + text(opinion.get("recommendation")) + '</td><td>' + text(opinion.get("confidence_label")) + ' <small>Heuristic, not probability</small></td><td>'
                + text(', '.join(coverage["reason_codes"])) + '<details><summary>Retained reasoning</summary><p>' + text(opinion.get("reasoning")) + '</p></details></td></tr>')
        decay = symbol["decay"]
        members.append('<tr><td>' + text(symbol["symbol"]) + '</td><td>Blackwell_Decay · separate observed calculation</td><td>' + text(decay["status"]) + '</td><td>'
            + text(decay["recommendation"]) + '</td><td>Heuristic only</td><td>' + text(', '.join(decay["reason_codes"])) + '</td></tr>')
    dissent = '<br>'.join(text(symbol["symbol"]) + ': ' + text(json.dumps(symbol["dissent"], sort_keys=True)) for symbol in packet["symbols"])
    retained_sources = ''.join('<li>' + text(ref["path"]) + ' <code>' + text(ref["sha256"]) + '</code></li>' for ref in event.evidence)
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BlackPod · Forecast and Brigade shadow review</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf1f5;color:#182b3a;font:15px/1.6 system-ui,sans-serif}main{max-width:1250px;margin:auto;padding:26px}header{background:#153047;color:white;border-radius:13px;padding:26px;margin-bottom:22px}h1{font-size:30px;line-height:1.3}h2{font-size:22px}section{background:white;border:1px solid #d3dce5;border-radius:10px;padding:24px;margin-bottom:22px}.badge{display:inline-block;border:1px solid #86bdaf;border-radius:6px;padding:4px 10px;margin:4px 8px 4px 0;font-size:12px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dbe3ea;padding:12px}th{background:#f1f5f8}small{display:block;color:#596c7d;font-size:11px;overflow-wrap:anywhere}.note{border-left:3px solid #b88e4a;background:#faf5eb;padding:14px}code{font-size:11px;overflow-wrap:anywhere}li{margin:8px 0}summary{cursor:pointer;color:#225b7a}footer{font-size:12px;overflow-wrap:anywhere}@media(max-width:700px){main{padding:12px}header,section{padding:18px}h1{font-size:25px}}</style></head><body><main><header>
<h1>Governed forecast intake &amp; Brigade shadow review</h1><span class="badge">SHADOW ONLY</span><span class="badge">AUTOMATION AUTHORITY OFF</span><span class="badge">NO ORDERS OR ALLOCATION</span><p>Recorded analysis clock: ''' + text(request["generated_at"]) + ' · recorded ' + text(request["recorded_at"]) + '''. Current runtime status is checked separately.</p></header>
<section><h2>Evidence before recommendations</h2><p>''' + str(packet["forecast_result"]["admitted_count"]) + ' forecast rows admitted at the frozen intake clock; ' + str(packet["forecast_result"]["deferred_count"]) + ''' deferred. Admission checks source-bound review, observed timestamps, target sessions and supported units. It does not authenticate a producer, verify model training, calibrate probabilities or establish investment value.</p>
<p class="note">Generation-time eligibility is reported separately below. A forecast admitted earlier can expire before a member runs. Default inference is disabled; imported response text is evidence, never permission to trade.</p><p>''' + text(packet["response_capture_status"]) + ' · ' + text(request["inference_mode"]) + '''. Five native personas share the forecast, observed market data and interpretation-model evidence; their agreement is not independent validation or authorization.</p></section>
<section><h2>Forecast values and horizons</h2><div class="table"><table><thead><tr><th>Symbol</th><th>Original source date</th><th>Explicit target</th><th>Raw Q10 / Q50 / Q90 · declared units</th><th>Intake gate</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div>
<p>Admissible inputs require predicted USD close-price levels, not returns or calibrated probabilities. Historical imports keep missing units and times unverified. The supported interface covers one to five declared trading sessions; it does not supply a longer-horizon investment thesis.</p></section>
<section><h2>Native member coverage and dissent</h2><div class="table"><table><thead><tr><th>Symbol</th><th>Member</th><th>Generation gate</th><th>Recommendation</th><th>Confidence label</th><th>Evidence or deferral</th></tr></thead><tbody>''' + ''.join(members) + '''</tbody></table></div><p>Preserved dissent: ''' + dissent + '''</p>
<p class="note">Observed closes and volume drive the shadow context. Pathfinder's path spans future predicted levels, not elapsed history. Actual Decay runs separately on observed closes with timestamp-aligned benchmark data; it is not legacy Watchtower coverage. Native trade-plan construction is suppressed.</p></section>
<section><h2>Governed local inference and recovery</h2><p>Only an explicit ModelDock shadow capture may make local text requests. The appliance owns model selection and sampling; the native requested temperature is not transmitted as an override. Requests and sanitized response provenance are retained. A consumed or interrupted attempt cannot automatically retry; recovery replays saved receipts and defers missing members.</p><p>Forecasts, recommendations, authorizations and executable orders remain different concepts. This review creates no authorization or order, changes no policy, installs no ownership and moves no capital. No realized trade P&amp;L or subsequent evaluation has been invented.</p></section>
''' + structured_evidence + '''<section><details><summary>Retained evidence and versioning</summary><p>''' + text(event.event_id) + ' · ' + text(request["analysis_id"]) + '''. Replay checks original input, source code, native prompts, responses and derived opinions without calling a model. Provenance declarations and sanitized captures are not cryptographic provider attestation.</p><ul>''' + retained_sources + '''</ul></details></section><footer>BlackPod · passive journal ''' + text(event.schema_version.rsplit('.', 1)[-1]) + ' · ' + text(packet["context_policy_version"]) + ''' · Every authority remains disabled.</footer></main></body></html>'''


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        events, blobs = store.verified_contents() if store.root.exists() else ((), {})
        if args.command in {"show", "render"}:
            event = next((item for item in events if item.event_id == args.event_id and item.event_type == "BRIGADE_SHADOW_ANALYSIS_RECORDED"), None)
            if event is None:
                raise ValueError("unknown verified Brigade shadow analysis")
            if args.command == "show":
                output = event.to_dict()
            else:
                raw = render_brigade_review(event).encode("utf-8")
                _write(args.output, raw, (store.root,))
                output = {"path": str(args.output.absolute()), "sha256": sha256_bytes(raw)}
        else:
            request = BrigadeShadowRequest.from_bytes(read_regular(args.request))
            if args.evidence_root is not None:
                check_separate_root(store.root, args.evidence_root)
                blobs = load_evidence(args.evidence_root, _references(request.to_dict()), blobs)
            if args.command in {"generate", "recover"}:
                from .brigade_shadow_transport import capture_modeldock
                check_separate_root(args.output_directory, store.root)
                if args.evidence_root is not None:
                    check_separate_root(args.output_directory, args.evidence_root)
                config = None
                if args.command == "generate" and any(getattr(args, key) is not None for key in ("modeldock_base_url", "modeldock_timeout_seconds", "modeldock_delivery_grace_seconds")):
                    from .modeldock_config import load_modeldock_config
                    environment = dict(os.environ)
                    for key, variable in (("modeldock_base_url", "MODELDOCK_BASE_URL"), ("modeldock_timeout_seconds", "MODELDOCK_TIMEOUT_SECONDS"), ("modeldock_delivery_grace_seconds", "MODELDOCK_DELIVERY_GRACE_SECONDS")):
                        value = getattr(args, key)
                        if value is not None:
                            environment[variable] = str(value)
                    config = load_modeldock_config(environ=environment)
                output = capture_modeldock(request, events, blobs, args.output_directory, config=config, recover=args.command == "recover")
            else:
                event = build_brigade_shadow_event(request, events, blobs)
                output = {"event_id": event.event_id, "decision_id": event.decision_id, **event.payload}
                if args.command == "record":
                    appended = store.append(event, evidence_for_brigade_shadow(request, events, blobs))
                    output.update(written=appended.written, sequence=appended.sequence)
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, KeyError, RecursionError) as exc:
        print("brigade-shadow: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
