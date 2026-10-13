"""
agents/blackwell_brigade_v2_expanded.py

EXPANDED Brigade with complementary specialties:
1. Scout (skew/momentum)
2. Sentry (tail risk)
3. Advisor (regime/macro)
4. Canary (volume/liquidity specialist)
5. Pathfinder (pattern recognition specialist)
6. Decay (OPTIONAL - multi-day drift/bleed detector; emits only when triggered)

This creates more diverse analysis with:
- 3 quantitative agents (Scout, Sentry, Advisor)
- 1 volume specialist (Canary)
- 1 pattern specialist (Pathfinder)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from pathlib import Path
import pandas as pd  # type: ignore

# Optional: Decay agent (multi-day drift / bleed detector)
try:
    from .decay import DecayAgent  # type: ignore
except Exception:
    DecayAgent = None  # type: ignore


# ----------------------------------------------------------------------------
# TradePlan dataclass and builder (from v2)
# ----------------------------------------------------------------------------

@dataclass
class TradePlan:
    """Concrete, execution-ready trade guidance derived from an agent opinion."""
    symbol: str
    intent: str  # ENTER_LONG, EXIT, NONE
    entry: Optional[float] = None
    stop: Optional[float] = None
    take_profit: Optional[float] = None
    qty: Optional[int] = None
    notional: Optional[float] = None
    order_type: str = "MARKET"
    time_in_force: str = "DAY"
    risk_dollars: Optional[float] = None
    notes: str = ""


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def build_trade_plan(
    *,
    symbol: str,
    action: str,
    confidence: float,
    q10: float,
    q50: float,
    q90: float,
    band: float,
    regime: str,
    context: Dict[str, Any],
) -> TradePlan:
    """Translate an agent ACTION + metrics into an execution-oriented trade plan."""

    allow_shorts = bool(context.get("allow_shorts", False))
    account_value = float(context.get("account_value", 0.0) or 0.0)
    risk_per_trade = float(context.get("risk_per_trade", 0.005) or 0.005)
    max_position_pct = float(context.get("max_position_pct", 0.10) or 0.10)
    min_qty = int(context.get("min_qty", 1) or 1)

    risk_scale = _clamp(0.35 + 0.95 * float(confidence), 0.50, 1.25)
    risk_budget = max(0.0, account_value) * max(0.0, risk_per_trade) * risk_scale

    if action in {"EXIT"}:
        return TradePlan(symbol=symbol, intent="EXIT", order_type="MARKET", time_in_force="DAY", notes="Agent voted EXIT.")
    if action in {"HOLD", "WATCH"}:
        return TradePlan(symbol=symbol, intent="NONE", notes="Agent voted HOLD/WATCH.")

    if action == "BUY":
        entry = float(context.get("entry_price", q50))

        if regime == "LOW":
            stop_buffer = 0.35
        elif regime == "HIGH":
            stop_buffer = 0.85
        else:
            stop_buffer = 0.55

        band_stop = entry - (stop_buffer * max(1e-9, band))
        stop = min(float(q10), float(band_stop), entry * 0.995)
        take_profit = max(float(q90), entry + (0.60 * max(1e-9, band)))

        per_share_risk = max(1e-9, entry - stop)
        qty_by_risk = int(risk_budget / per_share_risk) if risk_budget > 0 else 0

        max_notional = max(0.0, account_value) * max(0.0, max_position_pct)
        qty_by_notional = int(max_notional / max(1e-9, entry)) if max_notional > 0 else qty_by_risk

        qty = max(0, min(qty_by_risk, qty_by_notional))

        if account_value <= 0:
            return TradePlan(
                symbol=symbol,
                intent="ENTER_LONG",
                entry=entry,
                stop=stop,
                take_profit=take_profit,
                qty=None,
                notional=None,
                order_type=str(context.get("order_type", "MARKET")),
                time_in_force=str(context.get("time_in_force", "DAY")),
                risk_dollars=None,
                notes="Account sizing inputs missing.",
            )

        if qty < min_qty:
            return TradePlan(
                symbol=symbol,
                intent="ENTER_LONG",
                entry=entry,
                stop=stop,
                take_profit=take_profit,
                qty=0,
                notional=0.0,
                order_type=str(context.get("order_type", "MARKET")),
                time_in_force=str(context.get("time_in_force", "DAY")),
                risk_dollars=0.0,
                notes="Risk budget too small for minimum size.",
            )

        notional = qty * entry
        risk_dollars = qty * per_share_risk

        return TradePlan(
            symbol=symbol,
            intent="ENTER_LONG",
            entry=entry,
            stop=stop,
            take_profit=take_profit,
            qty=qty,
            notional=notional,
            order_type=str(context.get("order_type", "MARKET")),
            time_in_force=str(context.get("time_in_force", "DAY")),
            risk_dollars=risk_dollars,
            notes="Long entry derived from Q50/Q10/Q90 with regime-aware stop buffer.",
        )

    if action == "SELL" and allow_shorts:
        return TradePlan(symbol=symbol, intent="NONE", notes="Short logic not implemented.")

    return TradePlan(symbol=symbol, intent="NONE", notes=f"Unhandled action: {action}")


@dataclass
class BlackwellBrigadeOpinion:
    """Standard output format from any Blackwell Brigade agent"""
    module: str
    action: str  # BUY, EXIT, HOLD, WATCH
    priority: float  # confidence 0.0 to 1.0
    reasoning: str
    supporting_data: Dict[str, Any]
    trade_plan: Optional[TradePlan] = None


class BlackwellBrigadeAgent:
    """Base class for all Blackwell Brigade agents"""

    def __init__(self, name: str, persona: str, ai_client):
        self.name = name
        self.persona = persona
        self.ai = ai_client

    def _extract_action(self, response: str) -> str:
        """Parse ACTION from the model response."""
        for line in response.split("\n"):
            if line.strip().upper().startswith("ACTION:"):
                action = line.split(":", 1)[1].strip().upper()
                if action in {"BUY", "EXIT", "HOLD", "WATCH"}:
                    return action
        return "HOLD"

    def _extract_confidence(self, response: str) -> float:
        """Parse CONFIDENCE from the model response."""
        for line in response.split("\n"):
            if line.strip().upper().startswith("CONFIDENCE:"):
                try:
                    return float(line.split(":", 1)[1].strip())
                except Exception:
                    return 0.55
        return 0.55

    def _extract_reasoning(self, response: str) -> str:
        """Parse REASONING from the model response."""
        for line in response.split("\n"):
            if line.strip().upper().startswith("REASONING:"):
                return line.split(":", 1)[1].strip()
        # Fall back to first non-empty line if model omitted REASONING label
        for line in response.split("\n"):
            s = line.strip()
            if s and not s.upper().startswith(("ACTION:", "CONFIDENCE:")):
                return s
        return "AI decision based on analysis."

    



# ============================================================================
# ORIGINAL 3 AGENTS (Scout, Sentry, Advisor) - UNCHANGED
# ============================================================================

class ScoutAgent(BlackwellBrigadeAgent):
    """Skew and momentum specialist"""

    def __init__(self, ai_client):
        persona = """You are Blackwell Scout, an aggressive field analyst hunting for asymmetric opportunities.

