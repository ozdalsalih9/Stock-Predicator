from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd

from probora_ml.ingestion.twelve_data_equity import (
    _atomic_json_write,
    _safe_symbol_file,
    _symbols_pending_for_download,
    canonical_equity_symbol,
    load_membership_universe,
)

TIINGO_DAILY_URL = "https://api.tiingo.com/tiingo/daily"
TIINGO_SUPPORTED_TICKERS_URL = "https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip"
TIINGO_SOURCE = "tiingo-eod-total-return"
NEW_YORK = ZoneInfo("America/New_York")


class TiingoQuotaExhausted(RuntimeError):
    """Raised before a request that would exceed a configured safety budget."""


def _read_api_token(env_path: Path = Path(".env")) -> str:
    token = os.getenv("TIINGO_API_TOKEN", "").strip()
    if token:
        return token
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if raw_line.strip().startswith("TIINGO_API_TOKEN="):
                token = raw_line.split("=", 1)[1].strip().strip("\"'")
                break
    if not token:
        raise ValueError("TIINGO_API_TOKEN is not set in the environment or .env file.")
    return token


def normalize_tiingo_symbol(symbol: str) -> str:
    """Translate share-class punctuation without guessing corporate aliases."""
    return canonical_equity_symbol(symbol)


def parse_tiingo_prices(
    symbol: str,
    provider_symbol: str,
    content: bytes,
    *,
    ingested_at: datetime | None = None,
) -> pd.DataFrame:
    """Normalize Tiingo CSV while retaining raw and adjusted corporate-action fields."""
    try:
        frame = pd.read_csv(io.BytesIO(content))
    except Exception as error:
        raise ValueError(f"Tiingo returned invalid CSV for {symbol}.") from error
    required = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjOpen",
        "adjHigh",
        "adjLow",
        "adjClose",
        "adjVolume",
        "divCash",
        "splitFactor",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Tiingo {symbol} payload is missing: {', '.join(missing)}")
    if frame.empty:
        raise ValueError(f"Tiingo returned no daily values for {symbol}.")

    numeric_columns = sorted(required - {"date"})
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(float)).all():
        raise ValueError(f"Tiingo {symbol} payload contains non-finite market values.")
    session_dates = pd.to_datetime(
        frame["date"].astype(str).str.slice(0, 10),
        format="%Y-%m-%d",
        errors="raise",
    )
    if session_dates.duplicated().any():
        raise ValueError(f"Tiingo {symbol} payload contains duplicate sessions.")

    adjusted = numeric[["adjOpen", "adjHigh", "adjLow", "adjClose"]]
    if (adjusted <= 0).any().any() or (numeric[["volume", "adjVolume"]] < 0).any().any():
        raise ValueError(f"Tiingo {symbol} payload contains invalid prices or volumes.")
    tolerance = 1e-8
    if (
        (numeric["adjLow"] > adjusted[["adjOpen", "adjClose", "adjHigh"]].min(axis=1) + tolerance)
        | (numeric["adjHigh"] + tolerance < adjusted[["adjOpen", "adjClose", "adjLow"]].max(axis=1))
    ).any():
        raise ValueError(f"Tiingo {symbol} payload violates adjusted OHLC bounds.")

    local_cutoffs = session_dates.dt.tz_localize(NEW_YORK) + pd.to_timedelta(20, unit="h")
    captured_at = ingested_at or datetime.now(UTC)
    output = pd.DataFrame(
        {
            "symbol": symbol.upper(),
            "provider_symbol": provider_symbol.upper(),
            "open_time": session_dates.dt.tz_localize(UTC),
            "open": numeric["adjOpen"],
            "high": numeric["adjHigh"],
            "low": numeric["adjLow"],
            "close": numeric["adjClose"],
            "volume": numeric["adjVolume"],
            "raw_open": numeric["open"],
            "raw_high": numeric["high"],
            "raw_low": numeric["low"],
            "raw_close": numeric["close"],
            "raw_volume": numeric["volume"],
            "div_cash": numeric["divCash"],
            "split_factor": numeric["splitFactor"],
            "available_at": local_cutoffs.dt.tz_convert(UTC),
            "ingested_at": pd.Timestamp(captured_at).tz_convert(UTC),
            "source": TIINGO_SOURCE,
        }
    )
    return output.sort_values("open_time").reset_index(drop=True)


