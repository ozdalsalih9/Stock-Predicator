from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from probora_ml.config import EQUITY_FEATURE_NAMES, SEEDS
from probora_ml.evaluation.ablation import paired_block_bootstrap_interval
from probora_ml.evaluation.baselines import select_direction_baseline
from probora_ml.evaluation.calibration_ablation import _inner_calibration_masks
from probora_ml.evaluation.direction_model_ablation import (
    _binary_classifier,
    _calibrate_ordinal,
)
from probora_ml.evaluation.market_relative_ablation import (
    MARKET_RELATIVE_CONFIGS,
    attach_market_relative_targets,
)
from probora_ml.evaluation.market_relative_direction_ablation import (
    _daily_losses,
    _metrics,
    select_complexity_guarded_candidate,
)
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.features.equity_cross_sectional import (
    BREADTH_DISPERSION_FEATURE_NAMES,
    EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES,
    PEER_RELATIVE_FEATURE_NAMES,
    add_equity_cross_sectional_features,
)

FEATURE_GROUPS = {
    "base_ordinal": (),
    "breadth_ordinal": BREADTH_DISPERSION_FEATURE_NAMES,
    "peer_ordinal": PEER_RELATIVE_FEATURE_NAMES,
    "combined_ordinal": EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES,
}


def build_equity_cross_sectional_research_dataset(samples: pd.DataFrame) -> pd.DataFrame:
    enriched = add_equity_cross_sectional_features(samples)
    relative = attach_market_relative_targets(enriched, MARKET_RELATIVE_CONFIGS["us_equity"])
    relative["feature_set_version"] = "us-equity-daily-v1+cross-sectional-exp1"
    return relative


