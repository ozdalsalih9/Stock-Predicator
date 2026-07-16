from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.config import FEATURE_GROUPS, SEEDS
from probora_ml.evaluation.metrics import multiclass_brier
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import fit_temperature, temperature_scale
from probora_ml.training.pipeline import _classifier, _regressor


def bic_like_score(log_loss: float, feature_count: int, effective_sample_count: int) -> float:
    """A conservative IC diagnostic; not a classical BIC for boosted trees."""
    effective_samples = max(effective_sample_count, 2)
    return float(log_loss + feature_count * math.log(effective_samples) / (2 * effective_samples))


def _log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float:
    selected = probabilities[np.arange(len(labels)), labels.astype(int)]
    return float(-np.log(np.clip(selected, 1e-12, 1)).mean())


def paired_block_bootstrap_interval(
    baseline_by_fold: list[np.ndarray],
    candidate_by_fold: list[np.ndarray],
    block_size: int,
    iterations: int = 2_000,
    seed: int = 17,
) -> tuple[float, float]:
    if len(baseline_by_fold) != len(candidate_by_fold) or not baseline_by_fold:
        raise ValueError("Baseline and candidate folds must have the same non-zero length.")
    random = np.random.default_rng(seed)
    bootstrap_means = []
    for _ in range(iterations):
        sampled_differences = []
        for baseline, candidate in zip(baseline_by_fold, candidate_by_fold, strict=True):
            if len(baseline) != len(candidate) or len(baseline) == 0:
                raise ValueError("Paired fold losses must have the same non-zero length.")
            difference = candidate - baseline
            sample = []
            while len(sample) < len(difference):
                start = int(random.integers(0, len(difference)))
                indices = (np.arange(start, start + block_size) % len(difference)).astype(int)
                sample.extend(difference[indices].tolist())
            sampled_differences.extend(sample[: len(difference)])
        bootstrap_means.append(float(np.mean(sampled_differences)))
    lower, upper = np.quantile(bootstrap_means, [0.025, 0.975])
    return float(lower), float(upper)


def _feature_sets() -> dict[str, tuple[str, ...]]:
    spot = FEATURE_GROUPS["spot"]
    derivatives = FEATURE_GROUPS["derivatives"]
    cross_sectional = FEATURE_GROUPS["cross_sectional"]
    return {
        "spot": spot,
        "spot_cross": (*spot, *cross_sectional),
        "spot_derivatives": (*spot, *derivatives),
        "full": (*spot, *derivatives, *cross_sectional),
    }


def evaluate_feature_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].copy()
    folds = purged_walk_forward_splits(frame, embargo_days=7)
    variants: dict[str, list[dict[str, float | str]]] = {}
    daily_brier_losses: dict[str, list[np.ndarray]] = {}
    for variant, feature_names in _feature_sets().items():
        fold_results: list[dict[str, float | str]] = []
        variant_daily_losses: list[np.ndarray] = []
        for fold in folds:
            train_x = frame.loc[fold.train, feature_names].astype("float32")
            train_y = frame.loc[fold.train, "target_direction"].astype(int).to_numpy()
            validation_x = frame.loc[fold.validation, feature_names].astype("float32")
            validation_y = frame.loc[fold.validation, "target_direction"].astype(int).to_numpy()
            test_x = frame.loc[fold.test, feature_names].astype("float32")
            test_y = frame.loc[fold.test, "target_direction"].astype(int).to_numpy()

            classifier = _classifier(SEEDS[0], device_type).fit(train_x, train_y)
            validation_probabilities = classifier.predict_proba(validation_x)
            temperature = fit_temperature(validation_y, validation_probabilities)
            probabilities = temperature_scale(classifier.predict_proba(test_x), temperature)
            class_prior = np.bincount(train_y, minlength=3) / len(train_y)
            prior_probabilities = np.tile(class_prior, (len(test_y), 1))

            training_risk = 1 - np.exp(-frame.loc[fold.train, "target_volatility"].to_numpy())
            target_risk = 1 - np.exp(-frame.loc[fold.test, "target_volatility"].to_numpy())
            risk_model = _regressor(
                SEEDS[0], objective="regression", device_type=device_type
            ).fit(train_x, training_risk)
            risk_prediction = np.clip(risk_model.predict(test_x), 0, 1)

            unique_days = frame.loc[fold.test, "snapshot_time"].nunique()
            assets = frame.loc[fold.test, "asset_id"].nunique()
            effective_samples = max(2, math.ceil(unique_days / horizon_days) * assets)
            log_loss = _log_loss(test_y, probabilities)
            one_hot = np.eye(3)[test_y]
            row_brier = np.sum((probabilities - one_hot) ** 2, axis=1)
            loss_frame = pd.DataFrame(
                {
                    "snapshot_time": frame.loc[fold.test, "snapshot_time"].to_numpy(),
                    "loss": row_brier,
                }
            )
            variant_daily_losses.append(
                loss_frame.groupby("snapshot_time", sort=True)["loss"].mean().to_numpy()
            )
            fold_results.append(
                {
                    "fold": fold.name,
                    "feature_count": float(len(feature_names)),
                    "effective_sample_count": float(effective_samples),
                    "brier": multiclass_brier(test_y, probabilities),
                    "baseline_brier": multiclass_brier(test_y, prior_probabilities),
                    "log_loss": log_loss,
                    "baseline_log_loss": _log_loss(test_y, prior_probabilities),
                    "bic_like": bic_like_score(log_loss, len(feature_names), effective_samples),
                    "accuracy": float((probabilities.argmax(axis=1) == test_y).mean()),
                    "risk_mae": float(np.mean(np.abs(target_risk - risk_prediction))),
                    "temperature": temperature,
                }
            )
        variants[variant] = fold_results
        daily_brier_losses[variant] = variant_daily_losses

    summary = {}
    spot_results = variants["spot"]
    for variant, results in variants.items():
        confidence_interval = (0.0, 0.0)
        if variant != "spot":
            confidence_interval = paired_block_bootstrap_interval(
                daily_brier_losses["spot"],
                daily_brier_losses[variant],
                block_size=horizon_days,
            )
        summary[variant] = {
            "feature_count": int(results[0]["feature_count"]),
            "mean_brier": float(np.mean([float(row["brier"]) for row in results])),
            "mean_log_loss": float(np.mean([float(row["log_loss"]) for row in results])),
            "mean_bic_like": float(np.mean([float(row["bic_like"]) for row in results])),
            "mean_risk_mae": float(np.mean([float(row["risk_mae"]) for row in results])),
            "mean_brier_delta_vs_spot": float(
                np.mean(
                    [
                        float(row["brier"]) - float(spot["brier"])
                        for row, spot in zip(results, spot_results, strict=True)
                    ]
                )
            ),
            "brier_delta_ci95_vs_spot": [*confidence_interval],
            "brier_fold_wins_vs_spot": int(
                sum(
                    float(row["brier"]) < float(spot["brier"])
                    for row, spot in zip(results, spot_results, strict=True)
                )
            ),
        }
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "embargo_days": 7,
        "variants": variants,
        "summary": summary,
    }


def run_and_write_ablation(
    samples: pd.DataFrame,
    device_type: str,
    output_root: Path,
) -> Path:
    dataset_version = str(samples["dataset_version"].iloc[0])
    safe_dataset_version = dataset_version.lower().replace("_", "-")
    report = {
        "version": f"probora-ablation-{safe_dataset_version}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": dataset_version,
        "reports": [
            evaluate_feature_ablation(samples, horizon, device_type) for horizon in (30, 90)
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
