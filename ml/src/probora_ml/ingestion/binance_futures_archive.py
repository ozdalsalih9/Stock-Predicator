from __future__ import annotations

import hashlib
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

from probora_ml.ingestion.binance_archive import normalize_unix_timestamp, verify_checksum

ARCHIVE_ORIGIN = "https://data.binance.vision"
S3_LIST_ENDPOINT = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
)
FuturesDataType = Literal["fundingRate", "premiumIndexKlines", "klines", "metrics"]


@dataclass(frozen=True)
class FuturesDownloadResult:
    archive_path: Path
    parquet_path: Path
    sha256: str
    row_count: int
    data_type: FuturesDataType


def _read_single_csv(payload: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError("Binance futures archive must contain exactly one CSV file.")
        with archive.open(csv_names[0]) as csv_file:
            return csv_file.read()


def _parse_kline(payload: bytes, symbol: str, data_type: FuturesDataType) -> pd.DataFrame:
    csv_payload = _read_single_csv(payload)
    first_line = csv_payload.splitlines()[0].decode("utf-8")
    has_header = first_line.startswith("open_time,")
    frame = pd.read_csv(
        io.BytesIO(csv_payload),
        names=KLINE_COLUMNS,
        header=0 if has_header else None,
    )
    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    frame["trade_count"] = pd.to_numeric(frame["trade_count"], errors="raise").astype("int64")
    frame["open_time"] = frame["open_time"].map(lambda value: normalize_unix_timestamp(int(value)))
    frame["close_time"] = frame["close_time"].map(lambda value: normalize_unix_timestamp(int(value)))
    frame["asset_id"] = symbol
    frame["data_type"] = data_type
    frame["available_at"] = frame["close_time"]
    return frame.drop(columns=["ignore"])


def _parse_funding(payload: bytes, symbol: str) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(_read_single_csv(payload)))
    required = {"calc_time", "last_funding_rate"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Funding archive is missing columns: {sorted(required - set(frame.columns))}")
    frame["calc_time"] = frame["calc_time"].map(lambda value: normalize_unix_timestamp(int(value)))
    frame["last_funding_rate"] = pd.to_numeric(frame["last_funding_rate"], errors="raise")
    frame["asset_id"] = symbol
    frame["data_type"] = "fundingRate"
    frame["available_at"] = frame["calc_time"]
    return frame


def _parse_metrics(payload: bytes, symbol: str) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(_read_single_csv(payload)))
    required = {
        "create_time",
        "sum_open_interest",
        "sum_open_interest_value",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    }
    if not required.issubset(frame.columns):
        raise ValueError(f"Metrics archive is missing columns: {sorted(required - set(frame.columns))}")
    frame["create_time"] = pd.to_datetime(frame["create_time"], utc=True)
    for name in required - {"create_time"}:
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    frame["asset_id"] = symbol
    frame["data_type"] = "metrics"
    frame["available_at"] = frame["create_time"]
    return frame


def parse_futures_archive(
    payload: bytes, symbol: str, data_type: FuturesDataType
) -> pd.DataFrame:
    if data_type == "fundingRate":
        return _parse_funding(payload, symbol)
    if data_type in {"premiumIndexKlines", "klines"}:
        return _parse_kline(payload, symbol, data_type)
    if data_type == "metrics":
        return _parse_metrics(payload, symbol)
    raise ValueError(f"Unsupported futures data type: {data_type}")


def monthly_archive_key(
    symbol: str, data_type: FuturesDataType, year: int, month: int, interval: str = "1h"
) -> str:
    file_name = f"{symbol}-{year:04d}-{month:02d}.zip"
    if data_type in {"premiumIndexKlines", "klines"}:
        file_name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
        return f"data/futures/um/monthly/{data_type}/{symbol}/{interval}/{file_name}"
    if data_type == "fundingRate":
        file_name = f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
    return f"data/futures/um/monthly/{data_type}/{symbol}/{file_name}"


def list_daily_metrics_keys(
    symbol: str,
    start: date,
    end: date,
    client: httpx.Client,
) -> list[str]:
    prefix = f"data/futures/um/daily/metrics/{symbol}/"
    marker = ""
    keys: list[str] = []
    pattern = re.compile(rf"{re.escape(symbol)}-metrics-(\d{{4}}-\d{{2}}-\d{{2}})\.zip$")
    while True:
        response = client.get(
            S3_LIST_ENDPOINT,
            params={"prefix": prefix, "marker": marker, "max-keys": 1000},
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        page_keys = [node.text or "" for node in root.findall("s3:Contents/s3:Key", namespace)]
        for key in page_keys:
            match = pattern.search(key)
            if match and start <= date.fromisoformat(match.group(1)) <= end:
                keys.append(key)
        truncated = (root.findtext("s3:IsTruncated", default="false", namespaces=namespace)).lower()
        if truncated != "true" or not page_keys:
            break
        marker = page_keys[-1]
    return sorted(keys)


def _cached_result(
    key: str,
    data_type: FuturesDataType,
    raw_root: Path,
    processed_root: Path,
) -> FuturesDownloadResult | None:
    archive_path = raw_root / key.removeprefix("data/")
    parquet_path = (processed_root / key.removeprefix("data/")).with_suffix(".parquet")
    if not archive_path.exists() or not parquet_path.exists():
        return None
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    metadata = pd.read_parquet(parquet_path, columns=["source_checksum"])
    stored = metadata["source_checksum"].dropna().unique()
    if len(stored) != 1 or stored[0] != checksum:
        raise ValueError(f"Cached futures archive and parquet checksum differ: {archive_path}")
    return FuturesDownloadResult(archive_path, parquet_path, checksum, len(metadata), data_type)


def download_futures_archive(
    key: str,
    symbol: str,
    data_type: FuturesDataType,
    raw_root: Path,
    processed_root: Path,
    client: httpx.Client,
    use_cache: bool = True,
) -> FuturesDownloadResult:
    if use_cache:
        cached = _cached_result(key, data_type, raw_root, processed_root)
        if cached is not None:
            return cached
    response = client.get(f"{ARCHIVE_ORIGIN}/{key}")
    response.raise_for_status()
    checksum_response = client.get(f"{ARCHIVE_ORIGIN}/{key}.CHECKSUM")
    checksum_response.raise_for_status()
    checksum = verify_checksum(response.content, checksum_response.text)
    frame = parse_futures_archive(response.content, symbol, data_type)
    frame["source_checksum"] = checksum
    frame["source"] = "binance_futures_archive"

    archive_path = raw_root / key.removeprefix("data/")
    parquet_path = (processed_root / key.removeprefix("data/")).with_suffix(".parquet")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists() and hashlib.sha256(archive_path.read_bytes()).hexdigest() != checksum:
        raise FileExistsError(f"Immutable futures archive changed: {archive_path}")
    if not archive_path.exists():
        archive_path.write_bytes(response.content)
    frame.to_parquet(parquet_path, index=False, compression="zstd")
    return FuturesDownloadResult(archive_path, parquet_path, checksum, len(frame), data_type)


def previous_month_end(now: datetime | None = None) -> date:
    current = (now or datetime.now(UTC)).date().replace(day=1)
    return (pd.Timestamp(current) - pd.Timedelta(days=1)).date()
