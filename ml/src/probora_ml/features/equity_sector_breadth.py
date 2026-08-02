from __future__ import annotations

import numpy as np
import pandas as pd

EXISTING_SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV")
EXTERNAL_SECTOR_ETFS = ("XLY", "XLP", "XLI", "XLB", "XLU")
ALL_SECTOR_ETFS = (*EXISTING_SECTOR_ETFS, *EXTERNAL_SECTOR_ETFS)

SECTOR_BREADTH_FEATURE_NAMES = (
    "sector_breadth_5s",
    "sector_breadth_20s",
    "sector_breadth_60s",
    "sector_return_dispersion_20s",
    "sector_return_dispersion_60s",
    "sector_cyclical_defensive_spread_20s",
    "sector_cyclical_defensive_spread_60s",
)
SECTOR_PEER_FEATURE_NAMES = (
    "sector_peer_relative_return_20s",
    "sector_peer_relative_return_60s",
    "sector_peer_relative_volatility_20s",
)
EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES = (
    *SECTOR_BREADTH_FEATURE_NAMES,
    *SECTOR_PEER_FEATURE_NAMES,
)

SECTOR_PEER_BENCHMARKS = {
    "AAPL": "XLK",
    "MSFT": "XLK",
    "NVDA": "XLK",
    "AMZN": "XLY",
    "TSLA": "XLY",
    "JPM": "XLF",
    "V": "XLF",
    "XOM": "XLE",
    "UNH": "XLV",
    "WMT": "XLP",
    "GOOGL": "QQQ",
    "META": "QQQ",
}


def _external_sector_features(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "open_time", "close"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"External sector bars are missing: {', '.join(missing)}")
    frames: list[pd.DataFrame] = []
    for symbol, group in bars.groupby("symbol", sort=False):
        frame = group.sort_values("open_time").copy()
        close = frame["close"].astype(float)
        returns = np.log(close / close.shift(1))
        frames.append(
            pd.DataFrame(
                {
                    "asset_id": symbol,
                    "snapshot_time": pd.to_datetime(frame["open_time"], utc=True),
                    "return_5s": np.log(close / close.shift(5)),
                    "return_20s": np.log(close / close.shift(20)),
                    "return_60s": np.log(close / close.shift(60)),
                    "volatility_20s": returns.rolling(20).std(ddof=1) * np.sqrt(252),
                }
            )
        )
    return pd.concat(frames, ignore_index=True).dropna()


