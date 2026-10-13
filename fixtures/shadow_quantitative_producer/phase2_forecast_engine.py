# phase2_forecast_engine.py (regenerated)
# Purpose: Produce Q10/Q50/Q90 bands for +1D using Quantile Regression by default,
# with RSI/MACD features. Optional GBM-Quantile model via CONFIG.
# Keeps the SAME public API: generate_forecast(symbol, df) -> pd.DataFrame
# Output columns preserved for Phase 3 aggregator: [Date, Symbol, Q10, Q50, Q90, Pattern, Timeframe]

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd
from models.model_library import enrich_features

import json
import hashlib
from joblib import dump, load


# Technical indicators (optional if 'ta' installed)
try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD
except Exception:  # pragma: no cover
    RSIIndicator = None
    MACD = None

# Models
from sklearn.linear_model import QuantileRegressor
try:
    from sklearn.ensemble import GradientBoostingRegressor  # optional GBM
except Exception:  # pragma: no cover
    GradientBoostingRegressor = None

# -----------------------------
# Configuration (module-level)
# -----------------------------
FORECAST_DIR = Path("forecasts")
FORECAST_DIR.mkdir(parents=True, exist_ok=True)

CONFIG: Dict = {
    "model": {
        "type": os.getenv("PHASE2_MODEL_TYPE", "quantile_linear"),  # "quantile_linear" | "gbm_quantile"
        "quantiles": [0.10, 0.50, 0.90],
        "window": 252,  # training lookback window (trading days). Set None for full history
        # GBM defaults (used only when model.type == "gbm_quantile")
        "gbm": {
            "n_estimators": 300,
            "max_depth": 3,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "random_state": 42,
        },
    },
    "features": {
        "use_rsi": True,
        "rsi_period": 14,
        "use_macd": True,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
    },
    # Multi-horizon support (default 1–5D)
    "horizons": [1, 2, 3, 4, 5],
    "persist": {
        "enabled": True,
        "model_dir": "models/phase2_cache"
    },
}

Path(CONFIG["persist"]["model_dir"]).mkdir(parents=True, exist_ok=True)

