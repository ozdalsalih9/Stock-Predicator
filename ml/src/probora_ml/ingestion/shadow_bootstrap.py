from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import psycopg

from probora_ml.config import ASSETS

BASE_URL = "https://fapi.binance.com"
REQUIRED_COLUMNS = (
    "funding_rate",
    "premium",
    "futures_quote_volume",
    "futures_taker_buy_ratio",
    "open_interest_value",
    "long_short_ratio",
    "taker_long_short_ratio",
)


@dataclass(frozen=True)
class BootstrapResult:
    archive_written: int
    live_written: int
    target_cutoff: datetime


def _utc_midnight(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"{name} contains an invalid value: {value}")
    return number


class BinanceFuturesHistoryClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=30,
            headers={"User-Agent": "Probora/1.0 shadow-bootstrap"},
        )
        self._last_request = 0.0

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any]) -> list[Any]:
        for attempt in range(1, 6):
            delay = 0.10 - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            response = self._client.get(path, params=params)
            self._last_request = time.monotonic()
            if response.is_success:
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError(f"Unexpected Binance payload for {path}")
                return payload
            if response.status_code not in {418, 429, 500, 502, 503, 504} or attempt == 5:
                response.raise_for_status()
            retry_after = response.headers.get("retry-after")
            time.sleep(float(retry_after) if retry_after else min(30, 2**attempt))
        raise RuntimeError(f"Binance request failed: {path}")

    @staticmethod
    def _ensure_grid(name: str, times: list[int], start_ms: int, step_ms: int, count: int) -> None:
        if len(times) != count:
            raise ValueError(f"{name} contains {len(times)} points; expected {count}")
        expected = [start_ms + index * step_ms for index in range(count)]
        if sorted(times) != expected:
            raise ValueError(f"{name} is not contiguous in the requested UTC day")

    def daily_snapshot(self, symbol: str, cutoff: datetime) -> dict[str, Any]:
        start = cutoff - timedelta(days=1)
        start_ms = _milliseconds(start)
        cutoff_ms = _milliseconds(cutoff)
        common = {"symbol": symbol, "startTime": start_ms, "endTime": cutoff_ms - 1}
        futures = self._get("/fapi/v1/klines", {**common, "interval": "1h", "limit": 24})
        premium = self._get(
            "/fapi/v1/premiumIndexKlines", {**common, "interval": "1h", "limit": 24}
        )
        funding = self._get("/fapi/v1/fundingRate", {**common, "limit": 100})
        metric = {**common, "period": "5m", "limit": 500}
        open_interest = self._get("/futures/data/openInterestHist", metric)
        long_short = self._get("/futures/data/globalLongShortAccountRatio", metric)
        taker = self._get(
            "/futures/data/takerlongshortRatio",
            {**metric, "endTime": cutoff_ms + 300_000 - 1},
        )
        taker = [x for x in taker if start_ms <= int(x["timestamp"]) < cutoff_ms]

        self._ensure_grid("futures klines", [int(x[0]) for x in futures], start_ms, 3_600_000, 24)
        self._ensure_grid("premium klines", [int(x[0]) for x in premium], start_ms, 3_600_000, 24)
        self._ensure_grid(
            "open interest", [int(x["timestamp"]) for x in open_interest], start_ms, 300_000, 288
        )
        self._ensure_grid(
            "long/short ratio", [int(x["timestamp"]) for x in long_short], start_ms, 300_000, 288
        )
        self._ensure_grid(
            "taker ratio", [int(x["timestamp"]) for x in taker], start_ms, 300_000, 288
        )
        if not funding or any(not start_ms <= int(x["fundingTime"]) < cutoff_ms for x in funding):
            raise ValueError("funding is empty or outside the requested UTC day")
        if any(int(x[6]) >= cutoff_ms for x in [*futures, *premium]):
            raise ValueError("Binance returned a candle that was not final at the UTC cutoff")

        volume = sum(_finite(x[5], "futures volume") for x in futures)
        values = {
            "snapshot_time": cutoff,
            "funding_rate": sum(_finite(x["fundingRate"], "funding") for x in funding) / len(funding),
            "premium": _finite(premium[-1][4], "premium"),
            "futures_quote_volume": sum(_finite(x[7], "quote volume") for x in futures),
            "futures_taker_buy_ratio": (
                sum(_finite(x[9], "taker buy volume") for x in futures) / volume
                if volume
                else 0.5
            ),
            "open_interest_value": _finite(
                open_interest[-1]["sumOpenInterestValue"], "open interest", positive=True
            ),
            "long_short_ratio": sum(
                _finite(x["longShortRatio"], "long/short", positive=True) for x in long_short
            )
            / len(long_short),
            "taker_long_short_ratio": sum(
                _finite(x["buySellRatio"], "taker ratio", positive=True) for x in taker
            )
            / len(taker),
            "futures_kline_count": len(futures),
            "premium_kline_count": len(premium),
            "funding_point_count": len(funding),
            "open_interest_point_count": len(open_interest),
            "long_short_point_count": len(long_short),
            "taker_long_short_point_count": len(taker),
            "source_max_event_time": datetime.fromtimestamp(
                max(
                    max(int(x[6]) for x in futures),
                    max(int(x[6]) for x in premium),
                    max(int(x["fundingTime"]) for x in funding),
                    max(int(x["timestamp"]) for x in open_interest),
                    max(int(x["timestamp"]) for x in long_short),
                    max(int(x["timestamp"]) for x in taker),
                )
                / 1000,
                UTC,
            ),
        }
        identity = repr(
            (symbol, cutoff.isoformat(), futures, premium, funding, open_interest, long_short, taker)
        )
        values["source_checksum"] = hashlib.sha256(identity.encode()).hexdigest()
        return values


