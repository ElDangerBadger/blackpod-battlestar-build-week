#!/usr/bin/env python3
"""
Parse run_brigade_senate terminal output logs into:
- JSON: full structured representation
- CSV: per-symbol summary rows
- MD: human-friendly report

Designed for the format shown in the user's terminal output:
- "🔬 Analyzing SYMBOL"
- "📋 Blackwell Brigade Analysis:" followed by 5 module votes
- "🏛️ Senate Vote:" followed by 5 senator votes
- "📊 DECISION: ..."
- "============================================================" separators
Also tolerates partial/truncated runs (e.g., KeyboardInterrupt mid-symbol).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


RE_ANALYZING = re.compile(r"^\s*🔬\s*Analyzing\s+([A-Z0-9\.\-]+)\s*$")
RE_BRIGADE_LINE = re.compile(
    r"^\s*Blackwell_(\w+):\s*(BUY|EXIT|HOLD|WATCH)\s*\(confidence=([0-9]*\.?[0-9]+)\)\s*$"
)
RE_BRIGADE_REASON = re.compile(r"^\s*→\s*(.*)\s*$")

RE_SENATE_LINE = re.compile(
    r"^\s*[✓✗]\s*Sen\.\s*([A-Za-z ]+):\s*(LONG|SHORT|HOLD)\s*@\s*([0-9]*\.?[0-9]+)\s*$"
)
RE_SENATE_REASON = re.compile(r"^\s*→\s*(.*)\s*$")

RE_DECISION = re.compile(
    r"^\s*📊\s*DECISION:\s*(LONG|SHORT|HOLD)\s*@\s*([0-9]*\.?[0-9]+)\s*$"
)
RE_COHESION = re.compile(r"^\s*Cohesion:\s*([0-9]+)%\s*\((\d+)/(\d+)\s*agree\)\s*$")
RE_DISSENT = re.compile(r"^\s*Dissent:\s*(.*)\s*$")

RE_AI_CALL = re.compile(r"^\s*🤖\s*AI call completed in\s*([0-9]*\.?[0-9]+)s\s*$")
RE_SEPARATOR = re.compile(r"^\s*=+\s*$")


@dataclass
class BrigadeVote:
    module: str
    action: str
    confidence: float
    reasoning: str = ""


@dataclass
class SenateVote:
    senator: str
    direction: str
    confidence: float
    reasoning: str = ""


@dataclass
class FinalDecision:
    direction: str
    confidence: float
    cohesion_pct: Optional[int] = None
    cohesion_agree: Optional[int] = None
    cohesion_total: Optional[int] = None
    dissent: List[str] = None  # senator names
    raw_dissent_line: str = ""


@dataclass
class SymbolReport:
    symbol: str
    ai_calls_seconds: List[float]
    brigade: List[BrigadeVote]
    senate: List[SenateVote]
    decision: Optional[FinalDecision]
    incomplete: bool = False
    notes: List[str] = None


def _safe_float(x: str, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def parse_log(text: str) -> Dict[str, Any]:
    lines = text.splitlines()

    reports: List[SymbolReport] = []
    current: Optional[SymbolReport] = None

    mode = None  # None | "brigade" | "senate"
    pending_brigade_reason_for: Optional[int] = None
    pending_senate_reason_for: Optional[int] = None

    def finalize_current(mark_incomplete: bool = False, note: str = ""):
        nonlocal current
        if not current:
            return
        if current.notes is None:
            current.notes = []
        if note:
            current.notes.append(note)
        if mark_incomplete and not current.incomplete:
            current.incomplete = True
        reports.append(current)
        current = None

    for i, line in enumerate(lines):
        # New symbol begins
        m = RE_ANALYZING.match(line)
        if m:
            # If previous symbol didn't get a decision, mark incomplete
            if current is not None:
                finalize_current(mark_incomplete=True, note="New symbol started before prior symbol completed.")
            sym = m.group(1).strip()
            current = SymbolReport(
                symbol=sym,
                ai_calls_seconds=[],
                brigade=[],
                senate=[],
                decision=None,
                incomplete=False,
                notes=[],
            )
            mode = None
            pending_brigade_reason_for = None
            pending_senate_reason_for = None
            continue

        if current is None:
            # Ignore preamble noise until first symbol
            continue

        # Track AI calls
        m = RE_AI_CALL.match(line)
        if m:
            current.ai_calls_seconds.append(_safe_float(m.group(1)))
            continue

        # Mode switches
        if "📋 Blackwell Brigade Analysis" in line:
            mode = "brigade"
            continue
        if "🏛️ Senate Vote" in line:
            mode = "senate"
            continue

        # Brigade vote line + its subsequent "→" reasoning line
        if mode == "brigade":
            mb = RE_BRIGADE_LINE.match(line)
            if mb:
                module = mb.group(1).strip()
                action = mb.group(2).strip()
                conf = _safe_float(mb.group(3))
                current.brigade.append(BrigadeVote(module=f"Blackwell_{module}", action=action, confidence=conf))
                pending_brigade_reason_for = len(current.brigade) - 1
                continue

            mr = RE_BRIGADE_REASON.match(line)
            if mr and pending_brigade_reason_for is not None:
                current.brigade[pending_brigade_reason_for].reasoning = mr.group(1).strip()
                pending_brigade_reason_for = None
                continue

        # Senate vote line + its reasoning
        if mode == "senate":
            ms = RE_SENATE_LINE.match(line)
            if ms:
                senator = ms.group(1).strip()
                direction = ms.group(2).strip()
                conf = _safe_float(ms.group(3))
                current.senate.append(SenateVote(senator=senator, direction=direction, confidence=conf))
                pending_senate_reason_for = len(current.senate) - 1
                continue

            mr = RE_SENATE_REASON.match(line)
            if mr and pending_senate_reason_for is not None:
                # Some senator reasonings are multi-sentence; keep one line per original output line.
                existing = current.senate[pending_senate_reason_for].reasoning
                addition = mr.group(1).strip()
                current.senate[pending_senate_reason_for].reasoning = (existing + " " + addition).strip() if existing else addition
                continue

        # Decision block
        md = RE_DECISION.match(line)
        if md:
            direction = md.group(1).strip()
            conf = _safe_float(md.group(2))
            current.decision = FinalDecision(direction=direction, confidence=conf, dissent=[], raw_dissent_line="")
            continue

        if current.decision:
            mc = RE_COHESION.match(line)
            if mc:
                current.decision.cohesion_pct = int(mc.group(1))
                current.decision.cohesion_agree = int(mc.group(2))
                current.decision.cohesion_total = int(mc.group(3))
                continue

            mds = RE_DISSENT.match(line)
            if mds:
                raw = mds.group(1).strip()
                current.decision.raw_dissent_line = raw
                # Split by commas, strip prefixes like "Sen."
                parts = [p.strip() for p in raw.split(",") if p.strip()]
                cleaned = []
                for p in parts:
                    p = re.sub(r"^\s*Sen\.\s*", "", p).strip()
                    cleaned.append(p)
                current.decision.dissent = cleaned
                continue

        # If we hit a separator after having a decision, finalize symbol
        if RE_SEPARATOR.match(line):
            # Separator typically means end of a symbol chunk
            if current.decision is not None:
                finalize_current()
                mode = None
                pending_brigade_reason_for = None
                pending_senate_reason_for = None
            continue

        # Detect crash/interrupt markers that indicate incomplete symbol
        if "KeyboardInterrupt" in line or "Traceback" in line:
            current.incomplete = True
            if current.notes is None:
                current.notes = []
            current.notes.append("Run interrupted or error encountered during this symbol block.")
            # Don't finalize here; allow log to continue if it does.

    # finalize last symbol if present
    if current is not None:
        # Mark incomplete if no decision
        if current.decision is None:
            current.incomplete = True
            current.notes.append("No final decision found for this symbol (likely interrupted).")
        reports.append(current)

    # Convert to dict
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "symbols": [asdict(r) for r in reports],
    }
    return out


def render_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# BlackPod Brigade/Senate Run Report")
    lines.append("")
    lines.append(f"- Generated: `{report.get('generated_at','')}`")
    lines.append(f"- Symbols: `{len(report.get('symbols', []))}`")
    lines.append("")

    for sym in report.get("symbols", []):
        symbol = sym["symbol"]
        incomplete = sym.get("incomplete", False)
        lines.append(f"## {symbol}" + (" ⚠️ Incomplete" if incomplete else ""))
        lines.append("")
        ai_calls = sym.get("ai_calls_seconds", [])
        if ai_calls:
            lines.append(f"- AI calls: {len(ai_calls)} (total `{sum(ai_calls):.2f}s`, avg `{(sum(ai_calls)/len(ai_calls)):.2f}s`)")
        else:
            lines.append(f"- AI calls: 0")
        notes = sym.get("notes") or []
        if notes:
            lines.append(f"- Notes:")
            for n in notes:
                lines.append(f"  - {n}")
        lines.append("")

        # Brigade table
        lines.append("### Brigade")
        lines.append("")
        lines.append("| Module | Action | Conf | Reasoning |")
        lines.append("|---|---:|---:|---|")
        for bv in sym.get("brigade", []):
            _reason = (bv.get("reasoning", "") or "").replace("|", "\\|")
            lines.append(f"| {bv['module']} | {bv['action']} | {bv['confidence']:.2f} | {_reason} |")
        lines.append("")

        # Senate table
        lines.append("### Senate")
        lines.append("")
        lines.append("| Senator | Vote | Conf | Reasoning |")
        lines.append("|---|---:|---:|---|")
        for sv in sym.get("senate", []):
            _reason = (sv.get("reasoning", "") or "").replace("|", "\\|")
            lines.append(f"| {sv['senator']} | {sv['direction']} | {sv['confidence']:.2f} | {_reason} |")
        lines.append("")

        # Decision
        dec = sym.get("decision")
        if dec:
            lines.append("### Decision")
            lines.append("")
            lines.append(f"- **Decision:** `{dec['direction']}` @ `{dec['confidence']:.2f}`")
            if dec.get("cohesion_pct") is not None:
                lines.append(f"- **Cohesion:** `{dec['cohesion_pct']}%` ({dec.get('cohesion_agree')}/{dec.get('cohesion_total')})")
            dissent = dec.get("dissent") or []
            if dissent:
                lines.append(f"- **Dissent:** {', '.join(dissent)}")
            lines.append("")
        else:
            lines.append("### Decision")
            lines.append("")
            lines.append("- **Decision:** *(missing / not parsed)*")
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_summary_csv(report: Dict[str, Any], out_path: str) -> None:
    rows: List[Dict[str, Any]] = []
    for sym in report.get("symbols", []):
        dec = sym.get("decision") or {}
        rows.append({
            "Symbol": sym.get("symbol"),
            "Incomplete": bool(sym.get("incomplete", False)),
            "Decision": dec.get("direction", ""),
            "Decision_Confidence": dec.get("confidence", ""),
            "Cohesion_Pct": dec.get("cohesion_pct", ""),
            "Cohesion_Agree": dec.get("cohesion_agree", ""),
            "Cohesion_Total": dec.get("cohesion_total", ""),
            "Dissent": ", ".join(dec.get("dissent") or []),
            "AI_Calls": len(sym.get("ai_calls_seconds") or []),
            "AI_Total_Sec": f"{sum(sym.get('ai_calls_seconds') or []):.2f}",
        })

    fieldnames = [
        "Symbol",
        "Incomplete",
        "Decision",
        "Decision_Confidence",
        "Cohesion_Pct",
        "Cohesion_Agree",
        "Cohesion_Total",
        "Dissent",
        "AI_Calls",
        "AI_Total_Sec",
    ]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", help="Path to captured terminal output log (txt).")
    ap.add_argument("--outdir", default="reports", help="Output directory root.")
    ap.add_argument("--date", default="", help="Optional date folder (YYYY-MM-DD). Default: today.")
    args = ap.parse_args()

    with open(args.logfile, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    report = parse_log(text)

    date_folder = args.date.strip() or datetime.now().strftime("%Y-%m-%d")
    outdir = os.path.join(args.outdir, date_folder)
    os.makedirs(outdir, exist_ok=True)

    json_path = os.path.join(outdir, "run_report.json")
    md_path = os.path.join(outdir, "run_report.md")
    csv_path = os.path.join(outdir, "run_summary.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    write_summary_csv(report, csv_path)

    print(f"✅ Wrote:\n- {json_path}\n- {md_path}\n- {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())