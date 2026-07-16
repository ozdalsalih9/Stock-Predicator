from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AssetDefinition:
    symbol: str
    base_asset: str
    data_starts_at: datetime
    asset_class: str = "crypto"
    exchange: str = "BINANCE"


ASSETS = (
    AssetDefinition("BTCUSDT", "BTC", datetime(2017, 8, 1, tzinfo=UTC)),
    AssetDefinition("ETHUSDT", "ETH", datetime(2017, 8, 1, tzinfo=UTC)),
    AssetDefinition("SOLUSDT", "SOL", datetime(2020, 8, 1, tzinfo=UTC)),
    AssetDefinition("BNBUSDT", "BNB", datetime(2017, 11, 1, tzinfo=UTC)),
    AssetDefinition("XRPUSDT", "XRP", datetime(2018, 5, 1, tzinfo=UTC)),
    AssetDefinition("ADAUSDT", "ADA", datetime(2018, 4, 1, tzinfo=UTC)),
    AssetDefinition("LINKUSDT", "LINK", datetime(2019, 1, 1, tzinfo=UTC)),
    AssetDefinition("DOGEUSDT", "DOGE", datetime(2019, 7, 1, tzinfo=UTC)),
)

US_EQUITY_PILOT = tuple(
    AssetDefinition(symbol, symbol, datetime(year, month, day, tzinfo=UTC), "us_equity", exchange)
    for symbol, year, month, day, exchange in (
        ("SPY", 1993, 1, 29, "ARCA"),
        ("QQQ", 1999, 3, 10, "NASDAQ"),
        ("IWM", 2000, 5, 22, "ARCA"),
        ("DIA", 1998, 1, 20, "ARCA"),
        ("XLK", 1998, 12, 22, "ARCA"),
        ("XLF", 1998, 12, 22, "ARCA"),
        ("XLE", 1998, 12, 22, "ARCA"),
        ("XLV", 1998, 12, 22, "ARCA"),
        ("AAPL", 1980, 12, 12, "NASDAQ"),
        ("MSFT", 1986, 3, 13, "NASDAQ"),
        ("NVDA", 1999, 1, 22, "NASDAQ"),
        ("AMZN", 1997, 5, 15, "NASDAQ"),
        ("GOOGL", 2004, 8, 19, "NASDAQ"),
        ("META", 2012, 5, 18, "NASDAQ"),
        ("TSLA", 2010, 6, 29, "NASDAQ"),
        ("JPM", 1980, 1, 2, "NYSE"),
        ("V", 2008, 3, 19, "NYSE"),
        ("XOM", 1980, 1, 2, "NYSE"),
        ("UNH", 1984, 10, 17, "NYSE"),
        ("WMT", 1980, 1, 2, "NYSE"),
    )
)

FEATURE_SET_VERSION = "crypto-daily-v2"
EQUITY_FEATURE_SET_VERSION = "us-equity-daily-v1"
SPOT_FEATURE_NAMES = (
    "return_1d",
    "return_3d",
    "return_7d",
    "return_14d",
    "return_30d",
    "return_60d",
    "return_90d",
    "volatility_7d",
    "volatility_30d",
    "volatility_90d",
    "rsi_14",
    "macd_normalized",
    "atr_14_normalized",
    "bollinger_width_20",
    "ma_ratio_7d",
    "ma_ratio_30d",
    "ma_ratio_90d",
    "ma_ratio_200d",
    "ma_slope_30d",
    "volume_zscore_30d",
    "trade_count_zscore_30d",
    "taker_buy_ratio_7d",
    "btc_correlation_30d",
    "btc_correlation_90d",
    "btc_beta_30d",
    "relative_strength_30d",
    "market_breadth_30d",
    "market_regime",
)
DERIVATIVE_FEATURE_NAMES = (
    "funding_rate_mean_7d",
    "funding_rate_mean_30d",
    "funding_rate_zscore_90d",
    "premium_mean_7d",
    "premium_mean_30d",
    "premium_zscore_90d",
    "futures_volume_zscore_30d",
    "futures_taker_buy_ratio_7d",
    "open_interest_change_7d",
    "open_interest_change_30d",
    "open_interest_zscore_90d",
    "futures_long_short_ratio_7d",
    "futures_taker_long_short_ratio_7d",
    "derivatives_available",
)
CROSS_SECTIONAL_FEATURE_NAMES = (
    "momentum_rank_30d",
    "momentum_rank_90d",
    "volatility_rank_30d",
)
ASSET_FEATURE_NAMES = tuple(f"asset_{asset.symbol.lower()}" for asset in ASSETS)
FEATURE_NAMES = (
    *SPOT_FEATURE_NAMES,
    *DERIVATIVE_FEATURE_NAMES,
)
EQUITY_FEATURE_NAMES = (
    "return_1s", "return_3s", "return_5s", "return_10s", "return_20s", "return_60s", "return_120s",
    "volatility_5s", "volatility_20s", "volatility_60s", "downside_volatility_20s",
    "rsi_14", "macd_normalized", "atr_14_normalized", "bollinger_width_20",
    "ma_ratio_5s", "ma_ratio_20s", "ma_ratio_60s", "ma_ratio_200s", "ma_slope_20s",
    "volume_zscore_20s", "dollar_volume_zscore_20s", "overnight_gap_1s", "intraday_return_1s",
    "benchmark_correlation_20s", "benchmark_correlation_60s", "benchmark_beta_20s",
    "relative_strength_20s", "market_breadth_20s", "market_regime",
    "momentum_rank_20s", "momentum_rank_60s", "volatility_rank_20s",
)
EQUITY_MACRO_EXPERIMENT_FEATURE_NAMES = (
    "benchmark_return_20s", "benchmark_return_60s",
    "benchmark_volatility_20s", "benchmark_volatility_60s",
    "benchmark_trend_strength_60s", "benchmark_market_regime",
)
EQUITY_V3_EXPERIMENT_FEATURE_NAMES = (
    *EQUITY_FEATURE_NAMES,
    *EQUITY_MACRO_EXPERIMENT_FEATURE_NAMES,
)
ALL_FEATURE_NAMES = (
    *FEATURE_NAMES,
    *CROSS_SECTIONAL_FEATURE_NAMES,
    *ASSET_FEATURE_NAMES,
)
FEATURE_GROUPS = {
    "spot": SPOT_FEATURE_NAMES,
    "derivatives": DERIVATIVE_FEATURE_NAMES,
    "cross_sectional": (*CROSS_SECTIONAL_FEATURE_NAMES, *ASSET_FEATURE_NAMES),
}
HORIZONS = (30, 90)
SEEDS = (17, 29, 43, 71, 101)

FUTURES_STARTS_AT = {
    "BTCUSDT": datetime(2020, 1, 1, tzinfo=UTC),
    "ETHUSDT": datetime(2020, 1, 1, tzinfo=UTC),
    "SOLUSDT": datetime(2020, 9, 1, tzinfo=UTC),
    "BNBUSDT": datetime(2020, 2, 1, tzinfo=UTC),
    "XRPUSDT": datetime(2020, 1, 1, tzinfo=UTC),
    "ADAUSDT": datetime(2020, 1, 1, tzinfo=UTC),
    "LINKUSDT": datetime(2020, 1, 1, tzinfo=UTC),
    "DOGEUSDT": datetime(2020, 7, 1, tzinfo=UTC),
}
