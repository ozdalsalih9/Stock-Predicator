import io
import zipfile

from probora_ml.ingestion.binance_futures_archive import parse_futures_archive


def _zip_csv(name: str, contents: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, contents)
    return output.getvalue()


def test_parses_funding_archive() -> None:
    payload = _zip_csv(
        "BTCUSDT-fundingRate-2024-01.csv",
        "calc_time,funding_interval_hours,last_funding_rate\n1704067200000,8,0.0001\n",
    )

    frame = parse_futures_archive(payload, "BTCUSDT", "fundingRate")

    assert len(frame) == 1
    assert frame.loc[0, "last_funding_rate"] == 0.0001
    assert str(frame.loc[0, "calc_time"]) == "2024-01-01 00:00:00+00:00"


def test_parses_headerless_premium_kline() -> None:
    payload = _zip_csv(
        "BTCUSDT-1h-2020-01.csv",
        "1577836800000,-0.001,-0.0005,-0.002,-0.0015,0,1577840399999,0,60,0,0,0\n",
    )

    frame = parse_futures_archive(payload, "BTCUSDT", "premiumIndexKlines")

    assert len(frame) == 1
    assert frame.loc[0, "close"] == -0.0015


def test_parses_open_interest_metrics() -> None:
    payload = _zip_csv(
        "BTCUSDT-metrics-2024-01-02.csv",
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2024-01-02 00:00:00,BTCUSDT,100,4000000,1.1,1.2,1.05,0.9\n",
    )

    frame = parse_futures_archive(payload, "BTCUSDT", "metrics")

    assert len(frame) == 1
    assert frame.loc[0, "sum_open_interest_value"] == 4_000_000
    assert str(frame.loc[0, "create_time"]) == "2024-01-02 00:00:00+00:00"