YOUR DECISION FRAMEWORK:

STRONG BUY (confidence 0.75-0.90):
- Positive skew (>0.10) + uptrend + NORMAL/LOW vol

MODERATE BUY (confidence 0.60-0.74):
- Positive skew (>0.05) + uptrend
- OR: Strong uptrend (SMA3 > SMA10 * 1.02)

EXIT (confidence 0.70-0.85):
- Negative skew (<-0.10) + downtrend
- OR: Negative skew in HIGH vol

HOLD (confidence 0.50-0.65):
- ONLY when skew is neutral (-0.05 to +0.05) AND no trend

YOUR PERSONALITY:
You're an opportunist. You'd rather take a 0.60 confidence BUY than sit in cash.
You trust skew asymmetry + momentum more than anything.
"""
        super().__init__("Blackwell_Scout", persona, ai_client)

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Dict[str, Any]) -> BlackwellBrigadeOpinion:
        skew = context.get("skew", 0.0)
        uptrend = context.get("uptrend", False)
        downtrend = context.get("downtrend", False)
        regime = context.get("regime", "NORMAL")
        band = context.get("band", 0.0)
        sma3 = context.get("sma3", 0.0)
        sma10 = context.get("sma10", 0.0)

        trend_strength = ((sma3 / sma10) - 1.0) if sma10 > 0 else 0.0

        prompt = f"""Analyze {symbol} for asymmetric opportunity.

