import numpy as np
import pytest

from probora_ml.evaluation.label_ablation import (
    atr_confirmed_threshold,
    labels_for_thresholds,
)


def test_atr_confirmed_threshold_never_lowers_current_band_and_is_capped() -> None:
    threshold = atr_confirmed_threshold(
        np.array([0.06, 0.10]), np.array([0.02, 1.0]), 90, 0.5
    )

    assert threshold[0] >= 0.06
    assert threshold[1] == pytest.approx(0.18 * np.sqrt(3))


def test_labels_for_thresholds_keep_symmetric_neutral_band() -> None:
    labels = labels_for_thresholds(
        np.array([-0.11, -0.10, 0.00, 0.10, 0.11]), np.full(5, 0.10)
    )

    np.testing.assert_array_equal(labels, [0, 1, 1, 1, 2])
