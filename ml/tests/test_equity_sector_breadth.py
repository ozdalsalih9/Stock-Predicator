import numpy as np
import pandas as pd

from probora_ml.features.equity_sector_breadth import (
    EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES,
    EXTERNAL_SECTOR_ETFS,
    add_equity_sector_breadth_features,
)


def test_nine_sector_features_are_complete_and_sector_relative() -> None:
    date = pd.Timestamp("2026-04-01", tz="UTC")
    rows = []
    for symbol, return_20s in (
        ("SPY", 0.02),
        ("QQQ", 0.03),
        ("XLK", 0.04),
        ("XLF", 0.01),
        ("XLE", -0.02),
        ("XLV", 0.00),
        ("AAPL", 0.07),
        ("WMT", 0.03),
    ):
        rows.append(
            {
                "asset_id": symbol,
                "snapshot_time": date,
                "horizon_days": 90,
                "return_5s": return_20s / 4,
                "return_20s": return_20s,
                "return_60s": return_20s * 2,
                "volatility_20s": 0.2,
                "dataset_version": "equity-v1",
            }
        )
    samples = pd.DataFrame(rows)
    bar_rows = []
    dates = pd.bdate_range(end=date, periods=65, tz="UTC")
    for offset, symbol in enumerate(EXTERNAL_SECTOR_ETFS, start=1):
        for index, timestamp in enumerate(dates):
            bar_rows.append(
                {
                    "symbol": symbol,
                    "open_time": timestamp,
                    "close": 100 + offset + index * (0.1 + offset / 100),
                }
            )

    result = add_equity_sector_breadth_features(samples, pd.DataFrame(bar_rows))
    aapl = result[result["asset_id"] == "AAPL"].iloc[0]
    wmt = result[result["asset_id"] == "WMT"].iloc[0]

    assert aapl["sector_peer_benchmark_id"] == "XLK"
    assert wmt["sector_peer_benchmark_id"] == "XLP"
    assert np.isclose(aapl["sector_peer_relative_return_20s"], 0.03)
    assert np.isfinite(result.loc[:, EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES]).all().all()
    assert result["dataset_version"].eq("equity-v1+sector-breadth-exp1").all()
