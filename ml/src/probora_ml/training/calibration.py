from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression


@dataclass(frozen=True)
class LogProbabilityMatrixCalibrator:
    """Multiclass matrix calibrator in the Dirichlet-calibration form.

    This intentionally uses ordinary L2 regularisation from scikit-learn. It is
    a lightweight ablation candidate, not a claim of implementing ODIR or SMS.
    """

    coefficients: np.ndarray
    intercept: np.ndarray
    regularization_c: float

    @property
    def parameter_count(self) -> int:
        return int(self.coefficients.size + self.intercept.size)

    def predict_proba(self, probabilities: np.ndarray) -> np.ndarray:
        features = np.log(np.clip(probabilities, 1e-12, 1.0))
        scores = features @ self.coefficients.T + self.intercept
        scores -= scores.max(axis=1, keepdims=True)
        exponentials = np.exp(scores)
        return exponentials / exponentials.sum(axis=1, keepdims=True)


def fit_log_probability_matrix_calibrator(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    regularization_c: float = 0.1,
) -> LogProbabilityMatrixCalibrator:
    """Fit q=softmax(W log(p)+b) without touching any evaluation period."""
    labels = y_true.astype(int)
    if len(labels) != len(probabilities) or probabilities.ndim != 2:
        raise ValueError("Labels and probabilities must have matching sample counts.")
    if np.unique(labels).size != probabilities.shape[1]:
        raise ValueError("Calibration data must contain every class.")
    if regularization_c <= 0:
        raise ValueError("Regularization C must be positive.")
    estimator = LogisticRegression(
        C=regularization_c,
        solver="lbfgs",
        max_iter=5_000,
        random_state=17,
    ).fit(np.log(np.clip(probabilities, 1e-12, 1.0)), labels)
    return LogProbabilityMatrixCalibrator(
        coefficients=estimator.coef_.astype(float),
        intercept=estimator.intercept_.astype(float),
        regularization_c=float(regularization_c),
    )


def temperature_scale(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(probabilities, 1e-12, 1.0)) / max(temperature, 0.01)
    logits -= logits.max(axis=1, keepdims=True)
    exponentials = np.exp(logits)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def fit_temperature(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    # Search on a log scale so severely over-confident financial models are not
    # artificially pinned to a small upper bound.
    candidates = np.geomspace(0.25, 10.0, 321)
    losses = []
    for candidate in candidates:
        scaled = temperature_scale(probabilities, float(candidate))
        losses.append(
            float(-np.log(np.clip(scaled[np.arange(len(y_true)), y_true.astype(int)], 1e-12, 1)).mean())
        )
    return float(candidates[int(np.argmin(losses))])


def fit_probability_blend(
    y_true: np.ndarray,
    model_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
) -> float:
    """Fit convex model weight by validation Brier; zero falls back to train prior."""
    if model_probabilities.shape != prior_probabilities.shape or len(y_true) != len(model_probabilities):
        raise ValueError("Labels, model probabilities and priors must have matching shapes.")
    one_hot = np.eye(model_probabilities.shape[1])[y_true.astype(int)]
    direction = model_probabilities - prior_probabilities
    denominator = float(np.sum(direction**2))
    if denominator <= 1e-15:
        return 0.0
    weight = float(np.sum((one_hot - prior_probabilities) * direction) / denominator)
    return float(np.clip(weight, 0, 1))


def blend_probabilities(
    model_probabilities: np.ndarray,
    prior_probabilities: np.ndarray,
    model_weight: float,
) -> np.ndarray:
    if model_probabilities.shape != prior_probabilities.shape:
        raise ValueError("Model probabilities and priors must have matching shapes.")
    weight = float(np.clip(model_weight, 0, 1))
    return weight * model_probabilities + (1 - weight) * prior_probabilities


def conformal_interval_adjustment(
    target: np.ndarray, lower: np.ndarray, upper: np.ndarray, coverage: float = 0.8
) -> float:
    if not 0 < coverage < 1:
        raise ValueError("Coverage must be between zero and one.")
    if len(target) == 0 or len(target) != len(lower) or len(target) != len(upper):
        raise ValueError("Target and interval arrays must have the same non-zero length.")
    scores = np.maximum(lower - target, target - upper)
    quantile_level = min(1.0, np.ceil((len(scores) + 1) * coverage) / len(scores))
    # In production we use conformalization as a safety layer: it may widen a
    # raw interval but never narrow one under a later market regime.
    return max(0.0, float(np.quantile(scores, quantile_level, method="higher")))


def fit_scaled_conformal_multiplier(
    target: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    scale: np.ndarray,
    coverage: float = 0.8,
) -> float:
    """Fit a dimensionless conformal expansion against point-in-time scale."""
    if not 0 < coverage < 1:
        raise ValueError("Coverage must be between zero and one.")
    if not (len(target) == len(lower) == len(upper) == len(scale)) or len(target) == 0:
        raise ValueError("Target, bounds and scale must have the same non-zero length.")
    safe_scale = np.maximum(np.asarray(scale, dtype=float), 1e-4)
    scores = np.maximum(lower - target, target - upper) / safe_scale
    quantile_level = min(1.0, np.ceil((len(scores) + 1) * coverage) / len(scores))
    return max(0.0, float(np.quantile(scores, quantile_level, method="higher")))


def apply_scaled_conformal(
    lower: np.ndarray,
    upper: np.ndarray,
    scale: np.ndarray,
    multiplier: float,
) -> tuple[np.ndarray, np.ndarray]:
    adjustment = max(0, multiplier) * np.maximum(np.asarray(scale, dtype=float), 1e-4)
    return lower - adjustment, upper + adjustment