# -----------------------------
# Persistence helpers
# -----------------------------
def _hash_config(cfg: Dict) -> str:
    """Stable hash for model config relevant to training (type, quantiles, window, gbm params)."""
    m = hashlib.sha256()
    # Keep only keys that affect model fitting
    rel = {
        "type": cfg["model"].get("type"),
        "quantiles": cfg["model"].get("quantiles"),
        "window": cfg["model"].get("window"),
        "gbm": cfg["model"].get("gbm"),
    }
    m.update(json.dumps(rel, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return m.hexdigest()[:16]

def _hash_features(feature_cols: list) -> str:
    m = hashlib.sha256()
    m.update(json.dumps(sorted(feature_cols), separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    return m.hexdigest()[:16]

def _model_paths(symbol: str, horizon: int, quantile: float) -> Tuple[Path, Path]:
    """Return (model_path, meta_path)."""
    mdir = Path(CONFIG["persist"]["model_dir"]) / CONFIG["model"]["type"] / symbol / f"h{horizon}"
    mdir.mkdir(parents=True, exist_ok=True)
    qtag = f"q{int(round(quantile*100))}"
    return mdir / f"{qtag}.joblib", mdir / f"{qtag}_meta.json"

def _load_or_train_model(symbol: str,
                         horizon: int,
                         quantile: float,
                         X_h: pd.DataFrame,
                         y_vals: pd.Series,
                         feature_cols: list,
                         train_end_date,
                         cfg_hash: str) -> object:
    """Load cached model if fresh & compatible; else fit and persist."""
    model_path, meta_path = _model_paths(symbol, horizon, quantile)
    feature_hash = _hash_features(feature_cols)
    # Try load
    if model_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if (meta.get("cfg_hash") == cfg_hash and
                meta.get("feature_hash") == feature_hash and
                meta.get("n_rows") == int(len(X_h)) and
                str(meta.get("train_end_date")) == str(train_end_date)):
                return load(model_path)
        except Exception:
            pass  # fall through to retrain
    # Train fresh
    model = _make_model(float(quantile))
    model.fit(X_h, y_vals)
    # Persist
    meta = {
        "symbol": symbol,
        "horizon": int(horizon),
        "quantile": float(quantile),
        "model_type": CONFIG["model"].get("type"),
        "feature_cols": list(feature_cols),
        "feature_hash": feature_hash,
        "cfg_hash": cfg_hash,
        "n_rows": int(len(X_h)),
        "train_end_date": str(train_end_date),
    }
    try:
        dump(model, model_path)
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception as e:
        print(f"⚠️ Phase2: failed to persist model ({model_path}): {e}")
    return model

# -----------------------------
# Helpers
# -----------------------------

def _select_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, list]:
    """Build X, y from df. Keeps existing non-target numeric columns + indicators.
    Expects at least: [Date, Close]. Optionally: [Open, High, Low, Volume, RSI, MACD, MACD_Signal, MACD_Hist].
    Returns (X_df, y, feature_cols_list).
    """
    candidates = [c for c in df.columns if c not in ("Date", "Symbol", "Close")]
    # Ensure indicator columns are included if present
    for c in ("RSI", "MACD", "MACD_Signal", "MACD_Hist"):
        if c in df.columns and c not in candidates:
            candidates.append(c)

    # Keep only numeric columns for safety
    X_df = df[candidates].select_dtypes(include=["number"]).copy()
    y = df["Close"].astype(float)
    return X_df, y, list(X_df.columns)


def _make_model(q: float):
    mtype = CONFIG["model"].get("type", "quantile_linear")
    if mtype == "gbm_quantile":
        if GradientBoostingRegressor is None:
            print("⚠️ sklearn GradientBoostingRegressor unavailable; falling back to QuantileRegressor.")
        else:
            params = CONFIG["model"].get("gbm", {})
            return GradientBoostingRegressor(
                loss="quantile",
                alpha=q,
                n_estimators=int(params.get("n_estimators", 300)),
                max_depth=int(params.get("max_depth", 3)),
                learning_rate=float(params.get("learning_rate", 0.05)),
                subsample=float(params.get("subsample", 0.8)),
                random_state=int(params.get("random_state", 42)),
            )
    # Default linear quantile regression
    return QuantileRegressor(quantile=q, alpha=0.0, fit_intercept=True)


# ----------------------------------------
# Public API (kept identical):
#   generate_forecast(symbol, df) -> pd.DataFrame
# ----------------------------------------

def generate_forecast(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Train quantile model(s) on historical data and return a single LIVE +1D band row.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g., "AAPL").
    df : pd.DataFrame
        Must include columns: ["Date", "Close"]. Optional: ["Open","High","Low","Volume"].
        Additional engineered features are added internally (RSI/MACD) if available.

    Returns
    -------
    pd.DataFrame with columns: ["Date","Symbol","Q10","Q50","Q90","Pattern","Timeframe","Horizon"]. One row per horizon (e.g., 1D..5D).
    """
    if df is None or df.empty:
        raise ValueError("generate_forecast: empty dataframe provided")

    # Ensure proper ordering and types
    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["Date"]):
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date").dropna(subset=["Date", "Close"]).reset_index(drop=True)

    # Add technicals and optionally window the training set
    df_feat = enrich_features(df, cfg={"rsi_period": CONFIG["features"].get("rsi_period", 14), "macd_fast": CONFIG["features"].get("macd_fast", 12), "macd_slow": CONFIG["features"].get("macd_slow", 26), "macd_signal": CONFIG["features"].get("macd_signal", 9)})

    window = CONFIG["model"].get("window", 252)
    if isinstance(window, int) and window > 0 and len(df_feat) > window:
        train_df = df_feat.iloc[-window:].copy()
    else:
        train_df = df_feat

    cfg_hash = _hash_config(CONFIG)
    train_end_date = train_df["Date"].iloc[-1]

    # Build X/y
    X_df, y, feature_cols = _select_features(train_df)
    if len(X_df) < 30:  # minimal sanity to avoid degenerate fits
        raise ValueError(f"generate_forecast: insufficient rows after feature prep ({len(X_df)} < 30)")

    # Fit models and predict per horizon (direct multi-step: shift(-h))
    quantiles = CONFIG["model"].get("quantiles", [0.10, 0.50, 0.90])
    horizons = CONFIG.get("horizons", [1])

    rows = []
    asof = df_feat["Date"].iloc[-1]
    x_live = X_df.iloc[[-1]].copy()  # last available features as live anchor

    for h in horizons:
        # Future target at horizon h
        y_h = y.shift(-int(h))
        valid = y_h.notna()
        if valid.sum() < 30:
            # Skip horizons without enough training rows
            print(f"⚠️ Phase2: insufficient rows for horizon {h}D ({valid.sum()} < 30). Skipping.")
            continue

        X_h = X_df[valid].values
        y_vals = y_h[valid].values

        # Load-or-train one model per quantile with on-disk persistence
        models = {}
        for q in quantiles:
            m = _load_or_train_model(symbol=symbol,
                                     horizon=int(h),
                                     quantile=float(q),
                                     X_h=pd.DataFrame(X_h, columns=feature_cols) if not isinstance(X_h, pd.DataFrame) else X_h,
                                     y_vals=y_vals,
                                     feature_cols=feature_cols,
                                     train_end_date=train_end_date,
                                     cfg_hash=cfg_hash)
            models[q] = m

        # Predict LIVE quantiles for this horizon
        preds_h: Dict[float, float] = {q: float(models[q].predict(x_live)[0]) for q in quantiles}
        q10, q50, q90 = sorted([preds_h.get(0.10), preds_h.get(0.50), preds_h.get(0.90)])

        rows.append({
            "Date": asof,
            "Symbol": symbol,
            "Q10": q10,
            "Q50": q50,
            "Q90": q90,
            "Pattern": "LIVE",
            "Timeframe": "1D",
            "Horizon": f"{h}D",
        })

    if not rows:
        raise ValueError("generate_forecast: no horizons produced (insufficient data)")

    out = pd.DataFrame(rows)

    # Friendly log lines so runs are traceable
    for r in rows:
        print(
            f"Phase2 Quantile ({CONFIG['model']['type']}): {symbol} @1D +{r['Horizon']} → "
            f"Q10={r['Q10']:.2f}, Q50={r['Q50']:.2f}, Q90={r['Q90']:.2f}"
        )

    return out
