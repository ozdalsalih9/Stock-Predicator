import numpy as np

from probora_ml.evaluation.ablation import bic_like_score, paired_block_bootstrap_interval


def test_bic_like_diagnostic_penalizes_added_features() -> None:
    simple = bic_like_score(log_loss=1.0, feature_count=10, effective_sample_count=100)
    complex_model = bic_like_score(log_loss=1.0, feature_count=20, effective_sample_count=100)

    assert complex_model > simple


def test_paired_block_bootstrap_detects_consistent_improvement() -> None:
    baseline = [np.ones(120), np.ones(120)]
    candidate = [np.full(120, 0.8), np.full(120, 0.8)]

    lower, upper = paired_block_bootstrap_interval(
        baseline, candidate, block_size=30, iterations=100
    )

    assert lower < 0
    assert upper < 0
