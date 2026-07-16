import numpy as np

from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    interval_score,
    multiclass_brier,
    multiclass_brier_decomposition,
    quantile_interval_coverage,
)


def test_perfect_probabilities_have_zero_brier_and_ece() -> None:
    labels = np.array([0, 1, 2])
    probabilities = np.eye(3)
    assert multiclass_brier(labels, probabilities) == 0
    assert expected_calibration_error(labels, probabilities) == 0
    assert classwise_expected_calibration_error(labels, probabilities) == 0
    decomposition = multiclass_brier_decomposition(labels, probabilities)
    assert decomposition.reliability == 0
    assert abs(decomposition.resolution - decomposition.uncertainty) < 1e-15
    assert abs(decomposition.decomposed_brier) < 1e-15


def test_climatology_has_zero_skill_and_resolution() -> None:
    labels = np.array([0, 1, 2] * 20)
    probabilities = np.full((len(labels), 3), 1 / 3)
    brier = multiclass_brier(labels, probabilities)
    decomposition = multiclass_brier_decomposition(labels, probabilities)

    assert brier_skill_score(brier, brier) == 0
    assert abs(decomposition.reliability) < 1e-15
    assert abs(decomposition.resolution) < 1e-15
    assert abs(decomposition.uncertainty - 2 / 3) < 1e-15
    assert abs(decomposition.decomposed_brier - brier) < 1e-15


def test_brier_skill_is_positive_only_when_model_beats_baseline() -> None:
    assert brier_skill_score(0.5, 0.6) > 0
    assert brier_skill_score(0.7, 0.6) < 0


def test_interval_coverage() -> None:
    target = np.array([-1.0, 0.0, 1.0, 2.0])
    assert quantile_interval_coverage(target, np.array([-2, -1, 0, 3]), np.array([0, 1, 2, 4])) == 0.75


def test_interval_score_penalizes_misses_more_than_width() -> None:
    target = np.array([0.0, 3.0])
    score = interval_score(target, np.array([-1.0, -1.0]), np.array([1.0, 1.0]))

    assert score == 12.0
