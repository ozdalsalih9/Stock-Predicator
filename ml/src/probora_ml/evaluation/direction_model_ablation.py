from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, SEEDS
from probora_ml.evaluation.ablation import paired_block_bootstrap_interval
from probora_ml.evaluation.calibration_ablation import _inner_calibration_masks
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
from probora_ml.training.pipeline import _classifier, _device_parameters, _regressor

VARIANTS = ("multiclass", "ordinal", "nested_selected", "quantile_distribution")


def _binary_classifier(seed: int, device_type: str) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        objective="binary",
        n_estimators=400,
        learning_rate=0.025,
        num_leaves=15,
        max_depth=6,
        min_child_samples=40,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_alpha=0.2,
        reg_lambda=1.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
        **_device_parameters(device_type),
    )


def _binary_temperature_scale(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-12, 1 - 1e-12)
    logits = np.log(clipped / (1 - clipped)) / max(temperature, 0.01)
    return 1 / (1 + np.exp(-np.clip(logits, -50, 50)))


def _fit_binary_temperature(labels: np.ndarray, probabilities: np.ndarray) -> float:
    candidates = np.geomspace(0.25, 10.0, 321)
    losses = []
    for candidate in candidates:
        scaled = np.clip(_binary_temperature_scale(probabilities, float(candidate)), 1e-12, 1 - 1e-12)
        losses.append(float(-(labels * np.log(scaled) + (1 - labels) * np.log(1 - scaled)).mean()))
    return float(candidates[int(np.argmin(losses))])


