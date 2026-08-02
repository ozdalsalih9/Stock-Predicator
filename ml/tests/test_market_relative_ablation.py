import numpy as np
import pandas as pd

from probora_ml.evaluation.market_relative_ablation import (
    MARKET_RELATIVE_CONFIGS,
    _residual_volatility,
    attach_market_relative_targets,
)


def test_residual_volatility_respects_correlation() -> None:
    asset = pd.Series([0.4, 0.4])
    benchmark = pd.Series([0.2, 0.2])
    correlation = pd.Series([1.0, 0.0])

    result = _residual_volatility(asset, benchmark, correlation)

    np.testing.assert_allclose(result[0], 0.2)
    np.testing.assert_allclose(result[1], np.sqrt(0.2), rtol=1e-12)


def test_crypto_relative_targets_exclude_benchmark_and_use_excess_return() -> None:
    rows = []
    for asset_id, target_return, short_vol, long_vol, correlation in (
        ("BTCUSDT", 0.10, 0.50, 0.45, 1.0),
        ("ETHUSDT", 0.18, 0.70, 0.65, 0.7),
    ):
        rows.append(
            {
                "asset_id": asset_id,
                "snapshot_time": pd.Timestamp("2024-01-01", tz="UTC"),
                "horizon_days": 30,
                "target_return": target_return,
                "volatility_30d": short_vol,
                "volatility_90d": long_vol,
                "btc_correlation_30d": correlation,
                "btc_correlation_90d": correlation,
                "dataset_version": "test-v1",
            }
        )

    output = attach_market_relative_targets(pd.DataFrame(rows), MARKET_RELATIVE_CONFIGS["crypto"])

    assert output["asset_id"].tolist() == ["ETHUSDT"]
    assert output["market_relative_benchmark"].iloc[0] == "BTCUSDT"
    assert output["dataset_version"].iloc[0] == "test-v1-market-relative-v4"
    np.testing.assert_allclose(output["relative_target_return"].iloc[0], 0.08)
    assert output["relative_target_direction"].iloc[0] in (0, 1, 2)
