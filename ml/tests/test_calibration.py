import numpy as np

from probora_ml.training.calibration import (
    blend_probabilities,
    conformal_interval_adjustment,
    fit_log_probability_matrix_calibrator,
    fit_probability_blend,
    fit_temperature,
    temperature_scale,
)


def test_log_probability_matrix_calibrator_returns_simplex_probabilities() -> None:
    labels = np.array([0, 1, 2] * 30)
    probabilities = 0.75 * np.eye(3)[labels] + 0.25 / 3

    calibrator = fit_log_probability_matrix_calibrator(labels, probabilities)
    calibrated = calibrator.predict_proba(probabilities)

    assert calibrated.shape == probabilities.shape
    assert np.isfinite(calibrated).all()
    np.testing.assert_allclose(calibrated.sum(axis=1), 1)
    assert calibrator.parameter_count == 12


def test_probability_blend_falls_back_when_model_has_no_validation_skill() -> None:
    labels = np.array([0, 1, 2] * 20)
    prior = np.tile(np.array([1 / 3, 1 / 3, 1 / 3]), (len(labels), 1))
    wrong = np.roll(np.eye(3)[labels], 1, axis=1) * 0.9 + 0.1 / 3

    weight = fit_probability_blend(labels, wrong, prior)
    blended = blend_probabilities(wrong, prior, weight)

    assert weight == 0
    np.testing.assert_allclose(blended, prior)


def test_temperature_fit_can_correct_severe_overconfidence() -> None:
    labels = np.tile(np.array([0, 1, 2]), 100)
    probabilities = np.tile(np.array([[0.98, 0.01, 0.01]]), (len(labels), 1))

    temperature = fit_temperature(labels, probabilities)
    calibrated = temperature_scale(probabilities, temperature)

    assert temperature > 3.0
    assert calibrated[:, 0].mean() < 0.6


def test_conformal_adjustment_expands_undercovered_interval() -> None:
    target = np.arange(10, dtype=float)
    lower = target - 0.1
    upper = target + 0.1
    target[-2:] += 2.0

    adjustment = conformal_interval_adjustment(target, lower, upper, coverage=0.8)

    assert adjustment > 1.0


def test_conformal_adjustment_never_narrows_interval() -> None:
    target = np.arange(10, dtype=float)
    lower = target - 10
    upper = target + 10

    assert conformal_interval_adjustment(target, lower, upper, coverage=0.8) == 0