DATA:
- Skew: {skew:.3f}
- Trend: {'UPTREND' if uptrend else 'DOWNTREND' if downtrend else 'FLAT'}
  - Trend strength: {trend_strength:+.2%}
- Volatility Regime: {regime}
- Band Width: {band:.6f}

YOUR CALL:
ACTION: [BUY/EXIT/HOLD]
CONFIDENCE: [0.XX]
REASONING: [Be blunt. Cite skew and trend.]
"""

        response = self.ai.generate(prompt, system=self.persona, temperature=0.7, max_tokens=500)

        action = self._extract_action(response)
        confidence = self._extract_confidence(response)
        reasoning = self._extract_reasoning(response)

        trade_plan = build_trade_plan(
            symbol=symbol,
            action=action,
            confidence=confidence,
            q10=context.get("q10", 0.0),
            q50=context.get("q50", 0.0),
            q90=context.get("q90", 0.0),
            band=band,
            regime=regime,
            context=context,
        )

        return BlackwellBrigadeOpinion(
            module=self.name,
            action=action,
            priority=confidence,
            reasoning=reasoning,
            supporting_data={
                "Symbol": symbol,
                "Skew": round(skew, 4),
                "Trend_Strength": round(trend_strength, 4),
                "Regime": regime,
            },
            trade_plan=trade_plan,
        )


class SentryAgent(BlackwellBrigadeAgent):
    """Tail risk specialist"""

    def __init__(self, ai_client):
        persona = """You are Blackwell Sentry, the risk officer who hates losing money.

YOUR DECISION FRAMEWORK:

EXIT (confidence 0.75-0.90):
- Downside tail > 3%
- OR: Total band > 8%

HOLD (confidence 0.60-0.75):
- Downside tail 2-3%
- OR: Band 6-8%

BUY (confidence 0.65-0.80):
- ONLY if upside tail >> downside (ratio > 2.0)
- AND downside tail < 2%
- AND band < 6%

CRITICAL RULE:
If downside tail > 3%, you ALWAYS vote EXIT.
"""
        super().__init__("Blackwell_Sentry", persona, ai_client)

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Dict[str, Any]) -> BlackwellBrigadeOpinion:
        tail_down = context.get("tail_down_pct", 0.0)
        tail_up = context.get("tail_up_pct", 0.0)
        band_tot = context.get("band_tot_pct", 0.0)

        tail_ratio = (tail_up / tail_down) if tail_down > 0 else 0.0

        prompt = f"""Assess risk profile for {symbol}.

TAIL METRICS:
- Downside tail: {tail_down*100:.2f}%
- Upside tail: {tail_up*100:.2f}%
- Tail ratio (up/down): {tail_ratio:.2f}x
- Total band: {band_tot*100:.2f}%

