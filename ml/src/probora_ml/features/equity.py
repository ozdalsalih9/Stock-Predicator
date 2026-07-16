from __future__ import annotations

import math

import numpy as np
import pandas as pd

from probora_ml.config import EQUITY_FEATURE_NAMES, EQUITY_FEATURE_SET_VERSION


def _std(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if len(values) >= 2 else 0.0


def _returns(close: np.ndarray) -> np.ndarray:
    return np.log(close[1:] / close[:-1])


def _return(close: np.ndarray, sessions: int) -> float:
    return float(math.log(close[-1] / close[-(sessions + 1)]))


def _ema(values: np.ndarray, period: int) -> float:
    alpha = 2.0 / (period + 1)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1 - alpha) * result
    return result


def _correlation(left: np.ndarray, right: np.ndarray, period: int) -> float:
    if len(left) < period or len(right) < period:
        return 0.0
    x, y = left[-period:], right[-period:]
    denominator = _std(x) * _std(y)
    return 0.0 if denominator == 0 else float(np.cov(x, y, ddof=1)[0, 1] / denominator)


def _rank(value: float, peers: list[float]) -> float:
    return 0.5 if not peers else float(np.mean(np.asarray(peers) <= value))


def _regime(close: np.ndarray, returns: np.ndarray) -> float:
    trend = close[-1] / float(close[-60:].mean()) - 1
    volatility = _std(returns[-20:]) * math.sqrt(252)
    if abs(trend) < 0.03:
        return 0.0
    if trend > 0:
        return 1.0 if volatility < 0.35 else 2.0
    return -1.0 if volatility < 0.35 else -2.0


