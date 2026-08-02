from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from probora_ml.config import SEEDS
from probora_ml.evaluation.ablation import paired_block_bootstrap_interval
from probora_ml.evaluation.baselines import select_direction_baseline
from probora_ml.evaluation.calibration_ablation import _inner_calibration_masks
from probora_ml.evaluation.direction_model_ablation import (
    _binary_classifier,
    _calibrate_multiclass,
    _calibrate_ordinal,
)
from probora_ml.evaluation.market_relative_ablation import MarketRelativeConfig
from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    multiclass_brier,
    multiclass_brier_decomposition,
)
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import fit_log_probability_matrix_calibrator
from probora_ml.training.pipeline import _classifier

MATRIX_REGULARIZATION_CANDIDATES = (0.01, 0.1, 1.0)
MINIMUM_SELECTION_GAIN = 0.001
VARIANTS = ("nominal", "ordinal", "matrix", "nested_selected")


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
    one_hot = np.eye(3)[labels.astype(int)]
    losses = np.sum((probabilities - one_hot) ** 2, axis=1)
    return (
        pd.DataFrame({"snapshot_time": frame["snapshot_time"].to_numpy(), "loss": losses})
        .groupby("snapshot_time", sort=True)["loss"]
        .mean()
        .to_numpy()
    )


def select_complexity_guarded_candidate(
    labels: np.ndarray,
    probabilities_by_method: dict[str, np.ndarray],
    parameter_counts: dict[str, int],
) -> tuple[str, list[dict[str, float | str]]]:
    """Choose on a held-out validation tail, penalising avoidable flexibility."""
    if "prior" not in probabilities_by_method or parameter_counts.get("prior") != 0:
        raise ValueError("Candidate selection requires a zero-parameter prior.")
    rows: list[dict[str, float | str]] = []
    for method, probabilities in probabilities_by_method.items():
        parameter_count = parameter_counts[method]
        brier = multiclass_brier(labels, probabilities)
        rows.append(
            {
                "method": method,
                "selection_brier": brier,
                "parameter_count": float(parameter_count),
                "complexity_adjusted_score": brier + parameter_count / len(labels),
            }
        )
    winner = min(rows, key=lambda row: float(row["complexity_adjusted_score"]))
    prior_brier = next(float(row["selection_brier"]) for row in rows if row["method"] == "prior")
    if prior_brier - float(winner["selection_brier"]) < MINIMUM_SELECTION_GAIN:
        return "prior", rows
    return str(winner["method"]), rows


def _aggregate(rows: list[dict[str, object]], variant: str) -> dict[str, float]:
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
            np.mean(
                [
                    float(row["variants"][variant][metric])  # type: ignore[index]
                    for row in rows
                ]
            )
        )
        for metric in metric_names
    }


