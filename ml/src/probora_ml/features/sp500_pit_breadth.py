from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.ingestion.twelve_data_equity import (
    canonical_equity_symbol,
    load_sp500_history_symbol_files,
    require_sp500_pit_coverage,
)

SP500_PIT_BREADTH_FEATURE_NAMES = (
    "sp500_advance_ratio_1s",
    "sp500_breadth_5s",
    "sp500_breadth_20s",
    "sp500_breadth_60s",
    "sp500_above_ma_20s",
    "sp500_above_ma_60s",
    "sp500_return_dispersion_20s",
    "sp500_return_dispersion_60s",
    "sp500_median_return_20s",
    "sp500_median_return_60s",
)


def load_sp500_pit_bars(history_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in load_sp500_history_symbol_files(history_root).values():
        frames.append(pd.read_parquet(path, columns=["symbol", "open_time", "close"]))
    if not frames:
        raise ValueError("No successful S&P point-in-time price files were found.")
    return pd.concat(frames, ignore_index=True)


def _price_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "open_time", "close"}
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"S&P bars are missing: {', '.join(missing)}")
    frames: list[pd.DataFrame] = []
    for symbol, group in bars.groupby("symbol", sort=False):
        frame = group.sort_values("open_time").drop_duplicates("open_time", keep="last").copy()
        close = pd.to_numeric(frame["close"], errors="coerce")
        log_close = np.log(close)
        frame["symbol"] = canonical_equity_symbol(str(symbol))
        frame["snapshot_time"] = pd.to_datetime(frame["open_time"], utc=True).dt.normalize()
        for sessions in (1, 5, 20, 60):
            frame[f"return_{sessions}s"] = log_close - log_close.shift(sessions)
        for sessions in (20, 60):
            frame[f"ma_ratio_{sessions}s"] = close / close.rolling(sessions).mean() - 1
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def build_sp500_pit_breadth(
    bars: pd.DataFrame,
    membership: pd.DataFrame,
    required_dates: pd.Series,
    minimum_coverage: float = 0.95,
) -> pd.DataFrame:
    """Aggregate only members known at each completed session cutoff."""
    if not 0 < minimum_coverage <= 1:
        raise ValueError("Minimum S&P breadth coverage must be in (0, 1].")
    required = membership.copy()
    required["date"] = pd.to_datetime(required["date"], utc=True).dt.normalize()
    required = required.sort_values("date").drop_duplicates("date", keep="last")
    indicators = _price_indicators(bars)
    requested = pd.to_datetime(required_dates, utc=True).dt.normalize().drop_duplicates().sort_values()
    indicators = indicators[indicators["snapshot_time"].isin(requested)]
    days = {date: frame for date, frame in indicators.groupby("snapshot_time", sort=False)}
    membership_dates = required["date"].astype("int64").to_numpy()
    membership_values = required["tickers"].astype(str).to_numpy()

    rows: list[dict[str, object]] = []
    incomplete: list[tuple[str, float]] = []
    indicator_columns = (
        "return_1s",
        "return_5s",
        "return_20s",
        "return_60s",
        "ma_ratio_20s",
        "ma_ratio_60s",
    )

    def positive_share(values: pd.Series) -> float:
        available = values.dropna()
        return float((available > 0).mean())

    for date in requested:
        position = membership_dates.searchsorted(date.value, side="right") - 1
        if position < 0:
            incomplete.append((date.date().isoformat(), 0.0))
            continue
        members = {canonical_equity_symbol(ticker) for ticker in membership_values[position].split(",")}
        day = days.get(date)
        if day is None:
            incomplete.append((date.date().isoformat(), 0.0))
            continue
        active = day[day["symbol"].isin(members)].copy()
        coverage = active["symbol"].nunique() / len(members)
        if coverage < minimum_coverage:
            incomplete.append((date.date().isoformat(), coverage))
            continue
        minimum_indicator_coverage = min(
            float(active[column].notna().sum() / len(members)) for column in indicator_columns
        )
        if minimum_indicator_coverage < 0.90:
            incomplete.append((date.date().isoformat(), minimum_indicator_coverage))
            continue
        rows.append(
            {
                "snapshot_time": date,
                "sp500_advance_ratio_1s": positive_share(active["return_1s"]),
                "sp500_breadth_5s": positive_share(active["return_5s"]),
                "sp500_breadth_20s": positive_share(active["return_20s"]),
                "sp500_breadth_60s": positive_share(active["return_60s"]),
                "sp500_above_ma_20s": positive_share(active["ma_ratio_20s"]),
                "sp500_above_ma_60s": positive_share(active["ma_ratio_60s"]),
                "sp500_return_dispersion_20s": float(active["return_20s"].std(ddof=0)),
                "sp500_return_dispersion_60s": float(active["return_60s"].std(ddof=0)),
                "sp500_median_return_20s": float(active["return_20s"].median()),
                "sp500_median_return_60s": float(active["return_60s"].median()),
                "sp500_member_coverage_diagnostic": coverage,
                "sp500_indicator_coverage_diagnostic": minimum_indicator_coverage,
                "sp500_member_count_diagnostic": len(members),
            }
        )
    if incomplete:
        preview = ", ".join(f"{date}={coverage:.1%}" for date, coverage in incomplete[:5])
        raise ValueError(
            f"S&P point-in-time breadth is below {minimum_coverage:.0%} on "
            f"{len(incomplete)} cutoffs ({preview})."
        )
    output = pd.DataFrame(rows)
    values = output.loc[:, SP500_PIT_BREADTH_FEATURE_NAMES]
    if output.empty or not np.isfinite(values.to_numpy(float)).all():
        raise ValueError("S&P point-in-time breadth produced empty or non-finite features.")
    return output