YOUR CALL:
ACTION: [BUY/EXIT/HOLD]
CONFIDENCE: [0.XX]
REASONING: [Cite specific tail values]
"""

        response = self.ai.generate(prompt, system=self.persona, temperature=0.7, max_tokens=500)

        action = self._extract_action(response)
        confidence = self._extract_confidence(response)
        reasoning = self._extract_reasoning(response)

        trade_plan = build_trade_plan(
            symbol=symbol,
            action=action,
            confidence=confidence,
            q10=context.get("q10", 0.0),
            q50=context.get("q50", 0.0),
            q90=context.get("q90", 0.0),
            band=context.get("band", 0.0),
            regime=context.get("regime", "NORMAL"),
            context=context,
        )

        return BlackwellBrigadeOpinion(
            module=self.name,
            action=action,
            priority=confidence,
            reasoning=reasoning,
            supporting_data={
                "Symbol": symbol,
                "tail_down_pct": round(tail_down, 4),
                "tail_up_pct": round(tail_up, 4),
                "tail_ratio": round(tail_ratio, 2),
                "band_total_pct": round(band_tot, 4),
            },
            trade_plan=trade_plan,
        )


class AdvisorAgent(BlackwellBrigadeAgent):
    """Regime-aware strategist"""

    def __init__(self, ai_client):
        persona = """You are Blackwell Advisor, a macro strategist who adapts to market regimes.

YOUR DECISION FRAMEWORK:

LOW vol: BUY if z > 0.3, EXIT if z < -0.3
NORMAL vol: BUY if z > 0.5, EXIT if z < -0.5
HIGH vol: BUY if z > 0.7, EXIT if z < -0.3

PERSONALITY:
You adjust your risk appetite based on volatility regime.
In HIGH vol, demand strong conviction.
In LOW vol, take smaller edges.
"""
        super().__init__("Blackwell_Advisor", persona, ai_client)

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Dict[str, Any]) -> BlackwellBrigadeOpinion:
        z_score = context.get("z_score", 0.0)
        regime = context.get("regime", "NORMAL")
        reg_ratio = context.get("reg_ratio", 1.0)

        if regime == "LOW":
            buy_threshold = 0.3
            exit_threshold = -0.3
        elif regime == "HIGH":
            buy_threshold = 0.7
            exit_threshold = -0.3
        else:
            buy_threshold = 0.5
            exit_threshold = -0.5

        prompt = f"""Analyze {symbol} in regime context.

MACRO CONTEXT:
- Z-score (20-day): {z_score:.2f}
- Regime: {regime} (ratio={reg_ratio:.2f})
- BUY threshold: z > {buy_threshold}
- EXIT threshold: z < {exit_threshold}

YOUR CALL:
ACTION: [BUY/EXIT/HOLD]
CONFIDENCE: [0.XX]
REASONING: [Explain regime adjustment]
"""

        response = self.ai.generate(prompt, system=self.persona, temperature=0.7, max_tokens=500)

        action = self._extract_action(response)
        confidence = self._extract_confidence(response)
        reasoning = self._extract_reasoning(response)

        trade_plan = build_trade_plan(
            symbol=symbol,
            action=action,
            confidence=confidence,
            q10=context.get("q10", 0.0),
            q50=context.get("q50", 0.0),
            q90=context.get("q90", 0.0),
            band=context.get("band", 0.0),
            regime=regime,
            context=context,
        )

        return BlackwellBrigadeOpinion(
            module=self.name,
            action=action,
            priority=confidence,
            reasoning=reasoning,
            supporting_data={
                "Symbol": symbol,
                "Zscore20": round(z_score, 3),
                "Regime": regime,
                "Buy_Threshold": buy_threshold,
                "Exit_Threshold": exit_threshold,
            },
            trade_plan=trade_plan,
        )


# ============================================================================
# NEW AGENTS (Expanding to 5)
# ============================================================================

class CanaryAgent(BlackwellBrigadeAgent):
    """
    Volume and liquidity specialist.
    
    Philosophy: "Volume confirms price. No volume = no conviction."
    Bias: Confirms other agents' signals via volume analysis
    """

    def __init__(self, ai_client):
        persona = """You are Blackwell Canary, the volume and liquidity specialist.

