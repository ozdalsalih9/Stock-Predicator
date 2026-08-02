from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from probora_ml.evaluation.equity_cross_sectional_ablation import (
    evaluate_equity_cross_sectional_features,
)
from probora_ml.evaluation.market_relative_ablation import (
    MARKET_RELATIVE_CONFIGS,
    attach_market_relative_targets,
)
from probora_ml.features.equity_cross_sectional import add_equity_cross_sectional_features
from probora_ml.features.equity_sector_breadth import (
    EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES,
    SECTOR_BREADTH_FEATURE_NAMES,
    SECTOR_PEER_FEATURE_NAMES,
    add_equity_sector_breadth_features,
)

SECTOR_FEATURE_GROUPS = {
    "base_ordinal": (),
    "sector_breadth_ordinal": SECTOR_BREADTH_FEATURE_NAMES,
    "sector_peer_ordinal": SECTOR_PEER_FEATURE_NAMES,
    "sector_combined_ordinal": EQUITY_SECTOR_EXPERIMENT_FEATURE_NAMES,
}


def build_equity_sector_research_dataset(
    samples: pd.DataFrame,
    external_sector_bars: pd.DataFrame,
) -> pd.DataFrame:
    cross_sectional = add_equity_cross_sectional_features(samples)
    sector = add_equity_sector_breadth_features(cross_sectional, external_sector_bars)
    relative = attach_market_relative_targets(sector, MARKET_RELATIVE_CONFIGS["us_equity"])
    relative["feature_set_version"] = "us-equity-daily-v1+sector-breadth-exp1"
    return relative


def write_equity_sector_research_dataset(
    samples: pd.DataFrame,
    external_sector_bars: pd.DataFrame,
    output_path: Path,
) -> Path:
    output = build_equity_sector_research_dataset(samples, external_sector_bars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="zstd")
    return output_path


def run_and_write_equity_sector_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-us-equity-sector-breadth-v42-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_equity_cross_sectional_features(
            samples,
            horizon_days,
            device_type,
            feature_groups=SECTOR_FEATURE_GROUPS,
            methodology_prefix=(
                "Same-cutoff nine-sector ETF breadth and sector-relative features from "
                "split/dividend-adjusted daily bars"
            ),
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
