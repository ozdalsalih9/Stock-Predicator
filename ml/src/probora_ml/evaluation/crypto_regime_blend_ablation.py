from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.config import FEATURE_NAMES, SEEDS
from probora_ml.evaluation.ablation import paired_block_bootstrap_interval
from probora_ml.evaluation.calibration_ablation import _inner_calibration_masks
from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    multiclass_brier,
)
from probora_ml.evaluation.regime_analysis import _attach_regimes, _thresholds
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import (
    blend_probabilities,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)
from probora_ml.training.pipeline import _classifier

REGIME_CANDIDATES: tuple[tuple[str | None, float], ...] = (
    (None, 0.0),
    ("volatility_regime", 100.0),
    ("trend_strength", 100.0),
    ("market_regime", 100.0),
)
MINIMUM_RAW_SELECTION_GAIN = 0.001
MINIMUM_GROUP_SAMPLES = 50


@dataclass(frozen=True)
class RegimeBlend:
    group_column: str | None
    global_weight: float
    group_weights: dict[str, float]
    shrinkage: float

    @property
    def parameter_count(self) -> int:
        return 1 + len(self.group_weights)

    def to_dict(self) -> dict[str, object]:
        return {
            "group_column": self.group_column,
            "global_weight": self.global_weight,
            "group_weights": self.group_weights,
            "shrinkage": self.shrinkage,
            "parameter_count": self.parameter_count,
        }


def fit_regime_blend(
    labels: np.ndarray,
    model_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
    regimes: pd.DataFrame,
    group_column: str | None,
    shrinkage: float,
    minimum_group_samples: int = MINIMUM_GROUP_SAMPLES,
) -> RegimeBlend:
    if model_probabilities.shape != prior_probabilities.shape:
        raise ValueError("Model and prior probabilities must have matching shapes.")
    if len(labels) != len(model_probabilities) or len(regimes) != len(labels):
        raise ValueError("Labels, probabilities and regimes must have matching sample counts.")
    if shrinkage < 0:
        raise ValueError("Shrinkage cannot be negative.")
    if minimum_group_samples < 1:
        raise ValueError("Minimum group samples must be positive.")

    global_weight = fit_probability_blend(labels, model_probabilities, prior_probabilities)
    if group_column is None:
        return RegimeBlend(None, global_weight, {}, 0.0)
    if group_column not in regimes:
        raise ValueError(f"Missing regime column: {group_column}")

    one_hot = np.eye(model_probabilities.shape[1])[labels.astype(int)]
    direction = model_probabilities - prior_probabilities
    values = regimes[group_column].fillna("unknown").astype(str).reset_index(drop=True)
    group_weights: dict[str, float] = {}
    for value in sorted(values.unique()):
        mask = values.eq(value).to_numpy()
        if int(mask.sum()) < minimum_group_samples:
            continue
        numerator = float(
            np.sum((one_hot[mask] - prior_probabilities[mask]) * direction[mask]) + shrinkage * global_weight
        )
        denominator = float(np.sum(direction[mask] ** 2) + shrinkage)
        group_weights[value] = (
            global_weight if denominator <= 1e-15 else float(np.clip(numerator / denominator, 0, 1))
        )
    return RegimeBlend(group_column, global_weight, group_weights, shrinkage)


def apply_regime_blend(
    blend: RegimeBlend,
    model_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
    regimes: pd.DataFrame,
) -> np.ndarray:
    if model_probabilities.shape != prior_probabilities.shape:
        raise ValueError("Model and prior probabilities must have matching shapes.")
    if len(regimes) != len(model_probabilities):
        raise ValueError("Probabilities and regimes must have matching sample counts.")
    if blend.group_column is None:
        return blend_probabilities(model_probabilities, prior_probabilities, blend.global_weight)

    values = regimes[blend.group_column].fillna("unknown").astype(str).reset_index(drop=True)
    weights = np.array(
        [blend.group_weights.get(value, blend.global_weight) for value in values],
        dtype=float,
    )
    return weights[:, None] * model_probabilities + (1 - weights[:, None]) * prior_probabilities


