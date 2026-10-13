from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import math

import numpy as np


@dataclass
class DecayConfig:
    # windows
    w_fast: int = 5
    w_slow: int = 10

    # thresholds (tune later)
    ret10_exit: float = -6.0     # -6% over 10 bars triggers decay concern
    ret5_exit: float = -3.0      # -3% over 5 bars adds urgency
    dd10_exit: float = 5.0       # 5% max drawdown over 10 bars adds urgency

    # "recovery" / impulse detection
    impulse_up_day: float = 1.0  # +1.0% day counts as impulse
    min_impulses: int = 1        # require at least 1 impulse in last 10 bars to avoid decay flag

    # slope threshold (normalized)
    slope_exit: float = 0.0      # negative slope supports exit

    # relative weakness (optional; set None to disable)
    use_relative: bool = True
    rel10_exit: float = -2.0     # underperform benchmark by 2% over 10 bars

    # confidence shaping
    base_conf: float = 0.55
    max_conf: float = 0.90


def _pct(a: float, b: float) -> float:
    if b == 0 or math.isnan(a) or math.isnan(b):
        return 0.0
    return (a / b - 1.0) * 100.0


def _max_drawdown_pct(prices: np.ndarray) -> float:
    # max peak-to-trough drawdown in percent (positive number)
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices[1:]:
        peak = max(peak, p)
        if peak > 0:
            dd = (peak - p) / peak * 100.0
            max_dd = max(max_dd, dd)
    return float(max_dd)


def _slope(prices: np.ndarray) -> float:
    # simple linear regression slope on log(prices)
    if len(prices) < 3:
        return 0.0
    x = np.arange(len(prices), dtype=float)
    y = np.log(np.clip(prices.astype(float), 1e-9, None))
    # slope = cov(x,y)/var(x)
    vx = np.var(x)
    if vx <= 0:
        return 0.0
    return float(np.cov(x, y, bias=True)[0, 1] / vx)


def _impulse_count(closes: np.ndarray, impulse_up_day: float) -> int:
    if len(closes) < 2:
        return 0
    cnt = 0
    for i in range(1, len(closes)):
        r = _pct(closes[i], closes[i - 1])
        if r >= impulse_up_day:
            cnt += 1
    return cnt


class Blackwell_Decay:
    """
    Slow-bleed decay detector.
    Intended behavior:
      - EXIT when drift persists (5–10 bars) and recovery impulses are absent
      - HOLD otherwise
    """

    name = "Blackwell_Decay"

    def __init__(self, cfg: Optional[DecayConfig] = None):
        self.cfg = cfg or DecayConfig()

    def analyze(
        self,
        symbol: str,
        closes: np.ndarray,
        volumes: Optional[np.ndarray] = None,
        bench_closes: Optional[np.ndarray] = None,
    ) -> Dict[str, object]:
        c = self.cfg
        closes = np.asarray(closes, dtype=float)

        if len(closes) < c.w_slow + 1:
            return {
                "agent": self.name,
                "symbol": symbol,
                "vote": "HOLD",
                "confidence": 0.50,
                "reason": "Insufficient history for decay window.",
                "metrics": {},
            }

        window10 = closes[-c.w_slow:]
        window5 = closes[-c.w_fast:]

        ret10 = _pct(window10[-1], window10[0])
        ret5 = _pct(window5[-1], window5[0])
        dd10 = _max_drawdown_pct(window10)
        slope10 = _slope(window10)
        impulses = _impulse_count(window10, c.impulse_up_day)

        rel10 = None
        if c.use_relative and bench_closes is not None and len(bench_closes) >= c.w_slow:
            b = np.asarray(bench_closes, dtype=float)[-c.w_slow:]
            rel10 = _pct(window10[-1], window10[0]) - _pct(b[-1], b[0])

        # --- decay gating ---
        bleed = (ret10 <= c.ret10_exit) or (ret5 <= c.ret5_exit) or (dd10 >= c.dd10_exit)
        no_recovery = (impulses < c.min_impulses) and (slope10 <= c.slope_exit)

        rel_weak = True
        if c.use_relative and rel10 is not None:
            rel_weak = (rel10 <= c.rel10_exit)

        decay_flag = bleed and no_recovery and rel_weak

        # --- confidence shaping ---
        # Add points for multiple supporting signals
        score = 0
        score += 1 if ret10 <= c.ret10_exit else 0
        score += 1 if ret5 <= c.ret5_exit else 0
        score += 1 if dd10 >= c.dd10_exit else 0
        score += 1 if slope10 <= c.slope_exit else 0
        score += 1 if impulses < c.min_impulses else 0
        score += 1 if (rel10 is not None and rel10 <= c.rel10_exit) else 0

        # map score to confidence
        conf = c.base_conf + (score / 6.0) * (c.max_conf - c.base_conf)
        conf = float(np.clip(conf, 0.50, c.max_conf))

        if decay_flag:
            return {
                "agent": self.name,
                "symbol": symbol,
                "vote": "EXIT",
                "confidence": conf,
                "reason": (
                    f"Decay detected: ret10={ret10:.2f}%, ret5={ret5:.2f}%, "
                    f"dd10={dd10:.2f}%, impulses10={impulses}, slope10={slope10:.4f}"
                    + (f", rel10={rel10:.2f}%" if rel10 is not None else "")
                ),
                "metrics": {
                    "ret10": ret10,
                    "ret5": ret5,
                    "dd10": dd10,
                    "slope10": slope10,
                    "impulses10": impulses,
                    "rel10": rel10,
                },
            }

        return {
            "agent": self.name,
            "symbol": symbol,
            "vote": "HOLD",
            "confidence": max(0.50, conf - 0.10),
            "reason": (
                f"No decay: ret10={ret10:.2f}%, ret5={ret5:.2f}%, dd10={dd10:.2f}%, "
                f"impulses10={impulses}, slope10={slope10:.4f}"
                + (f", rel10={rel10:.2f}%" if rel10 is not None else "")
            ),
            "metrics": {
                "ret10": ret10,
                "ret5": ret5,
                "dd10": dd10,
                "slope10": slope10,
                "impulses10": impulses,
                "rel10": rel10,
            },
        }