def build_equity_feature_row(
    asset: pd.DataFrame,
    benchmark: pd.DataFrame,
    breadth: float,
    momentum_rank_20s: float,
    momentum_rank_60s: float,
    volatility_rank_20s: float,
) -> dict[str, float]:
    if len(asset) < 252:
        raise ValueError("At least 252 completed sessions are required.")
    frame = asset.sort_values("open_time")
    spy = benchmark.sort_values("open_time")
    close = frame["close"].to_numpy(float)
    returns = _returns(close)
    spy_close = spy["close"].to_numpy(float)
    spy_returns = _returns(spy_close) if len(spy_close) >= 61 else np.array([], dtype=float)
    volume = frame["volume"].to_numpy(float)
    dollar_volume = volume * close

    def mean(sessions: int, values: np.ndarray = close) -> float:
        return float(values[-sessions:].mean())

    def zscore(values: np.ndarray, sessions: int) -> float:
        tail = values[-sessions:]
        deviation = _std(tail)
        return 0.0 if deviation == 0 else float((tail[-1] - tail.mean()) / deviation)

    changes = np.diff(close[-15:])
    gains = changes[changes > 0].sum() / 14
    losses = -changes[changes < 0].sum() / 14
    rsi = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    tail = frame.tail(15).reset_index(drop=True)
    ranges = [
        max(
            tail.loc[index, "high"] - tail.loc[index, "low"],
            abs(tail.loc[index, "high"] - tail.loc[index - 1, "close"]),
            abs(tail.loc[index, "low"] - tail.loc[index - 1, "close"]),
        )
        for index in range(1, len(tail))
    ]
    beta = 0.0
    if len(returns) >= 20 and len(spy_returns) >= 20:
        variance = _std(spy_returns[-20:]) ** 2
        if variance != 0:
            beta = float(np.cov(returns[-20:], spy_returns[-20:], ddof=1)[0, 1] / variance)
    vol20 = _std(returns[-20:]) * math.sqrt(252)
    benchmark_return_60s = _return(spy_close, 60)
    benchmark_volatility_20s = _std(spy_returns[-20:]) * math.sqrt(252)
    benchmark_volatility_60s = _std(spy_returns[-60:]) * math.sqrt(252)
    benchmark_trend_strength_60s = abs(benchmark_return_60s) / max(
        benchmark_volatility_60s * math.sqrt(60 / 252), 1e-6
    )
    downside = returns[-20:][returns[-20:] < 0]
    trend = close[-1] / mean(60) - 1
    regime = (
        0.0
        if abs(trend) < 0.03
        else 1.0
        if trend > 0 and vol20 < 0.35
        else 2.0
        if trend > 0
        else -1.0
        if vol20 < 0.35
        else -2.0
    )
    previous_close = close[-2]
    latest_open = float(frame.iloc[-1]["open"])
    latest_close = close[-1]
    values = {
        "return_1s": _return(close, 1),
        "return_3s": _return(close, 3),
        "return_5s": _return(close, 5),
        "return_10s": _return(close, 10),
        "return_20s": _return(close, 20),
        "return_60s": _return(close, 60),
        "return_120s": _return(close, 120),
        "volatility_5s": _std(returns[-5:]) * math.sqrt(252),
        "volatility_20s": vol20,
        "volatility_60s": _std(returns[-60:]) * math.sqrt(252),
        "downside_volatility_20s": _std(downside) * math.sqrt(252),
        "rsi_14": rsi / 100,
        "macd_normalized": (_ema(close[-120:], 12) - _ema(close[-120:], 26)) / latest_close,
        "atr_14_normalized": float(np.mean(ranges)) / latest_close,
        "bollinger_width_20": 4 * _std(close[-20:]) / mean(20),
        "ma_ratio_5s": latest_close / mean(5) - 1,
        "ma_ratio_20s": latest_close / mean(20) - 1,
        "ma_ratio_60s": latest_close / mean(60) - 1,
        "ma_ratio_200s": latest_close / mean(200) - 1,
        "ma_slope_20s": mean(5) / float(close[:-5][-20:].mean()) - 1,
        "volume_zscore_20s": zscore(volume, 20),
        "dollar_volume_zscore_20s": zscore(dollar_volume, 20),
        "overnight_gap_1s": 0.0 if previous_close == 0 else math.log(latest_open / previous_close),
        "intraday_return_1s": 0.0 if latest_open == 0 else math.log(latest_close / latest_open),
        "benchmark_correlation_20s": _correlation(returns, spy_returns, 20),
        "benchmark_correlation_60s": _correlation(returns, spy_returns, 60),
        "benchmark_beta_20s": beta,
        "benchmark_return_20s": _return(spy_close, 20),
        "benchmark_return_60s": benchmark_return_60s,
        "benchmark_volatility_20s": benchmark_volatility_20s,
        "benchmark_volatility_60s": benchmark_volatility_60s,
        "benchmark_trend_strength_60s": benchmark_trend_strength_60s,
        "benchmark_market_regime": _regime(spy_close, spy_returns),
        "relative_strength_20s": _return(close, 20)
        - (_return(spy_close, 20) if len(spy_close) >= 21 else 0),
        "market_breadth_20s": float(np.clip(breadth, 0, 1)),
        "market_regime": regime,
        "momentum_rank_20s": momentum_rank_20s,
        "momentum_rank_60s": momentum_rank_60s,
        "volatility_rank_20s": volatility_rank_20s,
    }
    return {
        name: float(np.nan_to_num(values[name], nan=0.0, posinf=0.0, neginf=0.0))
        for name in EQUITY_FEATURE_NAMES
    }


