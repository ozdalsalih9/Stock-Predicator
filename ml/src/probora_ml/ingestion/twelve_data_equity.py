from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
TWELVE_DATA_STOCKS_URL = "https://api.twelvedata.com/stocks"
WIKIMEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
SP500_WIKIPEDIA_PAGE = "List_of_S&P_500_companies"
LONG_HISTORY_SECTOR_ETFS = ("XLY", "XLP", "XLI", "XLB", "XLU")


def canonical_equity_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def load_identity_quarantine(path: Path | None) -> set[str]:
    """Load provider symbols that cannot be tied to one historical security safely."""
    if path is None:
        return set()
    if not path.exists():
        raise ValueError(f"S&P identity quarantine file does not exist: {path}")
    frame = pd.read_csv(path)
    if "symbol" not in frame:
        raise ValueError("S&P identity quarantine must contain a symbol column.")
    symbols = {
        canonical_equity_symbol(symbol)
        for symbol in frame["symbol"].dropna().astype(str)
        if symbol.strip()
    }
    if not symbols:
        raise ValueError("S&P identity quarantine cannot be empty.")
    return symbols


def _parse_values(symbol: str, payload: dict[str, object]) -> pd.DataFrame:
    if str(payload.get("status", "")).lower() == "error":
        raise ValueError(f"Twelve Data rejected {symbol}: {payload.get('message', 'unknown error')}")
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"Twelve Data returned no daily values for {symbol}.")
    frame = pd.DataFrame(values)
    required = {"datetime", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Twelve Data {symbol} payload is missing: {', '.join(missing)}")
    output = pd.DataFrame(
        {
            "symbol": symbol,
            "open_time": pd.to_datetime(frame["datetime"], utc=True),
            "open": pd.to_numeric(frame["open"], errors="raise"),
            "high": pd.to_numeric(frame["high"], errors="raise"),
            "low": pd.to_numeric(frame["low"], errors="raise"),
            "close": pd.to_numeric(frame["close"], errors="raise"),
            "volume": pd.to_numeric(frame["volume"], errors="coerce").fillna(0),
        }
    )
    return output.sort_values("open_time").drop_duplicates("open_time", keep="last")


def download_twelve_data_equity_history(
    output_path: Path,
    symbols: tuple[str, ...] = LONG_HISTORY_SECTOR_ETFS,
    start_date: str = "2013-01-01",
    end_date: str | None = None,
    minimum_request_interval_seconds: float = 8.0,
) -> Path:
    """Download adjusted daily bars without placing the API key in URLs or artifacts."""
    api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY is not set.")
    end = end_date or datetime.now(UTC).date().isoformat()
    frames: list[pd.DataFrame] = []
    checksums: dict[str, str] = {}
    with httpx.Client(
        timeout=90,
        headers={"Authorization": f"apikey {api_key}", "User-Agent": "Probora/1.0"},
    ) as client:
        for index, symbol in enumerate(symbols):
            if index:
                time.sleep(minimum_request_interval_seconds)
            response: httpx.Response | None = None
            for attempt in range(3):
                response = client.get(
                    TWELVE_DATA_URL,
                    params={
                        "symbol": symbol,
                        "interval": "1day",
                        "start_date": start_date,
                        "end_date": end,
                        "order": "asc",
                        "timezone": "Exchange",
                        "adjust": "all",
                    },
                )
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt < 2:
                    time.sleep(max(minimum_request_interval_seconds, 60.0))
            assert response is not None
            response.raise_for_status()
            payload = response.json()
            frames.append(_parse_values(symbol, payload))
            checksums[symbol] = hashlib.sha256(response.content).hexdigest()

    output = pd.concat(frames, ignore_index=True)
    expected = set(symbols)
    received = set(output["symbol"].unique())
    if received != expected:
        raise ValueError(f"Sector history coverage mismatch: expected {expected}, received {received}")
    counts = output.groupby("symbol")["open_time"].nunique()
    if (counts < 3_000).any():
        insufficient = counts[counts < 3_000].to_dict()
        raise ValueError(f"Sector history is shorter than 3,000 sessions: {insufficient}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(output_path, index=False, compression="zstd")
    manifest = {
        "source": "Twelve Data /time_series",
        "source_url": TWELVE_DATA_URL,
        "license_scope": "Basic internal non-display research; recheck before commercial display",
        "adjustment": "all",
        "interval": "1day",
        "start_date": start_date,
        "end_date": end,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "symbols": [*symbols],
        "row_counts": {symbol: int(count) for symbol, count in counts.items()},
        "payload_sha256": checksums,
    }
    output_path.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output_path


def load_membership_universe(
    membership_path: Path,
    start_date: str = "2013-01-01",
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    membership = pd.read_csv(membership_path)
    if not {"date", "tickers"}.issubset(membership.columns):
        raise ValueError("Membership file must contain date and tickers columns.")
    membership["date"] = pd.to_datetime(membership["date"], utc=True, errors="raise")
    membership = membership[membership["date"] >= pd.Timestamp(start_date, tz="UTC")].copy()
    membership = membership.sort_values("date").drop_duplicates("date", keep="last")
    if membership.empty:
        raise ValueError("Membership file contains no rows in the requested period.")
    symbols = tuple(
        sorted(
            {
                canonical_equity_symbol(ticker)
                for value in membership["tickers"].astype(str)
                for ticker in value.split(",")
                if ticker.strip()
            }
        )
    )
    return membership.reset_index(drop=True), symbols


def split_symbol_batch(
    symbols: tuple[str, ...],
    batch_number: int,
    batch_count: int = 2,
) -> tuple[str, ...]:
    if batch_count < 1 or not 1 <= batch_number <= batch_count:
        raise ValueError("Batch number must be between one and batch count.")
    start = len(symbols) * (batch_number - 1) // batch_count
    end = len(symbols) * batch_number // batch_count
    return symbols[start:end]


def _clean_wiki_table_cell(value: str) -> str:
    cell = value.strip()
    cell = re.sub(r'^(?:rowspan|colspan)="?[^"]*"?\|', "", cell)
    cell = re.sub(r"<ref.*", "", cell).strip()
    return cell


def _parse_wikipedia_sp500_wikitext(
    wikitext: str,
) -> tuple[set[str], list[tuple[pd.Timestamp, str, str]]]:
    constituent_marker = 'id="constituents"'
    changes_marker = 'id="changes"'
    if constituent_marker not in wikitext or changes_marker not in wikitext:
        raise ValueError("Wikipedia S&P 500 tables could not be located.")

    constituent_start = wikitext.index(constituent_marker)
    constituent_end = wikitext.index("|}", constituent_start)
    constituent_table = wikitext[constituent_start:constituent_end]
    current = set(
        re.findall(
            r"^\|\{\{(?:NyseSymbol|NasdaqSymbol|AmexSymbol|BZX link)\|([^}|]+)",
            constituent_table,
            flags=re.MULTILINE,
        )
    )
    if len(current) < 490:
        raise ValueError(f"Wikipedia returned only {len(current)} current S&P securities.")

    changes_start = wikitext.index(changes_marker)
    changes_end = wikitext.index("|}", changes_start)
    changes: list[tuple[pd.Timestamp, str, str]] = []
    for block in wikitext[changes_start:changes_end].split("|-"):
        lines = [line for line in block.splitlines() if line.startswith("|") and not line.startswith("|}")]
        if not lines:
            continue
        if "||" in lines[0]:
            cells = [_clean_wiki_table_cell(cell) for cell in lines[0][1:].split("||")]
        else:
            cells = [_clean_wiki_table_cell(line[1:]) for line in lines]
        if len(cells) < 5:
            continue
        effective_date = pd.to_datetime(cells[0], format="mixed", errors="coerce", utc=True)
        if pd.isna(effective_date):
            continue
        changes.append((effective_date.normalize(), cells[1], cells[3]))
    if not changes:
        raise ValueError("Wikipedia S&P 500 change table was empty.")
    return current, changes


def refresh_sp500_membership(
    source_path: Path,
    output_path: Path,
    metadata_path: Path,
    effective_through: str | None = None,
) -> Path:
    """Causally extend the frozen MIT snapshot with later public component changes."""
    source = pd.read_csv(source_path)
    source["date"] = pd.to_datetime(source["date"], utc=True)
    source = source.sort_values("date").drop_duplicates("date", keep="last")
    cutoff = pd.Timestamp(effective_through or datetime.now(UTC).date(), tz="UTC")

    with httpx.Client(
        timeout=90,
        headers={
            "User-Agent": (
                "ProboraResearch/1.0 "
                "(https://github.com/ozdalsalih9/Stock-Predicator; historical index research)"
            ),
            "Accept": "application/json",
        },
    ) as client:
        for attempt in range(3):
            response = client.get(
                WIKIMEDIA_API_URL,
                params={
                    "action": "parse",
                    "page": SP500_WIKIPEDIA_PAGE,
                    "prop": "wikitext|revid",
                    "format": "json",
                    "formatversion": 2,
                },
            )
            if response.status_code not in {403, 429}:
                break
            if attempt < 2:
                time.sleep(2**attempt)
        response.raise_for_status()
    parsed = response.json().get("parse", {})
    wikitext = str(parsed.get("wikitext", ""))
    current, changes = _parse_wikipedia_sp500_wikitext(wikitext)

    source_last_date = source["date"].max()
    members = {ticker.strip().upper() for ticker in str(source.iloc[-1]["tickers"]).split(",")}
    additions: list[dict[str, object]] = []
    changes_frame = pd.DataFrame(changes, columns=["date", "added", "removed"])
    changes_frame = changes_frame[
        (changes_frame["date"] > source_last_date) & (changes_frame["date"] <= cutoff)
    ]
    for date, group in changes_frame.sort_values("date").groupby("date", sort=True):
        for removed in group["removed"]:
            if removed:
                members.discard(str(removed).upper())
        for added in group["added"]:
            if added:
                members.add(str(added).upper())
        additions.append({"date": date, "tickers": ",".join(sorted(members))})

    current = {ticker.strip().upper() for ticker in current}

    def canonical(values: set[str]) -> set[str]:
        return {value.replace(".", "-") for value in values}

    reconciliation = {
        "missing_from_reconstructed": sorted(canonical(current) - canonical(members)),
        "extra_in_reconstructed": sorted(canonical(members) - canonical(current)),
    }
    if cutoff.normalize() == pd.Timestamp(datetime.now(UTC).date(), tz="UTC") and current != members:
        members = current
        additions.append({"date": cutoff, "tickers": ",".join(sorted(members))})

    extended = pd.concat([source, pd.DataFrame(additions)], ignore_index=True)
    extended["date"] = pd.to_datetime(extended["date"], utc=True)
    extended = extended[extended["date"] <= cutoff]
    extended = extended.sort_values("date").drop_duplicates("date", keep="last")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    extended.assign(date=extended["date"].dt.date).to_csv(output_path, index=False)
    metadata = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_file": str(source_path),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_last_date": source_last_date.date().isoformat(),
        "effective_through": cutoff.date().isoformat(),
        "wikimedia_page": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "wikimedia_revision_id": parsed.get("revid"),
        "wikimedia_wikitext_sha256": hashlib.sha256(wikitext.encode("utf-8")).hexdigest(),
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "applied_change_rows": len(changes_frame),
        "current_security_count": len(current),
        "reconciliation": reconciliation,
    }
    _atomic_json_write(metadata_path, metadata)
    return output_path


def _safe_symbol_file(symbol: str) -> str:
    safe = re.sub(r"[^A-Z0-9._-]", "_", symbol.upper())
    suffix = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:8]
    return f"{safe}--{suffix}.parquet"


def _atomic_json_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def _symbols_pending_for_download(
    batch: tuple[str, ...],
    symbol_state: dict[str, object],
    output_root: Path,
    retry_failed: bool,
) -> list[str]:
    pending: list[str] = []
    for symbol in batch:
        item = symbol_state.get(symbol)
        if not isinstance(item, dict):
            pending.append(symbol)
            continue
        if item.get("status") == "succeeded" and (output_root / str(item.get("file"))).exists():
            continue
        if item.get("status") == "failed" and not retry_failed:
            continue
        pending.append(symbol)
    return pending


def load_sp500_history_symbol_files(output_root: Path) -> dict[str, Path]:
    """Resolve successful provider states, preferring the primary provider per symbol."""
    primary = output_root / "bootstrap-state.json"
    state_paths = ([primary] if primary.exists() else []) + sorted(
        path for path in output_root.glob("*-bootstrap-state.json") if path != primary
    )
    selected: dict[str, Path] = {}
    for state_path in state_paths:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for symbol, item in state.get("symbols", {}).items():
            canonical = canonical_equity_symbol(symbol)
            if canonical in selected or not isinstance(item, dict) or item.get("status") != "succeeded":
                continue
            path = output_root / str(item.get("file", ""))
            if path.exists():
                selected[canonical] = path
    return selected


def _fetch_twelve_symbol(
    client: httpx.Client,
    symbol: str,
    start_date: str,
    end_date: str,
    minimum_request_interval_seconds: float,
    resolve_delisted: bool = False,
    resolved_exchange: str | None = None,
) -> tuple[pd.DataFrame, str]:
    params = {
        "symbol": symbol,
        "interval": "1day",
        "start_date": start_date,
        "end_date": end_date,
        "order": "asc",
        "timezone": "Exchange",
        "adjust": "all",
    }
    if resolved_exchange:
        params["exchange"] = resolved_exchange
    response: httpx.Response | None = None
    for attempt in range(3):
        response = client.get(TWELVE_DATA_URL, params=params)
        if response.status_code != 429 and response.status_code < 500:
            break
        if attempt < 2:
            retry_after = float(response.headers.get("Retry-After", 60))
            time.sleep(max(retry_after, minimum_request_interval_seconds))
    assert response is not None
    if response.status_code == 404 and resolve_delisted:
        time.sleep(minimum_request_interval_seconds)
        catalog = client.get(
            TWELVE_DATA_STOCKS_URL,
            params={
                "symbol": symbol,
                "country": "United States",
                "include_delisted": "true",
                "show_plan": "true",
            },
        )
        catalog.raise_for_status()
        candidates = catalog.json().get("data", [])
        exchanges = [
            str(item.get("exchange"))
            for item in candidates
            if str(item.get("symbol", "")).upper() == symbol.upper() and item.get("exchange")
        ]
        for exchange in dict.fromkeys(exchanges):
            time.sleep(minimum_request_interval_seconds)
            response = client.get(TWELVE_DATA_URL, params={**params, "exchange": exchange})
            if response.is_success:
                break
    response.raise_for_status()
    frame = _parse_values(symbol, response.json())
    return frame, hashlib.sha256(response.content).hexdigest()


def _fetch_delisted_exchange_catalog(
    client: httpx.Client,
) -> dict[str, str]:
    """Fetch the US symbol catalog once so retries do not spend two lookup calls per ticker."""
    response = client.get(
        TWELVE_DATA_STOCKS_URL,
        params={
            "country": "United States",
            "include_delisted": "true",
            "show_plan": "true",
        },
    )
    response.raise_for_status()
    exchanges: dict[str, str] = {}
    for item in response.json().get("data", []):
        symbol = str(item.get("symbol", "")).strip().upper()
        exchange = str(item.get("exchange", "")).strip()
        if symbol and exchange:
            exchanges.setdefault(symbol, exchange)
    return exchanges


def bootstrap_sp500_pit_history(
    membership_path: Path,
    output_root: Path,
    batch_number: int,
    batch_count: int = 2,
    membership_start_date: str = "2013-01-01",
    price_start_date: str = "2012-01-01",
    end_date: str | None = None,
    minimum_request_interval_seconds: float = 8.0,
    maximum_symbols: int | None = None,
    retry_failed: bool = False,
    resolve_delisted: bool = False,
) -> Path:
    """Resumably fetch one deterministic slice of the point-in-time S&P universe."""
    api_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY is not set.")
    _, universe = load_membership_universe(membership_path, membership_start_date)
    batch = split_symbol_batch(universe, batch_number, batch_count)
    if maximum_symbols is not None:
        batch = batch[:maximum_symbols]
    end = end_date or datetime.now(UTC).date().isoformat()
    output_root.mkdir(parents=True, exist_ok=True)
    symbols_root = output_root / "symbols"
    symbols_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "bootstrap-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "version": 1,
            "source": "Twelve Data /time_series",
            "membership_file": str(membership_path),
            "membership_sha256": hashlib.sha256(membership_path.read_bytes()).hexdigest(),
            "universe_size": len(universe),
            "batch_count": batch_count,
            "symbols": {},
        }
    symbol_state: dict[str, object] = state["symbols"]  # type: ignore[assignment]
    pending = _symbols_pending_for_download(batch, symbol_state, output_root, retry_failed)
    with httpx.Client(
        timeout=90,
        headers={"Authorization": f"apikey {api_key}", "User-Agent": "Probora/1.0"},
    ) as client:
        resolved_exchanges: dict[str, str] = {}
        if retry_failed and resolve_delisted and pending:
            try:
                resolved_exchanges = _fetch_delisted_exchange_catalog(client)
                time.sleep(minimum_request_interval_seconds)
            except Exception:
                # A catalog failure falls back to the existing per-symbol resolution path.
                resolved_exchanges = {}
        for index, symbol in enumerate(pending):
            if index:
                time.sleep(minimum_request_interval_seconds)
            started = datetime.now(UTC)
            try:
                frame, checksum = _fetch_twelve_symbol(
                    client,
                    symbol,
                    price_start_date,
                    end,
                    minimum_request_interval_seconds,
                    resolve_delisted and symbol not in resolved_exchanges,
                    resolved_exchanges.get(symbol),
                )
                file_name = _safe_symbol_file(symbol)
                relative_path = Path("symbols") / file_name
                frame.to_parquet(output_root / relative_path, index=False, compression="zstd")
                symbol_state[symbol] = {
                    "status": "succeeded",
                    "file": relative_path.as_posix(),
                    "row_count": len(frame),
                    "first_bar_at": frame["open_time"].min().isoformat(),
                    "last_bar_at": frame["open_time"].max().isoformat(),
                    "payload_sha256": checksum,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "duration_seconds": (datetime.now(UTC) - started).total_seconds(),
                }
            except Exception as error:
                symbol_state[symbol] = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error)[:1_000],
                    "updated_at": datetime.now(UTC).isoformat(),
                    "duration_seconds": (datetime.now(UTC) - started).total_seconds(),
                }
            state["updated_at"] = datetime.now(UTC).isoformat()
            state["last_batch_number"] = batch_number
            _atomic_json_write(state_path, state)
    return state_path


