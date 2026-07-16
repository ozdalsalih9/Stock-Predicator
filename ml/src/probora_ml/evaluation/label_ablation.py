from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

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
from probora_ml.training.pipeline import _classifier

ATR_MULTIPLIERS = (0.35, 0.50, 0.65)
SCREENING_SEEDS = SEEDS[:3]


def atr_confirmed_threshold(
    current_threshold: np.ndarray,
    normalized_atr: np.ndarray,
    horizon_days: int,
    multiplier: float,
) -> np.ndarray:
    """Raise the neutral band with a bounded, point-in-time ATR floor."""
    current = np.asarray(current_threshold, dtype=float)
    atr = np.asarray(normalized_atr, dtype=float)
    if current.shape != atr.shape:
        raise ValueError("Threshold and ATR arrays must have matching shapes.")
    if horizon_days not in (30, 90) or multiplier <= 0:
        raise ValueError("A supported horizon and positive multiplier are required.")
    cap = 0.18 * math.sqrt(horizon_days / 30)
    atr_floor = multiplier * np.maximum(atr, 0) * math.sqrt(horizon_days)
    return np.minimum(cap, np.maximum(current, atr_floor))


def labels_for_thresholds(returns: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    forward = np.asarray(returns, dtype=float)
    bands = np.asarray(thresholds, dtype=float)
    if forward.shape != bands.shape:
        raise ValueError("Return and threshold arrays must have matching shapes.")
    return np.where(forward > bands, 2, np.where(forward < -bands, 0, 1)).astype(int)


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


def evaluate_label_candidates(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[
            *EQUITY_FEATURE_NAMES,
            "target_return",
            "target_direction",
            "neutral_band_threshold",
            "atr_14_normalized",
        ]
    ).copy()
    current_threshold = frame["neutral_band_threshold"].to_numpy(float)
    candidate_thresholds = {"current": current_threshold}
    for multiplier in ATR_MULTIPLIERS:
        candidate_thresholds[f"atr_{multiplier:.2f}"] = atr_confirmed_threshold(
            current_threshold,
            frame["atr_14_normalized"].to_numpy(float),
            horizon_days,
            multiplier,
        )
    candidate_labels = {
        name: labels_for_thresholds(frame["target_return"].to_numpy(float), thresholds)
        for name, thresholds in candidate_thresholds.items()
    }
    if not np.array_equal(
        candidate_labels["current"], frame["target_direction"].to_numpy(int)
    ):
        raise ValueError("Current label reconstruction does not match the versioned dataset.")

    x = frame.loc[:, EQUITY_FEATURE_NAMES].astype("float32")
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 label ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        train_position = frame.index.get_indexer(fold.train)
        validation_position = frame.index.get_indexer(fold.validation)
        test_position = frame.index.get_indexer(fold.test)
        variants: dict[str, object] = {}
        for name, labels in candidate_labels.items():
            train_y = labels[train_position]
            validation_y = labels[validation_position]
            test_y = labels[test_position]
            prior = np.bincount(train_y, minlength=3) / len(train_y)
            models = [
                _classifier(seed, device_type).fit(x.loc[fold.train], train_y)
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
            test_prior = np.tile(prior, (len(test_y), 1))
            test_counts = np.bincount(test_y, minlength=3) / len(test_y)
            variants[name] = {
                **_metrics(test_y, probabilities, test_prior),
                "class_shares": test_counts.tolist(),
                "median_threshold": float(
                    np.median(candidate_thresholds[name][test_position])
                ),
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
        metrics: dict[str, object] = {
            metric: float(
                np.mean([float(row["variants"][name][metric]) for row in rows])  # type: ignore[index]
            )
            for metric in metric_names
        }
        metrics["positive_bss_folds"] = int(
            sum(
                float(row["variants"][name]["brier_skill_score"]) > 0  # type: ignore[index]
                for row in rows
            )
        )
        metrics["mean_class_shares"] = np.mean(
            [row["variants"][name]["class_shares"] for row in rows], axis=0  # type: ignore[index]
        ).tolist()
        return metrics

    historical = fold_rows[:3]
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "seeds": list(SCREENING_SEEDS),
        "methodology": (
            "Point-in-time ATR only changes the target definition and is capped by the existing "
            "horizon-scaled maximum band. Each label has its own train prior, validation-only "
            "calibration and blind outer test. Brier scores across different labels are not treated "
            "as directly comparable; BSS, fold stability, calibration and class balance decide."
        ),
        "folds": fold_rows,
        "historical_2023_2025": {
            name: aggregate(historical, name) for name in candidate_labels
        },
        "locked_2026": {
            name: fold_rows[3]["variants"][name] for name in candidate_labels  # type: ignore[index]
        },
    }


def run_and_write_label_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-equity-label-ablation-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_label_candidates(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