INSERT_SQL = '''
INSERT INTO probora.derivative_daily_snapshots
("AssetId", "SnapshotTime", "FundingRate", "Premium", "FuturesQuoteVolume",
 "FuturesTakerBuyRatio", "OpenInterestValue", "LongShortRatio", "TakerLongShortRatio",
 "FuturesKlineCount", "PremiumKlineCount", "FundingPointCount", "OpenInterestPointCount",
 "LongShortPointCount", "TakerLongShortPointCount", "IsComplete", "SourceMaxEventTime",
 "AvailableAt", "IngestedAt", "Source", "SourceChecksum")
VALUES
(%(asset_id)s, %(snapshot_time)s, %(funding_rate)s, %(premium)s, %(futures_quote_volume)s,
 %(futures_taker_buy_ratio)s, %(open_interest_value)s, %(long_short_ratio)s,
 %(taker_long_short_ratio)s, %(futures_kline_count)s, %(premium_kline_count)s,
 %(funding_point_count)s, %(open_interest_point_count)s, %(long_short_point_count)s,
 %(taker_long_short_point_count)s, true, %(source_max_event_time)s, %(available_at)s,
 %(ingested_at)s, %(source)s, %(source_checksum)s)
ON CONFLICT ("AssetId", "SnapshotTime", "Source") DO UPDATE SET
 "FundingRate" = EXCLUDED."FundingRate", "Premium" = EXCLUDED."Premium",
 "FuturesQuoteVolume" = EXCLUDED."FuturesQuoteVolume",
 "FuturesTakerBuyRatio" = EXCLUDED."FuturesTakerBuyRatio",
 "OpenInterestValue" = EXCLUDED."OpenInterestValue",
 "LongShortRatio" = EXCLUDED."LongShortRatio",
 "TakerLongShortRatio" = EXCLUDED."TakerLongShortRatio",
 "FuturesKlineCount" = EXCLUDED."FuturesKlineCount",
 "PremiumKlineCount" = EXCLUDED."PremiumKlineCount",
 "FundingPointCount" = EXCLUDED."FundingPointCount",
 "OpenInterestPointCount" = EXCLUDED."OpenInterestPointCount",
 "LongShortPointCount" = EXCLUDED."LongShortPointCount",
 "TakerLongShortPointCount" = EXCLUDED."TakerLongShortPointCount",
 "IsComplete" = true, "SourceMaxEventTime" = EXCLUDED."SourceMaxEventTime",
 "AvailableAt" = EXCLUDED."AvailableAt", "IngestedAt" = EXCLUDED."IngestedAt",
 "SourceChecksum" = EXCLUDED."SourceChecksum";
'''


