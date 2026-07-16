from datetime import timedelta

import pandas as pd
import pytest

from probora_ml.evaluation.splits import purged_walk_forward_splits
from probora_ml.training.labels import direction_label, neutral_band_threshold


def test_direction_label_uses_volatility_adjusted_threshold() -> None:
    assert direction_label(100, 130, 0.5, 30) == 2
    assert direction_label(100, 70, 0.5, 30) == 0
    assert direction_label(100, 101, 0.5, 30) == 1


def test_neutral_band_is_dynamic_but_bounded() -> None:
    low_volatility = neutral_band_threshold(0.05, 30, 0.08)
    normal_volatility = neutral_band_threshold(0.60, 30, 0.70)
    extreme_volatility = neutral_band_threshold(4.0, 30, 3.0)

    assert low_volatility == pytest.approx(0.5 * 0.20 * (30 / 365) ** 0.5)
    assert low_volatility < normal_volatility < extreme_volatility
    assert extreme_volatility == 0.18


def test_long_term_volatility_stabilizes_neutral_band() -> None:
    short_spike = neutral_band_threshold(1.20, 30, 0.40)
    sustained_spike = neutral_band_threshold(1.20, 30, 1.20)

    assert short_spike < sustained_spike


def test_walk_forward_has_three_purged_outer_folds() -> None:
    timestamps = pd.date_range("2018-01-01", "2025-12-31", freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "snapshot_time": timestamps,
            "label_end_time": timestamps + timedelta(days=90),
            "horizon_days": 90,
        }
    )
    folds = purged_walk_forward_splits(frame)
    assert [fold.name for fold in folds] == ["wf-2023", "wf-2024", "wf-2025"]
    for fold in folds:
        assert (
            frame.loc[fold.train, "snapshot_time"].max() < frame.loc[fold.validation, "snapshot_time"].min()
        )
        assert frame.loc[fold.validation, "snapshot_time"].max() < frame.loc[fold.test, "snapshot_time"].min()
        assert (
            frame.loc[fold.train, "label_end_time"].max() + timedelta(days=7)
            < frame.loc[fold.validation, "snapshot_time"].min()
        )
        assert (
            frame.loc[fold.validation, "label_end_time"].max() + timedelta(days=7)
            < frame.loc[fold.test, "snapshot_time"].min()
        )


def test_30_day_horizon_uses_event_end_instead_of_fixed_90_day_purge() -> None:
    timestamps = pd.date_range("2020-01-01", "2025-12-31", freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "snapshot_time": timestamps,
            "label_end_time": timestamps + timedelta(days=30),
            "horizon_days": 30,
        }
    )

    first = purged_walk_forward_splits(frame)[0]

    latest_train_snapshot = frame.loc[first.train, "snapshot_time"].max()
    validation_start = frame.loc[first.validation, "snapshot_time"].min()
    assert validation_start - latest_train_snapshot < timedelta(days=45)


def test_walk_forward_can_add_a_locked_2026_fold() -> None:
    timestamps = pd.date_range("2018-01-01", "2026-12-31", freq="D", tz="UTC")
    frame = pd.DataFrame(
        {
            "snapshot_time": timestamps,
            "label_end_time": timestamps + timedelta(days=90),
            "horizon_days": 90,
        }
    )

    folds = purged_walk_forward_splits(frame, test_years=(2023, 2024, 2025, 2026))

    assert [fold.name for fold in folds] == ["wf-2023", "wf-2024", "wf-2025", "wf-2026"]