YOUR DECISION FRAMEWORK:

You validate price moves through volume analysis. Your motto: "Price whispers, volume shouts."

STRONG BUY (confidence 0.70-0.85):
- Volume ratio >1.5 (50% above average) + uptrend
- Rising volume on rising prices = healthy accumulation

MODERATE BUY (confidence 0.60-0.69):
- Volume ratio 1.2-1.5 + uptrend
- Decent volume confirmation

EXIT (confidence 0.65-0.80):
- Volume spike (>2.0x) with downward price action
- OR: Low volume (<0.8x) on attempted rally = weak hands

HOLD (confidence 0.50-0.65):
- Volume neutral (0.8-1.2x average)
- OR: Conflicting volume signals

CRITICAL RULES:
1. High volume + price up = BUY (money flowing in)
2. High volume + price down = EXIT (distribution)
3. Low volume + price up = HOLD (suspect rally)
4. Low volume + price down = HOLD (wait for capitulation)

YOUR PERSONALITY:
You're a liquidity hawk. You don't trust moves without volume confirmation.
You catch false breakouts (price up, volume low) and spot real accumulation (price up, volume high).
"""
        super().__init__("Blackwell_Canary", persona, ai_client)

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Dict[str, Any]) -> BlackwellBrigadeOpinion:
        # Volume ratio is expected to be computed upstream from raw OHLCV.
        # If unavailable, we surface that explicitly (no silent 1.00x fallback).
        volume_ratio = context.get("volume_ratio", None)
        volume_available = bool(context.get("volume_available", True)) and (volume_ratio is not None)
        uptrend = context.get("uptrend", False)
        downtrend = context.get("downtrend", False)
        price_change_pct = context.get("price_change_pct", 0.0)

        # Classify volume
        if not volume_available:
            vol_label = "UNAVAILABLE"
        elif volume_ratio > 1.5:
            vol_label = "HIGH (above avg)"
        elif volume_ratio < 0.8:
            vol_label = "LOW (below avg)"
        else:
            vol_label = "NORMAL"

        vr_text = "N/A" if not volume_available else f"{volume_ratio:.2f}x"

        prompt = f"""Analyze {symbol} volume and liquidity.

VOLUME DATA:
- Volume ratio: {vr_text} average ({vol_label})
- Price action: {'UPTREND' if uptrend else 'DOWNTREND' if downtrend else 'FLAT'}
- Recent price change: {price_change_pct:+.2f}%

VOLUME INTERPRETATION:
- Ratio >1.5 = strong interest (confirm direction)
- Ratio 0.8-1.2 = neutral
- Ratio <0.8 = weak conviction (suspect moves)
- If volume is UNAVAILABLE, you must NOT claim "1.00x" or invent a ratio.

DECISION MATRIX:
- High volume + uptrend = BUY (accumulation)
- High volume + downtrend = EXIT (distribution)
- Low volume + uptrend = HOLD (weak rally)
- Low volume + downtrend = HOLD (wait for flush)
- If volume is UNAVAILABLE, default to HOLD with moderate confidence (0.55-0.62) unless price action is extremely clear.

