from __future__ import annotations

import json
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
from probora_ml.ingestion.fred_market import (
    FRED_MARKET_FEATURE_NAMES,
    attach_fred_market_features,
    load_fred_market_features,
)
from probora_ml.training.calibration import (
    blend_probabilities,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)
from probora_ml.training.pipeline import _classifier

SCREENING_SEEDS = SEEDS[:3]
VARIANT_FEATURES = {
    "existing": EQUITY_FEATURE_NAMES,
    "fred_market": (*EQUITY_FEATURE_NAMES, *FRED_MARKET_FEATURE_NAMES),
}


def _metrics(
    labels: np.ndarray, probabilities: np.ndarray, baseline: np.ndarray
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


def evaluate_fred_macro_features(
    samples: pd.DataFrame,
    macro_root: Path,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    macro = load_fred_market_features(macro_root)
    frame = attach_fred_market_features(
        samples[samples["horizon_days"] == horizon_days].copy(), macro
    ).dropna(subset=[*VARIANT_FEATURES["fred_market"], "target_direction"])
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    if len(folds) != 4:
        raise ValueError("The 2023-2026 FRED macro ablation requires four complete folds.")

    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        train_y = frame.loc[fold.train, "target_direction"].to_numpy(int)
        validation_y = frame.loc[fold.validation, "target_direction"].to_numpy(int)
        test_y = frame.loc[fold.test, "target_direction"].to_numpy(int)
        prior = np.bincount(train_y, minlength=3) / len(train_y)
        variants: dict[str, object] = {}
        for name, feature_names in VARIANT_FEATURES.items():
            models = [
                _classifier(seed, device_type).fit(
                    frame.loc[fold.train, feature_names].astype("float32"), train_y
                )
                for seed in SCREENING_SEEDS
            ]
            validation_raw = np.mean(
                [
                    model.predict_proba(
                        frame.loc[fold.validation, feature_names].astype("float32")
                    )
                    for model in models
                ],
                axis=0,
            )
            test_raw = np.mean(
                [
                    model.predict_proba(
                        frame.loc[fold.test, feature_names].astype("float32")
                    )
                    for model in models
                ],
                axis=0,
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
            variants[name] = {
                **_metrics(test_y, probabilities, baseline),
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
        result["fold_wins_vs_existing"] = int(
            sum(
                float(row["variants"][name]["brier"])  # type: ignore[index]
                < float(row["variants"]["existing"]["brier"])  # type: ignore[index]
                for row in rows
            )
        )
        result["positive_bss_folds"] = int(
            sum(
                float(row["variants"][name]["brier_skill_score"]) > 0  # type: ignore[index]
                for row in rows
            )
        )
        return result

    historical = fold_rows[:3]
    return {
        "horizon_days": horizon_days,
        "device_type": device_type,
        "feature_names": list(FRED_MARKET_FEATURE_NAMES),
        "production_eligible": False,
        "production_blocker": (
            "The downloadable FRED graph is a current-vintage research snapshot. Live immutable "
            "as-of observations or ALFRED vintage reconstruction are required before promotion."
        ),
        "methodology": (
            "Every observation receives a conservative seven-calendar-day availability lag before a "
            "backward as-of join. Existing and macro variants use identical purged folds and "
            "validation-only calibration."
        ),
        "folds": fold_rows,
        "historical_2023_2025": {
            name: aggregate(historical, name) for name in VARIANT_FEATURES
        },
        "locked_2026": {
            name: fold_rows[3]["variants"][name] for name in VARIANT_FEATURES  # type: ignore[index]
        },
    }


def run_and_write_fred_macro_ablation(
    samples: pd.DataFrame,
    macro_root: Path,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-equity-fred-macro-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_fred_macro_features(
            samples, macro_root, horizon_days, device_type
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
