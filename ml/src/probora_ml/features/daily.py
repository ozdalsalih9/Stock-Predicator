from __future__ import annotations

import math

import numpy as np
import pandas as pd

from probora_ml.config import ALL_FEATURE_NAMES, ASSETS, FEATURE_SET_VERSION
from probora_ml.features.derivatives import build_derivative_feature_row


def aggregate_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    frame = hourly.copy()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.set_index("open_time").sort_index()
    daily = frame.resample("1D", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        quote_volume=("quote_volume", "sum"),
        trade_count=("trade_count", "sum"),
        taker_buy_base_volume=("taker_buy_base_volume", "sum"),
    )
    # A UTC day is only fully observable at the next midnight.
    daily.index = daily.index + pd.Timedelta(days=1)
    return daily.dropna(subset=["open", "high", "low", "close"]).reset_index()


def _std(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if len(values) >= 2 else 0.0


def _log_returns(close: np.ndarray) -> np.ndarray:
    return np.log(close[1:] / close[:-1])


def _return(close: np.ndarray, days: int) -> float:
    return float(math.log(close[-1] / close[-(days + 1)]))


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
    x_std, y_std = _std(x), _std(y)
    if x_std == 0 or y_std == 0:
        return 0.0
    covariance = float(np.sum((x - x.mean()) * (y - y.mean())) / (period - 1))
    return covariance / (x_std * y_std)


def build_feature_row(
    asset: pd.DataFrame,
    bitcoin: pd.DataFrame,
    market_breadth_30d: float,
    derivatives: pd.DataFrame | None = None,
    asset_symbol: str | None = None,
    cross_sectional: dict[str, float] | None = None,
) -> dict[str, float]:
    if len(asset) < 365:
        raise ValueError("At least 365 daily observations are required.")
    frame = asset.sort_values("open_time")
    btc = bitcoin.sort_values("open_time")
    close = frame["close"].to_numpy(dtype=float)
    returns = _log_returns(close)
    btc_close = btc["close"].to_numpy(dtype=float)
    btc_returns = _log_returns(btc_close) if len(btc_close) >= 91 else np.array([], dtype=float)

    changes = np.diff(close[-15:])
    gains = changes[changes > 0].sum() / 14
    losses = -changes[changes < 0].sum() / 14
    rsi = 100.0 if losses == 0 else 100 - (100 / (1 + gains / losses))
    ranges = []
    tail = frame.tail(15).reset_index(drop=True)
    for index in range(1, len(tail)):
        ranges.append(
            max(
                tail.loc[index, "high"] - tail.loc[index, "low"],
                abs(tail.loc[index, "high"] - tail.loc[index - 1, "close"]),
                abs(tail.loc[index, "low"] - tail.loc[index - 1, "close"]),
            )
        )
    volume = frame["volume"].to_numpy(dtype=float)
    trades = frame["trade_count"].to_numpy(dtype=float)

    def mean(days: int, values: np.ndarray = close) -> float:
        return float(values[-days:].mean())

    def zscore(values: np.ndarray, days: int) -> float:
        standard_deviation = _std(values[-days:])
        return (
            0.0
            if standard_deviation == 0
            else float((values[-1] - values[-days:].mean()) / standard_deviation)
        )

    beta = 0.0
    if len(returns) >= 30 and len(btc_returns) >= 30:
        x, y = returns[-30:], btc_returns[-30:]
        variance = _std(y) ** 2
        beta = 0.0 if variance == 0 else float(np.sum((x - x.mean()) * (y - y.mean())) / 29 / variance)
    trend = close[-1] / mean(90) - 1
    volatility_30 = _std(returns[-30:]) * math.sqrt(365)
    regime = (
        0.0
        if abs(trend) < 0.05
        else (
            1.0
            if trend > 0 and volatility_30 < 0.65
            else 2.0
            if trend > 0
            else -1.0
            if volatility_30 < 0.65
            else -2.0
        )
    )
    total_volume_7d = float(volume[-7:].sum())

    values = {
        "return_1d": _return(close, 1),
        "return_3d": _return(close, 3),
        "return_7d": _return(close, 7),
        "return_14d": _return(close, 14),
        "return_30d": _return(close, 30),
        "return_60d": _return(close, 60),
        "return_90d": _return(close, 90),
        "volatility_7d": _std(returns[-7:]) * math.sqrt(365),
        "volatility_30d": volatility_30,
        "volatility_90d": _std(returns[-90:]) * math.sqrt(365),
        "rsi_14": rsi / 100,
        "macd_normalized": (_ema(close[-120:], 12) - _ema(close[-120:], 26)) / close[-1],
        "atr_14_normalized": float(np.mean(ranges)) / close[-1],
        "bollinger_width_20": 4 * _std(close[-20:]) / mean(20),
        "ma_ratio_7d": close[-1] / mean(7) - 1,
        "ma_ratio_30d": close[-1] / mean(30) - 1,
        "ma_ratio_90d": close[-1] / mean(90) - 1,
        "ma_ratio_200d": close[-1] / mean(200) - 1,
        "ma_slope_30d": mean(7) / float(close[:-7][-30:].mean()) - 1,
        "volume_zscore_30d": zscore(volume, 30),
        "trade_count_zscore_30d": zscore(trades, 30),
        "taker_buy_ratio_7d": 0.5
        if total_volume_7d == 0
        else float(frame["taker_buy_base_volume"].tail(7).sum()) / total_volume_7d,
        "btc_correlation_30d": _correlation(returns, btc_returns, 30),
        "btc_correlation_90d": _correlation(returns, btc_returns, 90),
        "btc_beta_30d": beta,
        "relative_strength_30d": _return(close, 30) - (_return(btc_close, 30) if len(btc_close) >= 31 else 0),
        "market_breadth_30d": float(np.clip(market_breadth_30d, 0, 1)),
        "market_regime": regime,
    }
    values.update(build_derivative_feature_row(derivatives))
    ranks = cross_sectional or {}
    values.update(
        {
            "momentum_rank_30d": float(ranks.get("momentum_rank_30d", 0.5)),
            "momentum_rank_90d": float(ranks.get("momentum_rank_90d", 0.5)),
            "volatility_rank_30d": float(ranks.get("volatility_rank_30d", 0.5)),
        }
    )
    values.update(
        {
            f"asset_{definition.symbol.lower()}": float(asset_symbol == definition.symbol)
            for definition in ASSETS
        }
    )
    return {
        name: float(np.nan_to_num(values[name], nan=0.0, posinf=0.0, neginf=0.0))
        for name in ALL_FEATURE_NAMES
    }


def _percentile_rank(value: float, peers: list[float]) -> float:
    if not peers:
        return 0.5
    return float(np.mean(np.asarray(peers) <= value))


def create_feature_snapshots(
    daily_by_symbol: dict[str, pd.DataFrame],
    derivatives_by_symbol: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    btc = daily_by_symbol["BTCUSDT"].sort_values("open_time").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    for symbol, frame in daily_by_symbol.items():
        ordered = frame.sort_values("open_time").reset_index(drop=True)
        for index in range(364, len(ordered)):
            snapshot_time = pd.Timestamp(ordered.loc[index, "open_time"])
            history = ordered.iloc[: index + 1]
            btc_history = btc[btc["open_time"] <= snapshot_time]
            breadth_values = []
            peer_return_30d: list[float] = []
            peer_return_90d: list[float] = []
            peer_volatility_30d: list[float] = []
            for peer in daily_by_symbol.values():
                peer_history = peer[peer["open_time"] <= snapshot_time]
                if len(peer_history) >= 31:
                    peer_close = peer_history["close"].to_numpy(float)
                    return_30d = _return(peer_close, 30)
                    breadth_values.append(return_30d > 0)
                    peer_return_30d.append(return_30d)
                    peer_returns = _log_returns(peer_close)
                    peer_volatility_30d.append(_std(peer_returns[-30:]) * math.sqrt(365))
                    if len(peer_history) >= 91:
                        peer_return_90d.append(_return(peer_close, 90))
            breadth = float(np.mean(breadth_values)) if breadth_values else 0.5
            current_close = history["close"].to_numpy(float)
            current_returns = _log_returns(current_close)
            ranks = {
                "momentum_rank_30d": _percentile_rank(_return(current_close, 30), peer_return_30d),
                "momentum_rank_90d": _percentile_rank(_return(current_close, 90), peer_return_90d),
                "volatility_rank_30d": _percentile_rank(
                    _std(current_returns[-30:]) * math.sqrt(365), peer_volatility_30d
                ),
            }
            derivative_history = None
            if derivatives_by_symbol and symbol in derivatives_by_symbol:
                derivative_history = derivatives_by_symbol[symbol]
                derivative_history = derivative_history[
                    derivative_history["snapshot_time"] <= snapshot_time
                ]
            features = build_feature_row(
                history,
                btc_history,
                breadth,
                derivatives=derivative_history,
                asset_symbol=symbol,
                cross_sectional=ranks,
            )
            rows.append(
                {
                    "asset_id": symbol,
                    "snapshot_time": snapshot_time,
                    "feature_set_version": FEATURE_SET_VERSION,
                    **features,
                }
            )
    return pd.DataFrame(rows)
