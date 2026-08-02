from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from probora_ml.evaluation.equity_cross_sectional_ablation import (
    evaluate_equity_cross_sectional_features,
)
from probora_ml.evaluation.equity_sector_breadth_ablation import (
    build_equity_sector_research_dataset,
)
from probora_ml.features.equity_sector_breadth import SECTOR_PEER_FEATURE_NAMES
from probora_ml.features.sp500_pit_breadth import (
    SP500_PIT_BREADTH_FEATURE_NAMES,
    add_sp500_pit_breadth_features,
)
from probora_ml.ingestion.twelve_data_equity import require_sp500_pit_coverage

SP500_PIT_FEATURE_GROUPS = {
    "base_ordinal": (),
    "sector_peer_ordinal": SECTOR_PEER_FEATURE_NAMES,
    "sp500_pit_breadth_ordinal": SP500_PIT_BREADTH_FEATURE_NAMES,
    "sector_peer_plus_sp500_pit_ordinal": (
        *SECTOR_PEER_FEATURE_NAMES,
        *SP500_PIT_BREADTH_FEATURE_NAMES,
    ),
}


def write_equity_sp500_breadth_research_dataset(
    samples: pd.DataFrame,
    sector_bars: pd.DataFrame,
    sp500_bars: pd.DataFrame,
    membership: pd.DataFrame,
    coverage_report_path: Path,
    output_path: Path,
    membership_path: Path | None = None,
) -> Path:
    coverage_contract = require_sp500_pit_coverage(
        coverage_report_path,
        membership_path=membership_path,
    )
    sector = build_equity_sector_research_dataset(samples, sector_bars)
    output = add_sp500_pit_breadth_features(
        sector,
        sp500_bars,
        membership,
        coverage_report_path,
    )
    output["feature_set_version"] = "us-equity-daily-v1+sp500-pit-breadth-exp1"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="zstd")
    metadata = {
        "version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_file": str(output_path),
        "dataset_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "coverage_report_file": str(coverage_report_path),
        "coverage_report_sha256": hashlib.sha256(coverage_report_path.read_bytes()).hexdigest(),
        "membership_file": str(membership_path) if membership_path is not None else None,
        "membership_sha256": coverage_contract.get("membership_sha256"),
        "identity_quarantine_sha256": coverage_contract.get("identity_quarantine_sha256"),
        "coverage_start_date": coverage_contract["coverage_start_date"],
        "coverage_end_date": coverage_contract["coverage_end_date"],
        "row_count": len(output),
        "asset_count": int(output["asset_id"].nunique()),
        "horizons": sorted(int(value) for value in output["horizon_days"].unique()),
        "feature_names": list(SP500_PIT_BREADTH_FEATURE_NAMES),
    }
    output_path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    return output_path


def run_and_write_equity_sp500_breadth_ablation(
    samples: pd.DataFrame,
    horizon_days: int,
    device_type: str,
    output_root: Path,
) -> Path:
    report = {
        "version": f"probora-us-equity-sp500-pit-breadth-v43-{datetime.now(UTC):%Y%m%d%H%M%S}",
        "dataset_version": str(samples["dataset_version"].iloc[0]),
        "report": evaluate_equity_cross_sectional_features(
            samples,
            horizon_days,
            device_type,
            feature_groups=SP500_PIT_FEATURE_GROUPS,
            methodology_prefix=(
                "Point-in-time S&P 500 breadth with >=95% constituent price coverage, "
                "compared against the V4.2 sector-peer candidate"
            ),
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['version']}-{horizon_days}d.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
