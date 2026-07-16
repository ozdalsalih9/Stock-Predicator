import pandas as pd

from probora_ml.evaluation.linear_direction_ablation import _inner_masks


def test_inner_masks_purge_overlapping_labels_before_final_training_year() -> None:
    frame = pd.DataFrame(
        {
            "snapshot_time": pd.to_datetime(
                ["2020-01-01", "2021-01-01", "2021-06-01"], utc=True
            ),
            "label_end_time": pd.to_datetime(
                ["2020-12-20", "2021-04-01", "2021-09-01"], utc=True
            ),
        }
    )

    try:
        _inner_masks(frame)
    except ValueError as error:
        assert "complete final training year" in str(error)
