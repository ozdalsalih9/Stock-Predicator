import numpy as np

from probora_ml.evaluation.market_relative_direction_ablation import (
    select_complexity_guarded_candidate,
)


def _probabilities(labels: np.ndarray, confidence: float) -> np.ndarray:
    output = np.full((len(labels), 3), (1 - confidence) / 2)
    output[np.arange(len(labels)), labels] = confidence
    return output


def test_complexity_guard_prefers_material_simple_improvement() -> None:
    labels = np.tile(np.arange(3), 40)
    prior = np.full((len(labels), 3), 1 / 3)
    nominal = _probabilities(labels, 0.55)
    matrix = _probabilities(labels, 0.56)

    selected, rows = select_complexity_guarded_candidate(
        labels,
        {"prior": prior, "nominal": nominal, "matrix": matrix},
        {"prior": 0, "nominal": 2, "matrix": 12},
    )

    assert selected == "nominal"
    assert len(rows) == 3


def test_complexity_guard_falls_back_when_gain_is_too_small() -> None:
    labels = np.tile(np.arange(3), 100)
    prior = np.full((len(labels), 3), 1 / 3)
    almost_prior = prior.copy()
    almost_prior[np.arange(len(labels)), labels] += 0.0001
    almost_prior /= almost_prior.sum(axis=1, keepdims=True)

    selected, _ = select_complexity_guarded_candidate(
        labels,
        {"prior": prior, "nominal": almost_prior},
        {"prior": 0, "nominal": 0},
    )

    assert selected == "prior"
