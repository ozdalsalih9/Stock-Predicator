import numpy as np
import pandas as pd

from probora_ml.evaluation.conditional_prior_ablation import conditional_prior_probabilities


def test_conditional_prior_shrinks_sparse_group_toward_global_rate() -> None:
    fit = pd.DataFrame(
        {
            "snapshot_time": pd.date_range("2020-01-01", periods=6, tz="UTC"),
            "target_direction": [0, 0, 1, 1, 2, 2],
            "regime": ["common", "common", "common", "common", "common", "rare"],
        }
    )
    target = pd.DataFrame({"regime": ["rare", "missing"]})

    probabilities = conditional_prior_probabilities(
        fit, target, ("regime",), shrinkage=100, half_life_days=None
    )

    np.testing.assert_allclose(probabilities.sum(axis=1), 1)
    assert probabilities[0, 2] > probabilities[0, 0]
    np.testing.assert_allclose(probabilities[1], [1 / 3, 1 / 3, 1 / 3])
