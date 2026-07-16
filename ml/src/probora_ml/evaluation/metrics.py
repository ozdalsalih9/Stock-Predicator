from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import pairwise

import numpy as np


@dataclass(frozen=True)
class BrierDecomposition:
    """Binned multiclass Murphy decomposition.

    The decomposition is calculated one-vs-rest for every class and summed.
    ``decomposed_brier`` is the Brier score of the binned forecasts; the
    ``binning_gap`` makes the approximation to the unbinned score explicit.
    """

    brier: float
    reliability: float
    resolution: float
    uncertainty: float
    decomposed_brier: float
    binning_gap: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def multiclass_brier(y_true: np.ndarray, probabilities: np.ndarray, classes: int = 3) -> float:
    one_hot = np.eye(classes)[y_true.astype(int)]
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


def brier_skill_score(model_brier: float, baseline_brier: float) -> float:
    """Return skill relative to a reference forecast; positive is better."""
    if baseline_brier <= 0:
        raise ValueError("Baseline Brier score must be positive.")
    return float(1 - model_brier / baseline_brier)


def multiclass_brier_decomposition(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    classes: int = 3,
    bins: int = 10,
) -> BrierDecomposition:
    """Estimate multiclass reliability, resolution and uncertainty.

    Uniform bins keep this diagnostic stable and reproducible. Since continuous
    probabilities are grouped, REL - RES + UNC reconstructs the score of the
    binned forecasts, not necessarily the exact unbinned score.
    """
    if bins < 2:
        raise ValueError("At least two bins are required.")
    labels = y_true.astype(int)
    if probabilities.shape != (len(labels), classes):
        raise ValueError("Probabilities must have shape [samples, classes].")
    if len(labels) == 0:
        raise ValueError("At least one prediction is required.")

    one_hot = np.eye(classes)[labels]
    reliability = 0.0
    resolution = 0.0
    uncertainty = 0.0
    for class_index in range(classes):
        forecast = probabilities[:, class_index]
        observed = one_hot[:, class_index]
        base_rate = float(observed.mean())
        uncertainty += base_rate * (1 - base_rate)
        assignments = np.minimum((np.clip(forecast, 0, 1) * bins).astype(int), bins - 1)
        for bin_index in range(bins):
            mask = assignments == bin_index
            if not mask.any():
                continue
            weight = float(mask.mean())
            mean_forecast = float(forecast[mask].mean())
            event_rate = float(observed[mask].mean())
            reliability += weight * (mean_forecast - event_rate) ** 2
            resolution += weight * (event_rate - base_rate) ** 2

    brier = multiclass_brier(labels, probabilities, classes)
    decomposed = reliability - resolution + uncertainty
    return BrierDecomposition(
        brier=brier,
        reliability=float(reliability),
        resolution=float(resolution),
        uncertainty=float(uncertainty),
        decomposed_brier=float(decomposed),
        binning_gap=float(brier - decomposed),
    )


def expected_calibration_error(y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    confidence = probabilities.max(axis=1)
    prediction = probabilities.argmax(axis=1)
    correct = prediction == y_true
    result = 0.0
    edges = np.linspace(0, 1, bins + 1)
    for lower, upper in pairwise(edges):
        mask = (confidence > lower) & (confidence <= upper)
        if mask.any():
            result += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(result)


def classwise_expected_calibration_error(
    y_true: np.ndarray, probabilities: np.ndarray, bins: int = 10
) -> float:
    """Average one-vs-rest ECE so non-winning classes are not ignored."""
    labels = y_true.astype(int)
    one_hot = np.eye(probabilities.shape[1])[labels]
    edges = np.linspace(0, 1, bins + 1)
    class_errors: list[float] = []
    for class_index in range(probabilities.shape[1]):
        forecast = probabilities[:, class_index]
        observed = one_hot[:, class_index]
        assignments = np.minimum((np.clip(forecast, 0, 1) * bins).astype(int), bins - 1)
        error = 0.0
        for bin_index, _ in enumerate(pairwise(edges)):
            mask = assignments == bin_index
            if mask.any():
                error += mask.mean() * abs(observed[mask].mean() - forecast[mask].mean())
        class_errors.append(float(error))
    return float(np.mean(class_errors))


def quantile_interval_coverage(target: np.ndarray, p10: np.ndarray, p90: np.ndarray) -> float:
    return float(np.mean((target >= p10) & (target <= p90)))


def pinball_loss(target: np.ndarray, prediction: np.ndarray, quantile: float) -> float:
    error = target - prediction
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


def interval_score(
    target: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    miscoverage: float = 0.2,
) -> float:
    """Proper score for a central prediction interval; lower is better."""
    if not 0 < miscoverage < 1:
        raise ValueError("Miscoverage must be between zero and one.")
    if len(target) == 0 or len(target) != len(lower) or len(target) != len(upper):
        raise ValueError("Target and interval arrays must have the same non-zero length.")
    if np.any(lower > upper):
        raise ValueError("Lower interval bounds cannot exceed upper bounds.")
    width = upper - lower
    below = (2 / miscoverage) * (lower - target) * (target < lower)
    above = (2 / miscoverage) * (target - upper) * (target > upper)
    return float(np.mean(width + below + above))
