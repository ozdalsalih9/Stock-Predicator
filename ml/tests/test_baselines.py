import numpy as np

from probora_ml.evaluation.baselines import select_direction_baseline
from probora_ml.evaluation.metrics import multiclass_brier


def test_baseline_choice_is_locked_to_validation_even_when_test_winner_changes() -> None:
    validation_y = np.array([0, 0, 2, 2])
    validation_logistic = np.array(
        [
            [0.8, 0.1, 0.1],
            [0.8, 0.1, 0.1],
            [0.1, 0.1, 0.8],
            [0.1, 0.1, 0.8],
        ]
    )
    validation_prior = np.tile([0.45, 0.10, 0.45], (4, 1))
    test_y = np.array([0, 0])
    test_logistic = np.tile([0.05, 0.05, 0.90], (2, 1))
    test_prior = np.tile([0.90, 0.05, 0.05], (2, 1))

    selected = select_direction_baseline(
        validation_y,
        validation_logistic,
        validation_prior,
        test_y,
        test_logistic,
        test_prior,
    )

    assert selected.name == "logistic"
    np.testing.assert_allclose(selected.probabilities, test_logistic)
    assert selected.test_brier == multiclass_brier(test_y, test_logistic)
    assert selected.oracle_test_brier == multiclass_brier(test_y, test_prior)


def test_climatology_wins_exact_validation_tie_due_to_lower_complexity() -> None:
    labels = np.array([0, 2])
    probabilities = np.tile([0.45, 0.10, 0.45], (2, 1))

    selected = select_direction_baseline(
        labels,
        probabilities,
        probabilities,
        labels,
        probabilities,
        probabilities,
    )

    assert selected.name == "climatology"


def test_logistic_is_rejected_when_it_only_beats_a_worse_than_uniform_prior() -> None:
    labels = np.array([0, 0, 2, 2])
    logistic = np.tile([0.70, 0.20, 0.10], (4, 1))
    prior = np.tile([0.95, 0.04, 0.01], (4, 1))

    selected = select_direction_baseline(
        labels,
        logistic,
        prior,
        labels,
        logistic,
        prior,
    )

    assert selected.validation_logistic_brier < selected.validation_climatology_brier
    assert selected.validation_logistic_brier > selected.validation_uniform_brier
    assert selected.name == "climatology"
    assert selected.selection_reason == "climatology_complexity_guard"
