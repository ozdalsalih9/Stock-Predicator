from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from probora_ml.config import FEATURE_NAMES, SEEDS
from probora_ml.evaluation.metrics import expected_calibration_error, multiclass_brier
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import (
    blend_probabilities,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)
from probora_ml.training.pipeline import _classifier


def _macro_frame(frame: pd.DataFrame) -> pd.DataFrame:
    btc = frame[frame["asset_id"] == "BTCUSDT"].copy()
    btc = btc.sort_values("snapshot_time").drop_duplicates("snapshot_time", keep="last")
    btc["macro_volatility"] = btc["volatility_30d"].astype(float)
    btc["macro_volume"] = btc["volume_zscore_30d"].astype(float)
    denominator = btc["volatility_30d"].clip(lower=1e-6) * math.sqrt(30 / 365)
    btc["macro_trend_score"] = btc["return_30d"].abs() / denominator
    btc["macro_trend_direction"] = np.sign(btc["return_90d"].astype(float))
    return btc[
        [
            "snapshot_time",
            "macro_volatility",
            "macro_volume",
            "macro_trend_score",
            "macro_trend_direction",
        ]
    ]


def _thresholds(frame: pd.DataFrame) -> dict[str, tuple[float, float]]:
    macro = _macro_frame(frame)
    return {
        name: (float(macro[name].quantile(1 / 3)), float(macro[name].quantile(2 / 3)))
        for name in ("macro_volatility", "macro_volume", "macro_trend_score")
    }


def _bucket(values: pd.Series, limits: tuple[float, float], names: tuple[str, str, str]) -> pd.Series:
    lower, upper = limits
    return pd.Series(
        np.select([values <= lower, values >= upper], [names[0], names[2]], default=names[1]),
        index=values.index,
    )


def _attach_regimes(
    frame: pd.DataFrame, limits: dict[str, tuple[float, float]]
) -> pd.DataFrame:
    output = frame.merge(_macro_frame(frame), on="snapshot_time", how="left", validate="many_to_one")
    output["volatility_regime"] = _bucket(
        output["macro_volatility"], limits["macro_volatility"], ("low", "normal", "high")
    )
    output["volume_regime"] = _bucket(
        output["macro_volume"], limits["macro_volume"], ("low", "normal", "high")
    )
    output["trend_strength"] = _bucket(
        output["macro_trend_score"],
        limits["macro_trend_score"],
        ("mean_reverting", "transition", "trend"),
    )
    output["market_regime"] = np.select(
        [
            output["trend_strength"] == "mean_reverting",
            (output["trend_strength"] == "trend") & (output["macro_trend_direction"] > 0),
            (output["trend_strength"] == "trend") & (output["macro_trend_direction"] < 0),
        ],
        ["mean_reverting", "bull_trend", "bear_trend"],
        default="transition",
    )
    return output


def _segment_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    labels = group["target_direction"].to_numpy(int)
    probabilities = np.vstack(group["probabilities"])
    baseline = np.vstack(group["baseline_probabilities"])
    brier = multiclass_brier(labels, probabilities)
    baseline_brier = multiclass_brier(labels, baseline)
    return {
        "sample_count": len(group),
        "brier": brier,
        "baseline_brier": baseline_brier,
        "brier_delta": brier - baseline_brier,
        "accuracy": float((probabilities.argmax(axis=1) == labels).mean()),
        "ece": expected_calibration_error(labels, probabilities),
        "mean_confidence": float(probabilities.max(axis=1).mean()),
    }


def analyze_v2_regimes(
    samples: pd.DataFrame, horizon_days: int, device_type: str
) -> dict[str, object]:
    frame = samples[samples["horizon_days"] == horizon_days].copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    folds = purged_walk_forward_splits(frame, embargo_days=7)
    predictions: list[pd.DataFrame] = []
    fold_summaries: list[dict[str, object]] = []
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
        validation_probabilities = np.mean(
            [model.predict_proba(validation_x) for model in models], axis=0
        )
        temperature = fit_temperature(validation_y, validation_probabilities)
        prior = np.bincount(train_y.to_numpy(), minlength=3) / len(train_y)
        validation_prior = np.tile(prior, (len(validation_y), 1))
        calibrated_validation = temperature_scale(validation_probabilities, temperature)
        blend_weight = fit_probability_blend(
            validation_y, calibrated_validation, validation_prior
        )
        calibrated_test = temperature_scale(
            np.mean([model.predict_proba(test_x) for model in models], axis=0), temperature
        )
        prior_probabilities = np.tile(prior, (len(test_y), 1))
        probabilities = blend_probabilities(calibrated_test, prior_probabilities, blend_weight)
        logistic = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(
            train_x, train_y
        )
        logistic_probabilities = logistic.predict_proba(test_x)
        baseline_probabilities = (
            logistic_probabilities
            if multiclass_brier(test_y, logistic_probabilities)
            < multiclass_brier(test_y, prior_probabilities)
            else prior_probabilities
        )

        enriched = _attach_regimes(test, _thresholds(train))
        enriched["fold"] = fold.name
        enriched["probabilities"] = list(probabilities)
        enriched["baseline_probabilities"] = list(baseline_probabilities)
        predictions.append(enriched)
        fold_summaries.append(
            {
                "fold": fold.name,
                "temperature": temperature,
                "probability_blend_weight": blend_weight,
                **_segment_metrics(enriched),
            }
        )

    predicted = pd.concat(predictions, ignore_index=True)
    segment_rows: list[dict[str, object]] = []
    for dimension in ("fold", "volatility_regime", "volume_regime", "trend_strength", "market_regime"):
        for value, group in predicted.groupby(dimension, sort=True):
            segment_rows.append(
                {"dimension": dimension, "value": str(value), **_segment_metrics(group)}
            )
    worst = sorted(segment_rows, key=lambda row: float(row["brier_delta"]), reverse=True)
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "sample_count": len(predicted),
        "folds": fold_summaries,
        "segments": segment_rows,
        "worst_segments": worst[:8],
    }


def run_and_write_regime_analysis(
    samples: pd.DataFrame, device_type: str, output_root: Path
) -> Path:
    dataset_version = str(samples["dataset_version"].iloc[0])
    safe_dataset_version = dataset_version.lower().replace("_", "-")
    report = {
        "version": f"probora-{safe_dataset_version}-regime-analysis-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": dataset_version,
        "reports": [analyze_v2_regimes(samples, horizon, device_type) for horizon in (30, 90)],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