YOUR CALL:
ACTION: [BUY/EXIT/HOLD]
CONFIDENCE: [0.XX]
REASONING: [Cite volume ratio and price action. If UNAVAILABLE, say volume data was unavailable.]
"""

        response = self.ai.generate(prompt, system=self.persona, temperature=0.7, max_tokens=500)

        action = self._extract_action(response)
        confidence = self._extract_confidence(response)
        reasoning = self._extract_reasoning(response)

        trade_plan = build_trade_plan(
            symbol=symbol,
            action=action,
            confidence=confidence,
            q10=context.get("q10", 0.0),
            q50=context.get("q50", 0.0),
            q90=context.get("q90", 0.0),
            band=context.get("band", 0.0),
            regime=context.get("regime", "NORMAL"),
            context=context,
        )

        return BlackwellBrigadeOpinion(
            module=self.name,
            action=action,
            priority=confidence,
            reasoning=reasoning,
            supporting_data={
                "Symbol": symbol,
                "Volume_Ratio": (round(volume_ratio, 2) if volume_ratio is not None else None),
                "Volume_Available": volume_available,
                "Price_Change_Pct": round(price_change_pct, 2),
                "Uptrend": uptrend,
                "Downtrend": downtrend,
            },
            trade_plan=trade_plan,
        )


class PathfinderAgent(BlackwellBrigadeAgent):
    """
    Pattern recognition specialist.
    
    Philosophy: "History doesn't repeat, but it rhymes. I find the patterns."
    Bias: Identifies chart patterns and historical analogues
    """

    def __init__(self, ai_client):
        persona = """You are Blackwell Pathfinder, the pattern recognition specialist.

YOUR DECISION FRAMEWORK:

You identify repeating price structures and historical analogues. You're a chartist at heart.

STRONG BUY (confidence 0.70-0.85):
- Bullish reversal pattern detected (e.g., higher lows forming)
- OR: Breakout above resistance with expanding range

MODERATE BUY (confidence 0.60-0.69):
- Consolidation pattern near support
- OR: Bullish divergence (price down, momentum up)

EXIT (confidence 0.65-0.80):
- Bearish reversal pattern (e.g., lower highs forming)
- OR: Breakdown below support with expanding range

HOLD (confidence 0.50-0.65):
- Choppy, directionless pattern
- OR: Range-bound consolidation (no clear structure)

KEY PATTERNS YOU WATCH FOR:
1. Higher highs + higher lows = uptrend intact (BUY)
2. Lower highs + lower lows = downtrend intact (EXIT)
3. Narrowing range = consolidation (HOLD until breakout)
4. Expanding range = volatility increase (cautious)

YOUR PERSONALITY:
You're a visual thinker. You see patterns others miss.
You trust structure over noise. You wait for confirmation (breakouts, not fakeouts).
"""
        super().__init__("Blackwell_Pathfinder", persona, ai_client)

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Dict[str, Any]) -> BlackwellBrigadeOpinion:
        # Pattern metrics (derived from forecast_df)
        q50_series = forecast_df["Q50"].astype(float).tail(10)
        
        # Simple pattern detection
        if len(q50_series) >= 3:
            recent_high = float(q50_series.max())
            recent_low = float(q50_series.min())
            current = float(q50_series.iloc[-1])
            prev = float(q50_series.iloc[-2])
            
            range_pct = ((recent_high - recent_low) / recent_low) * 100 if recent_low > 0 else 0.0
            position_in_range = ((current - recent_low) / (recent_high - recent_low)) if (recent_high > recent_low) else 0.5
            
            if current > prev:
                price_direction = "RISING"
            elif current < prev:
                price_direction = "FALLING"
            else:
                price_direction = "FLAT"
        else:
            range_pct = 0.0
            position_in_range = 0.5
            price_direction = "UNKNOWN"

        uptrend = context.get("uptrend", False)
        downtrend = context.get("downtrend", False)

        prompt = f"""Analyze {symbol} for chart patterns.

PATTERN DATA:
- 10-period range: {range_pct:.2f}%
- Position in range: {position_in_range:.2%} (0%=low, 100%=high)
- Recent direction: {price_direction}
- Trend: {'UPTREND' if uptrend else 'DOWNTREND' if downtrend else 'SIDEWAYS'}

PATTERN INTERPRETATION:
- Position >70% + uptrend = near resistance, watch for breakout
- Position <30% + downtrend = near support, watch for breakdown
- Position 30-70% = mid-range, wait for direction
- Range expanding = volatility increasing (caution)
- Range contracting = consolidation (coiling for move)

