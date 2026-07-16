import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, EQUITY_FEATURE_SET_VERSION
from probora_ml.features.equity import (
    add_equity_macro_features,
    build_equity_feature_row,
    create_equity_feature_snapshots,
)


def _history(scale: float) -> pd.DataFrame:
    sessions = pd.bdate_range("2024-01-02", periods=280, tz="UTC")
    close = scale + np.arange(len(sessions)) * 0.1
    return pd.DataFrame(
        {
            "open_time": sessions,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000 + np.arange(len(sessions)) * 100,
        }
    )


def test_equity_feature_row_matches_declared_schema() -> None:
    features = build_equity_feature_row(_history(50), _history(100), 0.6, 0.7, 0.5, 0.4)

    assert tuple(features) == EQUITY_FEATURE_NAMES
    assert all(np.isfinite(value) for value in features.values())


def test_equity_snapshots_use_isolated_schema() -> None:
    snapshots = create_equity_feature_snapshots({"SPY": _history(100), "AAPL": _history(50)})

    assert not snapshots.empty
    assert set(snapshots["feature_set_version"]) == {EQUITY_FEATURE_SET_VERSION}
    assert set(EQUITY_FEATURE_NAMES).issubset(snapshots.columns)


def test_macro_experiment_upgrade_uses_only_contemporaneous_spy_features() -> None:
    snapshots = create_equity_feature_snapshots({"SPY": _history(100), "AAPL": _history(50)})
    snapshots["horizon_days"] = 30

    upgraded = add_equity_macro_features(snapshots)
    latest_time = upgraded["snapshot_time"].max()
    spy = snapshots[(snapshots["asset_id"] == "SPY") & (snapshots["snapshot_time"] == latest_time)].iloc[0]
    aapl = upgraded[(upgraded["asset_id"] == "AAPL") & (upgraded["snapshot_time"] == latest_time)].iloc[0]

    assert aapl["benchmark_return_20s"] == spy["return_20s"]
    assert aapl["benchmark_volatility_60s"] == spy["volatility_60s"]
    assert aapl["benchmark_market_regime"] == spy["market_regime"]
    assert aapl["feature_set_version"] == "us-equity-daily-v1+spy-macro-exp1"
