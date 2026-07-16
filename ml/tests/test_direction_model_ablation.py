import numpy as np

from probora_ml.evaluation.direction_model_ablation import (
    ordinal_probabilities,
    quantile_direction_probabilities,
)


def test_ordinal_probabilities_project_crossing_thresholds_to_simplex() -> None:
    probabilities = ordinal_probabilities(
        np.array([0.8, 0.3]),
        np.array([0.2, 0.7]),
    )

    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    assert (probabilities >= 0).all()
    np.testing.assert_allclose(probabilities[0], [0.2, 0.6, 0.2])
    assert probabilities[1, 1] == 0


def test_quantile_distribution_probabilities_respect_return_location() -> None:
    quantiles = np.array(
        [
            [-0.05, 0.00, 0.05],
            [0.05, 0.10, 0.15],
            [-0.15, -0.10, -0.05],
        ]
    )
    probabilities = quantile_direction_probabilities(quantiles, np.full(3, 0.03))

    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    assert probabilities[0, 1] == probabilities[0].max()
    assert probabilities[1, 2] == probabilities[1].max()
    assert probabilities[2, 0] == probabilities[2].max()