def evaluate_market_relative_direction_models(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    target_column = "relative_target_direction"
    required = [
        *config.feature_names,
        target_column,
        "relative_target_return",
        "relative_neutral_band_threshold",
        "label_end_time",
    ]
    frame = samples[samples["horizon_days"] == horizon_days].dropna(subset=required).copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    folds = purged_walk_forward_splits(
        frame,
        embargo_days=7,
        test_years=(2023, 2024, 2025, 2026),
    )
    if len(folds) != 4:
        raise ValueError("Market-relative direction ablation requires complete 2023-2026 folds.")

    x = frame.loc[:, config.feature_names].astype("float32")
    fold_rows: list[dict[str, object]] = []
    losses_by_variant: dict[str, list[np.ndarray]] = {name: [] for name in VARIANTS}
    baseline_losses: list[np.ndarray] = []

    for fold in folds:
        train_x = x.loc[fold.train]
        validation_x = x.loc[fold.validation]
        test_x = x.loc[fold.test]
        train_y = frame.loc[fold.train, target_column].astype(int).to_numpy()
        validation_y = frame.loc[fold.validation, target_column].astype(int).to_numpy()
        test_y = frame.loc[fold.test, target_column].astype(int).to_numpy()
        prior = np.bincount(train_y, minlength=3) / len(train_y)
        validation_prior = np.tile(prior, (len(validation_y), 1))
        test_prior = np.tile(prior, (len(test_y), 1))

        nominal_models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        nominal_validation = np.mean([model.predict_proba(validation_x) for model in nominal_models], axis=0)
        nominal_test = np.mean([model.predict_proba(test_x) for model in nominal_models], axis=0)
        nominal_probabilities, nominal_parameters = _calibrate_multiclass(
            validation_y,
            nominal_validation,
            nominal_test,
            prior,
        )

        not_down_models = [_binary_classifier(seed, device_type).fit(train_x, train_y >= 1) for seed in SEEDS]
        up_models = [_binary_classifier(seed, device_type).fit(train_x, train_y >= 2) for seed in SEEDS]
        validation_not_down = np.mean(
            [model.predict_proba(validation_x)[:, 1] for model in not_down_models], axis=0
        )
        validation_up = np.mean([model.predict_proba(validation_x)[:, 1] for model in up_models], axis=0)
        test_not_down = np.mean([model.predict_proba(test_x)[:, 1] for model in not_down_models], axis=0)
        test_up = np.mean([model.predict_proba(test_x)[:, 1] for model in up_models], axis=0)
        ordinal_probabilities, ordinal_parameters = _calibrate_ordinal(
            validation_y,
            validation_not_down,
            validation_up,
            test_not_down,
            test_up,
            prior,
        )

        calibration_fit, calibration_selection = _inner_calibration_masks(frame.loc[fold.validation])
        fit_y = validation_y[calibration_fit]
        selection_y = validation_y[calibration_selection]
        selection_prior = validation_prior[calibration_selection]
        nominal_selection, _ = _calibrate_multiclass(
            fit_y,
            nominal_validation[calibration_fit],
            nominal_validation[calibration_selection],
            prior,
        )
        ordinal_selection, _ = _calibrate_ordinal(
            fit_y,
            validation_not_down[calibration_fit],
            validation_up[calibration_fit],
            validation_not_down[calibration_selection],
            validation_up[calibration_selection],
            prior,
        )

        matrix_selection_by_c: dict[float, np.ndarray] = {}
        for regularization_c in MATRIX_REGULARIZATION_CANDIDATES:
            calibrator = fit_log_probability_matrix_calibrator(
                fit_y,
                nominal_validation[calibration_fit],
                regularization_c,
            )
            matrix_selection_by_c[regularization_c] = calibrator.predict_proba(
                nominal_validation[calibration_selection]
            )
        selected_matrix_c = min(
            MATRIX_REGULARIZATION_CANDIDATES,
            key=lambda candidate: multiclass_brier(selection_y, matrix_selection_by_c[candidate]),
        )
        matrix_calibrator = fit_log_probability_matrix_calibrator(
            validation_y,
            nominal_validation,
            selected_matrix_c,
        )
        matrix_probabilities = matrix_calibrator.predict_proba(nominal_test)

        selected_method, selection_rows = select_complexity_guarded_candidate(
            selection_y,
            {
                "prior": selection_prior,
                "nominal": nominal_selection,
                "ordinal": ordinal_selection,
                "matrix": matrix_selection_by_c[selected_matrix_c],
            },
            {
                "prior": 0,
                "nominal": 2,
                "ordinal": 3,
                "matrix": matrix_calibrator.parameter_count,
            },
        )
        nested_probabilities = {
            "prior": test_prior,
            "nominal": nominal_probabilities,
            "ordinal": ordinal_probabilities,
            "matrix": matrix_probabilities,
        }[selected_method]

        logistic = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(train_x, train_y)
        selected_baseline = select_direction_baseline(
            validation_y,
            logistic.predict_proba(validation_x),
            validation_prior,
            test_y,
            logistic.predict_proba(test_x),
            test_prior,
        )
        probabilities_by_variant = {
            "nominal": nominal_probabilities,
            "ordinal": ordinal_probabilities,
            "matrix": matrix_probabilities,
            "nested_selected": nested_probabilities,
        }
        parameters_by_variant: dict[str, object] = {
            "nominal": nominal_parameters,
            "ordinal": ordinal_parameters,
            "matrix": {"regularization_c": selected_matrix_c},
            "nested_selected": {
                "selected_method": selected_method,
                "inner_selection_candidates": selection_rows,
            },
        }
        test_frame = frame.loc[fold.test]
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "asset_count": int(test_frame["asset_id"].nunique()),
                "selected_baseline": selected_baseline.name,
                "baseline_selection_reason": selected_baseline.selection_reason,
                "variants": {
                    name: {
                        **_metrics(test_y, probabilities, selected_baseline.probabilities),
                        "parameters": parameters_by_variant[name],
                    }
                    for name, probabilities in probabilities_by_variant.items()
                },
            }
        )
        for name, probabilities in probabilities_by_variant.items():
            losses_by_variant[name].append(_daily_losses(test_frame, test_y, probabilities))
        baseline_losses.append(_daily_losses(test_frame, test_y, selected_baseline.probabilities))

    historical = fold_rows[:3]
    comparisons: dict[str, object] = {}
    for variant in VARIANTS:
        versus_baseline = paired_block_bootstrap_interval(
            baseline_losses[:3],
            losses_by_variant[variant][:3],
            block_size=horizon_days,
        )
        versus_nominal = (0.0, 0.0)
        if variant != "nominal":
            versus_nominal = paired_block_bootstrap_interval(
                losses_by_variant["nominal"][:3],
                losses_by_variant[variant][:3],
                block_size=horizon_days,
            )
        comparisons[variant] = {
            "historical_2023_2025": _aggregate(historical, variant),
            "locked_2026": fold_rows[3]["variants"][variant],  # type: ignore[index]
            "historical_fold_wins_vs_baseline": int(
                sum(
                    float(row["variants"][variant]["brier"])  # type: ignore[index]
                    < float(row["variants"][variant]["baseline_brier"])  # type: ignore[index]
                    for row in historical
                )
            ),
            "historical_fold_wins_vs_nominal": int(
                sum(
                    float(row["variants"][variant]["brier"])  # type: ignore[index]
                    < float(row["variants"]["nominal"]["brier"])  # type: ignore[index]
                    for row in historical
                )
            )
            if variant != "nominal"
            else 0,
            "historical_brier_delta_ci95_vs_baseline": [*versus_baseline],
            "historical_brier_delta_ci95_vs_nominal": [*versus_nominal],
        }

    nested_historical = comparisons["nested_selected"]["historical_2023_2025"]  # type: ignore[index]
    nested_locked = comparisons["nested_selected"]["locked_2026"]  # type: ignore[index]
    nested_vs_baseline = comparisons["nested_selected"][  # type: ignore[index]
        "historical_brier_delta_ci95_vs_baseline"
    ]
    promotable = (
        float(nested_historical["brier_skill_score"]) >= 0.05
        and int(comparisons["nested_selected"]["historical_fold_wins_vs_baseline"]) >= 2  # type: ignore[index]
        and float(nested_vs_baseline[1]) < 0
        and float(nested_historical["ece"]) <= 0.05
        and float(nested_locked["brier_skill_score"]) >= 0
    )
    return {
        "asset_class": config.asset_class,
        "benchmark_asset": config.benchmark_asset,
        "horizon_days": horizon_days,
        "device_type": device_type,
        "sample_count": len(frame),
        "asset_count": int(frame["asset_id"].nunique()),
        "methodology": (
            "BTC/SPY-relative volatility-scaled labels; purged 2023-2026 outer folds; "
            "seven-day embargo; chronological purged calibration fit/selection split; "
            "validation-only baseline and candidate selection; parameter-count complexity "
            "penalty; locked 2026 test. Intraday and repeated same-cutoff predictions are excluded."
        ),
        "promotable": promotable,
        "comparisons": comparisons,
        "folds": fold_rows,
    }


def run_and_write_market_relative_direction_ablation(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": (
            f"probora-{config.asset_class}-market-relative-direction-v4-{datetime.now(UTC):%Y%m%d%H%M%S}"
        ),
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_market_relative_direction_models(
            samples,
            config,
            horizon_days,
            device_type,
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
