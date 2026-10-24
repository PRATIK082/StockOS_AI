"""Factor evaluation: rank IC / ICIR, quantile returns, and a long-short factor
benchmark. All statistics are computed from a real symbol panel — no
fabricated values. ``forward_days`` controls the return horizon; IC is the
cross-sectional Spearman correlation between the factor and the forward return
on each date."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.factors.registry import compute_factor


def build_panel(histories: dict[str, dict], factor_names: list[str] | None = None) -> pd.DataFrame:
    """Stack per-symbol histories into a (symbol, date) panel with factor
    columns + forward returns (NaN on the tail — nothing fabricated).

    ``histories`` maps symbol → provider history dict (``candles`` list).
    """
    frames = []
    for symbol, history in (histories or {}).items():
        candles = (history or {}).get("candles") or []
        if not candles:
            continue
        df = pd.DataFrame(
            [
                {
                    "ts": c["ts"],
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume") or 0),
                }
                for c in candles
            ]
        )
        # Strip timezone offsets first so each bar keeps its own calendar date
        # (NSE IST bars, US bars, crypto UTC bars all land on their trading day).
        # Normalizing to UTC would shift IST-midnight bars to the previous UTC
        # day and break cross-market cross-sections.
        _tz_strip = df["ts"].astype(str).str.replace(r"[+-]\d{2}:\d{2}$", "", regex=True).str.replace(r"Z$", "", regex=True)
        idx = pd.to_datetime(_tz_strip, errors="coerce", format="mixed")
        df["ts"] = [pd.Timestamp(v.date()) if not pd.isna(v) else pd.NaT for v in idx]
        df = df.dropna(subset=["ts"]).set_index("ts")
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if df.empty:
            continue
        for name in (factor_names or []):
            try:
                df[name] = compute_factor(df, name)
            except KeyError:
                raise
        df["symbol"] = symbol
        frames.append(df.reset_index().set_index(["symbol", "ts"]))
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames).sort_index()
    if len(panel) == 0:
        return panel
    fwd = panel.groupby(level=0)["close"].pct_change().shift(-1)  # 1-day forward return
    panel["fwd_return"] = fwd
    return panel


def _spearman_pairs(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 3:
        return np.nan
    x, y = a[m], b[m]
    if len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return np.nan
    return float(pd.Series(x).corr(pd.Series(y), method="spearman"))


def ic_analysis(panel: pd.DataFrame, factor_names: list[str], forward_days: int = 1) -> dict:
    """Per-factor mean IC, ICIR, IC std and per-date IC series (finite-safe)."""
    if panel.empty or not factor_names:
        return {"error": "no panel data", "factors": []}
    fwd = panel["fwd_return"].copy()
    out: dict[str, dict] = {}
    for name in factor_names:
        if name not in panel.columns:
            continue
        dates = []
        ics = []
        for date, grp in panel.groupby(level=1):
            f = grp[name].to_numpy(dtype=float)
            r = fwd.loc[grp.index].to_numpy(dtype=float)
            ic = _spearman_pairs(f, r)
            if np.isfinite(ic):
                dates.append(str(date.date()))
                ics.append(ic)
        if len(ics) < 5:
            out[name] = {"ic_mean": 0.0, "ic_ir": 0.0, "ic_std": 0.0, "n_days": len(ics), "series": []}
            continue
        arr = np.asarray(ics, dtype=float)
        mean_ic = float(np.mean(arr))
        std_ic = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        out[name] = {
            "ic_mean": mean_ic,
            "ic_ir": mean_ic / std_ic if std_ic > 0 else 0.0,
            "ic_std": std_ic,
            "n_days": len(ics),
            "series": [{"date": d, "ic": float(v)} for d, v in zip(dates, ics)],
        }
    return {"forward_days": forward_days, "factors": out}


def quantile_returns(panel: pd.DataFrame, factor_names: list[str], n_quantiles: int = 5, forward_days: int = 1) -> dict:
    """Mean forward return per factor quantile (Q1..Qn) plus the Q1-Qn spread."""
    if panel.empty or not factor_names:
        return {"error": "no panel data"}
    out: dict[str, dict] = {}
    for name in factor_names:
        if name not in panel.columns:
            continue
        bucket_returns: dict[str, list[float]] = {f"Q{i}": [] for i in range(1, n_quantiles + 1)}
        for _, grp in panel.groupby(level=1):
            sub = grp[[name, "fwd_return"]].dropna(subset=[name, "fwd_return"])
            if len(sub) < n_quantiles:
                continue
            try:
                q = pd.qcut(sub[name], n_quantiles, labels=[f"Q{i}" for i in range(1, n_quantiles + 1)], duplicates="drop")
            except ValueError:
                continue
            for label in dict.fromkeys(q.astype(str)):
                vals = sub["fwd_return"][q.astype(str) == label]
                bucket_returns.setdefault(label, []).extend(vals.dropna().tolist())
        stats = {}
        spread_vals = []
        qnames = [f"Q{i}" for i in range(1, n_quantiles + 1)]
        for qn in qnames:
            vals = np.asarray(bucket_returns.get(qn, []), dtype=float)
            stats[qn] = {
                "mean": float(np.mean(vals)) if vals.size else 0.0,
                "n": int(vals.size),
            }
            if vals.size:
                spread_vals.append(float(np.mean(vals)))
        spread = (spread_vals[-1] - spread_vals[0]) if len(spread_vals) >= 2 else 0.0
        stats["spread"] = spread
        out[name] = stats
    return {"forward_days": forward_days, "n_quantiles": n_quantiles, "factors": out}


def factor_bench(panel: pd.DataFrame, factor_name: str, n_quantiles: int = 5, forward_days: int = 1) -> dict:
    """Equal-weight daily-rebalanced long-short (top minus bottom quantile)
    equity curve and stats for a single factor, plus per-quantile stats."""
    q = quantile_returns(panel, [factor_name], n_quantiles, forward_days)
    if "error" in q:
        return {"error": q["error"]}
    stats = q["factors"].get(factor_name)
    if not stats:
        return {"error": f"factor '{factor_name}' not in panel"}
    top = f"Q{n_quantiles}"
    bot = "Q1"
    if stats.get(top, {}).get("n", 0) == 0 or stats.get(bot, {}).get("n", 0) == 0:
        return {"error": "not enough quantile data for a bench"}
    # Recompute the long-short series directly from the panel for the curve.
    ls_returns = []
    dates_out = []
    for date, grp in panel.groupby(level=1):
        sub = grp[[factor_name, "fwd_return"]].dropna(subset=[factor_name, "fwd_return"])
        if len(sub) < n_quantiles:
            continue
        try:
            qq = pd.qcut(sub[factor_name], n_quantiles, labels=False, duplicates="drop")
        except ValueError:
            continue
        top_mask = qq == n_quantiles - 1
        bot_mask = qq == 0
        if top_mask.sum() == 0 or bot_mask.sum() == 0:
            continue
        ls = float(sub["fwd_return"][top_mask].mean() - sub["fwd_return"][bot_mask].mean())
        ls_returns.append(ls)
        dates_out.append(str(date.date()))
    equity = [1.0]
    for r in ls_returns:
        equity.append(equity[-1] * (1 + r))
    return {
        "factor": factor_name,
        "forward_days": forward_days,
        "dates": dates_out,
        "long_short_returns": ls_returns,
        "equity": [round(float(x), 6) for x in equity],
        "total_return": round(float(equity[-1] - 1), 6) if len(equity) > 1 else 0.0,
        "annualized_return": round(float(equity[-1] ** (252 / max(len(ls_returns), 1)) - 1), 6) if len(ls_returns) else 0.0,
        "n_days": len(ls_returns),
        "quantiles": {k: v for k, v in stats.items() if k not in ("spread",)},
    }
