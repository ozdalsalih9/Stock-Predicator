from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, SEEDS
from probora_ml.evaluation.metrics import interval_score, quantile_interval_coverage
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import (
    apply_scaled_conformal,
    conformal_interval_adjustment,
    fit_scaled_conformal_multiplier,
)
from probora_ml.training.pipeline import _regressor

VARIANTS = ("absolute", "predicted_width_scaled", "volatility_scaled")


def evaluate_interval_calibration(
    samples: pd.DataFrame, horizon_days: int, device_type: str
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[*EQUITY_FEATURE_NAMES, "target_return", "volatility_60s"]
    ).copy()
    x = frame.loc[:, EQUITY_FEATURE_NAMES].astype("float32")
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 interval ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        validation_predictions: list[np.ndarray] = []
        test_predictions: list[np.ndarray] = []
        for alpha in (0.1, 0.5, 0.9):
            model = _regressor(SEEDS[0], alpha=alpha, device_type=device_type).fit(
                x.loc[fold.train], frame.loc[fold.train, "target_return"]
            )
            validation_predictions.append(model.predict(x.loc[fold.validation]))
            test_predictions.append(model.predict(x.loc[fold.test]))
        validation = np.sort(np.column_stack(validation_predictions), axis=1)
        test = np.sort(np.column_stack(test_predictions), axis=1)
        validation_y = frame.loc[fold.validation, "target_return"].to_numpy(float)
        test_y = frame.loc[fold.test, "target_return"].to_numpy(float)
        validation_width = np.maximum(validation[:, 2] - validation[:, 0], 1e-4)
        test_width = np.maximum(test[:, 2] - test[:, 0], 1e-4)
        volatility_scale_validation = (
            frame.loc[fold.validation, "volatility_60s"].to_numpy(float)
            * np.sqrt(horizon_days / 252)
        )
        volatility_scale_test = (
            frame.loc[fold.test, "volatility_60s"].to_numpy(float)
            * np.sqrt(horizon_days / 252)
        )

        absolute = conformal_interval_adjustment(
            validation_y, validation[:, 0], validation[:, 2]
        )
        parameters = {
            "absolute": absolute,
            "predicted_width_scaled": fit_scaled_conformal_multiplier(
                validation_y,
                validation[:, 0],
                validation[:, 2],
                validation_width,
            ),
            "volatility_scaled": fit_scaled_conformal_multiplier(
                validation_y,
                validation[:, 0],
                validation[:, 2],
                volatility_scale_validation,
            ),
        }
        bounds = {
            "absolute": (test[:, 0] - absolute, test[:, 2] + absolute),
            "predicted_width_scaled": apply_scaled_conformal(
                test[:, 0], test[:, 2], test_width, parameters["predicted_width_scaled"]
            ),
            "volatility_scaled": apply_scaled_conformal(
                test[:, 0],
                test[:, 2],
                volatility_scale_test,
                parameters["volatility_scaled"],
            ),
        }
        train_y = frame.loc[fold.train, "target_return"].to_numpy(float)
        baseline_quantiles = np.quantile(train_y, [0.1, 0.9])
        baseline_lower = np.full(len(test_y), baseline_quantiles[0])
        baseline_upper = np.full(len(test_y), baseline_quantiles[1])
        baseline_score = interval_score(test_y, baseline_lower, baseline_upper)
        variants = {
            name: {
                "coverage": quantile_interval_coverage(test_y, lower, upper),
                "interval_score": interval_score(test_y, lower, upper),
                "baseline_interval_score": baseline_score,
                "interval_width": float(np.mean(upper - lower)),
                "parameter": parameters[name],
            }
            for name, (lower, upper) in bounds.items()
        }
        fold_rows.append(
            {"fold": fold.name, "sample_count": len(test_y), "variants": variants}
        )

    def aggregate(rows: list[dict[str, object]], name: str) -> dict[str, object]:
        score = float(
            np.mean([float(row["variants"][name]["interval_score"]) for row in rows])  # type: ignore[index]
        )
        baseline = float(
            np.mean(
                [
                    float(row["variants"][name]["baseline_interval_score"])  # type: ignore[index]
                    for row in rows
                ]
            )
        )
        return {
            "coverage": float(
                np.mean([float(row["variants"][name]["coverage"]) for row in rows])  # type: ignore[index]
            ),
            "interval_score": score,
            "baseline_interval_score": baseline,
            "interval_skill_score": 1 - score / baseline,
            "interval_width": float(
                np.mean([float(row["variants"][name]["interval_width"]) for row in rows])  # type: ignore[index]
            ),
            "fold_wins_vs_absolute": int(
                sum(
                    float(row["variants"][name]["interval_score"])  # type: ignore[index]
                    < float(row["variants"]["absolute"]["interval_score"])  # type: ignore[index]
                    for row in rows
                )
            ),
            "fold_wins_vs_baseline": int(
                sum(
                    float(row["variants"][name]["interval_score"])  # type: ignore[index]
                    < float(row["variants"][name]["baseline_interval_score"])  # type: ignore[index]
                    for row in rows
                )
            ),
        }

    historical = fold_rows[:3]
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "methodology": (
            "All variants use identical quantile models. Conformal parameters are fitted only on "
            "the purged outer validation year. Volatility scaling uses the point-in-time 60-session "
            "annualized volatility available at each forecast cutoff."
        ),
        "folds": fold_rows,
        "historical_2023_2025": {
            name: aggregate(historical, name) for name in VARIANTS
        },
        "locked_2026": {
            name: fold_rows[3]["variants"][name] for name in VARIANTS  # type: ignore[index]
        },
    }


def run_and_write_interval_calibration_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-equity-interval-calibration-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_interval_calibration(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
