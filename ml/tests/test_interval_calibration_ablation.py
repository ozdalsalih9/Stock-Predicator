import numpy as np

from probora_ml.training.calibration import (
    apply_scaled_conformal,
    fit_scaled_conformal_multiplier,
)


def test_scaled_conformal_applies_larger_adjustment_to_higher_volatility() -> None:
    multiplier = fit_scaled_conformal_multiplier(
        np.array([0.0, 0.4]),
        np.array([-0.1, -0.1]),
        np.array([0.1, 0.1]),
        np.array([0.1, 0.2]),
    )
    lower, upper = apply_scaled_conformal(
        np.array([-0.1, -0.1]),
        np.array([0.1, 0.1]),
        np.array([0.1, 0.2]),
        multiplier,
    )

    assert upper[1] - 0.1 > upper[0] - 0.1
    assert lower[1] < lower[0]
