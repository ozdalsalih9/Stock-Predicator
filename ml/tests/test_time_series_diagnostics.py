from __future__ import annotations

import numpy as np
import pandas as pd

from probora_ml.evaluation.time_series_diagnostics import (
    autocorrelation,
    probability_error_diagnostics,
)


def test_autocorrelation_detects_alternating_series() -> None:
    values = np.tile([1.0, -1.0], 30)

    result = autocorrelation(values, 1)

    assert result is not None
    assert result < -0.99


def test_probability_diagnostics_aggregate_assets_before_serial_analysis() -> None:
    rows: list[dict[str, object]] = []
    for day in range(30):
        for asset in ("BTCUSDT", "ETHUSDT"):
            label = day % 3
            probability = np.full(3, 0.15)
            probability[label] = 0.70 if day < 20 else 0.45
            probability[(label + 1) % 3] += 0.70 - probability[label]
            rows.append(
                {
                    "asset_id": asset,
                    "snapshot_time": pd.Timestamp("2025-01-01", tz="UTC")
                    + pd.to_timedelta(day, unit="D"),
                    "target_direction": label,
                    "probabilities": probability,
                    "baseline_probabilities": np.full(3, 1 / 3),
                }
            )

    result = probability_error_diagnostics(pd.DataFrame(rows), horizon_days=5)

    assert result["daily_observations"] == 30
    assert len(result["drift_windows"]) == 3
    assert result["drift_windows"][-1]["model_brier"] > result["drift_windows"][0]["model_brier"]
    assert result["label_horizon_days"] == 5
    assert set(result["non_overlapping_brier_delta_acf"]) == {"5", "10", "15"}