YOUR CALL:
ACTION: [BUY/EXIT/HOLD]
CONFIDENCE: [0.XX]
REASONING: [Describe pattern. "Position at X% with Y trend suggests..."]
"""

        response = self.ai.generate(prompt, system=self.persona, temperature=0.7, max_tokens=500)

        action = self._extract_action(response)
        confidence = self._extract_confidence(response)
        reasoning = self._extract_reasoning(response)

        trade_plan = build_trade_plan(
            symbol=symbol,
            action=action,
            confidence=confidence,
            q10=context.get("q10", 0.0),
            q50=context.get("q50", 0.0),
            q90=context.get("q90", 0.0),
            band=context.get("band", 0.0),
            regime=context.get("regime", "NORMAL"),
            context=context,
        )

        return BlackwellBrigadeOpinion(
            module=self.name,
            action=action,
            priority=confidence,
            reasoning=reasoning,
            supporting_data={
                "Symbol": symbol,
                "Range_Pct": round(range_pct, 2),
                "Position_In_Range": round(position_in_range, 2),
                "Price_Direction": price_direction,
            },
            trade_plan=trade_plan,
        )


# ============================================================================
# EXPANDED BRIGADE WATCHTOWER (5 Agents)
# ============================================================================

class BlackwellBrigadeWatchtower:
    """
    Runs all Brigade agents and collects opinions.
    """

    def __init__(self, ai_client):
        self.scout = ScoutAgent(ai_client)
        self.sentry = SentryAgent(ai_client)
        self.advisor = AdvisorAgent(ai_client)
        self.canary = CanaryAgent(ai_client)
        self.pathfinder = PathfinderAgent(ai_client)
        self.decay = DecayAgent(ai_client) if DecayAgent is not None else None

    def analyze(self, symbol: str, forecast_df: pd.DataFrame, context: Optional[Dict[str, Any]] = None, **kwargs) -> List[BlackwellBrigadeOpinion]:
        """Run all Brigade agents on a symbol."""
        computed_context = self._calculate_context(symbol, forecast_df)
        if context:
            computed_context.update(context)

        opinions: List[BlackwellBrigadeOpinion] = [
            self.scout.analyze(symbol, forecast_df, computed_context),
            self.sentry.analyze(symbol, forecast_df, computed_context),
            self.advisor.analyze(symbol, forecast_df, computed_context),
            self.canary.analyze(symbol, forecast_df, computed_context),
            self.pathfinder.analyze(symbol, forecast_df, computed_context),
        ]

        # Optional Decay opinion (only if the agent exists in this repo version)
        if self.decay is not None:
            try:
                opinions.append(self.decay.analyze(symbol, forecast_df, computed_context))
            except Exception:
                # Never break the Brigade if Decay errors; treat as "silent"
                pass

        return opinions

    def _calculate_context(self, symbol: str, forecast_df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate all metrics needed by Brigade agents."""

        q10 = float(forecast_df["Q10"].iloc[-1])
        q50 = float(forecast_df["Q50"].iloc[-1])
        q90 = float(forecast_df["Q90"].iloc[-1])

        band = q90 - q10
        band_safe = max(1e-9, abs(band))
        skew = ((q90 - q50) - (q50 - q10)) / band_safe

        tail_down = (q50 - q10) / max(1e-9, q50)
        tail_up = (q90 - q50) / max(1e-9, q50)
        band_tot = band / max(1e-9, q50)

        q50_series = forecast_df["Q50"].astype(float)

        if len(q50_series) >= 10:
            sma3 = float(q50_series.tail(3).mean())
            sma10 = float(q50_series.tail(10).mean())
        else:
            sma3 = float(q50)
            sma10 = float(q50)

        trend_strength = ((sma3 / sma10) - 1.0) if sma10 > 0 else 0.0
        uptrend = bool(trend_strength > 0.005)
        downtrend = bool(trend_strength < -0.005)

        window = min(20, len(q50_series))
        if window >= 5:
            w = q50_series.tail(window)
            mu = float(w.mean())
            sd = float(w.std(ddof=0))
            z_score = (q50 - mu) / sd if sd > 1e-9 else 0.0
        else:
            z_score = 0.0

        # Regime
        if len(q50_series) >= 15:
            rets = q50_series.pct_change().dropna()
            recent = rets.tail(14)
            vol = float(recent.std(ddof=0))
            base = float(rets.tail(min(60, len(rets))).std(ddof=0)) if len(rets) >= 20 else vol
            reg_ratio = (vol / base) if base > 1e-9 else 1.0
        else:
            vol = 0.0
            reg_ratio = 1.0

        if reg_ratio >= 1.35:
            regime = "HIGH"
        elif reg_ratio <= 0.75:
            regime = "LOW"
        else:
            regime = "NORMAL"

        # Volume metrics (for Canary)
        # Forecast frames often do NOT include Volume; prefer raw OHLCV if available.
        volume_ratio: Optional[float] = None
        volume_available: bool = False

        # 1) If Volume is present in forecast_df, use it.
        if "Volume" in forecast_df.columns:
            vol_series = pd.to_numeric(forecast_df["Volume"], errors="coerce")
            if len(vol_series.dropna()) >= 2:
                recent_vol = float(vol_series.iloc[-1])
                avg_vol = float(vol_series.tail(20).mean()) if len(vol_series) >= 20 else float(vol_series.mean())
                if avg_vol > 0:
                    volume_ratio = recent_vol / avg_vol
                    volume_available = True

        # 2) Otherwise, try raw OHLCV CSV in data/raw/{SYMBOL}.csv
        if volume_ratio is None:
            # Resolve raw data directory relative to the project root (not the current working directory).
            # This avoids "volume unavailable" when the script is launched from a different folder.
            project_root = Path(__file__).resolve().parents[1]
            raw_dir = project_root / "data" / "raw"
            candidates = [
                raw_dir / f"{symbol}.csv",
                raw_dir / f"{symbol.upper()}.csv",
                raw_dir / f"{symbol.lower()}.csv",
            ]
            raw_path = next((p for p in candidates if p.exists()), None)

            if raw_path is not None:
                try:
                    raw_df = pd.read_csv(raw_path)
                    # Normalize column names (defensive against whitespace/casing)
                    raw_df.columns = [str(c).strip() for c in raw_df.columns]
                    vol_col = "Volume" if "Volume" in raw_df.columns else ("volume" if "volume" in raw_df.columns else None)
                    if vol_col:
                        v = pd.to_numeric(raw_df[vol_col], errors="coerce").dropna()
                        if len(v) >= 2:
                            recent_vol = float(v.iloc[-1])
                            # Use prior 20 bars when possible to avoid including the latest bar in its own average.
                            if len(v) >= 21:
                                avg_vol = float(v.iloc[-21:-1].mean())
                            else:
                                avg_vol = float(v.mean())
                            if avg_vol > 0:
                                volume_ratio = recent_vol / avg_vol
                                volume_available = True
                except Exception:
                    volume_ratio = None
                    volume_available = False

        # Price change (for Canary)
        if len(q50_series) >= 2:
            price_change_pct = ((q50 / q50_series.iloc[-2]) - 1.0) * 100 if q50_series.iloc[-2] > 0 else 0.0
        else:
            price_change_pct = 0.0

        return {
            "q10": q10,
            "q50": q50,
            "q90": q90,
            "band": band,
            "skew": skew,
            "tail_down_pct": tail_down,
            "tail_up_pct": tail_up,
            "band_tot_pct": band_tot,
            "sma3": sma3,
            "sma10": sma10,
            "uptrend": uptrend,
            "downtrend": downtrend,
            "z_score": z_score,
            "regime": regime,
            "reg_ratio": reg_ratio,
            "volume_ratio": (float(volume_ratio) if volume_ratio is not None else None),
            "volume_available": bool(volume_available),
            "price_change_pct": price_change_pct,
        }