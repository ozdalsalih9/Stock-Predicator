from __future__ import annotations

import json
import zipfile

import pandas as pd

from probora_ml.ingestion.sp500_membership import (
    import_sp500_membership_archive,
    merge_membership_tail,
)


def test_membership_archive_is_frozen_with_license_and_provenance(tmp_path) -> None:
    archive_path = tmp_path / "sp500.zip"
    tickers = ",".join(f"T{index:03d}" for index in range(500))
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "sp500/S&P 500 Historical Components & Changes (Updated).csv",
            f'date,tickers\n1996-01-02,"{tickers}"\n2026-06-30,"{tickers}"\n',
        )
        archive.writestr("sp500/LICENSE", "MIT License\nCopyright test")
    output = tmp_path / "membership.csv"
    metadata = tmp_path / "membership.metadata.json"
    license_path = tmp_path / "membership.LICENSE"

    result = import_sp500_membership_archive(archive_path, output, metadata, license_path)

    manifest = json.loads(metadata.read_text(encoding="utf-8"))
    assert result == output
    assert manifest["first_date"] == "1996-01-02"
    assert manifest["last_date"] == "2026-06-30"
    assert manifest["distinct_ticker_count"] == 500
    assert license_path.read_text(encoding="utf-8").startswith("MIT License")


def test_membership_merge_uses_only_rows_after_frozen_cutoff(tmp_path) -> None:
    frozen = tmp_path / "frozen.csv"
    current = tmp_path / "current.csv"
    output = tmp_path / "audited.csv"
    metadata = tmp_path / "audited.metadata.json"
    pd.DataFrame({"date": ["2026-06-01", "2026-06-30"], "tickers": ["A,B", "A,C"]}).to_csv(
        frozen, index=False
    )
    pd.DataFrame({"date": ["2026-06-15", "2026-07-20"], "tickers": ["OLD", "A,D"]}).to_csv(
        current, index=False
    )

    merge_membership_tail(frozen, current, output, metadata)

    merged = pd.read_csv(output)
    assert merged["date"].tolist() == ["2026-06-01", "2026-06-30", "2026-07-20"]
    assert merged["tickers"].tolist() == ["A,B", "A,C", "A,D"]
