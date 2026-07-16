from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, SEEDS
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
from probora_ml.training.pipeline import _device_parameters

SCREENING_SEEDS = SEEDS[:3]


@dataclass(frozen=True)
class TreeVariant:
    name: str
    n_estimators: int
    learning_rate: float
    num_leaves: int
    max_depth: int
    min_child_samples: int
    reg_alpha: float
    reg_lambda: float
    colsample_bytree: float
    training_years: int | None = None


VARIANTS = (
    TreeVariant("current", 400, 0.025, 15, 6, 40, 0.2, 1.0, 0.8),
    TreeVariant("current_recent_6y", 400, 0.025, 15, 6, 40, 0.2, 1.0, 0.8, 6),
    TreeVariant("shallow", 300, 0.020, 7, 3, 200, 1.0, 10.0, 0.75),
    TreeVariant("shallow_recent_6y", 300, 0.020, 7, 3, 200, 1.0, 10.0, 0.75, 6),
    TreeVariant("very_shallow", 180, 0.020, 5, 3, 400, 2.0, 20.0, 0.70),
)


def _classifier(variant: TreeVariant, seed: int, device_type: str) -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=variant.n_estimators,
        learning_rate=variant.learning_rate,
        num_leaves=variant.num_leaves,
        max_depth=variant.max_depth,
        min_child_samples=variant.min_child_samples,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=variant.colsample_bytree,
        reg_alpha=variant.reg_alpha,
        reg_lambda=variant.reg_lambda,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
        **_device_parameters(device_type),
    )


def recent_training_index(
    frame: pd.DataFrame, train_index: pd.Index, years: int | None
) -> pd.Index:
    if years is None:
        return train_index
    timestamps = pd.to_datetime(frame.loc[train_index, "snapshot_time"], utc=True)
    cutoff = timestamps.max() - pd.DateOffset(years=years)
    return train_index[timestamps >= cutoff]


def _metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    baseline: np.ndarray,
) -> dict[str, float]:
    brier = multiclass_brier(labels, probabilities)
    baseline_brier = multiclass_brier(labels, baseline)
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
    }


def evaluate_tree_regularization(
    samples: pd.DataFrame, horizon_days: int, device_type: str
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[*EQUITY_FEATURE_NAMES, "target_direction", "label_end_time"]
    ).copy()
    x = frame.loc[:, EQUITY_FEATURE_NAMES].astype("float32")
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 regularization ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        validation_y = frame.loc[fold.validation, "target_direction"].to_numpy(int)
        test_y = frame.loc[fold.test, "target_direction"].to_numpy(int)
        variants: dict[str, object] = {}
        for variant in VARIANTS:
            train_index = recent_training_index(frame, fold.train, variant.training_years)
            train_y = frame.loc[train_index, "target_direction"].to_numpy(int)
            prior = np.bincount(train_y, minlength=3) / len(train_y)
            models = [
                _classifier(variant, seed, device_type).fit(x.loc[train_index], train_y)
                for seed in SCREENING_SEEDS
            ]
            validation_raw = np.mean(
                [model.predict_proba(x.loc[fold.validation]) for model in models], axis=0
            )
            test_raw = np.mean(
                [model.predict_proba(x.loc[fold.test]) for model in models], axis=0
            )
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
            variants[variant.name] = {
                **_metrics(test_y, probabilities, baseline),
                "train_sample_count": len(train_index),
                "temperature": temperature,
                "probability_blend_weight": weight,
            }
        fold_rows.append(
            {"fold": fold.name, "sample_count": len(fold.test), "variants": variants}
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

    def aggregate(rows: list[dict[str, object]], name: str) -> dict[str, object]:
        result: dict[str, object] = {
            metric: float(
                np.mean([float(row["variants"][name][metric]) for row in rows])  # type: ignore[index]
            )
            for metric in metric_names
        }
        result["positive_bss_folds"] = int(
            sum(
                float(row["variants"][name]["brier_skill_score"]) > 0  # type: ignore[index]
                for row in rows
            )
        )
        result["fold_wins_vs_current"] = int(
            sum(
                float(row["variants"][name]["brier"])  # type: ignore[index]
                < float(row["variants"]["current"]["brier"])  # type: ignore[index]
                for row in rows
            )
        )
        return result

    historical = fold_rows[:3]
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "seeds": list(SCREENING_SEEDS),
        "methodology": (
            "Predeclared capacity and recency variants use the same purged outer folds and "
            "validation-only temperature/prior blend. Historical 2023-2025 folds select the design; "
            "partial 2026 is a locked check."
        ),
        "variant_definitions": [variant.__dict__ for variant in VARIANTS],
        "folds": fold_rows,
        "historical_2023_2025": {
            variant.name: aggregate(historical, variant.name) for variant in VARIANTS
        },
        "locked_2026": {
            variant.name: fold_rows[3]["variants"][variant.name]  # type: ignore[index]
            for variant in VARIANTS
        },
    }


def run_and_write_tree_regularization_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-equity-tree-regularization-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_tree_regularization(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
