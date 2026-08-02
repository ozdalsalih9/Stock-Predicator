from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from probora_ml.config import ALL_FEATURE_NAMES, EQUITY_FEATURE_NAMES
from probora_ml.features.daily import create_feature_snapshots
from probora_ml.features.equity import create_equity_feature_snapshots


def _crypto_history(scale: float) -> pd.DataFrame:
    times = pd.date_range("2024-01-01", periods=370, freq="D", tz="UTC")
    close = scale + np.arange(len(times), dtype=float) * 0.2
    return pd.DataFrame(
        {
            "open_time": times,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 10_000 + np.arange(len(times), dtype=float) * 10,
            "quote_volume": (10_000 + np.arange(len(times), dtype=float) * 10) * close,
            "trade_count": 1_000 + np.arange(len(times)),
            "taker_buy_base_volume": 5_000 + np.arange(len(times), dtype=float) * 5,
        }
    )


def _equity_history(scale: float) -> pd.DataFrame:
    times = pd.bdate_range("2024-01-02", periods=258, tz="UTC")
    close = scale + np.arange(len(times), dtype=float) * 0.1
    return pd.DataFrame(
        {
            "open_time": times,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000 + np.arange(len(times), dtype=float) * 100,
        }
    )


def _row(frame: pd.DataFrame, symbol: str, timestamp: pd.Timestamp) -> pd.Series:
    return frame[(frame["asset_id"] == symbol) & (frame["snapshot_time"] == timestamp)].iloc[0]


def test_crypto_features_do_not_change_when_future_prices_are_perturbed() -> None:
    histories = {
        "BTCUSDT": _crypto_history(100),
        "ETHUSDT": _crypto_history(50),
    }
    cutoff = histories["BTCUSDT"].iloc[-3]["open_time"]
    original = create_feature_snapshots(histories)

    perturbed = {symbol: frame.copy() for symbol, frame in histories.items()}
    for frame in perturbed.values():
        future = frame["open_time"] > cutoff
        frame.loc[future, ["open", "high", "low", "close"]] *= 4
        frame.loc[future, ["volume", "quote_volume", "trade_count", "taker_buy_base_volume"]] *= 3
    changed = create_feature_snapshots(perturbed)

    for symbol in histories:
        assert_series_equal(
            _row(original, symbol, cutoff).loc[list(ALL_FEATURE_NAMES)],
            _row(changed, symbol, cutoff).loc[list(ALL_FEATURE_NAMES)],
            check_names=False,
        )
    assert not np.allclose(
        _row(original, "ETHUSDT", histories["ETHUSDT"].iloc[-1]["open_time"]).loc[
            list(ALL_FEATURE_NAMES)
        ].to_numpy(dtype=float),
        _row(changed, "ETHUSDT", histories["ETHUSDT"].iloc[-1]["open_time"]).loc[
            list(ALL_FEATURE_NAMES)
        ].to_numpy(dtype=float),
    )


def test_equity_features_do_not_change_when_future_sessions_are_perturbed() -> None:
    histories = {
        "SPY": _equity_history(100),
        "AAPL": _equity_history(50),
    }
    cutoff = histories["SPY"].iloc[-3]["open_time"]
    original = create_equity_feature_snapshots(histories)

    perturbed = {symbol: frame.copy() for symbol, frame in histories.items()}
    for frame in perturbed.values():
        future = frame["open_time"] > cutoff
        frame.loc[future, ["open", "high", "low", "close"]] *= 4
        frame.loc[future, "volume"] *= 3
    changed = create_equity_feature_snapshots(perturbed)

    for symbol in histories:
        assert_series_equal(
            _row(original, symbol, cutoff).loc[list(EQUITY_FEATURE_NAMES)],
            _row(changed, symbol, cutoff).loc[list(EQUITY_FEATURE_NAMES)],
            check_names=False,
        )
    assert not np.allclose(
        _row(original, "AAPL", histories["AAPL"].iloc[-1]["open_time"]).loc[
            list(EQUITY_FEATURE_NAMES)
        ].to_numpy(dtype=float),
        _row(changed, "AAPL", histories["AAPL"].iloc[-1]["open_time"]).loc[
            list(EQUITY_FEATURE_NAMES)
        ].to_numpy(dtype=float),
    )