def add_sp500_pit_breadth_features(
    samples: pd.DataFrame,
    bars: pd.DataFrame,
    membership: pd.DataFrame,
    coverage_report_path: Path,
) -> pd.DataFrame:
    coverage_contract = require_sp500_pit_coverage(coverage_report_path)
    frame = samples.drop(
        columns=[
            *SP500_PIT_BREADTH_FEATURE_NAMES,
            "sp500_member_coverage_diagnostic",
            "sp500_indicator_coverage_diagnostic",
            "sp500_member_count_diagnostic",
        ],
        errors="ignore",
    ).copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True).dt.normalize()
    coverage_start = pd.Timestamp(str(coverage_contract["coverage_start_date"]), tz="UTC")
    coverage_end = pd.Timestamp(str(coverage_contract["coverage_end_date"]), tz="UTC")
    frame = frame[
        (frame["snapshot_time"] >= coverage_start)
        & (frame["snapshot_time"] <= coverage_end)
    ].copy()
    if frame.empty:
        raise ValueError("No model rows remain inside the audited S&P coverage contract.")
    quarantined = {
        canonical_equity_symbol(str(symbol))
        for symbol in coverage_contract.get("identity_quarantined_symbols", [])
    }
    safe_bars = bars[
        ~bars["symbol"].astype(str).map(canonical_equity_symbol).isin(quarantined)
    ].copy()
    breadth = build_sp500_pit_breadth(safe_bars, membership, frame["snapshot_time"])
    frame = frame.merge(breadth, on="snapshot_time", how="left", validate="many_to_one")
    if frame[list(SP500_PIT_BREADTH_FEATURE_NAMES)].isna().any().any():
        raise ValueError("S&P point-in-time breadth is missing from one or more model rows.")
    if "dataset_version" in frame and not frame.empty:
        source = str(frame["dataset_version"].iloc[0]).split("+sp500-pit-breadth-exp1", maxsplit=1)[0]
        frame["dataset_version"] = f"{source}+sp500-pit-breadth-exp1"
    return frame
