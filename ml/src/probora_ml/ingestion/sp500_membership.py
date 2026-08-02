from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from probora_ml.ingestion.twelve_data_equity import _atomic_json_write

SOURCE_REPOSITORY = "https://github.com/fja05680/sp500"


def _find_membership_entry(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates = [
        entry
        for entry in archive.infolist()
        if entry.filename.lower().endswith(".csv")
        and "historical components & changes" in entry.filename.lower()
        and "updated" in entry.filename.lower()
    ]
    if not candidates:
        candidates = [
            entry
            for entry in archive.infolist()
            if entry.filename.lower().endswith(".csv")
            and "historical components & changes" in entry.filename.lower()
        ]
    if not candidates:
        raise ValueError("S&P archive does not contain a historical membership CSV.")
    return max(candidates, key=lambda entry: entry.file_size)


def import_sp500_membership_archive(
    archive_path: Path,
    output_path: Path,
    metadata_path: Path,
    license_path: Path,
) -> Path:
    """Freeze and validate the supplied MIT point-in-time membership archive."""
    archive_bytes = archive_path.read_bytes()
    with zipfile.ZipFile(archive_path) as archive:
        membership_entry = _find_membership_entry(archive)
        with archive.open(membership_entry) as stream:
            membership = pd.read_csv(stream)
        license_entries = [
            entry for entry in archive.infolist() if Path(entry.filename).name.upper() == "LICENSE"
        ]
        if len(license_entries) != 1:
            raise ValueError("S&P archive must contain exactly one LICENSE file.")
        license_text = archive.read(license_entries[0]).decode("utf-8-sig")
    if "MIT License" not in license_text:
        raise ValueError("S&P membership archive license is not the expected MIT license.")
    if not {"date", "tickers"}.issubset(membership.columns):
        raise ValueError("S&P membership CSV must contain date and tickers columns.")

    membership["date"] = pd.to_datetime(membership["date"], errors="raise")
    membership = membership.sort_values("date").drop_duplicates("date", keep="last")
    member_counts = (
        membership["tickers"]
        .astype(str)
        .map(lambda value: len({ticker.strip().upper() for ticker in value.split(",") if ticker.strip()}))
    )
    if membership.empty or membership["date"].min() > pd.Timestamp("2000-01-01"):
        raise ValueError("S&P membership archive does not provide the expected long history.")
    if member_counts.min() < 450 or member_counts.max() > 550:
        raise ValueError("S&P membership archive contains implausible constituent counts.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    membership.assign(date=membership["date"].dt.date).to_csv(output_path, index=False)
    license_path.write_text(license_text, encoding="utf-8")
    symbols = {
        ticker.strip().upper()
        for value in membership["tickers"].astype(str)
        for ticker in value.split(",")
        if ticker.strip()
    }
    metadata = {
        "version": 1,
        "imported_at": datetime.now(UTC).isoformat(),
        "source_repository": SOURCE_REPOSITORY,
        "source_archive": str(archive_path),
        "source_archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "source_entry": membership_entry.filename,
        "source_entry_crc32": f"{membership_entry.CRC:08x}",
        "license": "MIT",
        "license_sha256": hashlib.sha256(license_text.encode("utf-8")).hexdigest(),
        "row_count": len(membership),
        "first_date": membership["date"].min().date().isoformat(),
        "last_date": membership["date"].max().date().isoformat(),
        "distinct_ticker_count": len(symbols),
        "minimum_member_count": int(member_counts.min()),
        "maximum_member_count": int(member_counts.max()),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    _atomic_json_write(metadata_path, metadata)
    return output_path


def merge_membership_tail(
    frozen_path: Path,
    current_path: Path,
    output_path: Path,
    metadata_path: Path,
) -> Path:
    """Use the frozen archive through its cutoff and retain only the later audited tail."""
    frozen = pd.read_csv(frozen_path)
    current = pd.read_csv(current_path)
    for frame in (frozen, current):
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frozen_last = frozen["date"].max()
    tail = current[current["date"] > frozen_last]
    merged = pd.concat([frozen, tail], ignore_index=True)
    merged = merged.sort_values("date").drop_duplicates("date", keep="last")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.assign(date=merged["date"].dt.date).to_csv(output_path, index=False)
    metadata = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "frozen_file": str(frozen_path),
        "frozen_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
        "current_tail_file": str(current_path),
        "current_tail_sha256": hashlib.sha256(current_path.read_bytes()).hexdigest(),
        "frozen_last_date": frozen_last.date().isoformat(),
        "tail_rows": len(tail),
        "last_date": merged["date"].max().date().isoformat(),
        "row_count": len(merged),
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    _atomic_json_write(metadata_path, metadata)
    return output_path
