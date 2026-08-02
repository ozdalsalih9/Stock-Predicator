from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from probora_ml.evaluation.metrics import multiclass_brier

MINIMUM_LOGISTIC_BRIER_GAIN = 0.005


@dataclass(frozen=True)
class SelectedDirectionBaseline:
    name: str
    selection_reason: str
    probabilities: np.ndarray
    validation_logistic_brier: float
    validation_climatology_brier: float
    validation_uniform_brier: float
    test_logistic_brier: float
    test_climatology_brier: float

    @property
    def test_brier(self) -> float:
        return self.test_logistic_brier if self.name == "logistic" else self.test_climatology_brier

    @property
    def oracle_test_brier(self) -> float:
        """Diagnostic only; this value must never drive selection or gates."""
        return min(self.test_logistic_brier, self.test_climatology_brier)


def select_direction_baseline(
    validation_labels: np.ndarray,
    validation_logistic_probabilities: np.ndarray,
    validation_climatology_probabilities: np.ndarray,
    test_labels: np.ndarray,
    test_logistic_probabilities: np.ndarray,
    test_climatology_probabilities: np.ndarray,
) -> SelectedDirectionBaseline:
    """Select a stable baseline on validation, then keep it fixed on test.

    Logistic regression has more degrees of freedom than climatology. It is
    eligible only if it clears an absolute uniform-forecast sanity check and
    improves climatology by a predeclared margin.
    """
    validation_logistic_brier = multiclass_brier(validation_labels, validation_logistic_probabilities)
    validation_climatology_brier = multiclass_brier(validation_labels, validation_climatology_probabilities)
    classes = validation_logistic_probabilities.shape[1]
    validation_uniform_brier = multiclass_brier(
        validation_labels,
        np.full((len(validation_labels), classes), 1 / classes),
    )
    logistic_has_absolute_skill = (
        validation_logistic_brier <= validation_uniform_brier - MINIMUM_LOGISTIC_BRIER_GAIN
    )
    logistic_has_incremental_skill = (
        validation_logistic_brier <= validation_climatology_brier - MINIMUM_LOGISTIC_BRIER_GAIN
    )
    if logistic_has_absolute_skill and logistic_has_incremental_skill:
        name = "logistic"
        selection_reason = "logistic_cleared_uniform_and_climatology"
    else:
        name = "climatology"
        selection_reason = (
            "climatology_complexity_guard"
            if validation_logistic_brier < validation_climatology_brier
            else "climatology_validation_winner"
        )
    test_logistic_brier = multiclass_brier(test_labels, test_logistic_probabilities)
    test_climatology_brier = multiclass_brier(test_labels, test_climatology_probabilities)
    probabilities = test_logistic_probabilities if name == "logistic" else test_climatology_probabilities
    return SelectedDirectionBaseline(
        name=name,
        selection_reason=selection_reason,
        probabilities=probabilities,
        validation_logistic_brier=validation_logistic_brier,
        validation_climatology_brier=validation_climatology_brier,
        validation_uniform_brier=validation_uniform_brier,
        test_logistic_brier=test_logistic_brier,
        test_climatology_brier=test_climatology_brier,
    )
