from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, EQUITY_V3_EXPERIMENT_FEATURE_NAMES, SEEDS
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
    fit_log_probability_matrix_calibrator,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)
from probora_ml.training.pipeline import _classifier

REGULARIZATION_CANDIDATES = (0.01, 0.1, 1.0)


def _equity_macro_frame(frame: pd.DataFrame) -> pd.DataFrame:
    spy = frame[frame["asset_id"] == "SPY"].copy()
    spy = spy.sort_values("snapshot_time").drop_duplicates("snapshot_time", keep="last")
    spy["macro_volatility"] = spy["volatility_20s"].astype(float)
    spy["macro_volume"] = spy["volume_zscore_20s"].astype(float)
    denominator = spy["volatility_60s"].clip(lower=1e-6) * math.sqrt(60 / 252)
    spy["macro_trend_score"] = spy["return_60s"].abs() / denominator
    spy["macro_trend_direction"] = np.sign(spy["return_60s"].astype(float))
    return spy[
        [
            "snapshot_time",
            "macro_volatility",
            "macro_volume",
            "macro_trend_score",
            "macro_trend_direction",
        ]
    ]


def _macro_thresholds(frame: pd.DataFrame) -> dict[str, tuple[float, float]]:
    macro = _equity_macro_frame(frame)
    return {
        name: (float(macro[name].quantile(1 / 3)), float(macro[name].quantile(2 / 3)))
        for name in ("macro_volatility", "macro_volume", "macro_trend_score")
    }


def _bucket(
    values: pd.Series,
    limits: tuple[float, float],
    names: tuple[str, str, str],
) -> pd.Series:
    lower, upper = limits
    return pd.Series(
        np.select([values <= lower, values >= upper], [names[0], names[2]], default=names[1]),
        index=values.index,
    )


def _attach_macro_regimes(
    frame: pd.DataFrame,
    thresholds: dict[str, tuple[float, float]],
) -> pd.DataFrame:
    output = frame.merge(
        _equity_macro_frame(frame), on="snapshot_time", how="left", validate="many_to_one"
    )
    output["volatility_regime"] = _bucket(
        output["macro_volatility"], thresholds["macro_volatility"], ("low", "normal", "high")
    )
    output["volume_regime"] = _bucket(
        output["macro_volume"], thresholds["macro_volume"], ("low", "normal", "high")
    )
    output["trend_strength"] = _bucket(
        output["macro_trend_score"],
        thresholds["macro_trend_score"],
        ("mean_reverting", "transition", "trend"),
    )
    output["macro_market_regime"] = np.select(
        [
            output["trend_strength"] == "mean_reverting",
            (output["trend_strength"] == "trend") & (output["macro_trend_direction"] > 0),
            (output["trend_strength"] == "trend") & (output["macro_trend_direction"] < 0),
        ],
        ["mean_reverting", "bull_trend", "bear_trend"],
        default="transition",
    )
    return output


def _segment_summary(group: pd.DataFrame) -> dict[str, float | int]:
    labels = group["target_direction"].to_numpy(int)
    probabilities = np.vstack(group["probabilities"])
    baseline = np.vstack(group["baseline_probabilities"])
    metrics = _metric_summary(labels, probabilities, baseline)
    return {
        "sample_count": len(group),
        **metrics,
        "brier_delta": metrics["brier"] - metrics["baseline_brier"],
    }


def _metric_summary(
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
        "reliability": decomposition.reliability,
        "resolution": decomposition.resolution,
        "uncertainty": decomposition.uncertainty,
        "decomposed_brier": decomposition.decomposed_brier,
        "binning_gap": decomposition.binning_gap,
    }


