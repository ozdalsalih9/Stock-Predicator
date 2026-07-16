from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class WalkForwardFold:
    name: str
    train: pd.Index
    validation: pd.Index
    test: pd.Index


def purged_walk_forward_splits(
    frame: pd.DataFrame,
    embargo_days: int = 7,
    test_years: tuple[int, ...] = (2023, 2024, 2025),
) -> list[WalkForwardFold]:
    timestamps = pd.to_datetime(frame["snapshot_time"], utc=True)
    if "label_end_time" in frame:
        label_end = pd.to_datetime(frame["label_end_time"], utc=True)
    elif "horizon_days" in frame:
        label_end = timestamps + pd.to_timedelta(frame["horizon_days"], unit="D")
    else:
        # Backward-compatible conservative fallback for callers without event intervals.
        label_end = timestamps + pd.to_timedelta(90, unit="D")
    folds: list[WalkForwardFold] = []
    for test_year in test_years:
        validation_year = test_year - 1
        validation_start = pd.Timestamp(f"{validation_year}-01-01", tz="UTC")
        test_start = pd.Timestamp(f"{test_year}-01-01", tz="UTC")
        test_end = pd.Timestamp(f"{test_year}-12-31 23:59:59", tz="UTC")
        embargo = pd.to_timedelta(embargo_days, unit="D")
        train_mask = label_end < validation_start - embargo
        validation_mask = (timestamps >= validation_start) & (label_end < test_start - embargo)
        test_mask = (timestamps >= test_start) & (timestamps <= test_end)
        fold = WalkForwardFold(
            f"wf-{test_year}", frame.index[train_mask], frame.index[validation_mask], frame.index[test_mask]
        )
        if not fold.train.empty and not fold.validation.empty and not fold.test.empty:
            folds.append(fold)
    return folds