def _parse_supported_tickers(content: bytes) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError("Tiingo ticker archive must contain exactly one CSV file.")
            frame = pd.read_csv(archive.open(names[0]))
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("Tiingo supported ticker archive is invalid.") from error
    required = {"ticker", "exchange", "assetType", "priceCurrency", "startDate", "endDate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Tiingo ticker catalog is missing: {', '.join(missing)}")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    usable = frame[
        frame["assetType"].isin(["Stock", "ETF"])
        & frame["priceCurrency"].eq("USD")
        & frame["startDate"].notna()
        & frame["endDate"].notna()
    ].copy()
    return usable.sort_values("ticker").drop_duplicates("ticker", keep="last").reset_index(drop=True)


def download_supported_tickers(
    cache_root: Path,
    *,
    client: httpx.Client | None = None,
) -> tuple[pd.DataFrame, Path, str]:
    """Download the public catalog once per UTC date without sending the API token."""
    cache_root.mkdir(parents=True, exist_ok=True)
    date_key = datetime.now(UTC).date().isoformat().replace("-", "")
    path = cache_root / f"supported-tickers-{date_key}.zip"
    owns_client = client is None
    public_client = client or httpx.Client(timeout=90, headers={"User-Agent": "Probora/1.0"})
    try:
        if not path.exists():
            response = public_client.get(TIINGO_SUPPORTED_TICKERS_URL)
            response.raise_for_status()
            path.write_bytes(response.content)
        content = path.read_bytes()
    finally:
        if owns_client:
            public_client.close()
    checksum = hashlib.sha256(content).hexdigest()
    return _parse_supported_tickers(content), path, checksum