def add_equity_sector_breadth_features(
    samples: pd.DataFrame,
    external_sector_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Add nine-sector breadth and sector-relative features at the same EOD cutoff."""
    required = {
        "asset_id",
        "snapshot_time",
        "horizon_days",
        "return_5s",
        "return_20s",
        "return_60s",
        "volatility_20s",
    }
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(f"Equity samples are missing: {', '.join(missing)}")
    frame = samples.drop(
        columns=[*EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES, "sector_peer_benchmark_id"],
        errors="ignore",
    ).copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)

    existing = frame[frame["asset_id"].isin(EXISTING_SECTOR_ETFS)][
        [
            "asset_id",
            "snapshot_time",
            "return_5s",
            "return_20s",
            "return_60s",
            "volatility_20s",
        ]
    ].drop_duplicates(["asset_id", "snapshot_time"], keep="last")
    external = _external_sector_features(external_sector_bars)
    received_external = set(external["asset_id"].unique())
    if received_external != set(EXTERNAL_SECTOR_ETFS):
        raise ValueError(
            f"External sector coverage mismatch: expected {set(EXTERNAL_SECTOR_ETFS)}, "
            f"received {received_external}"
        )
    sectors = pd.concat([existing, external], ignore_index=True)
    sectors = sectors[sectors["asset_id"].isin(ALL_SECTOR_ETFS)]
    counts = sectors.groupby("snapshot_time")["asset_id"].nunique()
    complete_dates = counts[counts == len(ALL_SECTOR_ETFS)].index
    sectors = sectors[sectors["snapshot_time"].isin(complete_dates)].copy()

    aggregate = (
        sectors.groupby("snapshot_time", sort=False)
        .agg(
            sector_breadth_5s=("return_5s", lambda values: float((values > 0).mean())),
            sector_breadth_20s=("return_20s", lambda values: float((values > 0).mean())),
            sector_breadth_60s=("return_60s", lambda values: float((values > 0).mean())),
            sector_return_dispersion_20s=("return_20s", lambda values: float(values.std(ddof=0))),
            sector_return_dispersion_60s=("return_60s", lambda values: float(values.std(ddof=0))),
        )
        .reset_index()
    )
    returns = sectors.pivot(index="snapshot_time", columns="asset_id", values=["return_20s", "return_60s"])
    cyclical = ("XLK", "XLY", "XLI", "XLB", "XLF", "XLE")
    defensive = ("XLP", "XLU", "XLV")
    for sessions in (20, 60):
        values = returns[f"return_{sessions}s"]
        spread = values.loc[:, cyclical].mean(axis=1) - values.loc[:, defensive].mean(axis=1)
        aggregate = aggregate.merge(
            spread.rename(f"sector_cyclical_defensive_spread_{sessions}s").reset_index(),
            on="snapshot_time",
            how="left",
            validate="one_to_one",
        )
    frame = frame.merge(aggregate, on="snapshot_time", how="left", validate="many_to_one")

    peer_source = frame[
        [
            "asset_id",
            "snapshot_time",
            "return_20s",
            "return_60s",
            "volatility_20s",
        ]
    ].drop_duplicates(["asset_id", "snapshot_time"], keep="last")
    peer_source = pd.concat([peer_source, external], ignore_index=True).drop_duplicates(
        ["asset_id", "snapshot_time"], keep="last"
    )
    peer_source = peer_source.rename(
        columns={
            "asset_id": "sector_peer_benchmark_id",
            "return_20s": "sector_peer_return_20s",
            "return_60s": "sector_peer_return_60s",
            "volatility_20s": "sector_peer_volatility_20s",
        }
    )
    frame["sector_peer_benchmark_id"] = frame["asset_id"].map(SECTOR_PEER_BENCHMARKS).fillna("SPY")
    frame = frame.merge(
        peer_source[
            [
                "sector_peer_benchmark_id",
                "snapshot_time",
                "sector_peer_return_20s",
                "sector_peer_return_60s",
                "sector_peer_volatility_20s",
            ]
        ],
        on=["sector_peer_benchmark_id", "snapshot_time"],
        how="left",
        validate="many_to_one",
    )
    frame["sector_peer_relative_return_20s"] = frame["return_20s"] - frame["sector_peer_return_20s"]
    frame["sector_peer_relative_return_60s"] = frame["return_60s"] - frame["sector_peer_return_60s"]
    frame["sector_peer_relative_volatility_20s"] = (
        frame["volatility_20s"] - frame["sector_peer_volatility_20s"]
    )
    frame = frame.drop(
        columns=[
            "sector_peer_return_20s",
            "sector_peer_return_60s",
            "sector_peer_volatility_20s",
        ]
    )
    feature_values = frame.loc[:, EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES]
    if feature_values.isna().any().any():
        missing_rows = int(feature_values.isna().any(axis=1).sum())
        raise ValueError(f"Nine-sector feature coverage is incomplete for {missing_rows} rows.")
    if not np.isfinite(feature_values.to_numpy(float)).all():
        raise ValueError("Sector feature generation produced non-finite values.")
    if "dataset_version" in frame and not frame.empty:
        source_version = str(frame["dataset_version"].iloc[0]).split("+sector-breadth-exp1", maxsplit=1)[0]
        frame["dataset_version"] = f"{source_version}+sector-breadth-exp1"
    return frame
