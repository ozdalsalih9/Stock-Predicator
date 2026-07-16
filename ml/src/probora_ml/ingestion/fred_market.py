from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_MARKET_SERIES = {
    "VIXCLS": "vix",
    "DGS2": "treasury_2y",
    "DGS10": "treasury_10y",
    "NFCI": "financial_conditions",
}
FRED_MARKET_FEATURE_NAMES = (
    "vix_level",
    "vix_change_5s",
    "vix_zscore_60s",
    "treasury_10y_level",
    "yield_curve_10y_2y",
    "yield_curve_change_20s",
    "financial_conditions_level",
    "financial_conditions_change_20s",
)


def download_fred_market_data(
    output_root: Path,
    observation_start: str = "2013-01-01",
) -> Path:
    """Download a checksummed current-vintage research snapshot from official FRED CSVs."""
    output_root.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, object]] = {}
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for series_id in FRED_MARKET_SERIES:
            response = client.get(
                FRED_GRAPH_URL,
                params={"id": series_id, "cosd": observation_start},
            )
            response.raise_for_status()
            if not response.text.startswith(f"observation_date,{series_id}"):
                raise ValueError(f"Unexpected FRED response for {series_id}.")
            path = output_root / f"{series_id}.csv"
            path.write_bytes(response.content)
            files[series_id] = {
                "path": path.name,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "bytes": len(response.content),
            }
    manifest = {
        "downloaded_at": datetime.now(UTC).isoformat(),
        "source": FRED_GRAPH_URL,
        "observation_start": observation_start,
        "vintage_policy": "current-vintage-research-only",
        # NFCI is a weekly Friday observation normally released the next
        # Wednesday. Seven calendar days is conservative for every series.
        "availability_lag_days": 7,
        "files": files,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _read_series(path: Path, series_id: str, name: str) -> pd.DataFrame:
    raw = path.read_text(encoding="utf-8")
    frame = pd.read_csv(StringIO(raw))
    if frame.columns.tolist() != ["observation_date", series_id]:
        raise ValueError(f"Unexpected columns in {path.name}.")
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], utc=True)
    frame[name] = pd.to_numeric(frame[series_id], errors="coerce")
    return frame[["observation_date", name]]


def load_fred_market_features(root: Path) -> pd.DataFrame:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("vintage_policy") != "current-vintage-research-only":
        raise ValueError("FRED market snapshot has an unknown vintage policy.")
    combined: pd.DataFrame | None = None
    for series_id, name in FRED_MARKET_SERIES.items():
        path = root / f"{series_id}.csv"
        expected = manifest["files"][series_id]["sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch for {path.name}.")
        series = _read_series(path, series_id, name)
        combined = (
            series
            if combined is None
            else combined.merge(series, on="observation_date", how="outer", validate="one_to_one")
        )
    if combined is None:
        raise ValueError("No FRED market series were loaded.")
    combined = combined.sort_values("observation_date")
    value_names = list(FRED_MARKET_SERIES.values())
    combined[value_names] = combined[value_names].ffill(limit=10)
    combined["vix_level"] = combined["vix"] / 100
    combined["vix_change_5s"] = np.log(combined["vix"] / combined["vix"].shift(5))
    vix_mean = combined["vix"].rolling(60, min_periods=40).mean()
    vix_std = combined["vix"].rolling(60, min_periods=40).std().replace(0, np.nan)
    combined["vix_zscore_60s"] = (combined["vix"] - vix_mean) / vix_std
    combined["treasury_10y_level"] = combined["treasury_10y"] / 100
    combined["yield_curve_10y_2y"] = (
        combined["treasury_10y"] - combined["treasury_2y"]
    ) / 100
    combined["yield_curve_change_20s"] = combined["yield_curve_10y_2y"].diff(20)
    combined["financial_conditions_level"] = combined["financial_conditions"]
    combined["financial_conditions_change_20s"] = combined[
        "financial_conditions_level"
    ].diff(20)
    combined["available_at"] = combined["observation_date"] + pd.Timedelta(
        days=int(manifest["availability_lag_days"])
    )
    return combined[["observation_date", "available_at", *FRED_MARKET_FEATURE_NAMES]].dropna()


def attach_fred_market_features(samples: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    """Backward as-of join; every feature row must already be available at snapshot time."""
    left = samples.copy()
    left["snapshot_time"] = pd.to_datetime(left["snapshot_time"], utc=True)
    left["_original_order"] = np.arange(len(left))
    right = macro.sort_values("available_at").copy()
    merged = pd.merge_asof(
        left.sort_values("snapshot_time"),
        right,
        left_on="snapshot_time",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    invalid = merged["available_at"] > merged["snapshot_time"]
    if invalid.any():
        raise ValueError("FRED as-of join used a future observation.")
    return merged.sort_values("_original_order").drop(columns="_original_order")
