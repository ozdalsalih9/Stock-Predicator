import hashlib
from datetime import UTC, datetime

import pandas as pd
import pytest

from probora_ml.ingestion.binance_archive import (
    existing_download_result,
    normalize_unix_timestamp,
    verify_checksum,
)


@pytest.mark.parametrize("timestamp", [1_735_689_600_000, 1_735_689_600_000_000])
def test_normalize_unix_timestamp_supports_milliseconds_and_microseconds(timestamp: int) -> None:
    assert normalize_unix_timestamp(timestamp) == datetime(2025, 1, 1, tzinfo=UTC)


def test_verify_checksum_rejects_changed_payload() -> None:
    checksum = hashlib.sha256(b"original").hexdigest()
    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify_checksum(b"changed", f"{checksum}  file.zip")


def test_existing_download_result_validates_cached_pair(tmp_path) -> None:
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    archive = raw / "BTCUSDT" / "1h" / "BTCUSDT-1h-2025-01.zip"
    parquet = processed / "BTCUSDT" / "1h" / "BTCUSDT-1h-2025-01.parquet"
    archive.parent.mkdir(parents=True)
    parquet.parent.mkdir(parents=True)
    archive.write_bytes(b"archive")
    checksum = hashlib.sha256(b"archive").hexdigest()
    pd.DataFrame({"source_checksum": [checksum, checksum]}).to_parquet(parquet)

    result = existing_download_result("BTCUSDT", 2025, 1, raw, processed)

    assert result is not None
    assert result.sha256 == checksum
    assert result.row_count == 2
