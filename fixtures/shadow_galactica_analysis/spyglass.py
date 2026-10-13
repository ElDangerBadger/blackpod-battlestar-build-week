"""
Navigator S/R + Pattern Detection (v0.1)
----------------------------------------
Drop-in module for BlackPod Quorum / Blackwell Navigator.

What it does
============
1) Derives actionable Support/Resistance (S/R) levels from swing points and clusters them
   with an ATR-aware tolerance, then scores the levels by touches, recency, and volume.
2) Tracks breakout → retest logic against those levels and emits structured events.
3) Detects a handful of classic visual patterns without needing rendered charts:
   - Double Top / Double Bottom
   - Head & Shoulders / Inverse H&S
   - Symmetrical Triangle (converging L-H / H-L)
   - Flag / Pennant after an impulse leg
   - RSI/Price divergence on swing points (optional, if you pass in RSI)

Inputs
======
- A pandas DataFrame with columns: ['Open','High','Low','Close','Volume'] and DateTimeIndex.
- Optional precomputed RSI series for divergence checks (pandas Series indexed the same).

Outputs
=======
- compute_sr_levels(...) → List[Dict] of levels with fields: price, kind, strength, last_touch, touches, band.
- check_breakout_retest(...) → list of events: {'type': 'breakout'|'retest', 'level': float, 'dir': 'up'|'down', 'bar': Timestamp}
- detect_patterns(...) → Dict[str, List[Dict]] keyed by pattern name with boolean confirmations and metadata.

Integration (Navigator)
=======================
1) Import this module in your stream engine after you have a window of recent bars per symbol.
2) Cache S/R levels per symbol (e.g., in-memory dict) and refresh every N bars.
3) Use events + patterns to bias Navigator entries/exits alongside your EMA/RSI/Volume rules.

Author: BlackPod // 2025-09-03
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import math
import numpy as np
import pandas as pd

# -------------------------------
# Utilities
# -------------------------------

def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df['Close'].shift(1)
    tr = pd.concat([
        (df['High'] - df['Low']).abs(),
        (df['High'] - prev_close).abs(),
        (df['Low'] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14, wilder: bool = True) -> pd.Series:
    tr = _true_range(df)
    if wilder:
        # Wilder's smoothing
        atr = tr.ewm(alpha=1/period, adjust=False).mean()
    else:
        atr = tr.rolling(period).mean()
    return atr


@dataclass
class SRConfig:
    swing_lookback: int = 3           # k bars on each side for swing points
    min_touches: int = 2              # min swing touches to keep a level
    band_atr: float = 0.25            # width of an S/R band = band_atr * ATR
    cluster_merge_atr: float = 0.5    # when clustering raw swing levels
    recency_halflife: int = 200       # bars for recency decay in strength
    volume_weight: float = 0.2        # contribution of normalized volume to strength
    max_levels: int = 12              # cap to avoid clutter


@dataclass
class PatternConfig:
    min_separation: int = 10          # bars between peaks/troughs
    peak_tolerance_atr: float = 0.35  # tolerance for matching highs/lows in ATR
    min_pullback_atr: float = 0.4     # valley/peak depth between double top/bottom
    impulse_len: int = 15             # bars for impulse leg detection
    impulse_mult_atr: float = 2.0     # impulse move >= this * ATR(avg) over window
    flag_len: int = 12                # bars for flag/pennant window
    triangle_min_len: int = 20        # bars required to fit converging highs/lows
    slope_tol: float = 1e-4           # near-zero slope tolerance
    r2_min: float = 0.15              # minimal fit quality for regressions


# -------------------------------
# Swing points & S/R levels
# -------------------------------

def find_swings(df: pd.DataFrame, k: int) -> Tuple[pd.Index, pd.Index]:
    """Return indices of swing highs and swing lows (strictly dominant within k bars).
    A swing high at i: High[i] >= max(High[i-k:i+k]) and strictly > neighbors within window.
    Similar for swing low with Low.
    """
    highs = df['High'].values
    lows = df['Low'].values
    idx = df.index

    swing_high_idx = []
    swing_low_idx = []

    n = len(df)
    for i in range(k, n - k):
        h = highs[i]
        window_h = highs[i-k:i+k+1]
        if h == window_h.max() and (h > window_h[:k].max()) and (h > window_h[k+1:].max()):
            swing_high_idx.append(idx[i])
        l = lows[i]
        window_l = lows[i-k:i+k+1]
        if l == window_l.min() and (l < window_l[:k].min()) and (l < window_l[k+1:].min()):
            swing_low_idx.append(idx[i])

    return pd.Index(swing_high_idx), pd.Index(swing_low_idx)


def _merge_levels(raw_prices: List[float], tolerance: float) -> List[float]:
    """Simple 1D clustering: sort and merge neighbors within tolerance into their weighted mean."""
    if not raw_prices:
        return []
    raw_prices = sorted(raw_prices)
    clusters = []
    acc = [raw_prices[0]]
    for p in raw_prices[1:]:
        if abs(p - acc[-1]) <= tolerance:
            acc.append(p)
        else:
            clusters.append(float(np.mean(acc)))
            acc = [p]
    clusters.append(float(np.mean(acc)))
    return clusters


def compute_sr_levels(df: pd.DataFrame, cfg: SRConfig = SRConfig()) -> List[Dict]:
    """Compute S/R levels from swing highs/lows, cluster them, score, and return top-N.

    Returns a list of dicts with:
    - price: float
    - kind: 'resistance' | 'support'
    - band: (lo, hi) band bounds around price
    - touches: int (count of swing points in band)
    - strength: float in [0, 1]
    - last_touch: pd.Timestamp
    """
    if len(df) < cfg.swing_lookback * 2 + 10:
        return []

    atr_s = atr(df, period=14)
    atr_last = float(atr_s.iloc[-1]) if not math.isnan(atr_s.iloc[-1]) else float(_true_range(df).rolling(14).mean().iloc[-1])
    k = cfg.swing_lookback
    sh_idx, sl_idx = find_swings(df, k=k)

    swing_high_prices = df.loc[sh_idx, 'High'].tolist()
    swing_low_prices = df.loc[sl_idx, 'Low'].tolist()

    tol_cluster = cfg.cluster_merge_atr * atr_last
    res_levels = _merge_levels(swing_high_prices, tol_cluster)
    sup_levels = _merge_levels(swing_low_prices, tol_cluster)

    def _band(p):
        b = cfg.band_atr * atr_last
        return (p - b, p + b)

    levels: List[Dict] = []
    # Touch counting with recency & volume weighting inside band
    vol = df['Volume']
    vol_norm = (vol - vol.rolling(50).mean()) / (vol.rolling(50).std() + 1e-9)
    vol_norm = vol_norm.fillna(0)

    def score_level(p: float, kind: str) -> Tuple[int, float, Optional[pd.Timestamp]]:
        lo, hi = _band(p)
        touches = 0
        strength = 0.0
        last_touch = None
        halflife = cfg.recency_halflife
        # iterate swings of the matching type
        idxs = sh_idx if kind == 'resistance' else sl_idx
        for t in idxs:
            price = float(df.at[t, 'High'] if kind == 'resistance' else df.at[t, 'Low'])
            if lo <= price <= hi:
                touches += 1
                last_touch = t if (last_touch is None or t > last_touch) else last_touch
                # recency decay
                bars_ago = (df.index.get_loc(df.index[-1]) - df.index.get_loc(t))
                recency_w = 0.5 ** (bars_ago / max(1, halflife))
                v = float(vol_norm.get(t, 0.0))
                # distance weight (closer to center = better)
                dist_w = 1.0 - (abs(price - p) / max(1e-9, (hi - lo)))
                strength += recency_w * (1.0 + cfg.volume_weight * v) * dist_w
        return touches, float(max(0.0, min(1.0, strength))), last_touch

    for p in res_levels:
        touches, strength, last_touch = score_level(p, 'resistance')
        if touches >= cfg.min_touches:
            levels.append({
                'price': float(p),
                'kind': 'resistance',
                'band': _band(p),
                'touches': touches,
                'strength': strength,
                'last_touch': last_touch
            })

    for p in sup_levels:
        touches, strength, last_touch = score_level(p, 'support')
        if touches >= cfg.min_touches:
            levels.append({
                'price': float(p),
                'kind': 'support',
                'band': _band(p),
                'touches': touches,
                'strength': strength,
                'last_touch': last_touch
            })

    # Keep strongest N
    levels = sorted(levels, key=lambda d: (d['strength'], d['touches']), reverse=True)[:cfg.max_levels]
    return levels


# -------------------------------
# Breakout / Retest logic
# -------------------------------

def check_breakout_retest(df: pd.DataFrame, levels: List[Dict], vol_spike_z: float = 1.0) -> List[Dict]:
    """Emit breakout/retest events against S/R bands.

    Heuristics:
    - Breakout: bar closes outside band in the direction away from band center
      with either body > ATR or volume z-score > vol_spike_z.
    - Retest: after breakout, next bars trade back into band and then resume.

    Returns list of events with keys: type, level, dir, bar.
    """
    if not len(df) or not levels:
        return []

    events: List[Dict] = []
    atr_s = atr(df, 14)
    vol = df['Volume']
    vol_z = (vol - vol.rolling(50).mean()) / (vol.rolling(50).std() + 1e-9)

    close = df['Close']
    high = df['High']
    low = df['Low']

    last_bar = df.index[-1]
    c = float(close.iloc[-1])
    a = float(atr_s.iloc[-1]) if not math.isnan(atr_s.iloc[-1]) else float(_true_range(df).rolling(14).mean().iloc[-1])
    vz = float(vol_z.iloc[-1]) if not math.isnan(vol_z.iloc[-1]) else 0.0

    for lvl in levels:
        lo, hi = lvl['band']
        center = (lo + hi) / 2.0
        # Breakout
        if c > hi and (abs(c - center) > a or vz > vol_spike_z):
            events.append({'type': 'breakout', 'level': lvl['price'], 'dir': 'up', 'bar': last_bar})
        elif c < lo and (abs(c - center) > a or vz > vol_spike_z):
            events.append({'type': 'breakout', 'level': lvl['price'], 'dir': 'down', 'bar': last_bar})
        # Retest (simple): current bar intersects band after prior breakout
        # Check prev bar position relative to band
        if len(df) >= 2:
            prev_c = float(close.iloc[-2])
            # Up-breakout then retest: prev above band, now low <= hi <= high (tag band)
            if prev_c > hi and (low.iloc[-1] <= hi <= high.iloc[-1]):
                events.append({'type': 'retest', 'level': lvl['price'], 'dir': 'up', 'bar': last_bar})
            # Down-breakout then retest
            if prev_c < lo and (low.iloc[-1] <= lo <= high.iloc[-1]):
                events.append({'type': 'retest', 'level': lvl['price'], 'dir': 'down', 'bar': last_bar})
    return events


# -------------------------------
# Pattern detection
# -------------------------------

def _linear_fit(y: np.ndarray) -> Tuple[float, float, float]:
    """Return slope, intercept, r2 for a simple linear regression against index [0..n-1]."""
    x = np.arange(len(y))
    if len(y) < 2:
        return 0.0, float(y[-1] if len(y) else 0.0), 0.0
    slope, intercept = np.polyfit(x, y, 1)
    y_hat = slope * x + intercept
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2) + 1e-9
    r2 = 1 - ss_res / ss_tot
    return float(slope), float(intercept), float(max(0.0, min(1.0, r2)))


def _extract_swings_for_patterns(df: pd.DataFrame, k: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    sh, sl = find_swings(df, k)
    swings_high = pd.DataFrame({'price': df.loc[sh, 'High']}).assign(kind='H')
    swings_low = pd.DataFrame({'price': df.loc[sl, 'Low']}).assign(kind='L')
    return swings_high, swings_low


def detect_double_top_bottom(df: pd.DataFrame, cfg: PatternConfig, is_top: bool = True) -> List[Dict]:
    """Detect double top/bottom using swing points with ATR tolerance and depth constraint."""
    if len(df) < cfg.min_separation * 3:
        return []
    a = float(atr(df, 14).iloc[-1])
    swings_h, swings_l = _extract_swings_for_patterns(df, k=3)
    points = swings_h if is_top else swings_l
    points = points.sort_index()
    out = []
    for i in range(len(points) - 1):
        t1, p1 = points.index[i], float(points.iloc[i].price)
        for j in range(i + 1, len(points)):
            t2, p2 = points.index[j], float(points.iloc[j].price)
            bars = df.index.get_loc(t2) - df.index.get_loc(t1)
            if bars < cfg.min_separation:
                continue
            if abs(p1 - p2) <= cfg.peak_tolerance_atr * a:
                # depth: valley (for top) or peak (for bottom) between t1..t2
                mid = df.loc[t1:t2]
                if is_top:
                    valley = float(mid['Low'].min())
                    if (min(p1, p2) - valley) >= cfg.min_pullback_atr * a:
                        out.append({'confirmed': True, 't1': t1, 't2': t2, 'p': (p1 + p2)/2, 'type': 'double_top'})
                else:
                    peak = float(mid['High'].max())
                    if (peak - max(p1, p2)) >= cfg.min_pullback_atr * a:
                        out.append({'confirmed': True, 't1': t1, 't2': t2, 'p': (p1 + p2)/2, 'type': 'double_bottom'})
    return out[-3:]  # limit


def detect_head_shoulders(df: pd.DataFrame, cfg: PatternConfig, inverse: bool = False) -> List[Dict]:
    """Heuristic H&S detection using swing highs (or lows for inverse)."""
    swings_h, swings_l = _extract_swings_for_patterns(df, k=3)
    pts = swings_l if inverse else swings_h
    kind = 'inverse_hs' if inverse else 'head_shoulders'
    a = float(atr(df, 14).iloc[-1])
    out = []
    # Iterate triples i<j<k for L-S-R shoulders
    prices = pts['price'].values
    times = pts.index
    for i in range(len(pts) - 2):
        for j in range(i + 1, len(pts) - 1):
            for k in range(j + 1, len(pts)):
                L, H, R = float(prices[i]), float(prices[j]), float(prices[k])
                # shoulders roughly equal within tolerance; head higher (or lower if inverse)
                if not inverse:
                    cond_shoulder = abs(L - R) <= cfg.peak_tolerance_atr * a
                    cond_head = H >= max(L, R) + cfg.peak_tolerance_atr * a
                else:
                    cond_shoulder = abs(L - R) <= cfg.peak_tolerance_atr * a
                    cond_head = H <= min(L, R) - cfg.peak_tolerance_atr * a
                if cond_shoulder and cond_head:
                    tL, tH, tR = times[i], times[j], times[k]
                    # neckline from lows (or highs if inverse) between L..R
                    seg = df.loc[times[i]:times[k]]
                    if not inverse:
                        nl = float(seg['Low'].min())
                    else:
                        nl = float(seg['High'].max())
                    out.append({'confirmed': True, 'tL': tL, 'tH': tH, 'tR': tR, 'neckline': nl, 'type': kind})
    return out[-2:]


def detect_triangle(df: pd.DataFrame, cfg: PatternConfig) -> List[Dict]:
    """Symmetrical triangle: lower highs & higher lows over a window with converging regression lines."""
    if len(df) < cfg.triangle_min_len:
        return []
    win = df.tail(cfg.triangle_min_len)
    # rolling local extrema (cheap proxy)
    highs = win['High']
    lows = win['Low']
    # sample every ~3 bars to reduce noise
    h_samples = highs.iloc[::3].values
    l_samples = lows.iloc[::3].values
    sH, bH, r2H = _linear_fit(h_samples)
    sL, bL, r2L = _linear_fit(l_samples)
    # convergence: slopes opposite signs and lines intersect within window span
    if sH < 0 and sL > 0 and r2H >= cfg.r2_min and r2L >= cfg.r2_min:
        # estimate distance between lines at window end vs start
        n = max(len(h_samples), len(l_samples))
        dist_start = (sH * 0 + bH) - (sL * 0 + bL)
        dist_end = (sH * (n-1) + bH) - (sL * (n-1) + bL)
        if dist_end < dist_start and dist_end > 0:
            return [{'confirmed': True, 'type': 'triangle', 'tightening': float(dist_start/dist_end)}]
    return []


def detect_flag_pennant(df: pd.DataFrame, cfg: PatternConfig) -> List[Dict]:
    """Detect post-impulse consolidation (flag/pennant) using regression slope + ATR contraction."""
    if len(df) < (cfg.impulse_len + cfg.flag_len + 5):
        return []
    a = float(atr(df, 14).iloc[-1])
    # Impulse segment
    imp = df.tail(cfg.impulse_len)
    slope_imp, _, r2i = _linear_fit(imp['Close'].values)
    move = float(imp['Close'].iloc[-1] - imp['Close'].iloc[0])
    avg_atr = float(atr(df, 14).tail(cfg.impulse_len).mean())
    if abs(move) < cfg.impulse_mult_atr * avg_atr or r2i < cfg.r2_min:
        return []
    direction = 'up' if slope_imp > 0 else 'down'
    # Consolidation segment immediately after impulse
    con = df.tail(cfg.flag_len)
    slope_con, _, r2c = _linear_fit(con['Close'].values)
    atr_con = float(atr(df, 14).tail(cfg.flag_len).mean())
    # Opposite/near-flat slope & ATR contraction
    if direction == 'up' and slope_con <= 0 and r2c >= 0.05 and atr_con < avg_atr:
        return [{'confirmed': True, 'type': 'bull_flag'}]
    if direction == 'down' and slope_con >= 0 and r2c >= 0.05 and atr_con < avg_atr:
        return [{'confirmed': True, 'type': 'bear_flag'}]
    return []


def detect_rsi_divergence(df: pd.DataFrame, rsi: Optional[pd.Series], k: int = 3, min_sep: int = 8) -> List[Dict]:
    """Detect classic price/RSI divergence over swing points if RSI is provided."""
    if rsi is None or len(df) < k*2 + 10 or len(rsi) != len(df):
        return []
    sh, sl = find_swings(df, k)
    out = []
    # Bearish: higher high in price, lower high in RSI
    for i in range(len(sh) - 1):
        i1, i2 = sh[i], sh[i+1]
        if df.index.get_loc(i2) - df.index.get_loc(i1) < min_sep:
            continue
        if df.at[i2,'High'] > df.at[i1,'High'] and rsi.at[i2] < rsi.at[i1]:
            out.append({'type': 'bearish_div', 't1': i1, 't2': i2})
    # Bullish: lower low in price, higher low in RSI
    for i in range(len(sl) - 1):
        i1, i2 = sl[i], sl[i+1]
        if df.index.get_loc(i2) - df.index.get_loc(i1) < min_sep:
            continue
        if df.at[i2,'Low'] < df.at[i1,'Low'] and rsi.at[i2] > rsi.at[i1]:
            out.append({'type': 'bullish_div', 't1': i1, 't2': i2})
    return out[-4:]


def detect_patterns(df: pd.DataFrame, pcfg: PatternConfig = PatternConfig(), rsi: Optional[pd.Series] = None) -> Dict[str, List[Dict]]:
    return {
        'double_top': detect_double_top_bottom(df, pcfg, is_top=True),
        'double_bottom': detect_double_top_bottom(df, pcfg, is_top=False),
        'head_shoulders': detect_head_shoulders(df, pcfg, inverse=False),
        'inverse_hs': detect_head_shoulders(df, pcfg, inverse=True),
        'triangle': detect_triangle(df, pcfg),
        'flag_pennant': detect_flag_pennant(df, pcfg),
        'rsi_divergence': detect_rsi_divergence(df, rsi) if rsi is not None else []
    }


# -------------------------------
# Convenience: one-shot analyzer
# -------------------------------

def analyze_structure(
    df: pd.DataFrame,
    sr_cfg: SRConfig = SRConfig(),
    pat_cfg: PatternConfig = PatternConfig(),
    rsi: Optional[pd.Series] = None
) -> Dict[str, object]:
    """Compute S/R → events → patterns in one call for a Navigator symbol slice."""
    levels = compute_sr_levels(df, sr_cfg)
    events = check_breakout_retest(df, levels)
    patterns = detect_patterns(df, pat_cfg, rsi=rsi)
    return {'levels': levels, 'events': events, 'patterns': patterns}


# -------------------------------
# Example integration snippet (paste into Navigator once per symbol update)
# -------------------------------
EXAMPLE_USAGE = r"""
# Suppose 'bars' is your per-symbol OHLCV DataFrame (recent N bars),
# and you already computed rsi_series (optional).
from sr_patterns import analyze_structure, SRConfig, PatternConfig

sr_cfg = SRConfig(swing_lookback=3, min_touches=2, band_atr=0.30, max_levels=10)
pat_cfg = PatternConfig(min_separation=8, triangle_min_len=24)

struct = analyze_structure(bars, sr_cfg, pat_cfg, rsi=rsi_series)
levels = struct['levels']
events = struct['events']
patterns = struct['patterns']

# Use these to modulate Navigator decisions, for example:
# - Bias long entries when price is bouncing from support with bullish flag or triangle + up-breakout
# - Avoid fresh longs into nearby strong resistance (distance to nearest resistance < X * ATR)
# - Allow adds on successful retest events following breakouts

# Distance to nearest opposite level
def nearest_level_distance(price, levels, kind='resistance'):
    candidates = [abs(price - L['price']) for L in levels if L['kind'] == kind]
    return min(candidates) if candidates else float('inf')

px = float(bars['Close'].iloc[-1])
near_res = nearest_level_distance(px, levels, 'resistance')
near_sup = nearest_level_distance(px, levels, 'support')
"""
