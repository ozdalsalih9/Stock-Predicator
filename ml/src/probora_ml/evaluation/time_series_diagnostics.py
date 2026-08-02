from __future__ import annotations

import numpy as np
import pandas as pd

DIAGNOSTIC_LAGS = (1, 2, 5, 10, 20)


def autocorrelation(values: np.ndarray, lag: int) -> float | None:
    """Return a bounded sample autocorrelation, or None when it is undefined."""
    array = np.asarray(values, dtype=float)
    if lag < 1:
        raise ValueError("Autocorrelation lag must be positive.")
    if len(array) <= lag or not np.isfinite(array).all():
        return None
    left = array[:-lag] - array[:-lag].mean()
    right = array[lag:] - array[lag:].mean()
    denominator = float(np.sqrt(np.dot(left, left) * np.dot(right, right)))
    return None if denominator == 0 else float(np.clip(np.dot(left, right) / denominator, -1, 1))


def _acf(
    values: np.ndarray,
    lags: tuple[int, ...] = DIAGNOSTIC_LAGS,
) -> dict[str, float | None]:
    return {str(lag): autocorrelation(values, lag) for lag in lags}


def _window_metrics(frame: pd.DataFrame) -> list[dict[str, float | int | str]]:
    boundaries = np.linspace(0, len(frame), 4, dtype=int)
    windows = [frame.iloc[boundaries[index] : boundaries[index + 1]] for index in range(3)]
    names = ("early", "middle", "recent")
    return [
        {
            "window": name,
            "observation_days": len(window),
            "model_brier": float(window["model_brier"].mean()),
            "baseline_brier": float(window["baseline_brier"].mean()),
            "brier_delta": float(window["brier_delta"].mean()),
        }
        for name, window in zip(names, windows, strict=True)
        if not window.empty
    ]


def probability_error_diagnostics(
    predictions: pd.DataFrame,
    *,
    horizon_days: int,
) -> dict[str, object]:
    """Diagnose serial dependence after collapsing correlated assets to daily blocks."""
    if horizon_days < 1:
        raise ValueError("Diagnostic horizon must be positive.")
    required = {
        "snapshot_time",
        "target_direction",
        "probabilities",
        "baseline_probabilities",
    }
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"Time-series diagnostics are missing: {', '.join(missing)}")

    rows = predictions.loc[:, list(required)].copy()
    rows["snapshot_time"] = pd.to_datetime(rows["snapshot_time"], utc=True)
    probabilities = np.vstack(rows["probabilities"])
    baseline = np.vstack(rows["baseline_probabilities"])
    labels = rows["target_direction"].to_numpy(int)
    targets = np.eye(3)[labels]
    rows["model_brier"] = np.square(probabilities - targets).sum(axis=1)
    rows["baseline_brier"] = np.square(baseline - targets).sum(axis=1)
    rows["brier_delta"] = rows["model_brier"] - rows["baseline_brier"]
    for index, name in enumerate(("down", "neutral", "up")):
        rows[f"{name}_residual"] = targets[:, index] - probabilities[:, index]

    daily = (
        rows.groupby("snapshot_time", sort=True)[
            [
                "model_brier",
                "baseline_brier",
                "brier_delta",
                "down_residual",
                "neutral_residual",
                "up_residual",
            ]
        ]
        .mean()
        .reset_index()
    )
    windows = _window_metrics(daily)
    warnings: list[str] = []
    brier_delta_acf = _acf(daily["brier_delta"].to_numpy())
    non_overlapping_lags = tuple(horizon_days * multiplier for multiplier in (1, 2, 3))
    non_overlapping_brier_delta_acf = _acf(
        daily["brier_delta"].to_numpy(),
        non_overlapping_lags,
    )
    material = [
        (lag, value)
        for lag, value in non_overlapping_brier_delta_acf.items()
        if value is not None and abs(value) >= 0.20
    ]
    if material:
        warnings.append(
            "Non-overlapping excess Brier has material serial correlation at lag(s): "
            + ", ".join(f"{lag}={value:.3f}" for lag, value in material)
        )
    if len(windows) == 3 and float(windows[-1]["brier_delta"]) > float(windows[0]["brier_delta"]) + 0.01:
        warnings.append("Recent daily excess Brier is more than 0.01 worse than the early window.")

    return {
        "daily_observations": len(daily),
        "first_day": daily["snapshot_time"].min().isoformat(),
        "last_day": daily["snapshot_time"].max().isoformat(),
        "label_horizon_days": horizon_days,
        "overlap_note": (
            f"Daily lags below {horizon_days} days contain overlapping target windows "
            "and are descriptive only."
        ),
        "model_brier_acf": _acf(daily["model_brier"].to_numpy()),
        "brier_delta_acf": brier_delta_acf,
        "non_overlapping_brier_delta_acf": non_overlapping_brier_delta_acf,
        "class_residual_acf": {
            name: _acf(daily[f"{name}_residual"].to_numpy())
            for name in ("down", "neutral", "up")
        },
        "drift_windows": windows,
        "warnings": warnings,
    }
