import numpy as np
import pandas as pd

from probora_ml.evaluation.crypto_regime_blend_ablation import (
    apply_regime_blend,
    fit_regime_blend,
)
from probora_ml.evaluation.metrics import multiclass_brier


def test_regime_blend_learns_different_weights_for_useful_and_harmful_regimes() -> None:
    labels = np.array([2] * 60 + [0] * 60)
    model = np.vstack(
        [
            np.tile([0.05, 0.05, 0.90], (60, 1)),
            np.tile([0.05, 0.05, 0.90], (60, 1)),
        ]
    )
    prior = np.tile([0.45, 0.10, 0.45], (120, 1))
    regimes = pd.DataFrame({"market_regime": ["trend"] * 60 + ["transition"] * 60})

    fitted = fit_regime_blend(
        labels,
        model,
        prior,
        regimes,
        "market_regime",
        shrinkage=1,
        minimum_group_samples=10,
    )

    assert fitted.group_weights["trend"] > fitted.group_weights["transition"]
    probabilities = apply_regime_blend(fitted, model, prior, regimes)
    assert multiclass_brier(labels, probabilities) < multiclass_brier(labels, prior)


def test_unseen_or_small_regime_falls_back_to_global_weight() -> None:
    labels = np.array([0, 2, 0, 2])
    model = np.tile([0.20, 0.10, 0.70], (4, 1))
    prior = np.tile([0.45, 0.10, 0.45], (4, 1))
    fit_regimes = pd.DataFrame({"market_regime": ["trend", "trend", "rare", "rare"]})
    fitted = fit_regime_blend(
        labels,
        model,
        prior,
        fit_regimes,
        "market_regime",
        shrinkage=10,
        minimum_group_samples=3,
    )
    target_regimes = pd.DataFrame({"market_regime": ["rare", "unseen"]})

    probabilities = apply_regime_blend(fitted, model[:2], prior[:2], target_regimes)
    expected = fitted.global_weight * model[:2] + (1 - fitted.global_weight) * prior[:2]

    np.testing.assert_allclose(probabilities, expected)
