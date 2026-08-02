from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from probora_ml.config import EQUITY_FEATURE_NAMES, FEATURE_NAMES, SEEDS
from probora_ml.evaluation.ablation import paired_block_bootstrap_interval
from probora_ml.evaluation.baselines import select_direction_baseline
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
from probora_ml.training.labels import neutral_band_threshold
from probora_ml.training.pipeline import _classifier


@dataclass(frozen=True)
class MarketRelativeConfig:
    asset_class: str
    benchmark_asset: str
    feature_names: tuple[str, ...]
    volatility_short_column: str
    volatility_long_column: str
    correlation_short_column: str
    correlation_long_column: str
    periods_per_year: int


MARKET_RELATIVE_CONFIGS = {
    "crypto": MarketRelativeConfig(
        asset_class="crypto",
        benchmark_asset="BTCUSDT",
        feature_names=FEATURE_NAMES,
        volatility_short_column="volatility_30d",
        volatility_long_column="volatility_90d",
        correlation_short_column="btc_correlation_30d",
        correlation_long_column="btc_correlation_90d",
        periods_per_year=365,
    ),
    "us_equity": MarketRelativeConfig(
        asset_class="us_equity",
        benchmark_asset="SPY",
        feature_names=EQUITY_FEATURE_NAMES,
        volatility_short_column="volatility_20s",
        volatility_long_column="volatility_60s",
        correlation_short_column="benchmark_correlation_20s",
        correlation_long_column="benchmark_correlation_60s",
        periods_per_year=252,
    ),
}


def _residual_volatility(
    asset_volatility: pd.Series,
    benchmark_volatility: pd.Series,
    correlation: pd.Series,
) -> np.ndarray:
    asset = asset_volatility.to_numpy(float)
    benchmark = benchmark_volatility.to_numpy(float)
    bounded_correlation = np.clip(correlation.to_numpy(float), -1, 1)
    variance = asset**2 + benchmark**2 - 2 * bounded_correlation * asset * benchmark
    return np.sqrt(np.maximum(variance, 1e-8))


def attach_market_relative_targets(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
) -> pd.DataFrame:
    """Add causal volatility-scaled excess-return labels against BTC or SPY."""
    required = {
        "asset_id",
        "snapshot_time",
        "horizon_days",
        "target_return",
        config.volatility_short_column,
        config.volatility_long_column,
        config.correlation_short_column,
        config.correlation_long_column,
    }
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(f"Missing market-relative columns: {', '.join(missing)}")

    frame = samples.copy()
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    benchmark = frame[frame["asset_id"] == config.benchmark_asset][
        [
            "snapshot_time",
            "horizon_days",
            "target_return",
            config.volatility_short_column,
            config.volatility_long_column,
        ]
    ].drop_duplicates(["snapshot_time", "horizon_days"], keep="last")
    benchmark = benchmark.rename(
        columns={
            "target_return": "benchmark_target_return",
            config.volatility_short_column: "benchmark_label_volatility_short",
            config.volatility_long_column: "benchmark_label_volatility_long",
        }
    )
    output = frame.merge(
        benchmark,
        on=["snapshot_time", "horizon_days"],
        how="inner",
        validate="many_to_one",
    )
    output = output[output["asset_id"] != config.benchmark_asset].copy()
    output["relative_target_return"] = output["target_return"].astype(float) - output[
        "benchmark_target_return"
    ].astype(float)
    output["relative_label_volatility_short"] = _residual_volatility(
        output[config.volatility_short_column],
        output["benchmark_label_volatility_short"],
        output[config.correlation_short_column],
    )
    output["relative_label_volatility_long"] = _residual_volatility(
        output[config.volatility_long_column],
        output["benchmark_label_volatility_long"],
        output[config.correlation_long_column],
    )
    output["relative_neutral_band_threshold"] = [
        neutral_band_threshold(
            float(short_volatility),
            int(horizon_days),
            float(long_volatility),
            periods_per_year=config.periods_per_year,
        )
        for short_volatility, long_volatility, horizon_days in zip(
            output["relative_label_volatility_short"],
            output["relative_label_volatility_long"],
            output["horizon_days"],
            strict=True,
        )
    ]
    returns = output["relative_target_return"].to_numpy(float)
    thresholds = output["relative_neutral_band_threshold"].to_numpy(float)
    output["relative_target_direction"] = np.select(
        [returns < -thresholds, returns > thresholds],
        [0, 2],
        default=1,
    ).astype(int)
    original_version = (
        str(output["dataset_version"].iloc[0])
        if "dataset_version" in output and not output.empty
        else "unversioned"
    )
    output["source_dataset_version"] = original_version
    output["dataset_version"] = f"{original_version}-market-relative-v4"
    output["market_relative_benchmark"] = config.benchmark_asset
    return output.reset_index(drop=True)


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


