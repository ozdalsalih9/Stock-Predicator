import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import httpx
import mlflow
import pandas as pd
import psycopg
import typer

from probora_ml.config import (
    ASSETS,
    EQUITY_FEATURE_NAMES,
    EQUITY_FEATURE_SET_VERSION,
    FUTURES_STARTS_AT,
    HORIZONS,
    US_EQUITY_PILOT,
)
from probora_ml.evaluation.ablation import run_and_write_ablation
from probora_ml.evaluation.calibration_ablation import run_and_write_equity_calibration_ablation
from probora_ml.evaluation.conditional_prior_ablation import run_and_write_conditional_prior_ablation
from probora_ml.evaluation.direction_model_ablation import run_and_write_direction_model_ablation
from probora_ml.evaluation.fred_macro_ablation import run_and_write_fred_macro_ablation
from probora_ml.evaluation.interval_calibration_ablation import (
    run_and_write_interval_calibration_ablation,
)
from probora_ml.evaluation.label_ablation import run_and_write_label_ablation
from probora_ml.evaluation.linear_direction_ablation import run_and_write_linear_direction_ablation
from probora_ml.evaluation.regime_analysis import run_and_write_regime_analysis
from probora_ml.evaluation.tree_regularization_ablation import (
    run_and_write_tree_regularization_ablation,
)
from probora_ml.features.daily import aggregate_daily, create_feature_snapshots
from probora_ml.features.derivatives import load_derivatives_daily
from probora_ml.features.equity import add_equity_macro_features, create_equity_feature_snapshots
from probora_ml.hardware import resolve_training_device
from probora_ml.ingestion.binance_archive import download_month
from probora_ml.ingestion.binance_futures_archive import (
    download_futures_archive,
    list_daily_metrics_keys,
    monthly_archive_key,
    previous_month_end,
)
from probora_ml.ingestion.fred_market import download_fred_market_data
from probora_ml.ingestion.shadow_bootstrap import bootstrap_shadow_snapshots
from probora_ml.training.labels import attach_targets
from probora_ml.training.pipeline import train_and_evaluate

app = typer.Typer(no_args_is_help=True)


@app.command("ablate-interval-calibration")
def ablate_interval_calibration_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Compare absolute and scale-adaptive conformal return intervals."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_interval_calibration_ablation(
        samples, horizon, device_type, output
    )
    typer.echo(f"Interval calibration ablation ({device_type}) -> {report_path}")


@app.command("download-fred-market")
def download_fred_market_command(
    output: Path = Path("data/raw-macro/fred-market"),
    observation_start: str = "2013-01-01",
) -> None:
    """Download checksummed official FRED market-stress research series."""
    manifest = download_fred_market_data(output, observation_start)
    typer.echo(f"FRED market research snapshot -> {manifest}")


@app.command("ablate-fred-macro")
def ablate_fred_macro_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    macro_root: Path = Path("data/raw-macro/fred-market"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Ablate lagged VIX, Treasury curve and high-yield stress features."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_fred_macro_ablation(
        samples, macro_root, horizon, device_type, output
    )
    typer.echo(f"FRED macro ablation ({device_type}) -> {report_path}")


@app.command("ablate-tree-regularization")
def ablate_tree_regularization_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Screen lower-capacity and recent-window LightGBM direction models."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_tree_regularization_ablation(
        samples, horizon, device_type, output
    )
    typer.echo(f"Tree regularization ablation ({device_type}) -> {report_path}")


@app.command("ablate-labels")
def ablate_labels_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Screen bounded ATR-confirmed neutral-band labels without changing production."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_label_ablation(
        samples, horizon, device_type, output
    )
    typer.echo(f"Label ablation ({device_type}) -> {report_path}")


@app.command("ablate-linear-direction")
def ablate_linear_direction_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
) -> None:
    """Evaluate a conservative, regularized and calibrated linear direction model."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_linear_direction_ablation(samples, horizon, output)
    typer.echo(f"Linear direction ablation -> {report_path}")


@app.command("ablate-conditional-prior")
def ablate_conditional_prior_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
) -> None:
    """Evaluate interpretable, regime-conditioned shrinkage priors."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_conditional_prior_ablation(samples, horizon, output)
    typer.echo(f"Conditional prior ablation -> {report_path}")


