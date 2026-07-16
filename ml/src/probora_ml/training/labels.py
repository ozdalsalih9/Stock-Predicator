from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class NeutralBandConfig:
    volatility_multiplier: float = 0.5
    long_term_volatility_weight: float = 0.35
    annualized_volatility_floor: float = 0.20
    annualized_volatility_cap: float = 1.50
    minimum_30d_threshold: float = 0.025
    maximum_30d_threshold: float = 0.18


DEFAULT_NEUTRAL_BAND = NeutralBandConfig()


def neutral_band_threshold(
    annualized_volatility_30d: float,
    horizon_days: int,
    annualized_volatility_90d: float | None = None,
    config: NeutralBandConfig = DEFAULT_NEUTRAL_BAND,
    periods_per_year: int = 365,
) -> float:
    if horizon_days not in (30, 90):
        raise ValueError("Only 30 and 90 day horizons are supported.")
    long_term = (
        annualized_volatility_30d
        if annualized_volatility_90d is None
        else annualized_volatility_90d
    )
    if not math.isfinite(annualized_volatility_30d) or not math.isfinite(long_term):
        raise ValueError("Volatility must be finite.")
    weight = config.long_term_volatility_weight
    blended = math.sqrt(
        (1 - weight) * annualized_volatility_30d**2 + weight * long_term**2
    )
    robust_volatility = min(
        config.annualized_volatility_cap,
        max(config.annualized_volatility_floor, blended),
    )
    horizon_scale = math.sqrt(horizon_days / 30)
    raw_threshold = (
        config.volatility_multiplier * robust_volatility * math.sqrt(horizon_days / periods_per_year)
    )
    return min(
        config.maximum_30d_threshold * horizon_scale,
        max(config.minimum_30d_threshold * horizon_scale, raw_threshold),
    )


def direction_label(
    current_close: float,
    future_close: float,
    annualized_volatility_30d: float,
    horizon_days: int,
    annualized_volatility_90d: float | None = None,
    config: NeutralBandConfig = DEFAULT_NEUTRAL_BAND,
    periods_per_year: int = 365,
) -> int:
    if current_close <= 0 or future_close <= 0:
        raise ValueError("Prices must be positive.")
    forward_return = math.log(future_close / current_close)
    threshold = neutral_band_threshold(
        annualized_volatility_30d,
        horizon_days,
        annualized_volatility_90d,
        config,
        periods_per_year,
    )
    return 2 if forward_return > threshold else 0 if forward_return < -threshold else 1


def attach_targets(
    features: pd.DataFrame,
    daily_by_symbol: dict[str, pd.DataFrame],
    horizon_days: int,
    periods_per_year: int = 365,
    volatility_short_column: str = "volatility_30d",
    volatility_long_column: str = "volatility_90d",
) -> pd.DataFrame:
    output = features.copy()
    target_rows: list[dict[str, object]] = []
    for symbol, rows in output.groupby("asset_id", sort=False):
        prices = daily_by_symbol[symbol].copy()
        prices["open_time"] = pd.to_datetime(prices["open_time"], utc=True)
        prices = prices.set_index("open_time").sort_index()
        for index, row in rows.iterrows():
            snapshot = pd.Timestamp(row["snapshot_time"])
            if snapshot not in prices.index:
                continue
            location = prices.index.get_loc(snapshot)
            if not isinstance(location, int) or location + horizon_days >= len(prices):
                continue
            current = float(prices.iloc[location]["close"])
            future_window = prices.iloc[location + 1 : location + horizon_days + 1]
            future = float(future_window.iloc[-1]["close"])
            forward_return = math.log(future / current)
            future_returns = np.diff(np.log(future_window["close"].to_numpy(float)))
            label_volatility_30d = float(row[volatility_short_column])
            label_volatility_90d = float(row[volatility_long_column])
            neutral_threshold = neutral_band_threshold(
                label_volatility_30d,
                horizon_days,
                label_volatility_90d,
                periods_per_year=periods_per_year,
            )
            target_rows.append(
                {
                    "index": index,
                    "target_return": forward_return,
                    "target_direction": direction_label(
                        current,
                        future,
                        label_volatility_30d,
                        horizon_days,
                        label_volatility_90d,
                        periods_per_year=periods_per_year,
                    ),
                    "neutral_band_threshold": neutral_threshold,
                    "label_volatility_30d": label_volatility_30d,
                    "label_volatility_90d": label_volatility_90d,
                    "target_volatility": float(
                        np.std(future_returns, ddof=1) * math.sqrt(periods_per_year)
                    )
                    if len(future_returns) > 1
                    else 0,
                    "target_max_drawdown": float(
                        (future_window["close"] / future_window["close"].cummax() - 1).min()
                    ),
                    "label_end_time": pd.Timestamp(future_window.index[-1]),
                    "horizon_days": horizon_days,
                }
            )
    targets = pd.DataFrame(target_rows).set_index("index") if target_rows else pd.DataFrame()
    return output.join(targets, how="inner")