def audit_sp500_pit_coverage(
    membership_path: Path,
    output_root: Path,
    trading_samples_path: Path,
    report_path: Path,
    membership_start_date: str = "2013-01-01",
    coverage_start_date: str | None = None,
    identity_quarantine_path: Path | None = None,
) -> Path:
    membership, universe = load_membership_universe(membership_path, membership_start_date)
    primary_state_path = output_root / "bootstrap-state.json"
    primary_state = (
        json.loads(primary_state_path.read_text(encoding="utf-8"))
        if primary_state_path.exists()
        else {"symbols": {}}
    )
    symbol_state: dict[str, dict[str, object]] = primary_state.get("symbols", {})  # type: ignore[assignment]
    provider_status_counts: dict[str, dict[str, int]] = {}
    for state_path in sorted(output_root.glob("*bootstrap-state.json")):
        provider_state = json.loads(state_path.read_text(encoding="utf-8"))
        counts = Counter(
            str(item.get("status", "unknown"))
            for item in provider_state.get("symbols", {}).values()
            if isinstance(item, dict)
        )
        provider_status_counts[state_path.name] = dict(counts)
    identity_quarantine = load_identity_quarantine(identity_quarantine_path)
    available_dates: dict[str, set[pd.Timestamp]] = {}
    for symbol, path in load_sp500_history_symbol_files(output_root).items():
        if symbol in identity_quarantine:
            continue
        bars = pd.read_parquet(path, columns=["open_time"])
        available_dates[symbol] = set(pd.to_datetime(bars["open_time"], utc=True).dt.normalize())

    samples = pd.read_parquet(trading_samples_path, columns=["asset_id", "snapshot_time"])
    trading_dates = (
        pd.to_datetime(samples[samples["asset_id"] == "SPY"]["snapshot_time"], utc=True)
        .dt.normalize()
        .drop_duplicates()
        .sort_values()
    )
    if coverage_start_date is not None:
        requested_start = pd.Timestamp(coverage_start_date)
        requested_start = (
            requested_start.tz_localize("UTC")
            if requested_start.tzinfo is None
            else requested_start.tz_convert("UTC")
        ).normalize()
        trading_dates = trading_dates[trading_dates >= requested_start]
    if trading_dates.empty:
        raise ValueError("S&P coverage audit contains no trading dates after filtering.")
    membership_dates = membership["date"].astype("int64").to_numpy()
    membership_values = membership["tickers"].astype(str).to_numpy()
    missing_frequency: Counter[str] = Counter()
    daily_rows: list[dict[str, object]] = []
    for date in trading_dates:
        position = membership_dates.searchsorted(date.value, side="right") - 1
        if position < 0:
            continue
        members = {canonical_equity_symbol(ticker) for ticker in membership_values[position].split(",")}
        covered = {symbol for symbol in members if date in available_dates.get(symbol, set())}
        missing = members - covered
        missing_frequency.update(missing)
        daily_rows.append(
            {
                "date": date.date().isoformat(),
                "member_count": len(members),
                "covered_count": len(covered),
                "coverage": len(covered) / len(members),
            }
        )
    coverage = pd.DataFrame(daily_rows)
    statuses = Counter(str(item.get("status", "unknown")) for item in symbol_state.values())
    membership_last_snapshot = membership["date"].max()
    latest_trading_date = trading_dates.max() if not trading_dates.empty else pd.NaT
    membership_freshness_days = (
        max(0, int((latest_trading_date - membership_last_snapshot).days))
        if pd.notna(latest_trading_date)
        else None
    )
    membership_fresh = bool(membership_freshness_days is not None and membership_freshness_days <= 35)
    coverage_passed = bool(not coverage.empty and (coverage["coverage"] >= 0.95).all())
    identity_quarantine_applied = bool(identity_quarantine_path is not None)
    report = {
        "version": 2,
        "checked_at": datetime.now(UTC).isoformat(),
        "membership_file": str(membership_path),
        "membership_sha256": hashlib.sha256(membership_path.read_bytes()).hexdigest(),
        "universe_size": len(universe),
        "download_status_counts": dict(statuses),
        "provider_status_counts": provider_status_counts,
        "downloaded_symbol_count": len(available_dates),
        "trading_date_count": len(coverage),
        "mean_daily_coverage": float(coverage["coverage"].mean()) if not coverage.empty else 0,
        "minimum_daily_coverage": float(coverage["coverage"].min()) if not coverage.empty else 0,
        "p05_daily_coverage": float(coverage["coverage"].quantile(0.05)) if not coverage.empty else 0,
        "latest_daily_coverage": float(coverage.iloc[-1]["coverage"]) if not coverage.empty else 0,
        "minimum_required_daily_coverage": 0.95,
        "coverage_passed": coverage_passed,
        "coverage_start_date": trading_dates.min().date().isoformat(),
        "coverage_end_date": trading_dates.max().date().isoformat(),
        "requested_coverage_start_date": coverage_start_date,
        "identity_quarantine_applied": identity_quarantine_applied,
        "identity_quarantine_file": (
            str(identity_quarantine_path) if identity_quarantine_path is not None else None
        ),
        "identity_quarantine_sha256": (
            hashlib.sha256(identity_quarantine_path.read_bytes()).hexdigest()
            if identity_quarantine_path is not None
            else None
        ),
        "identity_quarantined_symbols": sorted(identity_quarantine),
        "identity_quarantined_symbol_count": len(identity_quarantine),
        "membership_last_snapshot_date": membership_last_snapshot.date().isoformat(),
        "latest_trading_date": (
            latest_trading_date.date().isoformat() if pd.notna(latest_trading_date) else None
        ),
        "membership_freshness_days": membership_freshness_days,
        "membership_fresh": membership_fresh,
        "coverage_ready": bool(
            coverage_passed and membership_fresh and identity_quarantine_applied
        ),
        "most_frequently_missing": [
            {"symbol": symbol, "missing_trading_dates": count}
            for symbol, count in missing_frequency.most_common(100)
        ],
        "daily_coverage": daily_rows,
    }
    _atomic_json_write(report_path, report)
    return report_path


def require_sp500_pit_coverage(
    report_path: Path,
    membership_path: Path | None = None,
) -> dict[str, object]:
    """Block V4.3 feature/model work until breadth data and membership are safe."""
    report: dict[str, object] = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("coverage_ready") is True
        and report.get("identity_quarantine_applied") is True
        and report.get("coverage_start_date")
        and report.get("coverage_end_date")
    ):
        if membership_path is not None:
            expected_membership_hash = str(report.get("membership_sha256", ""))
            actual_membership_hash = hashlib.sha256(membership_path.read_bytes()).hexdigest()
            if not expected_membership_hash or actual_membership_hash != expected_membership_hash:
                raise ValueError(
                    "S&P membership file no longer matches the audited V4.3 coverage contract."
                )
        return report
    coverage = float(report.get("minimum_daily_coverage", 0))
    freshness = report.get("membership_freshness_days")
    raise ValueError(
        "S&P point-in-time coverage gate is closed: "
        f"minimum daily coverage={coverage:.2%}, membership freshness={freshness} days. "
        "V4.3 requires >=95% on every retained cutoff, membership no more than 35 days stale, "
        "and an explicit identity quarantine contract."
    )
