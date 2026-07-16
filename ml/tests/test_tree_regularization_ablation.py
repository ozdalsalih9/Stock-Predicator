import pandas as pd

from probora_ml.evaluation.tree_regularization_ablation import recent_training_index


def test_recent_training_index_keeps_only_requested_trailing_window() -> None:
    frame = pd.DataFrame(
        {
            "snapshot_time": pd.to_datetime(
                ["2014-01-01", "2019-12-31", "2020-01-01", "2025-01-01"], utc=True
            )
        }
    )

    selected = recent_training_index(frame, frame.index, 5)

    assert selected.tolist() == [2, 3]
