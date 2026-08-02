from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import mlflow
import numpy as np
import onnxmltools
import onnxruntime as ort
import pandas as pd
from onnxmltools.convert.common.data_types import FloatTensorType
from sklearn.linear_model import LogisticRegression

from probora_ml.config import FEATURE_NAMES, FEATURE_SET_VERSION, SEEDS
from probora_ml.evaluation.baselines import select_direction_baseline
from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    interval_score,
    multiclass_brier,
    multiclass_brier_decomposition,
    pinball_loss,
    quantile_interval_coverage,
)
from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.calibration import (
    apply_scaled_conformal,
    blend_probabilities,
    fit_probability_blend,
    fit_scaled_conformal_multiplier,
    fit_temperature,
    temperature_scale,
)


@dataclass(frozen=True)
class TrainingReport:
    version: str
    horizon_days: int
    brier_score: float
    baseline_brier_score: float
    brier_skill_score: float
    brier_reliability: float
    brier_resolution: float
    brier_uncertainty: float
    ece: float
    classwise_ece: float
    directional_accuracy: float
    interval_coverage: float
    quantile_pinball: float
    baseline_quantile_pinball: float
    interval_score: float
    baseline_interval_score: float
    risk_mae: float
    baseline_risk_mae: float
    sample_count: int
    direction_passed_gate: bool
    scenario_passed_gate: bool
    passed_promotion_gate: bool
    artifact_directory: str


def _device_parameters(device_type: str) -> dict[str, object]:
    if device_type == "gpu":
        return {"device_type": "gpu", "gpu_use_dp": False, "max_bin": 255}
    return {"device_type": "cpu", "max_bin": 255}


def _classifier(seed: int, device_type: str = "cpu") -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=400,
        learning_rate=0.025,
        num_leaves=15,
        max_depth=6,
        min_child_samples=40,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_alpha=0.2,
        reg_lambda=1.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
        **_device_parameters(device_type),
    )


def _regressor(
    seed: int, objective: str = "quantile", alpha: float = 0.5, device_type: str = "cpu"
) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        objective=objective,
        alpha=alpha,
        n_estimators=400,
        learning_rate=0.025,
        num_leaves=15,
        max_depth=6,
        min_child_samples=40,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_alpha=0.2,
        reg_lambda=1.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
        **_device_parameters(device_type),
    )


def _export(model: object, path: Path, feature_count: int) -> None:
    onnx = onnxmltools.convert_lightgbm(
        model,
        initial_types=[("features", FloatTensorType([None, feature_count]))],
        target_opset=15,
        zipmap=False,
    )
    path.write_bytes(onnx.SerializeToString())


def _artifact_sha256(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.onnx")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_runtime_parity_fixture(
    directory: Path,
    manifest: dict[str, object],
    feature_names: tuple[str, ...],
    reference_row: pd.Series,
) -> None:
    """Freeze Python ONNX outputs so the .NET runtime can reject contract drift."""
    values = reference_row.loc[list(feature_names)].to_numpy(dtype=np.float32)
    inputs = {str(manifest["inputName"]): values.reshape(1, -1)}
    direction_predictions: list[np.ndarray] = []
    for relative_path in manifest["directionModels"]:  # type: ignore[union-attr]
        session = ort.InferenceSession(
            (directory / str(relative_path)).as_posix(), providers=["CPUExecutionProvider"]
        )
        output_names = [output.name for output in session.get_outputs()]
        desired = str(manifest["outputName"])
        output_name = desired if desired in output_names else output_names[-1]
        direction_predictions.append(
            np.asarray(session.run([output_name], inputs)[0], dtype=float).reshape(-1)
        )
    probabilities = np.mean(direction_predictions, axis=0)
    probabilities = temperature_scale(
        probabilities.reshape(1, -1), float(manifest["temperature"])
    )[0]
    prior = np.asarray(manifest["classPrior"], dtype=float)
    blend_weight = float(manifest["probabilityBlendWeight"])
    probabilities = blend_weight * probabilities + (1 - blend_weight) * prior

    quantiles = []
    quantile_models = manifest["quantileModels"]
    for name in ("p10", "p50", "p90"):
        path = directory / str(quantile_models[name])  # type: ignore[index]
        session = ort.InferenceSession(path.as_posix(), providers=["CPUExecutionProvider"])
        quantiles.append(float(np.asarray(session.run(None, inputs)[0]).reshape(-1)[0]))
    quantiles.sort()
    scale_feature = str(manifest["conformalScaleFeature"])
    scale_value = float(values[list(feature_names).index(scale_feature)])
    scale = max(scale_value, 0) * np.sqrt(
        float(manifest["horizonDays"]) / max(1, float(manifest["conformalPeriodsPerYear"]))
    )
    adjustment = max(0, float(manifest["conformalMultiplier"])) * max(scale, 1e-4)
    quantiles[0] -= adjustment
    quantiles[2] += adjustment

    risk_session = ort.InferenceSession(
        (directory / str(manifest["riskModel"])).as_posix(), providers=["CPUExecutionProvider"]
    )
    risk = float(np.clip(np.asarray(risk_session.run(None, inputs)[0]).reshape(-1)[0], 0, 1))

    baseline_prior = np.asarray(manifest["baselineClassPrior"], dtype=float)
    baseline = baseline_prior
    coefficients = manifest.get("baselineCoefficients")
    intercept = manifest.get("baselineIntercept")
    if manifest["baselineType"] == "logistic" and coefficients is not None and intercept is not None:
        scores = np.asarray(coefficients, dtype=float).reshape(3, -1) @ values.astype(float)
        scores += np.asarray(intercept, dtype=float)
        exponentials = np.exp(scores - scores.max())
        baseline = exponentials / exponentials.sum()

    fixture = {
        "contractVersion": "v1",
        "featureSetVersion": manifest["featureSetVersion"],
        "features": {name: float(value) for name, value in zip(feature_names, values, strict=True)},
        "expected": {
            "up": float(probabilities[2]),
            "neutral": float(probabilities[1]),
            "down": float(probabilities[0]),
            "p10": quantiles[0],
            "p50": quantiles[1],
            "p90": quantiles[2],
            "riskScore": risk,
            "baselineUp": float(baseline[2]),
            "baselineNeutral": float(baseline[1]),
            "baselineDown": float(baseline[0]),
        },
    }
    (directory / "runtime_parity.json").write_text(
        json.dumps(fixture, indent=2), encoding="utf-8"
    )


