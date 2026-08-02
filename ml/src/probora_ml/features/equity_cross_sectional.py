from __future__ import annotations

import numpy as np
import pandas as pd

BREADTH_DISPERSION_FEATURE_NAMES = (
    "market_breadth_5s",
    "market_breadth_60s",
    "market_above_ma_20s",
    "market_above_ma_60s",
    "cross_sectional_return_dispersion_20s",
    "cross_sectional_return_dispersion_60s",
    "market_breadth_momentum",
)

PEER_RELATIVE_FEATURE_NAMES = (
    "peer_relative_return_20s",
    "peer_relative_return_60s",
    "peer_relative_volatility_20s",
)

EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES = (
    *BREADTH_DISPERSION_FEATURE_NAMES,
    *PEER_RELATIVE_FEATURE_NAMES,
)

PEER_BENCHMARKS = {
    "AAPL": "QQQ",
    "AMZN": "QQQ",
    "GOOGL": "QQQ",
    "META": "QQQ",
    "MSFT": "QQQ",
    "NVDA": "QQQ",
    "TSLA": "QQQ",
    "JPM": "XLF",
    "V": "XLF",
    "XOM": "XLE",
    "UNH": "XLV",
}


def add_equity_cross_sectional_features(samples: pd.DataFrame) -> pd.DataFrame:
    """Add same-cutoff breadth, dispersion and peer-relative research features.

    Every input row must represent a completed daily session. Aggregations only
    use feature values sharing that snapshot and horizon, so no future price or
    outcome enters the feature group.
    """
    required = {
        "asset_id",
        "snapshot_time",
        "horizon_days",
        "return_5s",
        "return_20s",
        "return_60s",
        "volatility_20s",
        "ma_ratio_20s",
        "ma_ratio_60s",
        "market_regime",
    }
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(f"Equity samples are missing: {', '.join(missing)}")

    frame = samples.drop(
        columns=[
            *EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES,
            "peer_benchmark_id",
        ],
        errors="ignore",
    ).copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    keys = ["snapshot_time", "horizon_days"]
    universe = frame[frame["asset_id"] != "SPY"]

    breadth = (
        universe.groupby(keys, sort=False)
        .agg(
            market_breadth_5s=("return_5s", lambda values: float((values > 0).mean())),
            market_breadth_60s=("return_60s", lambda values: float((values > 0).mean())),
            market_above_ma_20s=("ma_ratio_20s", lambda values: float((values > 0).mean())),
            market_above_ma_60s=("ma_ratio_60s", lambda values: float((values > 0).mean())),
            cross_sectional_return_dispersion_20s=("return_20s", lambda values: float(values.std(ddof=0))),
            cross_sectional_return_dispersion_60s=("return_60s", lambda values: float(values.std(ddof=0))),
        )
        .reset_index()
    )
    breadth["market_breadth_momentum"] = breadth["market_breadth_5s"] - breadth["market_breadth_60s"]
    frame = frame.merge(breadth, on=keys, how="left", validate="many_to_one")

    benchmark_regime = frame[frame["asset_id"] == "SPY"][[*keys, "market_regime"]].rename(
        columns={"market_regime": "benchmark_market_regime_diagnostic"}
    )
    frame = frame.merge(benchmark_regime, on=keys, how="left", validate="many_to_one")

    frame["peer_benchmark_id"] = frame["asset_id"].map(PEER_BENCHMARKS).fillna("SPY")
    peers = frame[
        [
            *keys,
            "asset_id",
            "return_20s",
            "return_60s",
            "volatility_20s",
        ]
    ].rename(
        columns={
            "asset_id": "peer_benchmark_id",
            "return_20s": "peer_return_20s",
            "return_60s": "peer_return_60s",
            "volatility_20s": "peer_volatility_20s",
        }
    )
    frame = frame.merge(
        peers,
        on=[*keys, "peer_benchmark_id"],
        how="left",
        validate="many_to_one",
    )
    if frame[["peer_return_20s", "peer_return_60s", "peer_volatility_20s"]].isna().any().any():
        raise ValueError("A peer benchmark is missing at one or more equity cutoffs.")
    frame["peer_relative_return_20s"] = frame["return_20s"] - frame["peer_return_20s"]
    frame["peer_relative_return_60s"] = frame["return_60s"] - frame["peer_return_60s"]
    frame["peer_relative_volatility_20s"] = frame["volatility_20s"] - frame["peer_volatility_20s"]
    frame = frame.drop(columns=["peer_return_20s", "peer_return_60s", "peer_volatility_20s"])
    feature_values = frame.loc[:, EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES]
    if not np.isfinite(feature_values.to_numpy(float)).all():
        raise ValueError("Cross-sectional feature generation produced non-finite values.")
    if "dataset_version" in frame and not frame.empty:
        source_version = str(frame["dataset_version"].iloc[0]).split("+cross-sectional-exp1", maxsplit=1)[0]
        frame["dataset_version"] = f"{source_version}+cross-sectional-exp1"
    return frame