@app.command("ablate-direction-models")
def ablate_direction_models_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    horizon: int = typer.Option(90, help="Direction horizon: 30 or 90 sessions."),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Compare nominal, ordinal and quantile-derived direction probabilities."""
    if horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_direction_model_ablation(
        samples, horizon, device_type, output
    )
    typer.echo(f"Direction model ablation ({device_type}) -> {report_path}")


@app.command("upgrade-equity-v3-dataset")
def upgrade_equity_v3_dataset_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("data/equity_training_samples_v3.parquet"),
) -> None:
    """Add causal SPY macro features to the existing versioned equity samples."""
    samples = add_equity_macro_features(pd.read_parquet(dataset))
    dataset_version = f"us-equity-v3-{datetime.now(UTC):%Y%m%d}"
    samples["dataset_version"] = dataset_version
    output.parent.mkdir(parents=True, exist_ok=True)
    samples.to_parquet(output, index=False, compression="zstd")
    typer.echo(f"{len(samples)} samples -> {output} ({dataset_version})")


@app.command("ablate-equity-calibration")
def ablate_equity_calibration_command(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Compare leakage-safe multiclass calibration candidates for equity V3."""
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_equity_calibration_ablation(samples, device_type, output)
    typer.echo(f"Equity calibration ablation ({device_type}) -> {report_path}")