def train_and_evaluate(
    samples: pd.DataFrame,
    horizon_days: int,
    output_root: Path,
    device_type: str = "cpu",
    *,
    feature_names: tuple[str, ...] = FEATURE_NAMES,
    feature_set_version: str = FEATURE_SET_VERSION,
    asset_class: str = "crypto",
    version_prefix: str = "probora-crypto-v3",
    allow_production: bool = True,
    risk_baseline_feature: str = "volatility_30d",
    conformal_scale_feature: str = "volatility_90d",
    periods_per_year: int = 365,
) -> TrainingReport:
    frame = samples[samples["horizon_days"] == horizon_days].dropna(
        subset=[*feature_names, "target_direction"]
    )
    if frame.empty:
        raise ValueError(f"No training samples for {horizon_days} days.")
    x = frame.loc[:, feature_names].astype("float32")
    y = frame["target_direction"].astype(int).to_numpy()
    folds = purged_walk_forward_splits(frame, embargo_days=7)
    if len(folds) != 3:
        raise ValueError("Three complete 2023-2025 walk-forward folds are required.")

    fold_metrics = []
    for fold in folds:
        train_x, train_y = x.loc[fold.train], frame.loc[fold.train, "target_direction"].astype(int)
        validation_x, validation_y = (
            x.loc[fold.validation],
            frame.loc[fold.validation, "target_direction"].astype(int).to_numpy(),
        )
        test_x, test_y = x.loc[fold.test], frame.loc[fold.test, "target_direction"].astype(int).to_numpy()
        models = [_classifier(seed, device_type).fit(train_x, train_y) for seed in SEEDS]
        validation_probabilities = np.mean([model.predict_proba(validation_x) for model in models], axis=0)
        temperature = fit_temperature(validation_y, validation_probabilities)
        class_prior = np.bincount(train_y.to_numpy(), minlength=3) / len(train_y)
        validation_prior = np.tile(class_prior, (len(validation_y), 1))
        calibrated_validation = temperature_scale(validation_probabilities, temperature)
        probability_blend_weight = fit_probability_blend(
            validation_y, calibrated_validation, validation_prior
        )
        calibrated_test = temperature_scale(
            np.mean([model.predict_proba(test_x) for model in models], axis=0), temperature
        )
        climatology_probabilities = np.tile(class_prior, (len(test_y), 1))
        probabilities = blend_probabilities(
            calibrated_test, climatology_probabilities, probability_blend_weight
        )
        baseline = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(train_x, train_y)
        validation_logistic_probabilities = baseline.predict_proba(validation_x)
        logistic_probabilities = baseline.predict_proba(test_x)
        selected_baseline = select_direction_baseline(
            validation_y,
            validation_logistic_probabilities,
            validation_prior,
            test_y,
            logistic_probabilities,
            climatology_probabilities,
        )

        validation_quantile_predictions = {}
        test_quantile_predictions = {}
        for name, alpha in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
            model = _regressor(SEEDS[0], alpha=alpha, device_type=device_type).fit(
                train_x, frame.loc[fold.train, "target_return"]
            )
            validation_quantile_predictions[name] = model.predict(validation_x)
            test_quantile_predictions[name] = model.predict(test_x)
        validation_ordered = np.sort(np.column_stack(list(validation_quantile_predictions.values())), axis=1)
        ordered = np.sort(np.column_stack(list(test_quantile_predictions.values())), axis=1)
        validation_target_return = frame.loc[fold.validation, "target_return"].to_numpy()
        validation_scale = validation_x[conformal_scale_feature].to_numpy(float) * np.sqrt(
            horizon_days / periods_per_year
        )
        test_scale = test_x[conformal_scale_feature].to_numpy(float) * np.sqrt(
            horizon_days / periods_per_year
        )
        conformal_multiplier = fit_scaled_conformal_multiplier(
            validation_target_return,
            validation_ordered[:, 0],
            validation_ordered[:, 2],
            validation_scale,
        )
        target_return = frame.loc[fold.test, "target_return"].to_numpy()
        calibrated_lower, calibrated_upper = apply_scaled_conformal(
            ordered[:, 0], ordered[:, 2], test_scale, conformal_multiplier
        )
        training_return = frame.loc[fold.train, "target_return"].to_numpy()
        baseline_quantiles = np.quantile(training_return, [0.1, 0.5, 0.9])
        quantile_pinball = float(
            np.mean(
                [
                    pinball_loss(target_return, ordered[:, index], alpha)
                    for index, alpha in enumerate((0.1, 0.5, 0.9))
                ]
            )
        )
        baseline_quantile_pinball = float(
            np.mean(
                [
                    pinball_loss(
                        target_return,
                        np.full(len(target_return), baseline_quantiles[index]),
                        alpha,
                    )
                    for index, alpha in enumerate((0.1, 0.5, 0.9))
                ]
            )
        )
        scored_interval = interval_score(target_return, calibrated_lower, calibrated_upper)
        baseline_interval_score = interval_score(
            target_return,
            np.full(len(target_return), baseline_quantiles[0]),
            np.full(len(target_return), baseline_quantiles[2]),
        )
        training_risk = 1 - np.exp(-frame.loc[fold.train, "target_volatility"].to_numpy())
        target_risk = 1 - np.exp(-frame.loc[fold.test, "target_volatility"].to_numpy())
        risk_model = _regressor(SEEDS[0], objective="regression", device_type=device_type).fit(
            train_x, training_risk
        )
        risk_prediction = np.clip(risk_model.predict(test_x), 0, 1)
        baseline_risk_prediction = np.clip(1 - np.exp(-test_x[risk_baseline_feature].to_numpy()), 0, 1)
        risk_mae = float(np.mean(np.abs(target_risk - risk_prediction)))
        baseline_risk_mae = float(np.mean(np.abs(target_risk - baseline_risk_prediction)))
        fold_brier = multiclass_brier(test_y, probabilities)
        fold_baseline_brier = selected_baseline.test_brier
        decomposition = multiclass_brier_decomposition(test_y, probabilities)
        fold_metrics.append(
            {
                "name": fold.name,
                "brier": fold_brier,
                "baseline_brier": fold_baseline_brier,
                "brier_skill_score": brier_skill_score(fold_brier, fold_baseline_brier),
                "brier_reliability": decomposition.reliability,
                "brier_resolution": decomposition.resolution,
                "brier_uncertainty": decomposition.uncertainty,
                "brier_decomposed": decomposition.decomposed_brier,
                "brier_binning_gap": decomposition.binning_gap,
                "selected_baseline": selected_baseline.name,
                "baseline_selection_reason": selected_baseline.selection_reason,
                "validation_logistic_brier": selected_baseline.validation_logistic_brier,
                "validation_climatology_brier": (selected_baseline.validation_climatology_brier),
                "validation_uniform_brier": selected_baseline.validation_uniform_brier,
                "logistic_brier": selected_baseline.test_logistic_brier,
                "climatology_brier": selected_baseline.test_climatology_brier,
                "oracle_baseline_brier": selected_baseline.oracle_test_brier,
                "ece": expected_calibration_error(test_y, probabilities),
                "classwise_ece": classwise_expected_calibration_error(test_y, probabilities),
                "accuracy": float((probabilities.argmax(axis=1) == test_y).mean()),
                "raw_coverage": quantile_interval_coverage(target_return, ordered[:, 0], ordered[:, 2]),
                "coverage": quantile_interval_coverage(target_return, calibrated_lower, calibrated_upper),
                "interval_width": float(np.mean(calibrated_upper - calibrated_lower)),
                "interval_score": scored_interval,
                "baseline_interval_score": baseline_interval_score,
                "quantile_pinball": quantile_pinball,
                "baseline_quantile_pinball": baseline_quantile_pinball,
                "conformal_adjustment": 0.0,
                "conformal_mode": "volatility_scaled",
                "conformal_scale_feature": conformal_scale_feature,
                "conformal_multiplier": conformal_multiplier,
                "risk_mae": risk_mae,
                "baseline_risk_mae": baseline_risk_mae,
                "sample_count": len(test_y),
                "temperature": temperature,
                "probability_blend_weight": probability_blend_weight,
            }
        )

    brier = float(np.mean([metric["brier"] for metric in fold_metrics]))
    baseline_brier = float(np.mean([metric["baseline_brier"] for metric in fold_metrics]))
    brier_skill = brier_skill_score(brier, baseline_brier)
    brier_reliability = float(np.mean([metric["brier_reliability"] for metric in fold_metrics]))
    brier_resolution = float(np.mean([metric["brier_resolution"] for metric in fold_metrics]))
    brier_uncertainty = float(np.mean([metric["brier_uncertainty"] for metric in fold_metrics]))
    ece = float(np.mean([metric["ece"] for metric in fold_metrics]))
    classwise_ece = float(np.mean([metric["classwise_ece"] for metric in fold_metrics]))
    accuracy = float(np.mean([metric["accuracy"] for metric in fold_metrics]))
    coverage = float(np.mean([metric["coverage"] for metric in fold_metrics]))
    quantile_pinball = float(np.mean([metric["quantile_pinball"] for metric in fold_metrics]))
    baseline_quantile_pinball = float(
        np.mean([metric["baseline_quantile_pinball"] for metric in fold_metrics])
    )
    scored_interval = float(np.mean([metric["interval_score"] for metric in fold_metrics]))
    baseline_scored_interval = float(np.mean([metric["baseline_interval_score"] for metric in fold_metrics]))
    risk_mae = float(np.mean([metric["risk_mae"] for metric in fold_metrics]))
    baseline_risk_mae = float(np.mean([metric["baseline_risk_mae"] for metric in fold_metrics]))
    fold_wins = sum(metric["brier"] < metric["baseline_brier"] for metric in fold_metrics)
    risk_fold_wins = sum(metric["risk_mae"] < metric["baseline_risk_mae"] for metric in fold_metrics)
    quantile_fold_wins = sum(
        metric["quantile_pinball"] < metric["baseline_quantile_pinball"] for metric in fold_metrics
    )
    interval_fold_wins = sum(
        metric["interval_score"] < metric["baseline_interval_score"] for metric in fold_metrics
    )
    direction_passed = brier <= baseline_brier * 0.95 and fold_wins >= 2 and ece <= 0.05
    scenario_passed = (
        quantile_pinball <= baseline_quantile_pinball * 0.98
        and quantile_fold_wins >= 2
        and scored_interval <= baseline_scored_interval * 0.98
        and interval_fold_wins >= 2
        and 0.75 <= coverage <= 0.85
        and risk_mae <= baseline_risk_mae * 0.95
        and risk_fold_wins >= 2
    )
    # A validated scenario can be published without a directional call. The
    # contract exposes eligibility per output and the UI suppresses direction.
    passed = scenario_passed

    version = f"{version_prefix}-{horizon_days}d-{datetime.now(UTC):%Y%m%d%H%M%S}"
    artifact_directory = output_root / version
    artifact_directory.mkdir(parents=True, exist_ok=False)
    final_models = [_classifier(seed, device_type).fit(x, y) for seed in SEEDS]
    direction_paths = []
    for seed, model in zip(SEEDS, final_models, strict=True):
        name = f"direction-{seed}.onnx"
        _export(model, artifact_directory / name, len(feature_names))
        direction_paths.append(name)

    quantile_paths = {}
    for name, alpha in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
        model = _regressor(SEEDS[0], alpha=alpha, device_type=device_type).fit(x, frame["target_return"])
        path = f"return-{name}.onnx"
        _export(model, artifact_directory / path, len(feature_names))
        quantile_paths[name] = path
    final_risk_target = 1 - np.exp(-frame["target_volatility"].to_numpy())
    risk_model = _regressor(SEEDS[0], objective="regression", device_type=device_type).fit(
        x, final_risk_target
    )
    risk_path = "risk.onnx"
    _export(risk_model, artifact_directory / risk_path, len(feature_names))
    artifact_sha = _artifact_sha256(artifact_directory)

    final_baseline_type = str(fold_metrics[-1]["selected_baseline"])
    baseline_coefficients: list[float] | None = None
    baseline_intercept: list[float] | None = None
    if final_baseline_type == "logistic":
        final_baseline = LogisticRegression(max_iter=2_000, class_weight="balanced").fit(x, y)
        baseline_coefficients = final_baseline.coef_.astype(float).reshape(-1).tolist()
        baseline_intercept = final_baseline.intercept_.astype(float).tolist()

    # Use the most recent validation temperature; it is never fitted on an outer test period.
    manifest = {
        "version": version,
        "assetClass": asset_class,
        "horizonDays": horizon_days,
        "featureSetVersion": feature_set_version,
        "datasetVersion": str(samples.attrs.get("dataset_version", "unversioned")),
        "trainingDevice": device_type,
        "artifactSha256": artifact_sha,
        "temperature": fold_metrics[-1]["temperature"],
        "probabilityBlendWeight": fold_metrics[-1]["probability_blend_weight"],
        "classPrior": (np.bincount(y, minlength=3) / len(y)).tolist(),
        "baselineType": final_baseline_type,
        "baselineClassPrior": (np.bincount(y, minlength=3) / len(y)).tolist(),
        "baselineCoefficients": baseline_coefficients,
        "baselineIntercept": baseline_intercept,
        "runtimeParityContractVersion": "v1",
        # Explanations perturb one feature to its training median. Zero is not a
        # neutral reference for ranks, RSI, breadth, beta or regime variables.
        "featureReference": {name: float(x[name].median()) for name in feature_names},
        "conformalAdjustment": 0,
        "conformalMode": "volatility_scaled",
        "conformalScaleFeature": conformal_scale_feature,
        "conformalMultiplier": fold_metrics[-1]["conformal_multiplier"],
        "conformalPeriodsPerYear": periods_per_year,
        "minimumProbability": 0.55,
        "minimumMargin": 0.15,
        "directionModels": direction_paths,
        "quantileModels": quantile_paths,
        "riskModel": risk_path,
        "inputName": "features",
        "outputName": "probabilities",
        "directionEligible": direction_passed,
        "scenarioEligible": scenario_passed,
        "productionEligible": passed and allow_production,
    }
    (artifact_directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (artifact_directory / "feature_schema.json").write_text(
        json.dumps({"version": feature_set_version, "features": feature_names}, indent=2), encoding="utf-8"
    )
    (artifact_directory / "metrics.json").write_text(json.dumps(fold_metrics, indent=2), encoding="utf-8")

    _write_runtime_parity_fixture(
        artifact_directory,
        manifest,
        feature_names,
        x.iloc[-1],
    )

    # Smoke-load every ONNX artifact before returning it as a valid bundle.
    for onnx_path in artifact_directory.glob("*.onnx"):
        ort.InferenceSession(onnx_path.as_posix(), providers=["CPUExecutionProvider"])

    report = TrainingReport(
        version=version,
        horizon_days=horizon_days,
        brier_score=brier,
        baseline_brier_score=baseline_brier,
        brier_skill_score=brier_skill,
        brier_reliability=brier_reliability,
        brier_resolution=brier_resolution,
        brier_uncertainty=brier_uncertainty,
        ece=ece,
        classwise_ece=classwise_ece,
        directional_accuracy=accuracy,
        interval_coverage=coverage,
        quantile_pinball=quantile_pinball,
        baseline_quantile_pinball=baseline_quantile_pinball,
        interval_score=scored_interval,
        baseline_interval_score=baseline_scored_interval,
        risk_mae=risk_mae,
        baseline_risk_mae=baseline_risk_mae,
        sample_count=int(sum(metric["sample_count"] for metric in fold_metrics)),
        direction_passed_gate=direction_passed,
        scenario_passed_gate=scenario_passed,
        passed_promotion_gate=passed,
        artifact_directory=str(artifact_directory),
    )
    with mlflow.start_run(run_name=version):
        mlflow.log_params(
            {
                "horizon_days": horizon_days,
                "feature_set": feature_set_version,
                "asset_class": asset_class,
                "seeds": str(SEEDS),
            }
        )
        mlflow.log_metrics(
            {key: value for key, value in asdict(report).items() if isinstance(value, (int, float, bool))}
        )
        mlflow.log_artifacts(str(artifact_directory))
    return report