def _daily_losses(frame: pd.DataFrame, labels: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    one_hot = np.eye(3)[labels.astype(int)]
    losses = np.sum((probabilities - one_hot) ** 2, axis=1)
    return (
        pd.DataFrame(
            {
                "snapshot_time": frame["snapshot_time"].to_numpy(),
                "loss": losses,
            }
        )
        .groupby("snapshot_time", sort=True)["loss"]
        .mean()
        .to_numpy()
    )


def evaluate_market_relative_direction(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
    horizon_days: int,
    device_type: str,
) -> dict[str, object]:
    target_column = "relative_target_direction"
    if target_column not in samples:
        samples = attach_market_relative_targets(samples, config)
    frame = (
        samples[samples["horizon_days"] == horizon_days]
        .dropna(subset=[*config.feature_names, target_column, "label_end_time"])
        .copy()
    )
    frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
    folds = purged_walk_forward_splits(frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026))
    if len(folds) != 4:
        raise ValueError("Market-relative V4 requires complete 2023-2026 folds.")

    fold_rows: list[dict[str, object]] = []
    model_daily_losses: list[np.ndarray] = []
    baseline_daily_losses: list[np.ndarray] = []
    for fold in folds:
        train = frame.loc[fold.train]
        validation = frame.loc[fold.validation]
        test = frame.loc[fold.test]
        train_x = train.loc[:, config.feature_names].astype("float32")
        validation_x = validation.loc[:, config.feature_names].astype("float32")
        test_x = test.loc[:, config.feature_names].astype("float32")
        train_y = train[target_column].astype(int)
        validation_y = validation[target_column].to_numpy(int)
        test_y = test[target_column].to_numpy(int)

        models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        raw_validation = np.mean([model.predict_proba(validation_x) for model in models], axis=0)
        raw_test = np.mean([model.predict_proba(test_x) for model in models], axis=0)
        temperature = fit_temperature(validation_y, raw_validation)
        calibrated_validation = temperature_scale(raw_validation, temperature)
        calibrated_test = temperature_scale(raw_test, temperature)
        prior = np.bincount(train_y.to_numpy(), minlength=3) / len(train_y)
        validation_prior = np.tile(prior, (len(validation_y), 1))
        test_prior = np.tile(prior, (len(test_y), 1))
        blend_weight = fit_probability_blend(validation_y, calibrated_validation, validation_prior)
        probabilities = blend_probabilities(calibrated_test, test_prior, blend_weight)

        logistic = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(train_x, train_y)
        selected_baseline = select_direction_baseline(
            validation_y,
            logistic.predict_proba(validation_x),
            validation_prior,
            test_y,
            logistic.predict_proba(test_x),
            test_prior,
        )
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test_y),
                "asset_count": int(test["asset_id"].nunique()),
                "selected_baseline": selected_baseline.name,
                "baseline_selection_reason": selected_baseline.selection_reason,
                "validation_logistic_brier": (selected_baseline.validation_logistic_brier),
                "validation_climatology_brier": (selected_baseline.validation_climatology_brier),
                "validation_uniform_brier": selected_baseline.validation_uniform_brier,
                "oracle_baseline_brier": selected_baseline.oracle_test_brier,
                "temperature": temperature,
                "probability_blend_weight": blend_weight,
                "class_prior": prior.tolist(),
                "class_counts": np.bincount(test_y, minlength=3).tolist(),
                "metrics": _metrics(test_y, probabilities, selected_baseline.probabilities),
            }
        )
        model_daily_losses.append(_daily_losses(test, test_y, probabilities))
        baseline_daily_losses.append(_daily_losses(test, test_y, selected_baseline.probabilities))

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

    def aggregate(rows: list[dict[str, object]]) -> dict[str, float]:
        return {
            name: float(
                np.mean(
                    [
                        float(row["metrics"][name])  # type: ignore[index]
                        for row in rows
                    ]
                )
            )
            for name in metric_names
        }

    historical = fold_rows[:3]
    historical_metrics = aggregate(historical)
    confidence_interval = paired_block_bootstrap_interval(
        baseline_daily_losses[:3],
        model_daily_losses[:3],
        block_size=horizon_days,
    )
    fold_wins = sum(
        float(row["metrics"]["brier"])  # type: ignore[index]
        < float(row["metrics"]["baseline_brier"])  # type: ignore[index]
        for row in historical
    )
    locked_metrics = fold_rows[3]["metrics"]
    promotable_component = (
        historical_metrics["brier_skill_score"] >= 0.05
        and fold_wins >= 2
        and confidence_interval[1] < 0
        and historical_metrics["ece"] <= 0.05
        and float(locked_metrics["brier_skill_score"]) >= 0  # type: ignore[index]
    )
    return {
        "asset_class": config.asset_class,
        "benchmark_asset": config.benchmark_asset,
        "horizon_days": horizon_days,
        "device_type": device_type,
        "sample_count": len(frame),
        "asset_count": int(frame["asset_id"].nunique()),
        "methodology": (
            "The target is the asset log return minus the contemporaneous benchmark log "
            "return. Its neutral band is computed from point-in-time residual volatility "
            "using asset/benchmark volatility and correlation. Purged outer folds, a "
            "seven-day embargo, validation-only calibration and validation-only baseline "
            "selection are used. The 2026 fold is locked."
        ),
        "historical_2023_2025": {
            **historical_metrics,
            "fold_wins": fold_wins,
            "brier_delta_ci95_vs_baseline": [*confidence_interval],
        },
        "locked_2026": locked_metrics,
        "promotable_component": promotable_component,
        "folds": fold_rows,
    }


def write_market_relative_dataset(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
    output_path: Path,
) -> Path:
    output = attach_market_relative_targets(samples, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="zstd")
    return output_path


def run_and_write_market_relative_ablation(
    samples: pd.DataFrame,
    config: MarketRelativeConfig,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": (f"probora-{config.asset_class}-market-relative-v4-{datetime.now(UTC):%Y%m%d%H%M%S}"),
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_market_relative_direction(samples, config, horizon_days, device_type),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