def _archive_rows(
    processed_root: Path, history_days: int, target: datetime
) -> tuple[list[dict[str, Any]], dict[str, set[datetime]]]:
    frames: dict[str, pd.DataFrame] = {}
    for asset in ASSETS:
        path = processed_root / "consolidated" / f"{asset.symbol}-daily.parquet"
        frame = pd.read_parquet(path)
        frame["snapshot_time"] = pd.to_datetime(frame["snapshot_time"], utc=True)
        frame = frame.dropna(subset=list(REQUIRED_COLUMNS)).sort_values("snapshot_time")
        if frame.empty:
            raise ValueError(f"No complete derivative archive rows for {asset.symbol}")
        frames[asset.symbol] = frame
    start = target - timedelta(days=history_days - 1)
    rows: list[dict[str, Any]] = []
    available: dict[str, set[datetime]] = {}
    for symbol, frame in frames.items():
        selected = frame[(frame["snapshot_time"] >= start) & (frame["snapshot_time"] <= target)]
        available[symbol] = {
            pd.Timestamp(value).to_pydatetime() for value in selected["snapshot_time"]
        }
        for record in selected.to_dict("records"):
            cutoff = pd.Timestamp(record["snapshot_time"]).to_pydatetime()
            identity = "|".join(
                [symbol, cutoff.isoformat(), *(repr(float(record[x])) for x in REQUIRED_COLUMNS)]
            )
            rows.append(
                {
                    **{name: float(record[name]) for name in REQUIRED_COLUMNS},
                    "symbol": symbol,
                    "snapshot_time": cutoff,
                    "futures_kline_count": 24,
                    "premium_kline_count": 24,
                    "funding_point_count": 0,
                    "open_interest_point_count": 0,
                    "long_short_point_count": 0,
                    "taker_long_short_point_count": 0,
                    "source_max_event_time": cutoff - timedelta(milliseconds=1),
                    "available_at": cutoff + timedelta(minutes=5),
                    "source": "binance-usdm-archive",
                    "source_checksum": hashlib.sha256(identity.encode()).hexdigest(),
                }
            )
    return rows, available


def bootstrap_shadow_snapshots(
    processed_root: Path,
    database_url: str,
    history_days: int = 120,
    *,
    now: datetime | None = None,
) -> BootstrapResult:
    target = _utc_midnight(now or datetime.now(UTC))
    archive_rows, archive_cutoffs = _archive_rows(processed_root, history_days, target)
    started_at = datetime.now(UTC)
    run_id = uuid.uuid4()
    live_rows: list[dict[str, Any]] = []
    client = BinanceFuturesHistoryClient()
    try:
        cutoff = target - timedelta(days=history_days - 1)
        while cutoff <= target:
            for asset in ASSETS:
                if cutoff in archive_cutoffs[asset.symbol]:
                    continue
                if cutoff < target - timedelta(days=29):
                    raise ValueError(
                        f"{asset.symbol} is missing {cutoff.isoformat()} outside Binance's "
                        "30-day live history window"
                    )
                row = client.daily_snapshot(asset.symbol, cutoff)
                row.update(symbol=asset.symbol, source="binance-usdm", available_at=datetime.now(UTC))
                live_rows.append(row)
            cutoff += timedelta(days=1)
    finally:
        client.close()

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT "Symbol", "Id" FROM probora.assets WHERE "IsActive"')
            asset_ids = dict(cursor.fetchall())
            all_rows = [*archive_rows, *live_rows]
            ingested_at = datetime.now(UTC)
            for row in all_rows:
                if row["symbol"] not in asset_ids:
                    raise ValueError(f"Active asset is missing from database: {row['symbol']}")
                row.update(asset_id=asset_ids[row["symbol"]], ingested_at=ingested_at)
            cursor.executemany(INSERT_SQL, all_rows)
            cursor.execute(
                '''INSERT INTO probora.ingestion_runs
                   ("Id", "Source", "Dataset", "StartedAt", "CompletedAt", "Status",
                    "RecordsRead", "RecordsWritten", "Error")
                   VALUES (%s, 'binance-usdm', 'derivative_daily_shadow', %s, %s,
                           'succeeded', %s, %s, NULL)''',
                (run_id, started_at, ingested_at, len(all_rows), len(all_rows)),
            )
    return BootstrapResult(len(archive_rows), len(live_rows), target)