def _ordinal_predictions(
    train_x: pd.DataFrame,
    train_y: np.ndarray,
    validation_x: pd.DataFrame,
    test_x: pd.DataFrame,
    validation_y: np.ndarray,
    prior: np.ndarray,
    device_type: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    not_down_models = [_binary_classifier(seed, device_type).fit(train_x, train_y >= 1) for seed in SEEDS]
    up_models = [_binary_classifier(seed, device_type).fit(train_x, train_y >= 2) for seed in SEEDS]
    validation_not_down = np.mean(
        [model.predict_proba(validation_x)[:, 1] for model in not_down_models], axis=0
    )
    validation_up = np.mean([model.predict_proba(validation_x)[:, 1] for model in up_models], axis=0)
    test_not_down = np.mean([model.predict_proba(test_x)[:, 1] for model in not_down_models], axis=0)
    test_up = np.mean([model.predict_proba(test_x)[:, 1] for model in up_models], axis=0)
    probabilities, parameters = _calibrate_ordinal(
        validation_y,
        validation_not_down,
        validation_up,
        test_not_down,
        test_up,
        prior,
    )
    return (
        validation_not_down,
        validation_up,
        test_not_down,
        test_up,
        probabilities,
        parameters,
    )


def _mean_metrics(rows: list[dict[str, object]], variant: str) -> dict[str, float]:
    names = (
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
        name: float(
            np.mean(
                [
                    float(row["variants"][variant][name])  # type: ignore[index]
                    for row in rows
                ]
            )
        )
        for name in names
    }


def _regime_thresholds(train: pd.DataFrame) -> dict[str, tuple[float, float]]:
    daily = train.sort_values("snapshot_time").drop_duplicates("snapshot_time", keep="last")
    return {
        column: (float(daily[column].quantile(1 / 3)), float(daily[column].quantile(2 / 3)))
        for column in (
            "market_breadth_60s",
            "cross_sectional_return_dispersion_20s",
        )
    }


def _three_way_regime(
    values: pd.Series,
    thresholds: tuple[float, float],
    names: tuple[str, str, str],
) -> pd.Series:
    lower, upper = thresholds
    return pd.Series(
        np.select([values <= lower, values >= upper], [names[0], names[2]], default=names[1]),
        index=values.index,
    )


def _attach_regimes(
    test: pd.DataFrame,
    thresholds: dict[str, tuple[float, float]],
) -> pd.DataFrame:
    output = test.copy()
    output["breadth_regime"] = _three_way_regime(
        output["market_breadth_60s"],
        thresholds["market_breadth_60s"],
        ("narrow", "mixed", "broad"),
    )
    output["dispersion_regime"] = _three_way_regime(
        output["cross_sectional_return_dispersion_20s"],
        thresholds["cross_sectional_return_dispersion_20s"],
        ("low", "normal", "high"),
    )
    benchmark_regime = output["benchmark_market_regime_diagnostic"].astype(float)
    output["benchmark_regime"] = np.select(
        [benchmark_regime < 0, benchmark_regime > 0],
        ["bear", "bull"],
        default="sideways",
    )
    return output


def _segment_metrics(group: pd.DataFrame) -> dict[str, float | int]:
    labels = group["label"].to_numpy(int)
    probabilities = np.vstack(group["probabilities"])
    baseline = np.vstack(group["baseline_probabilities"])
    metrics = _metrics(labels, probabilities, baseline)
    return {
        "sample_count": len(group),
        **metrics,
        "brier_delta": metrics["brier"] - metrics["baseline_brier"],
    }


def evaluate_equity_cross_sectional_features(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    feature_groups: dict[str, tuple[str, ...]] | None = None,
    methodology_prefix: str = "Same-cutoff cross-sectional features from the completed 20-asset universe",
) -> dict[str, object]:
    selected_feature_groups = feature_groups or FEATURE_GROUPS
    variants = (*selected_feature_groups, "nested_selected")
    if "relative_target_direction" not in samples:
        samples = build_equity_cross_sectional_research_dataset(samples)
    required = [
        *EQUITY_FEATURE_NAMES,
        *EQUITY_CROSS_SECTIONAL_EXPERIMENT_FEATURE_NAMES,
        *dict.fromkeys(feature for features in selected_feature_groups.values() for feature in features),
        "relative_target_direction",
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
        raise ValueError("Cross-sectional ablation requires complete 2023-2026 folds.")

    target_column = "relative_target_direction"
    fold_rows: list[dict[str, object]] = []
    losses_by_variant: dict[str, list[np.ndarray]] = {name: [] for name in variants}
    baseline_losses: list[np.ndarray] = []
    regime_predictions: list[pd.DataFrame] = []
    for fold in folds:
        train_y = frame.loc[fold.train, target_column].astype(int).to_numpy()
        validation_y = frame.loc[fold.validation, target_column].astype(int).to_numpy()
        test_y = frame.loc[fold.test, target_column].astype(int).to_numpy()
        prior = np.bincount(train_y, minlength=3) / len(train_y)
        validation_prior = np.tile(prior, (len(validation_y), 1))
        test_prior = np.tile(prior, (len(test_y), 1))
        calibration_fit, calibration_selection = _inner_calibration_masks(frame.loc[fold.validation])
        selection_y = validation_y[calibration_selection]
        probabilities_by_variant: dict[str, np.ndarray] = {}
        selection_probabilities: dict[str, np.ndarray] = {"prior": validation_prior[calibration_selection]}
        parameters_by_variant: dict[str, object] = {}

        for variant, extra_features in selected_feature_groups.items():
            feature_names = (*EQUITY_FEATURE_NAMES, *extra_features)
            train_x = frame.loc[fold.train, feature_names].astype("float32")
            validation_x = frame.loc[fold.validation, feature_names].astype("float32")
            test_x = frame.loc[fold.test, feature_names].astype("float32")
            (
                validation_not_down,
                validation_up,
                _,
                _,
                test_probabilities,
                parameters,
            ) = _ordinal_predictions(
                train_x,
                train_y,
                validation_x,
                test_x,
                validation_y,
                prior,
                device_type,
            )
            probabilities_by_variant[variant] = test_probabilities
            selection_probabilities[variant], _ = _calibrate_ordinal(
                validation_y[calibration_fit],
                validation_not_down[calibration_fit],
                validation_up[calibration_fit],
                validation_not_down[calibration_selection],
                validation_up[calibration_selection],
                prior,
            )
            parameters_by_variant[variant] = {
                **parameters,
                "feature_count": len(feature_names),
                "added_feature_count": len(extra_features),
            }

        parameter_counts = {
            "prior": 0,
            **{
                variant: 3 + len(extra_features)
                for variant, extra_features in selected_feature_groups.items()
            },
        }
        selected_method, selection_rows = select_complexity_guarded_candidate(
            selection_y,
            selection_probabilities,
            parameter_counts,
        )
        probabilities_by_variant["nested_selected"] = (
            test_prior if selected_method == "prior" else probabilities_by_variant[selected_method]
        )
        parameters_by_variant["nested_selected"] = {
            "selected_method": selected_method,
            "inner_selection_candidates": selection_rows,
        }

        base_features = frame.loc[:, EQUITY_FEATURE_NAMES].astype("float32")
        logistic = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(
            base_features.loc[fold.train], train_y
        )
        selected_baseline = select_direction_baseline(
            validation_y,
            logistic.predict_proba(base_features.loc[fold.validation]),
            validation_prior,
            test_y,
            logistic.predict_proba(base_features.loc[fold.test]),
            test_prior,
        )
        test_frame = frame.loc[fold.test]
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "selected_baseline": selected_baseline.name,
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
            regimes = _attach_regimes(test_frame, _regime_thresholds(frame.loc[fold.train]))
            regimes["variant"] = name
            regimes["label"] = test_y
            regimes["probabilities"] = list(probabilities)
            regimes["baseline_probabilities"] = list(selected_baseline.probabilities)
            regime_predictions.append(regimes)
        baseline_losses.append(_daily_losses(test_frame, test_y, selected_baseline.probabilities))

    historical = fold_rows[:3]
    comparisons: dict[str, object] = {}
    for variant in variants:
        versus_baseline = paired_block_bootstrap_interval(
            baseline_losses[:3], losses_by_variant[variant][:3], block_size=horizon_days
        )
        versus_base = (0.0, 0.0)
        if variant != "base_ordinal":
            versus_base = paired_block_bootstrap_interval(
                losses_by_variant["base_ordinal"][:3],
                losses_by_variant[variant][:3],
                block_size=horizon_days,
            )
        comparisons[variant] = {
            "historical_2023_2025": _mean_metrics(historical, variant),
            "held_out_2026_diagnostic": fold_rows[3]["variants"][variant],  # type: ignore[index]
            "historical_fold_wins_vs_baseline": int(
                sum(
                    float(row["variants"][variant]["brier"])  # type: ignore[index]
                    < float(row["variants"][variant]["baseline_brier"])  # type: ignore[index]
                    for row in historical
                )
            ),
            "historical_fold_wins_vs_base_ordinal": int(
                sum(
                    float(row["variants"][variant]["brier"])  # type: ignore[index]
                    < float(row["variants"]["base_ordinal"]["brier"])  # type: ignore[index]
                    for row in historical
                )
            )
            if variant != "base_ordinal"
            else 0,
            "historical_brier_delta_ci95_vs_baseline": [*versus_baseline],
            "historical_brier_delta_ci95_vs_base_ordinal": [*versus_base],
        }

    eligible_variants = []
    for variant in selected_feature_groups:
        historical_metrics = comparisons[variant]["historical_2023_2025"]  # type: ignore[index]
        ci = comparisons[variant]["historical_brier_delta_ci95_vs_baseline"]  # type: ignore[index]
        if (
            float(historical_metrics["brier_skill_score"]) >= 0.05
            and int(comparisons[variant]["historical_fold_wins_vs_baseline"]) >= 2  # type: ignore[index]
            and float(ci[1]) < 0
            and float(historical_metrics["ece"]) <= 0.05
        ):
            eligible_variants.append(variant)
    predicted = pd.concat(regime_predictions, ignore_index=True)
    regime_segments: list[dict[str, object]] = []
    for variant in variants:
        variant_frame = predicted[predicted["variant"] == variant]
        for dimension in ("benchmark_regime", "breadth_regime", "dispersion_regime"):
            for value, group in variant_frame.groupby(dimension, sort=True):
                regime_segments.append(
                    {
                        "variant": variant,
                        "dimension": dimension,
                        "value": str(value),
                        **_segment_metrics(group),
                    }
                )

    return {
        "asset_class": "us_equity",
        "benchmark_asset": "SPY",
        "horizon_days": horizon_days,
        "device_type": device_type,
        "sample_count": len(frame),
        "feature_groups": {name: [*features] for name, features in selected_feature_groups.items()},
        "methodology": (
            f"{methodology_prefix}; "
            "SPY-relative volatility-scaled ordinal labels; purged 2023-2026 outer folds; "
            "seven-day embargo; chronological purged inner selection; added-feature complexity "
            "penalty. The already-open 2026 fold is diagnostic, not fresh confirmation."
        ),
        "shadow_eligible_variants": eligible_variants,
        "requires_unseen_shadow_evidence": True,
        "comparisons": comparisons,
        "folds": fold_rows,
        "regime_segments": regime_segments,
        "worst_regime_segments": {
            variant: sorted(
                [row for row in regime_segments if row["variant"] == variant],
                key=lambda row: float(row["brier_delta"]),
                reverse=True,
            )[:5]
            for variant in variants
        },
    }


def write_equity_cross_sectional_research_dataset(
    samples: pd.DataFrame,
    output_path: Path,
) -> Path:
    output = build_equity_cross_sectional_research_dataset(samples)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="zstd")
    return output_path


def run_and_write_equity_cross_sectional_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-us-equity-cross-sectional-v4-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "source_dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_equity_cross_sectional_features(samples, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
