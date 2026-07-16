from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from probora_ml.config import EQUITY_FEATURE_NAMES
from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    multiclass_brier,
    multiclass_brier_decomposition,
)
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import (
    blend_probabilities,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)

STABLE_FEATURE_NAMES = (
    "return_5s",
    "return_20s",
    "return_60s",
    "return_120s",
    "volatility_20s",
    "volatility_60s",
    "downside_volatility_20s",
    "rsi_14",
    "atr_14_normalized",
    "ma_ratio_20s",
    "ma_ratio_60s",
    "ma_ratio_200s",
    "volume_zscore_20s",
    "benchmark_correlation_60s",
    "benchmark_beta_20s",
    "relative_strength_20s",
    "market_breadth_20s",
    "market_regime",
    "momentum_rank_20s",
    "momentum_rank_60s",
    "volatility_rank_20s",
)
CANDIDATE_C = (0.001, 0.01, 0.1, 1.0)
FEATURE_SETS = {
    "stable": STABLE_FEATURE_NAMES,
    "full": EQUITY_FEATURE_NAMES,
}


def _model(regularization_c: float) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    C=regularization_c,
                    solver="lbfgs",
                    max_iter=5_000,
                    random_state=17,
                ),
            ),
        ]
    )


def _inner_masks(frame: pd.DataFrame, embargo_days: int = 7) -> tuple[np.ndarray, np.ndarray]:
    timestamps = pd.to_datetime(frame["snapshot_time"], utc=True)
    label_end = pd.to_datetime(frame["label_end_time"], utc=True)
    final_year = int(timestamps.dt.year.max())
    selection_start = pd.Timestamp(f"{final_year}-01-01", tz="UTC")
    embargo = pd.to_timedelta(embargo_days, unit="D")
    fit = (label_end < selection_start - embargo).to_numpy()
    selection = (timestamps >= selection_start).to_numpy()
    if fit.sum() < 500 or selection.sum() < 100:
        raise ValueError("Inner model selection requires a complete final training year.")
    return fit, selection


def _fit_selected_model(
    train: pd.DataFrame,
) -> tuple[Pipeline, tuple[str, ...], dict[str, object]]:
    fit_mask, selection_mask = _inner_masks(train)
    fit_y = train.loc[fit_mask, "target_direction"].to_numpy(int)
    selection_y = train.loc[selection_mask, "target_direction"].to_numpy(int)
    candidates: list[dict[str, object]] = []
    for feature_set_name, feature_names in FEATURE_SETS.items():
        for regularization_c in CANDIDATE_C:
            model = _model(regularization_c).fit(
                train.loc[fit_mask, feature_names], fit_y
            )
            probabilities = model.predict_proba(
                train.loc[selection_mask, feature_names]
            )
            candidates.append(
                {
                    "feature_set": feature_set_name,
                    "regularization_c": regularization_c,
                    "selection_brier": multiclass_brier(selection_y, probabilities),
                    "parameter_count": len(feature_names) * 3 + 3,
                }
            )
    # A tiny complexity penalty breaks near-ties in favour of the smaller model.
    winner = min(
        candidates,
        key=lambda row: float(row["selection_brier"])
        + 1e-5 * int(row["parameter_count"]),
    )
    feature_names = tuple(FEATURE_SETS[str(winner["feature_set"])])
    model = _model(float(winner["regularization_c"])).fit(
        train.loc[:, feature_names], train["target_direction"].to_numpy(int)
    )
    selection = {
        **winner,
        "top_candidates": sorted(
            candidates, key=lambda row: float(row["selection_brier"])
        )[:4],
    }
    return model, feature_names, selection


def _metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    baseline_probabilities: np.ndarray,
) -> dict[str, float]:
    brier = multiclass_brier(labels, probabilities)
    baseline = multiclass_brier(labels, baseline_probabilities)
    decomposition = multiclass_brier_decomposition(labels, probabilities)
    return {
        "brier": brier,
        "baseline_brier": baseline,
        "brier_skill_score": brier_skill_score(brier, baseline),
        "ece": expected_calibration_error(labels, probabilities),
        "classwise_ece": classwise_expected_calibration_error(labels, probabilities),
        "accuracy": float((probabilities.argmax(axis=1) == labels).mean()),
        "reliability": decomposition.reliability,
        "resolution": decomposition.resolution,
    }


def evaluate_linear_direction_model(
    samples: pd.DataFrame, horizon_days: int
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[*EQUITY_FEATURE_NAMES, "target_direction", "label_end_time"]
    ).copy()
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 linear ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        train = frame.loc[fold.train]
        validation = frame.loc[fold.validation]
        test = frame.loc[fold.test]
        train_y = train["target_direction"].to_numpy(int)
        validation_y = validation["target_direction"].to_numpy(int)
        test_y = test["target_direction"].to_numpy(int)
        prior = np.bincount(train_y, minlength=3) / len(train_y)

        model, feature_names, selection = _fit_selected_model(train)
        validation_raw = model.predict_proba(validation.loc[:, feature_names])
        test_raw = model.predict_proba(test.loc[:, feature_names])
        temperature = fit_temperature(validation_y, validation_raw)
        validation_calibrated = temperature_scale(validation_raw, temperature)
        weight = fit_probability_blend(
            validation_y,
            validation_calibrated,
            np.tile(prior, (len(validation_y), 1)),
        )
        probabilities = blend_probabilities(
            temperature_scale(test_raw, temperature),
            np.tile(prior, (len(test_y), 1)),
            weight,
        )
        baseline = np.tile(prior, (len(test_y), 1))
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "selection": selection,
                "calibration": {
                    "temperature": temperature,
                    "probability_blend_weight": weight,
                },
                "metrics": _metrics(test_y, probabilities, baseline),
            }
        )

    metric_names = (
        "brier",
        "baseline_brier",
        "brier_skill_score",
        "ece",
        "classwise_ece",
        "accuracy",
        "reliability",
        "resolution",
    )

    def aggregate(rows: list[dict[str, object]]) -> dict[str, float]:
        return {
            metric: float(
                np.mean([float(row["metrics"][metric]) for row in rows])  # type: ignore[index]
            )
            for metric in metric_names
        }

    return {
        "horizon_days": horizon_days,
        "methodology": (
            "Regularization and a predeclared stable/full feature set are selected on the final "
            "purged year inside each outer training period. Temperature and prior blend are fitted "
            "only on the outer validation year. The outer test year remains blind."
        ),
        "folds": fold_rows,
        "historical_2023_2025": aggregate(fold_rows[:3]),
        "locked_2026": fold_rows[3]["metrics"],
    }


def run_and_write_linear_direction_ablation(
    samples: pd.DataFrame, horizon_days: int, output_root: Path
) -> Path:
    report = {
        "version": f"probora-equity-linear-direction-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_linear_direction_model(samples, horizon_days),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