def ordinal_probabilities(not_down: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Project cumulative probabilities to P(down), P(neutral), P(up)."""
    lower = np.clip(np.asarray(not_down, dtype=float), 0, 1).copy()
    upper = np.clip(np.asarray(up, dtype=float), 0, 1).copy()
    if lower.shape != upper.shape:
        raise ValueError("Ordinal threshold probabilities must have matching shapes.")
    crossing = upper > lower
    midpoint = (upper[crossing] + lower[crossing]) / 2
    lower[crossing] = midpoint
    upper[crossing] = midpoint
    return np.column_stack((1 - lower, lower - upper, upper))


def _normal_cdf(values: np.ndarray) -> np.ndarray:
    flattened = np.asarray(values, dtype=float).ravel()
    result = np.fromiter(
        (0.5 * (1 + math.erf(value / math.sqrt(2))) for value in flattened),
        dtype=float,
        count=len(flattened),
    )
    return result.reshape(np.asarray(values).shape)


def quantile_direction_probabilities(
    quantiles: np.ndarray,
    neutral_thresholds: np.ndarray,
) -> np.ndarray:
    """Approximate direction probabilities from p10/p50/p90 return forecasts."""
    ordered = np.sort(np.asarray(quantiles, dtype=float), axis=1)
    thresholds = np.asarray(neutral_thresholds, dtype=float)
    if ordered.shape[1] != 3 or len(ordered) != len(thresholds):
        raise ValueError("Three quantiles and one neutral threshold are required per sample.")
    location = ordered[:, 1]
    scale = np.maximum((ordered[:, 2] - ordered[:, 0]) / (2 * 1.2815515655446004), 1e-4)
    down = _normal_cdf((-thresholds - location) / scale)
    up = 1 - _normal_cdf((thresholds - location) / scale)
    neutral = np.maximum(0, 1 - down - up)
    probabilities = np.column_stack((down, neutral, up))
    return probabilities / probabilities.sum(axis=1, keepdims=True)


def _calibrate_multiclass(
    validation_y: np.ndarray,
    validation_probabilities: np.ndarray,
    test_probabilities: np.ndarray,
    prior: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    temperature = fit_temperature(validation_y, validation_probabilities)
    calibrated_validation = temperature_scale(validation_probabilities, temperature)
    validation_prior = np.tile(prior, (len(validation_y), 1))
    weight = fit_probability_blend(validation_y, calibrated_validation, validation_prior)
    calibrated_test = temperature_scale(test_probabilities, temperature)
    return blend_probabilities(
        calibrated_test, np.tile(prior, (len(test_probabilities), 1)), weight
    ), {"temperature": temperature, "probability_blend_weight": weight}


def _calibrate_ordinal(
    fit_y: np.ndarray,
    fit_not_down: np.ndarray,
    fit_up: np.ndarray,
    target_not_down: np.ndarray,
    target_up: np.ndarray,
    prior: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    not_down_temperature = _fit_binary_temperature(fit_y >= 1, fit_not_down)
    up_temperature = _fit_binary_temperature(fit_y >= 2, fit_up)
    fit_probabilities = ordinal_probabilities(
        _binary_temperature_scale(fit_not_down, not_down_temperature),
        _binary_temperature_scale(fit_up, up_temperature),
    )
    weight = fit_probability_blend(
        fit_y, fit_probabilities, np.tile(prior, (len(fit_y), 1))
    )
    target_probabilities = ordinal_probabilities(
        _binary_temperature_scale(target_not_down, not_down_temperature),
        _binary_temperature_scale(target_up, up_temperature),
    )
    return blend_probabilities(
        target_probabilities, np.tile(prior, (len(target_probabilities), 1)), weight
    ), {
        "not_down_temperature": not_down_temperature,
        "up_temperature": up_temperature,
        "probability_blend_weight": weight,
    }


def _metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    baseline_probabilities: np.ndarray,
) -> dict[str, float]:
    brier = multiclass_brier(labels, probabilities)
    baseline_brier = multiclass_brier(labels, baseline_probabilities)
    decomposition = multiclass_brier_decomposition(labels, probabilities)
    return {
        "brier": brier,
        "baseline_brier": baseline_brier,
        "brier_skill_score": brier_skill_score(brier, baseline_brier),
        "ece": expected_calibration_error(labels, probabilities),
        "classwise_ece": classwise_expected_calibration_error(labels, probabilities),
        "accuracy": float((probabilities.argmax(axis=1) == labels).mean()),
        "reliability": decomposition.reliability,
        "resolution": decomposition.resolution,
        "uncertainty": decomposition.uncertainty,
        "binning_gap": decomposition.binning_gap,
    }


def _daily_losses(
    frame: pd.DataFrame,
    labels: np.ndarray,
    probabilities: np.ndarray,
) -> np.ndarray:
    one_hot = np.eye(3)[labels]
    losses = np.sum((probabilities - one_hot) ** 2, axis=1)
    return pd.DataFrame(
        {"snapshot_time": frame["snapshot_time"].to_numpy(), "loss": losses}
    ).groupby("snapshot_time", sort=True)["loss"].mean().to_numpy()


def evaluate_direction_models(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[*EQUITY_FEATURE_NAMES, "target_direction", "neutral_band_threshold"]
    ).copy()
    x = frame.loc[:, EQUITY_FEATURE_NAMES].astype("float32")
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 direction ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    losses_by_variant: dict[str, list[np.ndarray]] = {name: [] for name in VARIANTS}
    for fold in folds:
        train_x, validation_x, test_x = x.loc[fold.train], x.loc[fold.validation], x.loc[fold.test]
        train_y = frame.loc[fold.train, "target_direction"].astype(int).to_numpy()
        validation_y = frame.loc[fold.validation, "target_direction"].astype(int).to_numpy()
        test_y = frame.loc[fold.test, "target_direction"].astype(int).to_numpy()
        prior = np.bincount(train_y, minlength=3) / len(train_y)
        test_prior = np.tile(prior, (len(test_y), 1))

        multiclass_models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        multiclass_validation = np.mean(
            [model.predict_proba(validation_x) for model in multiclass_models], axis=0
        )
        multiclass_test = np.mean(
            [model.predict_proba(test_x) for model in multiclass_models], axis=0
        )
        multiclass_probabilities, multiclass_parameters = _calibrate_multiclass(
            validation_y, multiclass_validation, multiclass_test, prior
        )

        not_down_models = [
            _binary_classifier(seed, device_type).fit(train_x, train_y >= 1) for seed in SEEDS
        ]
        up_models = [
            _binary_classifier(seed, device_type).fit(train_x, train_y >= 2) for seed in SEEDS
        ]
        validation_not_down = np.mean(
            [model.predict_proba(validation_x)[:, 1] for model in not_down_models], axis=0
        )
        validation_up = np.mean(
            [model.predict_proba(validation_x)[:, 1] for model in up_models], axis=0
        )
        test_not_down = np.mean(
            [model.predict_proba(test_x)[:, 1] for model in not_down_models], axis=0
        )
        test_up = np.mean([model.predict_proba(test_x)[:, 1] for model in up_models], axis=0)
        ordinal_probabilities_test, ordinal_parameters = _calibrate_ordinal(
            validation_y,
            validation_not_down,
            validation_up,
            test_not_down,
            test_up,
            prior,
        )

        validation_frame = frame.loc[fold.validation]
        calibration_fit, calibration_selection = _inner_calibration_masks(validation_frame)
        selection_y = validation_y[calibration_selection]
        selection_prior = np.tile(prior, (len(selection_y), 1))
        current_selection_probabilities, _ = _calibrate_multiclass(
            validation_y[calibration_fit],
            multiclass_validation[calibration_fit],
            multiclass_validation[calibration_selection],
            prior,
        )
        ordinal_selection_probabilities, _ = _calibrate_ordinal(
            validation_y[calibration_fit],
            validation_not_down[calibration_fit],
            validation_up[calibration_fit],
            validation_not_down[calibration_selection],
            validation_up[calibration_selection],
            prior,
        )
        selection_scores = {
            "prior": multiclass_brier(selection_y, selection_prior),
            "multiclass": multiclass_brier(selection_y, current_selection_probabilities),
            "ordinal": multiclass_brier(selection_y, ordinal_selection_probabilities),
        }
        selected_method = min(selection_scores, key=selection_scores.get)  # type: ignore[arg-type]
        if selection_scores["prior"] - selection_scores[selected_method] < 0.001:
            selected_method = "prior"
        nested_selected_probabilities = {
            "prior": test_prior,
            "multiclass": multiclass_probabilities,
            "ordinal": ordinal_probabilities_test,
        }[selected_method]
        nested_selected_parameters: dict[str, float | str] = {
            "selected_method": selected_method,
            "selection_prior_brier": selection_scores["prior"],
            "selection_multiclass_brier": selection_scores["multiclass"],
            "selection_ordinal_brier": selection_scores["ordinal"],
        }

        validation_quantiles = []
        test_quantiles = []
        for alpha in (0.1, 0.5, 0.9):
            model = _regressor(SEEDS[0], alpha=alpha, device_type=device_type).fit(
                train_x, frame.loc[fold.train, "target_return"]
            )
            validation_quantiles.append(model.predict(validation_x))
            test_quantiles.append(model.predict(test_x))
        quantile_validation = quantile_direction_probabilities(
            np.column_stack(validation_quantiles),
            frame.loc[fold.validation, "neutral_band_threshold"].to_numpy(float),
        )
        quantile_test = quantile_direction_probabilities(
            np.column_stack(test_quantiles),
            frame.loc[fold.test, "neutral_band_threshold"].to_numpy(float),
        )
        quantile_probabilities, quantile_parameters = _calibrate_multiclass(
            validation_y, quantile_validation, quantile_test, prior
        )

        probabilities_by_variant = {
            "multiclass": multiclass_probabilities,
            "ordinal": ordinal_probabilities_test,
            "nested_selected": nested_selected_probabilities,
            "quantile_distribution": quantile_probabilities,
        }
        parameters_by_variant = {
            "multiclass": multiclass_parameters,
            "ordinal": ordinal_parameters,
            "nested_selected": nested_selected_parameters,
            "quantile_distribution": quantile_parameters,
        }
        test_frame = frame.loc[fold.test]
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "variants": {
                    name: {
                        **_metrics(test_y, probabilities, test_prior),
                        "parameters": parameters_by_variant[name],
                    }
                    for name, probabilities in probabilities_by_variant.items()
                },
            }
        )
        for name, probabilities in probabilities_by_variant.items():
            losses_by_variant[name].append(_daily_losses(test_frame, test_y, probabilities))

    def aggregate(rows: list[dict[str, object]], variant: str) -> dict[str, float]:
        metric_names = (
            "brier",
            "baseline_brier",
            "brier_skill_score",
            "ece",
            "classwise_ece",
            "accuracy",
            "reliability",
            "resolution",
            "uncertainty",
            "binning_gap",
        )
        return {
            metric: float(
                np.mean([float(row["variants"][variant][metric]) for row in rows])  # type: ignore[index]
            )
            for metric in metric_names
        }

    historical = fold_rows[:3]
    comparisons: dict[str, object] = {}
    for variant in VARIANTS:
        ci = (0.0, 0.0)
        if variant != "multiclass":
            ci = paired_block_bootstrap_interval(
                losses_by_variant["multiclass"][:3],
                losses_by_variant[variant][:3],
                block_size=horizon_days,
            )
        comparisons[variant] = {
            "historical_2023_2025": aggregate(historical, variant),
            "locked_2026": fold_rows[3]["variants"][variant],  # type: ignore[index]
            "historical_fold_wins_vs_multiclass": int(
                sum(
                    float(row["variants"][variant]["brier"])  # type: ignore[index]
                    < float(row["variants"]["multiclass"]["brier"])  # type: ignore[index]
                    for row in historical
                )
            )
            if variant != "multiclass"
            else 0,
            "historical_brier_delta_ci95_vs_multiclass": [*ci],
        }

    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "feature_names": EQUITY_FEATURE_NAMES,
        "methodology": (
            "Purged walk-forward with validation-only calibration. Candidate design uses 2023-2025; "
            "2026 is reported once as a locked, small-sample check."
        ),
        "folds": fold_rows,
        "comparisons": comparisons,
    }


def run_and_write_direction_model_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-equity-direction-ablation-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_direction_models(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