def select_recovery_symbols(
    primary_state: dict[str, Any],
    catalog: pd.DataFrame,
    *,
    explicit_symbols: tuple[str, ...] = (),
    membership_symbols: tuple[str, ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Select only failed primary symbols that Tiingo says have EOD coverage."""
    succeeded = {
        normalize_tiingo_symbol(symbol)
        for symbol, item in primary_state.get("symbols", {}).items()
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }
    if explicit_symbols:
        candidates = {normalize_tiingo_symbol(symbol) for symbol in explicit_symbols if symbol.strip()}
    else:
        candidates = {
            normalize_tiingo_symbol(symbol)
            for symbol, item in primary_state.get("symbols", {}).items()
            if isinstance(item, dict) and item.get("status") == "failed"
        }
        candidates.update(normalize_tiingo_symbol(symbol) for symbol in membership_symbols)
        candidates.difference_update(succeeded)
    supported = set(catalog["ticker"].astype(str))
    selected = [(symbol, symbol) for symbol in sorted(candidates) if symbol in supported]
    return tuple(selected)


def _quota_usage(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    usage = state.setdefault("usage", {})
    eastern = now.astimezone(NEW_YORK)
    hour_bucket = now.astimezone(UTC).strftime("%Y-%m-%dT%H")
    day_bucket = eastern.strftime("%Y-%m-%d")
    month_bucket = eastern.strftime("%Y-%m")
    if usage.get("hour_bucket") != hour_bucket:
        usage["hour_bucket"] = hour_bucket
        usage["hour_requests"] = 0
    if usage.get("day_bucket") != day_bucket:
        usage["day_bucket"] = day_bucket
        usage["day_requests"] = 0
    if usage.get("month_bucket") != month_bucket:
        usage["month_bucket"] = month_bucket
        usage["month_bytes"] = 0
        usage["unique_symbols"] = []
    usage.setdefault("unique_symbols", [])
    usage.setdefault("month_bytes", 0)
    return usage


def _reserve_quota(
    state: dict[str, Any],
    symbol: str,
    *,
    now: datetime,
    hourly_limit: int,
    daily_limit: int,
    monthly_unique_limit: int,
    monthly_byte_limit: int,
) -> None:
    usage = _quota_usage(state, now)
    if int(usage["hour_requests"]) >= hourly_limit:
        raise TiingoQuotaExhausted("Configured hourly Tiingo request safety budget is exhausted.")
    if int(usage["day_requests"]) >= daily_limit:
        raise TiingoQuotaExhausted("Configured daily Tiingo request safety budget is exhausted.")
    if int(usage["month_bytes"]) >= monthly_byte_limit:
        raise TiingoQuotaExhausted("Configured monthly Tiingo bandwidth safety budget is exhausted.")
    unique = set(map(str, usage["unique_symbols"]))
    if symbol not in unique and len(unique) >= monthly_unique_limit:
        raise TiingoQuotaExhausted("Configured monthly Tiingo unique-symbol safety budget is exhausted.")
    unique.add(symbol)
    usage["unique_symbols"] = sorted(unique)
    usage["hour_requests"] = int(usage["hour_requests"]) + 1
    usage["day_requests"] = int(usage["day_requests"]) + 1


def _record_response_bytes(state: dict[str, Any], byte_count: int, now: datetime) -> None:
    usage = _quota_usage(state, now)
    usage["month_bytes"] = int(usage["month_bytes"]) + max(0, byte_count)


def bootstrap_tiingo_sp500_recovery(
    history_root: Path,
    *,
    membership_path: Path | None = None,
    start_date: str = "2012-01-01",
    end_date: str | None = None,
    explicit_symbols: tuple[str, ...] = (),
    maximum_symbols: int | None = None,
    retry_failed: bool = False,
    minimum_request_interval_seconds: float = 80.0,
    hourly_request_limit: int = 45,
    daily_request_limit: int = 900,
    monthly_unique_limit: int = 450,
    monthly_byte_limit: int = 800_000_000,
) -> Path:
    """Recover missing PIT histories without overwriting the primary provider files."""
    if min(hourly_request_limit, daily_request_limit, monthly_unique_limit, monthly_byte_limit) < 1:
        raise ValueError("Tiingo safety budgets must be positive.")
    token = _read_api_token()
    primary_state_path = history_root / "bootstrap-state.json"
    if not primary_state_path.exists():
        raise ValueError(f"Primary S&P bootstrap state does not exist: {primary_state_path}")
    primary_state = json.loads(primary_state_path.read_text(encoding="utf-8"))
    membership_symbols: tuple[str, ...] = ()
    if membership_path is not None:
        _, membership_symbols = load_membership_universe(membership_path)
    catalog, catalog_path, catalog_sha256 = download_supported_tickers(history_root / "tiingo-catalog")
    selected = select_recovery_symbols(
        primary_state,
        catalog,
        explicit_symbols=explicit_symbols,
        membership_symbols=membership_symbols,
    )
    if maximum_symbols is not None:
        selected = selected[:maximum_symbols]

    state_path = history_root / "tiingo-bootstrap-state.json"
    if state_path.exists():
        state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "version": 1,
            "source": "Tiingo EOD /tiingo/daily/{ticker}/prices",
            "license_scope": "Internal/personal non-redistribution; recheck before public use",
            "primary_state_file": str(primary_state_path),
            "primary_state_sha256": hashlib.sha256(primary_state_path.read_bytes()).hexdigest(),
            "membership_file": str(membership_path) if membership_path else None,
            "symbols": {},
            "usage": {},
        }
    state["catalog_file"] = str(catalog_path)
    state["catalog_sha256"] = catalog_sha256
    state["catalog_usable_symbols"] = len(catalog)
    state["candidate_count"] = len(selected)
    if membership_path is not None:
        state["membership_file"] = str(membership_path)
        state["membership_sha256"] = hashlib.sha256(membership_path.read_bytes()).hexdigest()
    symbol_state: dict[str, Any] = state["symbols"]
    canonical = tuple(symbol for symbol, _ in selected)
    pending_symbols = set(
        _symbols_pending_for_download(
            canonical,
            symbol_state,
            history_root,
            retry_failed,
        )
    )
    pending = [(symbol, provider) for symbol, provider in selected if symbol in pending_symbols]
    end = end_date or datetime.now(UTC).date().isoformat()
    symbols_root = history_root / "tiingo-symbols"
    symbols_root.mkdir(parents=True, exist_ok=True)
    state["paused_reason"] = None
    _atomic_json_write(state_path, state)

    with httpx.Client(
        timeout=120,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "text/csv",
            "Content-Type": "application/json",
            "User-Agent": "Probora/1.0",
        },
    ) as client:
        last_request_at: float | None = None
        for symbol, provider_symbol in pending:
            if last_request_at is not None:
                elapsed = time.monotonic() - last_request_at
                if elapsed < minimum_request_interval_seconds:
                    time.sleep(minimum_request_interval_seconds - elapsed)
            started = datetime.now(UTC)
            response: httpx.Response | None = None
            try:
                for attempt in range(3):
                    now = datetime.now(UTC)
                    _reserve_quota(
                        state,
                        provider_symbol,
                        now=now,
                        hourly_limit=hourly_request_limit,
                        daily_limit=daily_request_limit,
                        monthly_unique_limit=monthly_unique_limit,
                        monthly_byte_limit=monthly_byte_limit,
                    )
                    response = client.get(
                        f"{TIINGO_DAILY_URL}/{provider_symbol}/prices",
                        params={
                            "startDate": start_date,
                            "endDate": end,
                            "format": "csv",
                            "resampleFreq": "daily",
                        },
                    )
                    last_request_at = time.monotonic()
                    _record_response_bytes(state, len(response.content), datetime.now(UTC))
                    state["updated_at"] = datetime.now(UTC).isoformat()
                    _atomic_json_write(state_path, state)
                    if response.status_code != 429 and response.status_code < 500:
                        break
                    if attempt < 2:
                        retry_after = float(response.headers.get("Retry-After", 60))
                        time.sleep(max(retry_after, minimum_request_interval_seconds))
                assert response is not None
                response.raise_for_status()
                frame = parse_tiingo_prices(symbol, provider_symbol, response.content)
                file_name = _safe_symbol_file(symbol)
                relative_path = Path("tiingo-symbols") / file_name
                frame.to_parquet(history_root / relative_path, index=False, compression="zstd")
                symbol_state[symbol] = {
                    "status": "succeeded",
                    "provider_symbol": provider_symbol,
                    "source": TIINGO_SOURCE,
                    "file": relative_path.as_posix(),
                    "row_count": len(frame),
                    "first_bar_at": frame["open_time"].min().isoformat(),
                    "last_bar_at": frame["open_time"].max().isoformat(),
                    "payload_sha256": hashlib.sha256(response.content).hexdigest(),
                    "payload_bytes": len(response.content),
                    "updated_at": datetime.now(UTC).isoformat(),
                    "duration_seconds": (datetime.now(UTC) - started).total_seconds(),
                }
            except TiingoQuotaExhausted as error:
                state["paused_reason"] = str(error)
                state["updated_at"] = datetime.now(UTC).isoformat()
                _atomic_json_write(state_path, state)
                break
            except Exception as error:
                symbol_state[symbol] = {
                    "status": "failed",
                    "provider_symbol": provider_symbol,
                    "source": TIINGO_SOURCE,
                    "error_type": type(error).__name__,
                    "error": str(error)[:1_000],
                    "updated_at": datetime.now(UTC).isoformat(),
                    "duration_seconds": (datetime.now(UTC) - started).total_seconds(),
                }
            state["updated_at"] = datetime.now(UTC).isoformat()
            _atomic_json_write(state_path, state)
    return state_path
