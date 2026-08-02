import hashlib
import json

import httpx
import numpy as np
import pandas as pd

from probora_ml.ingestion.twelve_data_equity import (
    _fetch_twelve_symbol,
    _parse_values,
    _symbols_pending_for_download,
    load_identity_quarantine,
    load_membership_universe,
    load_sp500_history_symbol_files,
    require_sp500_pit_coverage,
    split_symbol_batch,
)


def test_parse_twelve_data_values_normalizes_daily_bars() -> None:
    frame = _parse_values(
        "XLY",
        {
            "values": [
                {
                    "datetime": "2026-01-02",
                    "open": "10.0",
                    "high": "11.0",
                    "low": "9.0",
                    "close": "10.5",
                    "volume": "100",
                }
            ]
        },
    )

    assert frame.iloc[0]["symbol"] == "XLY"
    assert str(frame.iloc[0]["open_time"].tzinfo) == "UTC"
    assert np.isclose(frame.iloc[0]["close"], 10.5)


def test_parse_twelve_data_values_rejects_provider_error() -> None:
    try:
        _parse_values("XLY", {"status": "error", "message": "rate limit"})
    except ValueError as error:
        assert "rate limit" in str(error)
    else:
        raise AssertionError("Provider errors must fail closed.")


def test_membership_universe_is_unique_and_batches_cover_it_once(tmp_path) -> None:
    path = tmp_path / "membership.csv"
    pd.DataFrame(
        {
            "date": ["2012-01-01", "2013-01-02", "2014-01-02"],
            "tickers": ["OLD", "A,B,C", "B,C,D"],
        }
    ).to_csv(path, index=False)

    membership, universe = load_membership_universe(path)
    first = split_symbol_batch(universe, 1)
    second = split_symbol_batch(universe, 2)

    assert len(membership) == 2
    assert universe == ("A", "B", "C", "D")
    assert set(first).isdisjoint(second)
    assert tuple(sorted((*first, *second))) == universe


def test_resume_skips_successes_and_failures_unless_retry_is_explicit(tmp_path) -> None:
    completed = tmp_path / "symbols" / "A.parquet"
    completed.parent.mkdir()
    completed.touch()
    state: dict[str, object] = {
        "A": {"status": "succeeded", "file": "symbols/A.parquet"},
        "B": {"status": "failed", "error": "not found"},
    }

    assert _symbols_pending_for_download(("A", "B", "C"), state, tmp_path, False) == ["C"]
    assert _symbols_pending_for_download(("A", "B", "C"), state, tmp_path, True) == ["B", "C"]


def test_v43_coverage_gate_fails_closed_and_accepts_ready_report(tmp_path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            {
                "coverage_ready": False,
                "minimum_daily_coverage": 0.94,
                "membership_freshness_days": 10,
            }
        ),
        encoding="utf-8",
    )
    try:
        require_sp500_pit_coverage(path)
    except ValueError as error:
        assert ">=95%" in str(error)
    else:
        raise AssertionError("V4.3 must fail closed below 95% coverage.")

    path.write_text(
        json.dumps(
            {
                "coverage_ready": True,
                "identity_quarantine_applied": True,
                "coverage_start_date": "2020-01-28",
                "coverage_end_date": "2026-05-28",
            }
        ),
        encoding="utf-8",
    )
    assert require_sp500_pit_coverage(path)["coverage_ready"] is True


def test_identity_quarantine_is_explicit_and_canonical(tmp_path) -> None:
    path = tmp_path / "quarantine.csv"
    pd.DataFrame({"symbol": ["brk.b", " fb "]}).to_csv(path, index=False)

    assert load_identity_quarantine(path) == {"BRK-B", "FB"}


def test_v43_coverage_contract_rejects_changed_membership(tmp_path) -> None:
    membership = tmp_path / "membership.csv"
    membership.write_text("date,tickers\n2020-01-01,A\n", encoding="utf-8")
    membership_hash = hashlib.sha256(membership.read_bytes()).hexdigest()
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(
            {
                "coverage_ready": True,
                "identity_quarantine_applied": True,
                "coverage_start_date": "2020-01-28",
                "coverage_end_date": "2026-05-28",
                "membership_sha256": membership_hash,
            }
        ),
        encoding="utf-8",
    )

    assert require_sp500_pit_coverage(report, membership)["coverage_ready"] is True
    membership.write_text("date,tickers\n2020-01-01,B\n", encoding="utf-8")
    try:
        require_sp500_pit_coverage(report, membership)
    except ValueError as error:
        assert "no longer matches" in str(error)
    else:
        raise AssertionError("Changed membership must invalidate the audited V4.3 contract.")


def test_delisted_resolution_retries_with_catalog_exchange() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/stocks":
            return httpx.Response(
                200,
                json={"data": [{"symbol": "ATVI", "exchange": "NASDAQ"}]},
            )
        if request.url.params.get("exchange") == "NASDAQ":
            return httpx.Response(
                200,
                json={
                    "values": [
                        {
                            "datetime": "2023-10-12",
                            "open": "94.0",
                            "high": "95.0",
                            "low": "93.5",
                            "close": "94.5",
                            "volume": "1000",
                        }
                    ]
                },
            )
        return httpx.Response(404, text="not found")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        frame, _ = _fetch_twelve_symbol(client, "ATVI", "2012-01-01", "2026-07-18", 0, True)

    assert len(frame) == 1
    assert [request.url.path for request in requests] == ["/time_series", "/stocks", "/time_series"]


def test_pre_resolved_exchange_avoids_repeated_catalog_call() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "values": [
                    {
                        "datetime": "2023-10-12",
                        "open": "94.0",
                        "high": "95.0",
                        "low": "93.5",
                        "close": "94.5",
                        "volume": "1000",
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        frame, _ = _fetch_twelve_symbol(
            client,
            "ATVI",
            "2012-01-01",
            "2026-07-18",
            0,
            True,
            "NASDAQ",
        )

    assert len(frame) == 1
    assert len(requests) == 1
    assert requests[0].url.params.get("exchange") == "NASDAQ"


def test_history_loader_uses_secondary_provider_only_for_missing_symbols(tmp_path) -> None:
    primary_file = tmp_path / "symbols" / "A.parquet"
    secondary_a = tmp_path / "tiingo-symbols" / "A.parquet"
    secondary_b = tmp_path / "tiingo-symbols" / "B.parquet"
    primary_file.parent.mkdir()
    secondary_a.parent.mkdir()
    primary_file.touch()
    secondary_a.touch()
    secondary_b.touch()
    (tmp_path / "bootstrap-state.json").write_text(
        json.dumps({"symbols": {"A": {"status": "succeeded", "file": "symbols/A.parquet"}}}),
        encoding="utf-8",
    )
    (tmp_path / "tiingo-bootstrap-state.json").write_text(
        json.dumps(
            {
                "symbols": {
                    "A": {"status": "succeeded", "file": "tiingo-symbols/A.parquet"},
                    "B": {"status": "succeeded", "file": "tiingo-symbols/B.parquet"},
                }
            }
        ),
        encoding="utf-8",
    )

    selected = load_sp500_history_symbol_files(tmp_path)

    assert selected == {"A": primary_file, "B": secondary_b}