def _inner_calibration_masks(validation: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Chronological fit/selection split with event purging and a 7-day embargo."""
    timestamps = pd.to_datetime(validation["snapshot_time"], utc=True)
    unique_dates = np.array(sorted(timestamps.dt.normalize().unique()))
    if len(unique_dates) < 4:
        raise ValueError("Calibration validation period is too short.")
    selection_start = pd.Timestamp(unique_dates[int(len(unique_dates) * 0.67)])
    label_end = pd.to_datetime(validation["label_end_time"], utc=True)
    fitting = (label_end < selection_start - pd.Timedelta(days=7)).to_numpy()
    selection = (timestamps >= selection_start).to_numpy()
    if fitting.sum() == 0 or selection.sum() == 0:
        raise ValueError("Purged calibration split produced an empty period.")
    return fitting, selection


def _temperature_blend(
    fit_y: np.ndarray,
    fit_probabilities: np.ndarray,
    target_probabilities: np.ndarray,
    prior: np.ndarray,
) -> tuple[np.ndarray, dict[str, float]]:
    temperature = fit_temperature(fit_y, fit_probabilities)
    fit_scaled = temperature_scale(fit_probabilities, temperature)
    fit_prior = np.tile(prior, (len(fit_y), 1))
    weight = fit_probability_blend(fit_y, fit_scaled, fit_prior)
    target_scaled = temperature_scale(target_probabilities, temperature)
    target_prior = np.tile(prior, (len(target_probabilities), 1))
    return blend_probabilities(target_scaled, target_prior, weight), {
        "temperature": temperature,
        "probability_blend_weight": weight,
    }


def _select_calibrator(
    validation: pd.DataFrame,
    validation_y: np.ndarray,
    validation_probabilities: np.ndarray,
    prior: np.ndarray,
) -> tuple[str, float | None, list[dict[str, float | str]]]:
    fitting, selection = _inner_calibration_masks(validation)
    fit_y = validation_y[fitting]
    fit_probabilities = validation_probabilities[fitting]
    selection_y = validation_y[selection]
    selection_probabilities = validation_probabilities[selection]
    selection_prior = np.tile(prior, (len(selection_y), 1))

    candidates: list[dict[str, float | str]] = []

    def record(name: str, probabilities: np.ndarray, parameters: int, c: float | None = None) -> None:
        brier = multiclass_brier(selection_y, probabilities)
        # A simple out-of-sample complexity guard inspired by information
        # criteria. It is deliberately reported as a heuristic, not as AIC/BIC.
        adjusted = brier + parameters / len(selection_y)
        row: dict[str, float | str] = {
            "method": name,
            "selection_brier": brier,
            "parameter_count": float(parameters),
            "complexity_adjusted_score": adjusted,
        }
        if c is not None:
            row["regularization_c"] = c
        candidates.append(row)

    record("prior", selection_prior, 0)
    temperature_probabilities, _ = _temperature_blend(
        fit_y, fit_probabilities, selection_probabilities, prior
    )
    record("temperature_blend", temperature_probabilities, 2)
    for regularization_c in REGULARIZATION_CANDIDATES:
        calibrator = fit_log_probability_matrix_calibrator(
            fit_y, fit_probabilities, regularization_c
        )
        record(
            "log_probability_matrix",
            calibrator.predict_proba(selection_probabilities),
            calibrator.parameter_count,
            regularization_c,
        )

    winner = min(candidates, key=lambda row: float(row["complexity_adjusted_score"]))
    return (
        str(winner["method"]),
        float(winner["regularization_c"]) if "regularization_c" in winner else None,
        candidates,
    )


def analyze_equity_calibration(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[
            *(
                EQUITY_V3_EXPERIMENT_FEATURE_NAMES
                if set(EQUITY_V3_EXPERIMENT_FEATURE_NAMES).issubset(samples.columns)
                else EQUITY_FEATURE_NAMES
            ),
            "target_direction",
        ]
    ).copy()
    feature_names = (
        EQUITY_V3_EXPERIMENT_FEATURE_NAMES
        if set(EQUITY_V3_EXPERIMENT_FEATURE_NAMES).issubset(frame.columns)
        else EQUITY_FEATURE_NAMES
    )
    x = frame.loc[:, feature_names].astype("float32")
    folds = purged_walk_forward_splits(frame, embargo_days=7)
    fold_rows: list[dict[str, object]] = []
    regime_predictions: list[pd.DataFrame] = []

    for fold in folds:
        train_x = x.loc[fold.train]
        validation_x = x.loc[fold.validation]
        test_x = x.loc[fold.test]
        train_y = frame.loc[fold.train, "target_direction"].astype(int).to_numpy()
        validation_y = frame.loc[fold.validation, "target_direction"].astype(int).to_numpy()
        test_y = frame.loc[fold.test, "target_direction"].astype(int).to_numpy()
        models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        validation_probabilities = np.mean(
            [model.predict_proba(validation_x) for model in models], axis=0
        )
        test_probabilities = np.mean([model.predict_proba(test_x) for model in models], axis=0)
        prior = np.bincount(train_y, minlength=3) / len(train_y)
        test_prior = np.tile(prior, (len(test_y), 1))

        current_probabilities, current_parameters = _temperature_blend(
            validation_y, validation_probabilities, test_probabilities, prior
        )
        selected_method, regularization_c, selection_candidates = _select_calibrator(
            frame.loc[fold.validation], validation_y, validation_probabilities, prior
        )
        selected_parameters: dict[str, float | str] = {"method": selected_method}
        if selected_method == "prior":
            selected_probabilities = test_prior
        elif selected_method == "temperature_blend":
            selected_probabilities, fitted = _temperature_blend(
                validation_y, validation_probabilities, test_probabilities, prior
            )
            selected_parameters.update(fitted)
        else:
            assert regularization_c is not None
            calibrator = fit_log_probability_matrix_calibrator(
                validation_y, validation_probabilities, regularization_c
            )
            selected_probabilities = calibrator.predict_proba(test_probabilities)
            selected_parameters["regularization_c"] = regularization_c

        enriched = _attach_macro_regimes(
            frame.loc[fold.test].copy(), _macro_thresholds(frame.loc[fold.train])
        )
        enriched["fold"] = fold.name
        enriched["probabilities"] = list(current_probabilities)
        enriched["baseline_probabilities"] = list(test_prior)
        regime_predictions.append(enriched)

        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "raw": _metric_summary(test_y, test_probabilities, test_prior),
                "current_temperature_blend": _metric_summary(
                    test_y, current_probabilities, test_prior
                ),
                "selected": _metric_summary(test_y, selected_probabilities, test_prior),
                "current_parameters": current_parameters,
                "selected_parameters": selected_parameters,
                "inner_selection_candidates": selection_candidates,
            }
        )

    def mean_metrics(name: str) -> dict[str, float]:
        keys = fold_rows[0][name].keys()  # type: ignore[union-attr]
        return {
            key: float(np.mean([float(row[name][key]) for row in fold_rows]))  # type: ignore[index]
            for key in keys
        }

    predicted = pd.concat(regime_predictions, ignore_index=True)
    segments: list[dict[str, object]] = []
    for dimension in (
        "fold",
        "volatility_regime",
        "volume_regime",
        "trend_strength",
        "macro_market_regime",
    ):
        for value, group in predicted.groupby(dimension, sort=True):
            segments.append(
                {"dimension": dimension, "value": str(value), **_segment_summary(group)}
            )

    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "feature_names": feature_names,
        "folds": fold_rows,
        "mean": {
            "raw": mean_metrics("raw"),
            "current_temperature_blend": mean_metrics("current_temperature_blend"),
            "selected": mean_metrics("selected"),
        },
        "selected_methods": [row["selected_parameters"] for row in fold_rows],
        "regime_method": "current_temperature_blend",
        "segments": segments,
        "worst_segments": sorted(
            segments, key=lambda row: float(row["brier_delta"]), reverse=True
        )[:10],
    }


def run_and_write_equity_calibration_ablation(
    samples: pd.DataFrame,
    device_type: str,
    output_root: Path,
) -> Path:
    dataset_version = str(samples["dataset_version"].iloc[0])
    report = {
        "version": f"probora-equity-v3-calibration-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": dataset_version,
        "methodology": (
            "Outer purged walk-forward test; inner chronological calibration selection "
            "with event purging, seven-day embargo and parameter-count complexity guard."
        ),
        "reports": [
            analyze_equity_calibration(samples, horizon, device_type) for horizon in (30, 90)
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
