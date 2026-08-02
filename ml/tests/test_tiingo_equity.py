from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import pandas as pd

from probora_ml.ingestion.tiingo_equity import (
    TiingoQuotaExhausted,
    _parse_supported_tickers,
    _reserve_quota,
    normalize_tiingo_symbol,
    parse_tiingo_prices,
    select_recovery_symbols,
)


def _price_csv() -> bytes:
    return (
        b"date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,"
        b"divCash,splitFactor\n"
        b"2026-01-02T00:00:00.000Z,100,102,98,99,1000,50,51,49,49.5,2000,0.25,2\n"
        b"2026-04-02T00:00:00.000Z,103,104,101,102,1200,51.5,52,50.5,51,2400,0,1\n"
    )


def _catalog_zip() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "supported_tickers.csv",
            "ticker,exchange,assetType,priceCurrency,startDate,endDate\n"
            "BF-B,NYSE,Stock,USD,1984-09-07,2026-07-30\n"
            "ABC,NYSE,Stock,USD,,\n"
            "EURUSD,FX,Forex,USD,2010-01-01,2026-07-30\n",
        )
    return stream.getvalue()


def test_tiingo_parser_uses_adjusted_prices_and_dst_aware_cutoffs() -> None:
    frame = parse_tiingo_prices(
        "BF.B",
        "BF-B",
        _price_csv(),
        ingested_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert frame["symbol"].tolist() == ["BF.B", "BF.B"]
    assert frame["provider_symbol"].tolist() == ["BF-B", "BF-B"]
    assert frame["close"].tolist() == [50.0, 51.5]
    assert frame["raw_close"].tolist() == [100, 103]
    assert frame["available_at"].dt.strftime("%Y-%m-%dT%H:%MZ").tolist() == [
        "2026-01-03T01:00Z",
        "2026-04-03T00:00Z",
    ]


def test_catalog_and_recovery_selection_avoid_unsupported_requests() -> None:
    catalog = _parse_supported_tickers(_catalog_zip())
    primary = {
        "symbols": {
            "BF.B": {"status": "failed"},
            "ABC": {"status": "failed"},
            "AAPL": {"status": "succeeded"},
        }
    }

    selected = select_recovery_symbols(primary, catalog)

    assert normalize_tiingo_symbol("BF.B") == "BF-B"
    assert selected == (("BF-B", "BF-B"),)


def test_quota_guard_fails_before_crossing_safety_limit() -> None:
    state: dict[str, object] = {}
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    _reserve_quota(
        state,
        "AAPL",
        now=now,
        hourly_limit=1,
        daily_limit=10,
        monthly_unique_limit=10,
        monthly_byte_limit=1_000,
    )

    try:
        _reserve_quota(
            state,
            "MSFT",
            now=now,
            hourly_limit=1,
            daily_limit=10,
            monthly_unique_limit=10,
            monthly_byte_limit=1_000,
        )
    except TiingoQuotaExhausted as error:
        assert "hourly" in str(error)
    else:
        raise AssertionError("Quota guard must fail before issuing the second request.")


def test_catalog_parser_keeps_only_usable_usd_stocks_and_etfs() -> None:
    catalog = _parse_supported_tickers(_catalog_zip())

    assert isinstance(catalog, pd.DataFrame)
    assert catalog["ticker"].tolist() == ["BF-B"]