def create_equity_feature_snapshots(daily_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    indexed = {
        symbol: frame.sort_values("open_time").reset_index(drop=True)
        for symbol, frame in daily_by_symbol.items()
    }
    benchmark = indexed["SPY"][["open_time", "close"]].copy()
    benchmark["benchmark_return"] = np.log(benchmark["close"] / benchmark["close"].shift(1))
    benchmark["benchmark_return_20s"] = np.log(benchmark["close"] / benchmark["close"].shift(20))
    benchmark["benchmark_return_60s"] = np.log(benchmark["close"] / benchmark["close"].shift(60))
    benchmark_returns = np.log(benchmark["close"] / benchmark["close"].shift(1))
    benchmark["benchmark_volatility_20s"] = benchmark_returns.rolling(20).std(ddof=1) * math.sqrt(252)
    benchmark["benchmark_volatility_60s"] = benchmark_returns.rolling(60).std(ddof=1) * math.sqrt(252)
    benchmark["benchmark_trend_strength_60s"] = benchmark["benchmark_return_60s"].abs() / (
        benchmark["benchmark_volatility_60s"].clip(lower=1e-6) * math.sqrt(60 / 252)
    )
    benchmark_trend = benchmark["close"] / benchmark["close"].rolling(60).mean() - 1
    benchmark["benchmark_market_regime"] = np.select(
        [
            benchmark_trend.abs() < 0.03,
            (benchmark_trend > 0) & (benchmark["benchmark_volatility_20s"] < 0.35),
            benchmark_trend > 0,
            benchmark["benchmark_volatility_20s"] < 0.35,
        ],
        [0.0, 1.0, 2.0, -1.0],
        default=-2.0,
    )

    frames: list[pd.DataFrame] = []
    for symbol, source in indexed.items():
        frame = source.copy()
        close = frame["close"].astype(float)
        open_price = frame["open"].astype(float)
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)
        volume = frame["volume"].astype(float)
        returns = np.log(close / close.shift(1))
        gains = returns.clip(lower=0).rolling(14).mean()
        losses = (-returns.clip(upper=0)).rolling(14).mean()
        true_range = pd.concat(
            [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
        ).max(axis=1)
        mean20 = close.rolling(20).mean()
        vol20 = returns.rolling(20).std(ddof=1) * math.sqrt(252)
        downside20 = returns.where(returns < 0).rolling(20, min_periods=2).std(ddof=1) * math.sqrt(252)
        result = pd.DataFrame(
            {
                "asset_id": symbol,
                "snapshot_time": frame["open_time"],
                "feature_set_version": EQUITY_FEATURE_SET_VERSION,
                "return_1s": np.log(close / close.shift(1)),
                "return_3s": np.log(close / close.shift(3)),
                "return_5s": np.log(close / close.shift(5)),
                "return_10s": np.log(close / close.shift(10)),
                "return_20s": np.log(close / close.shift(20)),
                "return_60s": np.log(close / close.shift(60)),
                "return_120s": np.log(close / close.shift(120)),
                "volatility_5s": returns.rolling(5).std(ddof=1) * math.sqrt(252),
                "volatility_20s": vol20,
                "volatility_60s": returns.rolling(60).std(ddof=1) * math.sqrt(252),
                "downside_volatility_20s": downside20.fillna(0),
                "rsi_14": (100 - 100 / (1 + gains / losses.replace(0, np.nan))).fillna(100) / 100,
                "macd_normalized": (
                    close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
                ) / close,
                "atr_14_normalized": true_range.rolling(14).mean() / close,
                "bollinger_width_20": 4 * close.rolling(20).std(ddof=1) / mean20,
                "ma_ratio_5s": close / close.rolling(5).mean() - 1,
                "ma_ratio_20s": close / mean20 - 1,
                "ma_ratio_60s": close / close.rolling(60).mean() - 1,
                "ma_ratio_200s": close / close.rolling(200).mean() - 1,
                "ma_slope_20s": close.rolling(5).mean() / mean20.shift(5) - 1,
                "volume_zscore_20s": (volume - volume.rolling(20).mean()) / volume.rolling(20).std(ddof=1),
                "dollar_volume_zscore_20s": (
                    volume * close - (volume * close).rolling(20).mean()
                ) / (volume * close).rolling(20).std(ddof=1),
                "overnight_gap_1s": np.log(open_price / close.shift(1)),
                "intraday_return_1s": np.log(close / open_price),
                "market_regime": np.select(
                    [
                        (close / close.rolling(60).mean() - 1).abs() < 0.03,
                        (close / close.rolling(60).mean() - 1 > 0) & (vol20 < 0.35),
                        close / close.rolling(60).mean() - 1 > 0,
                        vol20 < 0.35,
                    ],
                    [0.0, 1.0, 2.0, -1.0],
                    default=-2.0,
                ),
            }
        )
        aligned = result.merge(
            benchmark[
                [
                    "open_time",
                    "benchmark_return",
                    "benchmark_return_20s",
                    "benchmark_return_60s",
                    "benchmark_volatility_20s",
                    "benchmark_volatility_60s",
                    "benchmark_trend_strength_60s",
                    "benchmark_market_regime",
                ]
            ],
            left_on="snapshot_time",
            right_on="open_time",
            how="left",
        ).drop(columns="open_time")
        aligned["benchmark_correlation_20s"] = returns.rolling(20).corr(aligned["benchmark_return"])
        aligned["benchmark_correlation_60s"] = returns.rolling(60).corr(aligned["benchmark_return"])
        aligned["benchmark_beta_20s"] = (
            returns.rolling(20).cov(aligned["benchmark_return"])
            / aligned["benchmark_return"].rolling(20).var(ddof=1)
        )
        aligned["relative_strength_20s"] = aligned["return_20s"] - aligned["benchmark_return_20s"]
        frames.append(aligned)

    combined = pd.concat(frames, ignore_index=True)
    combined["market_breadth_20s"] = combined.groupby("snapshot_time")["return_20s"].transform(
        lambda values: float((values > 0).mean())
    )
    combined["momentum_rank_20s"] = combined.groupby("snapshot_time")["return_20s"].rank(pct=True)
    combined["momentum_rank_60s"] = combined.groupby("snapshot_time")["return_60s"].rank(pct=True)
    combined["volatility_rank_20s"] = combined.groupby("snapshot_time")["volatility_20s"].rank(pct=True)
    columns = ["asset_id", "snapshot_time", "feature_set_version", *EQUITY_FEATURE_NAMES]
    return combined.loc[:, columns].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def add_equity_macro_features(samples: pd.DataFrame) -> pd.DataFrame:
    """Upgrade a point-in-time-safe v1 sample set using its contemporaneous SPY rows."""
    required = {
        "asset_id",
        "snapshot_time",
        "horizon_days",
        "return_20s",
        "return_60s",
        "volatility_20s",
        "volatility_60s",
        "market_regime",
    }
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(f"Equity samples are missing: {', '.join(missing)}")
    macro_names = [
        "benchmark_return_20s",
        "benchmark_return_60s",
        "benchmark_volatility_20s",
        "benchmark_volatility_60s",
        "benchmark_trend_strength_60s",
        "benchmark_market_regime",
    ]
    output = samples.drop(
        columns=[name for name in macro_names if name in samples], errors="ignore"
    ).copy()
    spy = output[output["asset_id"] == "SPY"][
        [
            "snapshot_time",
            "horizon_days",
            "return_20s",
            "return_60s",
            "volatility_20s",
            "volatility_60s",
            "market_regime",
        ]
    ].drop_duplicates(["snapshot_time", "horizon_days"])
    spy = spy.rename(
        columns={
            "return_20s": "benchmark_return_20s",
            "return_60s": "benchmark_return_60s",
            "volatility_20s": "benchmark_volatility_20s",
            "volatility_60s": "benchmark_volatility_60s",
            "market_regime": "benchmark_market_regime",
        }
    )
    spy["benchmark_trend_strength_60s"] = spy["benchmark_return_60s"].abs() / (
        spy["benchmark_volatility_60s"].clip(lower=1e-6) * math.sqrt(60 / 252)
    )
    output = output.merge(
        spy, on=["snapshot_time", "horizon_days"], how="left", validate="many_to_one"
    )
    output["feature_set_version"] = "us-equity-daily-v1+spy-macro-exp1"
    return output