def _metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    current_probabilities: np.ndarray,
) -> dict[str, float]:
    brier = multiclass_brier(labels, probabilities)
    current_brier = multiclass_brier(labels, current_probabilities)
    return {
        "brier": brier,
        "current_brier": current_brier,
        "brier_delta_vs_current": brier - current_brier,
        "brier_skill_vs_current": brier_skill_score(brier, current_brier),
        "ece": expected_calibration_error(labels, probabilities),
        "classwise_ece": classwise_expected_calibration_error(labels, probabilities),
        "accuracy": float((probabilities.argmax(axis=1) == labels).mean()),
        "mean_confidence": float(probabilities.max(axis=1).mean()),
    }


def _daily_losses(frame: pd.DataFrame, labels: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    one_hot = np.eye(probabilities.shape[1])[labels.astype(int)]
    losses = np.sum((probabilities - one_hot) ** 2, axis=1)
    return (
        pd.DataFrame(
            {
                "snapshot_time": pd.to_datetime(frame["snapshot_time"], utc=True).to_numpy(),
                "loss": losses,
            }
        )
        .groupby("snapshot_time", sort=True)["loss"]
        .mean()
        .to_numpy()
    )


def _effective_selection_samples(frame: pd.DataFrame, horizon_days: int) -> int:
    unique_days = frame["snapshot_time"].nunique()
    assets = frame["asset_id"].nunique()
    return max(2, math.ceil(unique_days / horizon_days) * assets)


def _select_candidate(
    validation: pd.DataFrame,
    labels: np.ndarray,
    raw_probabilities: np.ndarray,
    prior: np.ndarray,
    horizon_days: int,
) -> tuple[str | None, list[dict[str, object]]]:
    fitting, selection = _inner_calibration_masks(validation)
    enriched = _attach_regimes(validation, _thresholds(validation.loc[fitting]))
    temperature = fit_temperature(labels[fitting], raw_probabilities[fitting])
    scaled_fit = temperature_scale(raw_probabilities[fitting], temperature)
    scaled_selection = temperature_scale(raw_probabilities[selection], temperature)
    fit_prior = np.tile(prior, (int(fitting.sum()), 1))
    selection_prior = np.tile(prior, (int(selection.sum()), 1))
    selection_frame = enriched.loc[selection].reset_index(drop=True)
    effective_samples = _effective_selection_samples(selection_frame, horizon_days)
    rows: list[dict[str, object]] = []

    for group_column, shrinkage in REGIME_CANDIDATES:
        fitted = fit_regime_blend(
            labels[fitting],
            scaled_fit,
            fit_prior,
            enriched.loc[fitting].reset_index(drop=True),
            group_column,
            shrinkage,
        )
        probabilities = apply_regime_blend(fitted, scaled_selection, selection_prior, selection_frame)
        brier = multiclass_brier(labels[selection], probabilities)
        incremental_parameters = max(0, fitted.parameter_count - 1)
        complexity_penalty = incremental_parameters * math.log(effective_samples) / (2 * len(selection_frame))
        rows.append(
            {
                "group_column": group_column,
                "selection_brier": brier,
                "complexity_penalty": complexity_penalty,
                "complexity_adjusted_score": brier + complexity_penalty,
                "effective_sample_count": effective_samples,
                "fit": fitted.to_dict(),
            }
        )

    global_row = next(row for row in rows if row["group_column"] is None)
    winner = min(rows, key=lambda row: float(row["complexity_adjusted_score"]))
    raw_gain = float(global_row["selection_brier"]) - float(winner["selection_brier"])
    if winner["group_column"] is None or raw_gain < MINIMUM_RAW_SELECTION_GAIN:
        winner = global_row
    for row in rows:
        row["selected"] = row is winner
        row["raw_gain_vs_global"] = float(global_row["selection_brier"]) - float(row["selection_brier"])
    return (
        str(winner["group_column"]) if winner["group_column"] is not None else None,
        rows,
    )


def evaluate_crypto_regime_blend(
    samples: pd.DataFrame, horizon_days: int, device_type: str
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    folds = purged_walk_forward_splits(frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026))
    if len(folds) != 4:
        raise ValueError("The regime blend ablation requires complete 2023-2026 folds.")

    fold_rows: list[dict[str, object]] = []
    current_daily_losses: list[np.ndarray] = []
    candidate_daily_losses: list[np.ndarray] = []
    for fold in folds:
        train = frame.loc[fold.train]
        validation = frame.loc[fold.validation]
        test = frame.loc[fold.test]
        train_x = train.loc[:, FEATURE_NAMES].astype("float32")
        validation_x = validation.loc[:, FEATURE_NAMES].astype("float32")
        test_x = test.loc[:, FEATURE_NAMES].astype("float32")
        train_y = train["target_direction"].astype(int)
        validation_y = validation["target_direction"].to_numpy(int)
        test_y = test["target_direction"].to_numpy(int)

        models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        raw_validation = np.mean([model.predict_proba(validation_x) for model in models], axis=0)
        raw_test = np.mean([model.predict_proba(test_x) for model in models], axis=0)
        prior = np.bincount(train_y.to_numpy(), minlength=3) / len(train_y)
        selected_group, selection_rows = _select_candidate(
            validation, validation_y, raw_validation, prior, horizon_days
        )

        temperature = fit_temperature(validation_y, raw_validation)
        scaled_validation = temperature_scale(raw_validation, temperature)
        scaled_test = temperature_scale(raw_test, temperature)
        validation_prior = np.tile(prior, (len(validation_y), 1))
        test_prior = np.tile(prior, (len(test_y), 1))
        thresholds = _thresholds(train)
        enriched_validation = _attach_regimes(validation, thresholds)
        enriched_test = _attach_regimes(test, thresholds)

        global_blend = fit_regime_blend(
            validation_y,
            scaled_validation,
            validation_prior,
            enriched_validation,
            None,
            0,
        )
        current_probabilities = apply_regime_blend(global_blend, scaled_test, test_prior, enriched_test)
        selected_shrinkage = next(
            shrinkage for group_column, shrinkage in REGIME_CANDIDATES if group_column == selected_group
        )
        candidate_blend = fit_regime_blend(
            validation_y,
            scaled_validation,
            validation_prior,
            enriched_validation,
            selected_group,
            selected_shrinkage,
        )
        candidate_probabilities = apply_regime_blend(candidate_blend, scaled_test, test_prior, enriched_test)
        current_daily_losses.append(_daily_losses(test, test_y, current_probabilities))
        candidate_daily_losses.append(_daily_losses(test, test_y, candidate_probabilities))
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test),
                "selected_group": selected_group,
                "selection_candidates": selection_rows,
                "temperature": temperature,
                "current_blend": global_blend.to_dict(),
                "candidate_blend": candidate_blend.to_dict(),
                "candidate": _metrics(test_y, candidate_probabilities, current_probabilities),
                "current": _metrics(test_y, current_probabilities, current_probabilities),
                "prior_brier": multiclass_brier(test_y, test_prior),
            }
        )

    historical = fold_rows[:3]
    historical_ci = paired_block_bootstrap_interval(
        current_daily_losses[:3],
        candidate_daily_losses[:3],
        block_size=horizon_days,
    )
    mean_candidate = float(
        np.mean([float(row["candidate"]["brier"]) for row in historical])  # type: ignore[index]
    )
    mean_current = float(
        np.mean([float(row["current"]["brier"]) for row in historical])  # type: ignore[index]
    )
    mean_candidate_ece = float(
        np.mean([float(row["candidate"]["ece"]) for row in historical])  # type: ignore[index]
    )
    mean_current_ece = float(
        np.mean([float(row["current"]["ece"]) for row in historical])  # type: ignore[index]
    )
    fold_wins = sum(
        float(row["candidate"]["brier"]) < float(row["current"]["brier"])  # type: ignore[index]
        for row in historical
    )
    locked_delta = float(
        fold_rows[3]["candidate"]["brier_delta_vs_current"]  # type: ignore[index]
    )
    promotable = (
        mean_candidate < mean_current
        and fold_wins >= 2
        and historical_ci[1] < 0
        and mean_candidate_ece <= mean_current_ece + 0.01
        and locked_delta <= 0
    )
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "methodology": (
            "Regime structure is selected on a purged chronological inner validation split. "
            "Additional regime weights are charged an information-criterion-like penalty. "
            "The selected structure is refit on the full outer validation period, never on test."
        ),
        "historical_2023_2025": {
            "candidate_brier": mean_candidate,
            "current_brier": mean_current,
            "brier_delta_vs_current": mean_candidate - mean_current,
            "brier_delta_ci95_vs_current": [*historical_ci],
            "fold_wins": fold_wins,
            "candidate_ece": mean_candidate_ece,
            "current_ece": mean_current_ece,
        },
        "locked_2026": fold_rows[3],
        "promotable": promotable,
        "folds": fold_rows,
    }


def run_and_write_crypto_regime_blend_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-crypto-regime-blend-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_crypto_regime_blend(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
