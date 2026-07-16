from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.config import DERIVATIVE_FEATURE_NAMES


def _read_many(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        return pd.DataFrame()
    return pd.concat((pd.read_parquet(path) for path in paths), ignore_index=True)


def _daily_klines(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    values = frame.copy()
    values["snapshot_time"] = (
        pd.to_datetime(values["open_time"], utc=True).dt.floor("D") + pd.Timedelta(days=1)
    )
    return values.groupby("snapshot_time", as_index=False).agg(
        **{
            f"{prefix}_close": ("close", "last"),
            f"{prefix}_quote_volume": ("quote_volume", "sum"),
            f"{prefix}_volume": ("volume", "sum"),
            f"{prefix}_taker_buy_volume": ("taker_buy_base_volume", "sum"),
        }
    )


def load_derivatives_daily(processed_root: Path, symbol: str) -> pd.DataFrame:
    cache_path = processed_root / "consolidated" / f"{symbol}-daily.parquet"
    base = processed_root / "futures" / "um"
    funding_paths = sorted((base / "monthly" / "fundingRate" / symbol).glob("*.parquet"))
    premium_paths = sorted(
        (base / "monthly" / "premiumIndexKlines" / symbol / "1h").glob("*.parquet")
    )
    futures_paths = sorted((base / "monthly" / "klines" / symbol / "1h").glob("*.parquet"))
    metrics_paths = sorted((base / "daily" / "metrics" / symbol).glob("*.parquet"))
    source_paths = [*funding_paths, *premium_paths, *futures_paths, *metrics_paths]
    if cache_path.exists() and source_paths:
        newest_source = max(path.stat().st_mtime_ns for path in source_paths)
        if cache_path.stat().st_mtime_ns >= newest_source:
            return pd.read_parquet(cache_path)
    funding = _read_many(funding_paths)
    premium = _read_many(premium_paths)
    futures = _read_many(futures_paths)

    frames: list[pd.DataFrame] = []
    if not funding.empty:
        funding["snapshot_time"] = (
            pd.to_datetime(funding["calc_time"], utc=True).dt.floor("D") + pd.Timedelta(days=1)
        )
        frames.append(
            funding.groupby("snapshot_time", as_index=False).agg(
                funding_rate=("last_funding_rate", "mean")
            )
        )
    if not premium.empty:
        premium_daily = _daily_klines(premium, "premium")
        frames.append(
            premium_daily[["snapshot_time", "premium_close"]].rename(
                columns={"premium_close": "premium"}
            )
        )
    if not futures.empty:
        futures_daily = _daily_klines(futures, "futures")
        futures_daily["futures_taker_buy_ratio"] = np.where(
            futures_daily["futures_volume"] > 0,
            futures_daily["futures_taker_buy_volume"] / futures_daily["futures_volume"],
            0.5,
        )
        frames.append(
            futures_daily[
                ["snapshot_time", "futures_quote_volume", "futures_taker_buy_ratio"]
            ]
        )

    metrics_rows: list[dict[str, object]] = []
    for path in metrics_paths:
        metrics = pd.read_parquet(
            path,
            columns=[
                "create_time",
                "sum_open_interest_value",
                "count_long_short_ratio",
                "sum_taker_long_short_vol_ratio",
            ],
        )
        if metrics.empty:
            continue
        metrics = metrics.sort_values("create_time")
        metrics_rows.append(
            {
                "snapshot_time": pd.Timestamp(metrics.iloc[-1]["create_time"]).floor("D")
                + pd.Timedelta(days=1),
                "open_interest_value": float(metrics.iloc[-1]["sum_open_interest_value"]),
                "long_short_ratio": float(metrics["count_long_short_ratio"].mean()),
                "taker_long_short_ratio": float(
                    metrics["sum_taker_long_short_vol_ratio"].mean()
                ),
            }
        )
    if metrics_rows:
        frames.append(pd.DataFrame(metrics_rows))
    if not frames:
        return pd.DataFrame()

    daily = frames[0]
    for frame in frames[1:]:
        daily = daily.merge(frame, on="snapshot_time", how="outer")
    required_columns = (
        "funding_rate",
        "premium",
        "futures_quote_volume",
        "futures_taker_buy_ratio",
        "open_interest_value",
        "long_short_ratio",
        "taker_long_short_ratio",
    )
    for name in required_columns:
        if name not in daily:
            daily[name] = np.nan
    daily["snapshot_time"] = pd.to_datetime(daily["snapshot_time"], utc=True)
    daily = daily.sort_values("snapshot_time").drop_duplicates("snapshot_time", keep="last")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(cache_path, index=False, compression="zstd")
    return daily


def _mean(values: pd.Series, days: int, default: float = 0.0) -> float:
    valid = values.dropna().tail(days)
    return float(valid.mean()) if not valid.empty else default


def _zscore(values: pd.Series, days: int) -> float:
    valid = values.dropna().tail(days)
    if len(valid) < 10:
        return 0.0
    standard_deviation = float(valid.std(ddof=1))
    return 0.0 if standard_deviation == 0 else float((valid.iloc[-1] - valid.mean()) / standard_deviation)


def _log_change(values: pd.Series, days: int) -> float:
    valid = values.dropna()
    if len(valid) <= days:
        return 0.0
    current = float(valid.iloc[-1])
    previous = float(valid.iloc[-(days + 1)])
    return 0.0 if current <= 0 or previous <= 0 else math.log(current / previous)


def build_derivative_feature_row(history: pd.DataFrame | None) -> dict[str, float]:
    if history is None or history.empty:
        return {name: 0.0 for name in DERIVATIVE_FEATURE_NAMES}
    frame = history.sort_values("snapshot_time")
    latest = pd.Timestamp(frame.iloc[-1]["snapshot_time"])
    required = [
        "funding_rate",
        "premium",
        "futures_quote_volume",
        "open_interest_value",
    ]
    available = (
        len(frame) >= 30
        and latest - pd.Timestamp(frame.iloc[-30]["snapshot_time"]) >= pd.Timedelta(days=29)
        and bool(frame.iloc[-1][required].notna().all())
    )
    values = {
        "funding_rate_mean_7d": _mean(frame["funding_rate"], 7),
        "funding_rate_mean_30d": _mean(frame["funding_rate"], 30),
        "funding_rate_zscore_90d": _zscore(frame["funding_rate"], 90),
        "premium_mean_7d": _mean(frame["premium"], 7),
        "premium_mean_30d": _mean(frame["premium"], 30),
        "premium_zscore_90d": _zscore(frame["premium"], 90),
        "futures_volume_zscore_30d": _zscore(frame["futures_quote_volume"], 30),
        "futures_taker_buy_ratio_7d": _mean(frame["futures_taker_buy_ratio"], 7, 0.5),
        "open_interest_change_7d": _log_change(frame["open_interest_value"], 7),
        "open_interest_change_30d": _log_change(frame["open_interest_value"], 30),
        "open_interest_zscore_90d": _zscore(frame["open_interest_value"], 90),
        "futures_long_short_ratio_7d": _mean(frame["long_short_ratio"], 7, 1.0),
        "futures_taker_long_short_ratio_7d": _mean(
            frame["taker_long_short_ratio"], 7, 1.0
        ),
        "derivatives_available": float(available),
    }
    return {
        name: float(np.nan_to_num(values[name], nan=0.0, posinf=0.0, neginf=0.0))
        for name in DERIVATIVE_FEATURE_NAMES
    }
