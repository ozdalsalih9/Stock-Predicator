import numpy as np
import pandas as pd

from probora_ml.features.equity_cross_sectional import (
    EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES,
    add_equity_cross_sectional_features,
)


def _row(symbol: str, return_5s: float, return_20s: float, return_60s: float) -> dict[str, object]:
    return {
        "asset_id": symbol,
        "snapshot_time": pd.Timestamp("2026-01-02", tz="UTC"),
        "horizon_days": 90,
        "return_5s": return_5s,
        "return_20s": return_20s,
        "return_60s": return_60s,
        "volatility_20s": abs(return_20s) + 0.1,
        "ma_ratio_20s": return_20s,
        "ma_ratio_60s": return_60s,
        "market_regime": float(np.sign(return_60s)),
        "dataset_version": "equity-v1",
    }


def test_cross_sectional_features_use_same_cutoff_and_peer_benchmark() -> None:
    samples = pd.DataFrame(
        [
            _row("SPY", 0.01, 0.02, 0.03),
            _row("QQQ", 0.02, 0.04, 0.06),
            _row("AAPL", 0.03, 0.08, 0.12),
            _row("XLF", -0.01, -0.02, -0.03),
            _row("JPM", 0.01, 0.01, 0.02),
        ]
    )

    result = add_equity_cross_sectional_features(samples)
    aapl = result[result["asset_id"] == "AAPL"].iloc[0]
    jpm = result[result["asset_id"] == "JPM"].iloc[0]

    assert aapl["peer_benchmark_id"] == "QQQ"
    assert jpm["peer_benchmark_id"] == "XLF"
    assert np.isclose(aapl["peer_relative_return_20s"], 0.04)
    assert np.isclose(jpm["peer_relative_return_60s"], 0.05)
    assert np.isclose(aapl["market_breadth_5s"], 0.75)
    assert aapl["benchmark_market_regime_diagnostic"] == 1
    assert np.isfinite(result.loc[:, EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES]).all().all()
    assert result["dataset_version"].eq("equity-v1+cross-sectional-exp1").all()


def test_cross_sectional_features_reject_missing_peer() -> None:
    samples = pd.DataFrame([_row("SPY", 0.01, 0.02, 0.03), _row("AAPL", 0.03, 0.08, 0.12)])

    try:
        add_equity_cross_sectional_features(samples)
    except ValueError as error:
        assert "peer benchmark" in str(error)
    else:
        raise AssertionError("Missing QQQ should fail closed.")
