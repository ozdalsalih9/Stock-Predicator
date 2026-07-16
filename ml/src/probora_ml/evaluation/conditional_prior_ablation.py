from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from probora_ml.evaluation.metrics import (
    brier_skill_score,
    classwise_expected_calibration_error,
    expected_calibration_error,
    multiclass_brier,
)
from probora_ml.evaluation.splits import purged_walk_forward_splits

GROUP_CANDIDATES = (
    (),
    ("market_regime",),
    ("spy_regime",),
    ("spy_regime", "market_regime"),
    ("asset_id", "spy_regime"),
    ("asset_id", "spy_regime", "market_regime"),
)
HALF_LIFE_CANDIDATES = (None, 730, 1_460)
SHRINKAGE_CANDIDATES = (100.0, 500.0, 2_000.0)


def attach_spy_regime(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    spy = output[output["asset_id"] == "SPY"][
        ["snapshot_time", "market_regime"]
    ].drop_duplicates("snapshot_time")
    spy = spy.rename(columns={"market_regime": "spy_regime"})
    return output.merge(spy, on="snapshot_time", how="left", validate="many_to_one")


def conditional_prior_probabilities(
    fit: pd.DataFrame,
    target: pd.DataFrame,
    group_columns: tuple[str, ...],
    shrinkage: float,
    half_life_days: int | None,
) -> np.ndarray:
    if fit.empty or target.empty:
        raise ValueError("Fit and target periods must be non-empty.")
    weighted = fit.copy()
    timestamps = pd.to_datetime(weighted["snapshot_time"], utc=True)
    if half_life_days is None:
        weighted["_weight"] = 1.0
    else:
        ages = (timestamps.max() - timestamps).dt.total_seconds() / 86_400
        weighted["_weight"] = np.exp(-math.log(2) * ages / half_life_days)
    global_counts = (
        weighted.groupby("target_direction")["_weight"].sum().reindex(range(3), fill_value=0).to_numpy(float)
    )
    global_prior = global_counts / global_counts.sum()
    if not group_columns:
        return np.tile(global_prior, (len(target), 1))

    counts = weighted.pivot_table(
        index=list(group_columns),
        columns="target_direction",
        values="_weight",
        aggfunc="sum",
        fill_value=0,
    ).reindex(columns=range(3), fill_value=0)
    totals = counts.sum(axis=1).to_numpy(float)
    smoothed = (counts.to_numpy(float) + shrinkage * global_prior) / (
        totals[:, None] + shrinkage
    )
    probability_columns = [f"_p{index}" for index in range(3)]
    lookup = counts.reset_index()[list(group_columns)].copy()
    lookup[probability_columns] = smoothed
    merged = target.reset_index(drop=True).merge(
        lookup, on=list(group_columns), how="left", validate="many_to_one", sort=False
    )
    probabilities = merged[probability_columns].to_numpy(float)
    missing = np.isnan(probabilities).any(axis=1)
    probabilities[missing] = global_prior
    return probabilities


def _metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    baseline_probabilities: np.ndarray,
) -> dict[str, float]:
    brier = multiclass_brier(labels, probabilities)
    baseline = multiclass_brier(labels, baseline_probabilities)
    return {
        "brier": brier,
        "baseline_brier": baseline,
        "brier_skill_score": brier_skill_score(brier, baseline),
        "ece": expected_calibration_error(labels, probabilities),
        "classwise_ece": classwise_expected_calibration_error(labels, probabilities),
        "accuracy": float((probabilities.argmax(axis=1) == labels).mean()),
    }


def evaluate_conditional_priors(samples: pd.DataFrame, horizon_days: int) -> dict[str, object]:
    frame = attach_spy_regime(samples[samples["horizon_days"] == horizon_days].copy())
    folds = purged_walk_forward_splits(
        frame, embargo_days=7, test_years=(2023, 2024, 2025, 2026)
    )
    fold_rows: list[dict[str, object]] = []
    for fold in folds:
        train = frame.loc[fold.train]
        validation = frame.loc[fold.validation]
        test = frame.loc[fold.test]
        validation_y = validation["target_direction"].to_numpy(int)
        test_y = test["target_direction"].to_numpy(int)
        train_global = conditional_prior_probabilities(train, test, (), 0, None)

        candidates: list[dict[str, object]] = []
        for groups in GROUP_CANDIDATES:
            shrinkages = (0.0,) if not groups else SHRINKAGE_CANDIDATES
            for half_life in HALF_LIFE_CANDIDATES:
                for shrinkage in shrinkages:
                    probabilities = conditional_prior_probabilities(
                        train, validation, groups, shrinkage, half_life
                    )
                    candidates.append(
                        {
                            "groups": list(groups),
                            "half_life_days": half_life,
                            "shrinkage": shrinkage,
                            "validation_brier": multiclass_brier(validation_y, probabilities),
                        }
                    )
        winner = min(candidates, key=lambda row: float(row["validation_brier"]))
        global_validation_brier = min(
            float(row["validation_brier"]) for row in candidates if not row["groups"]
        )
        if global_validation_brier - float(winner["validation_brier"]) < 0.001:
            winner = min(
                (row for row in candidates if not row["groups"]),
                key=lambda row: float(row["validation_brier"]),
            )

        refit = pd.concat([train, validation], ignore_index=True)
        probabilities = conditional_prior_probabilities(
            refit,
            test,
            tuple(str(value) for value in winner["groups"]),
            float(winner["shrinkage"]),
            int(winner["half_life_days"]) if winner["half_life_days"] is not None else None,
        )
        updated_global = conditional_prior_probabilities(
            refit,
            test,
            (),
            0,
            int(winner["half_life_days"]) if winner["half_life_days"] is not None else None,
        )
        fold_rows.append(
            {
                "fold": fold.name,
                "sample_count": len(test),
                "selected": winner,
                "conditional": _metrics(test_y, probabilities, train_global),
                "updated_global": _metrics(test_y, updated_global, train_global),
                "train_global": _metrics(test_y, train_global, train_global),
                "top_validation_candidates": sorted(
                    candidates, key=lambda row: float(row["validation_brier"])
                )[:5],
            }
        )

    def aggregate(rows: list[dict[str, object]], name: str) -> dict[str, float]:
        keys = ("brier", "baseline_brier", "brier_skill_score", "ece", "classwise_ece", "accuracy")
        return {
            key: float(np.mean([float(row[name][key]) for row in rows]))  # type: ignore[index]
            for key in keys
        }

    return {
        "horizon_days": horizon_days,
        "methodology": (
            "Candidate groups and decay are selected on the outer validation year; counts are then "
            "refit on train plus purged validation before the blind test year."
        ),
        "folds": fold_rows,
        "historical_2023_2025": {
            name: aggregate(fold_rows[:3], name)
            for name in ("conditional", "updated_global", "train_global")
        },
        "locked_2026": {
            name: fold_rows[3][name]
            for name in ("conditional", "updated_global", "train_global")
        },
    }


def run_and_write_conditional_prior_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-conditional-prior-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_conditional_priors(samples, horizon_days),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