@app.command("analyze-regimes")
def analyze_regimes_command(
    dataset: Path = Path("data/training_samples.parquet"),
    output: Path = Path("artifacts/reports"),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    """Rebuild outer-fold predictions and diagnose macro market regimes."""
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_regime_analysis(samples, device_type, output)
    typer.echo(f"Regime analysis ({device_type}) -> {report_path}")


@app.command("bootstrap-shadow")
def bootstrap_shadow_command(
    processed_root: Path = Path("data/processed-futures"),
    database_url: str = "postgresql://probora:probora_dev@127.0.0.1:5432/probora",
    history_days: int = typer.Option(120, min=97, max=365),
) -> None:
    """Seed verified history and strictly backfill the live UTC cutoffs."""
    result = bootstrap_shadow_snapshots(processed_root, database_url, history_days)
    typer.echo(
        f"archive={result.archive_written}, live={result.live_written}, "
        f"cutoff={result.target_cutoff.isoformat()}"
    )


@app.command("download-month")
def download_month_command(symbol: str, year: int, month: int, root: Path = Path("data")) -> None:
    allowed = {asset.symbol for asset in ASSETS}
    if symbol.upper() not in allowed:
        raise typer.BadParameter(f"Unsupported symbol. Use one of: {', '.join(sorted(allowed))}")
    result = download_month(symbol.upper(), year, month, root / "raw", root / "processed")
    typer.echo(f"{result.row_count} rows -> {result.parquet_path} ({result.sha256})")


@app.command("download-history")
def download_history(
    root: Path = Path("data"), interval: str = "1h", workers: int = typer.Option(4, min=1, max=8)
) -> None:
    now = datetime.now(UTC)
    final_year, final_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    tasks: list[tuple[str, int, int]] = []
    for asset in ASSETS:
        year, month = asset.data_starts_at.year, asset.data_starts_at.month
        while (year, month) <= (final_year, final_month):
            tasks.append((asset.symbol, year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_month, symbol, year, month, root / "raw", root / "processed", interval
            ): (symbol, year, month)
            for symbol, year, month in tasks
        }
        for future in as_completed(futures):
            symbol, year, month = futures[future]
            try:
                result = future.result()
                typer.echo(f"{symbol} {year:04d}-{month:02d}: {result.row_count} rows")
            except Exception as error:
                failures.append(f"{symbol} {year:04d}-{month:02d}: {error}")
                typer.echo(f"FAILED {failures[-1]}", err=True)
    if failures:
        typer.echo(f"{len(failures)} archive downloads failed.", err=True)
        raise typer.Exit(code=1)


@app.command("build-dataset")
def build_dataset(
    processed_root: Path = Path("data/processed"),
    derivatives_root: Path = Path("data/processed-futures"),
    output: Path = Path("data/training_samples.parquet"),
) -> None:
    daily_by_symbol = {}
    derivatives_by_symbol = {}
    for asset in ASSETS:
        files = sorted((processed_root / asset.symbol / "1h").glob("*.parquet"))
        if not files:
            raise typer.BadParameter(f"No processed files for {asset.symbol}.")
        hourly = pd.concat((pd.read_parquet(path) for path in files), ignore_index=True).drop_duplicates(
            "open_time"
        )
        daily_by_symbol[asset.symbol] = aggregate_daily(hourly)
        derivatives = load_derivatives_daily(derivatives_root, asset.symbol)
        if derivatives.empty:
            raise typer.BadParameter(f"No processed derivatives data for {asset.symbol}.")
        derivatives_by_symbol[asset.symbol] = derivatives
    features = create_feature_snapshots(daily_by_symbol, derivatives_by_symbol)
    samples = pd.concat(
        (attach_targets(features, daily_by_symbol, horizon) for horizon in HORIZONS), ignore_index=True
    )
    dataset_version = f"crypto-v3-{datetime.now(UTC):%Y%m%d}"
    samples["dataset_version"] = dataset_version
    output.parent.mkdir(parents=True, exist_ok=True)
    samples.to_parquet(output, index=False, compression="zstd")
    typer.echo(f"{len(samples)} samples -> {output} ({dataset_version})")


@app.command("build-equity-dataset")
def build_equity_dataset(
    database_url: str = "postgresql://probora:probora_dev@127.0.0.1:5432/probora",
    output: Path = Path("data/equity_training_samples.parquet"),
) -> None:
    """Build a point-in-time-safe pilot dataset from adjusted US-equity EOD bars."""
    symbols = [asset.symbol for asset in US_EQUITY_PILOT]
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a."Symbol", p."OpenTime", p."Open", p."High", p."Low", p."Close", p."Volume"
                FROM probora.price_bars p
                JOIN probora.assets a ON a."Id" = p."AssetId"
                WHERE a."AssetClass" = 'us_equity'
                  AND p."Source" = 'twelvedata-us-eod-total-return'
                  AND p."Interval" = '1d'
                  AND p."IsFinal"
                ORDER BY a."Symbol", p."OpenTime"
                """
            )
            rows = cursor.fetchall()
    frame = pd.DataFrame(rows, columns=["symbol", "open_time", "open", "high", "low", "close", "volume"])
    if frame.empty:
        raise typer.BadParameter("No adjusted US-equity EOD bars are available.")
    frame = frame[frame["symbol"].isin(symbols)]
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = frame[column].astype(float)
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    daily_by_symbol = {
        symbol: group.drop(columns="symbol").reset_index(drop=True)
        for symbol, group in frame.groupby("symbol", sort=False)
    }
    missing = sorted(set(symbols) - set(daily_by_symbol))
    if missing:
        raise typer.BadParameter(f"Missing EOD history for: {', '.join(missing)}")
    features = create_equity_feature_snapshots(daily_by_symbol)
    samples = pd.concat(
        (
            attach_targets(
                features,
                daily_by_symbol,
                horizon,
                periods_per_year=252,
                volatility_short_column="volatility_20s",
                volatility_long_column="volatility_60s",
            )
            for horizon in HORIZONS
        ),
        ignore_index=True,
    )
    dataset_version = f"us-equity-pilot-v1-{datetime.now(UTC):%Y%m%d}"
    samples["dataset_version"] = dataset_version
    output.parent.mkdir(parents=True, exist_ok=True)
    samples.to_parquet(output, index=False, compression="zstd")
    typer.echo(f"{len(samples)} samples -> {output} ({dataset_version})")


@app.command("download-derivatives-history")
def download_derivatives_history(
    root: Path = Path("data"),
    workers: int = typer.Option(16, min=1, max=32),
    include_metrics: bool = typer.Option(True, help="Include daily open-interest metrics archives."),
) -> None:
    end = previous_month_end()
    tasks: list[tuple[str, str, str]] = []
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
    transport = httpx.HTTPTransport(retries=3)
    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "Probora/1.0"},
        limits=limits,
        transport=transport,
    ) as client:
        for asset in ASSETS:
            symbol = asset.symbol
            start = FUTURES_STARTS_AT[symbol]
            year, month = start.year, start.month
            while (year, month) <= (end.year, end.month):
                for data_type in ("fundingRate", "premiumIndexKlines", "klines"):
                    tasks.append((monthly_archive_key(symbol, data_type, year, month), symbol, data_type))
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            if include_metrics:
                metrics_keys = list_daily_metrics_keys(symbol, start.date(), end, client)
                tasks.extend((key, symbol, "metrics") for key in metrics_keys)

        typer.echo(f"Derivative archives scheduled: {len(tasks)}")
        failures: list[str] = []
        completed = 0
        counts: dict[str, int] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    download_futures_archive,
                    key,
                    symbol,
                    data_type,
                    root / "raw-futures",
                    root / "processed-futures",
                    client,
                ): (key, data_type)
                for key, symbol, data_type in tasks
            }
            for future in as_completed(futures):
                key, data_type = futures[future]
                try:
                    result = future.result()
                    counts[data_type] = counts.get(data_type, 0) + result.row_count
                except Exception as error:
                    failures.append(f"{key}: {error}")
                completed += 1
                if completed % 250 == 0 or completed == len(tasks):
                    typer.echo(f"Derivative archives: {completed}/{len(tasks)}")
        for data_type, row_count in sorted(counts.items()):
            typer.echo(f"{data_type}: {row_count} rows")
        if failures:
            for failure in failures[:20]:
                typer.echo(f"FAILED {failure}", err=True)
            typer.echo(f"{len(failures)} derivative archive downloads failed.", err=True)
            raise typer.Exit(code=1)


@app.command("train")
def train(
    dataset: Path = Path("data/training_samples.parquet"),
    artifacts: Path = Path("artifacts/models"),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
    horizon: int | None = typer.Option(None, help="Train only one horizon: 30 or 90."),
    tracking_uri: str = typer.Option("sqlite:///mlflow.db", help="MLflow tracking backend."),
) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if horizon is not None and horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    typer.echo(f"Training device: {device_type}")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("probora-crypto")
    samples = pd.read_parquet(dataset)
    if "dataset_version" in samples:
        samples.attrs["dataset_version"] = str(samples["dataset_version"].iloc[0])
    selected_horizons = (horizon,) if horizon is not None else HORIZONS
    for selected_horizon in selected_horizons:
        report = train_and_evaluate(samples, selected_horizon, artifacts, device_type=device_type)
        typer.echo(report)


@app.command("train-equity")
def train_equity(
    dataset: Path = Path("data/equity_training_samples.parquet"),
    artifacts: Path = Path("artifacts/models"),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
    horizon: int | None = typer.Option(None, help="Train only one horizon: 30 or 90 sessions."),
    tracking_uri: str = typer.Option("sqlite:///mlflow.db", help="MLflow tracking backend."),
) -> None:
    """Train isolated 30/90-session US-equity shadow candidates."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if horizon is not None and horizon not in HORIZONS:
        raise typer.BadParameter(f"Horizon must be one of: {', '.join(map(str, HORIZONS))}")
    device_type = resolve_training_device(device)
    typer.echo(f"Training device: {device_type}")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("probora-us-equity-shadow")
    samples = pd.read_parquet(dataset)
    if "dataset_version" in samples:
        samples.attrs["dataset_version"] = str(samples["dataset_version"].iloc[0])
    selected_horizons = (horizon,) if horizon is not None else HORIZONS
    for selected_horizon in selected_horizons:
        report = train_and_evaluate(
            samples,
            selected_horizon,
            artifacts,
            device_type=device_type,
            feature_names=EQUITY_FEATURE_NAMES,
            feature_set_version=EQUITY_FEATURE_SET_VERSION,
            asset_class="us_equity",
            version_prefix="probora-us-equity-v1",
            allow_production=False,
            risk_baseline_feature="volatility_20s",
            conformal_scale_feature="volatility_60s",
            periods_per_year=252,
        )
        typer.echo(report)


@app.command("ablate")
def ablate(
    dataset: Path = Path("data/training_samples.parquet"),
    output: Path = Path("artifacts/ablations"),
    device: str = typer.Option("auto", help="Training device: auto, gpu, or cpu."),
) -> None:
    device_type = resolve_training_device(device)
    samples = pd.read_parquet(dataset)
    report_path = run_and_write_ablation(samples, device_type, output)
    typer.echo(f"Ablation report -> {report_path}")


if __name__ == "__main__":
    app()
