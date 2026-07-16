from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

ARCHIVE_BASE = "https://data.binance.vision/data/spot/monthly/klines"
COLUMNS = (
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


@dataclass(frozen=True)
class DownloadResult:
    archive_path: Path
    parquet_path: Path
    sha256: str
    row_count: int


def existing_download_result(
    symbol: str,
    year: int,
    month: int,
    raw_root: Path,
    processed_root: Path,
    interval: str = "1h",
) -> DownloadResult | None:
    file_name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    archive_path = raw_root / symbol / interval / file_name
    parquet_path = processed_root / symbol / interval / file_name.replace(".zip", ".parquet")
    if not archive_path.exists() or not parquet_path.exists():
        return None
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    metadata = pd.read_parquet(parquet_path, columns=["source_checksum"])
    stored_checksums = metadata["source_checksum"].dropna().unique()
    if len(stored_checksums) != 1 or stored_checksums[0] != checksum:
        raise ValueError(f"Cached archive and parquet checksum differ: {archive_path}")
    return DownloadResult(archive_path, parquet_path, checksum, len(metadata))


def normalize_unix_timestamp(value: int) -> datetime:
    """Normalize Binance millisecond and post-2025 archive microsecond timestamps."""
    milliseconds = value // 1_000 if value >= 100_000_000_000_000 else value
    return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)


def verify_checksum(payload: bytes, checksum_text: str) -> str:
    expected = checksum_text.strip().split()[0].lower()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"Checksum mismatch: expected {expected}, received {actual}.")
    return actual


def parse_archive(payload: bytes, symbol: str, interval: str, source_checksum: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError("Binance archive must contain exactly one CSV file.")
        with archive.open(csv_names[0]) as csv_file:
            frame = pd.read_csv(csv_file, names=COLUMNS, header=None)

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
    frame["interval"] = interval
    frame["source"] = "binance_archive"
    frame["source_checksum"] = source_checksum
    frame["available_at"] = frame["close_time"]
    frame["is_final"] = True
    frame = frame.drop(columns=["ignore"])
    validate_frame(frame)
    return frame


def validate_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("Archive contains no rows.")
    if frame.duplicated(["asset_id", "open_time", "interval", "source"]).any():
        raise ValueError("Archive contains duplicate bars.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Archive contains non-positive OHLC prices.")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ValueError("Archive contains an invalid high price.")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ValueError("Archive contains an invalid low price.")
    if (frame[["volume", "quote_volume", "trade_count"]] < 0).any().any():
        raise ValueError("Archive contains negative activity values.")
    if not frame["open_time"].is_monotonic_increasing:
        raise ValueError("Archive timestamps are not monotonic.")


def download_month(
    symbol: str,
    year: int,
    month: int,
    raw_root: Path,
    processed_root: Path,
    interval: str = "1h",
    client: httpx.Client | None = None,
    use_cache: bool = True,
) -> DownloadResult:
    if use_cache:
        cached = existing_download_result(symbol, year, month, raw_root, processed_root, interval)
        if cached is not None:
            return cached
    file_name = f"{symbol}-{interval}-{year:04d}-{month:02d}.zip"
    url = f"{ARCHIVE_BASE}/{symbol}/{interval}/{file_name}"
    owns_client = client is None
    http = client or httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "Probora/1.0"},
        transport=httpx.HTTPTransport(retries=3),
    )
    try:
        payload_response = http.get(url)
        payload_response.raise_for_status()
        checksum_response = http.get(f"{url}.CHECKSUM")
        checksum_response.raise_for_status()
        checksum = verify_checksum(payload_response.content, checksum_response.text)
    finally:
        if owns_client:
            http.close()

    archive_path = raw_root / symbol / interval / file_name
    parquet_path = processed_root / symbol / interval / file_name.replace(".zip", ".parquet")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists() and hashlib.sha256(archive_path.read_bytes()).hexdigest() != checksum:
        raise FileExistsError(f"Immutable raw archive changed: {archive_path}")
    if not archive_path.exists():
        archive_path.write_bytes(payload_response.content)

    frame = parse_archive(payload_response.content, symbol, interval, checksum)
    frame.to_parquet(parquet_path, index=False, compression="zstd")
    return DownloadResult(archive_path, parquet_path, checksum, len(frame))
