import json

import numpy as np
import pandas as pd

from probora_ml.features.sp500_pit_breadth import (
    SP500_PIT_BREADTH_FEATURE_NAMES,
    add_sp500_pit_breadth_features,
    build_sp500_pit_breadth,
)


def _bars(symbols: tuple[str, ...] = ("A", "B", "C")) -> pd.DataFrame:
    dates = pd.date_range("2025-01-02", periods=80, freq="B", tz="UTC")
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "open_time": date,
                    "close": 100 + symbol_index * 5 + index * (symbol_index + 1),
                }
            )
    return pd.DataFrame(rows)


def test_sp500_breadth_uses_point_in_time_members_and_is_finite() -> None:
    bars = _bars()
    dates = pd.Series(pd.date_range("2025-04-21", periods=3, freq="B", tz="UTC"))
    membership = pd.DataFrame({"date": ["2025-01-01"], "tickers": ["A,B,C"]})

    output = build_sp500_pit_breadth(bars, membership, dates)

    assert len(output) == 3
    assert np.isfinite(output[list(SP500_PIT_BREADTH_FEATURE_NAMES)].to_numpy()).all()
    assert (output["sp500_member_coverage_diagnostic"] == 1).all()


def test_sp500_breadth_fails_closed_below_coverage_threshold() -> None:
    bars = _bars(("A", "B"))
    dates = pd.Series([pd.Timestamp("2025-04-21", tz="UTC")])
    membership = pd.DataFrame({"date": ["2025-01-01"], "tickers": ["A,B,C"]})

    try:
        build_sp500_pit_breadth(bars, membership, dates)
    except ValueError as error:
        assert "66.7%" in str(error)
    else:
        raise AssertionError("Broad breadth must not be built below the 95% gate.")


def test_coverage_contract_filters_dates_and_quarantined_symbols(tmp_path) -> None:
    bars = _bars()
    samples = pd.DataFrame(
        {
            "snapshot_time": pd.to_datetime(
                ["2025-04-18", "2025-04-21", "2025-04-22"], utc=True
            ),
            "dataset_version": ["test"] * 3,
        }
    )
    membership = pd.DataFrame({"date": ["2025-01-01"], "tickers": ["A,B,C"]})
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(
            {
                "coverage_ready": True,
                "identity_quarantine_applied": True,
                "coverage_start_date": "2025-04-21",
                "coverage_end_date": "2025-04-22",
                "identity_quarantined_symbols": [],
            }
        ),
        encoding="utf-8",
    )

    output = add_sp500_pit_breadth_features(samples, bars, membership, report)

    assert output["snapshot_time"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-04-21",
        "2025-04-22",
    ]
