namespace Probora.ML.Runtime.Features;

public static class FeatureSchema
{
    public const string Version = "crypto-daily-v2";

    public static readonly IReadOnlyList<string> Names =
    [
        "return_1d", "return_3d", "return_7d", "return_14d", "return_30d", "return_60d", "return_90d",
        "volatility_7d", "volatility_30d", "volatility_90d",
        "rsi_14", "macd_normalized", "atr_14_normalized", "bollinger_width_20",
        "ma_ratio_7d", "ma_ratio_30d", "ma_ratio_90d", "ma_ratio_200d",
        "ma_slope_30d", "volume_zscore_30d", "trade_count_zscore_30d", "taker_buy_ratio_7d",
        "btc_correlation_30d", "btc_correlation_90d", "btc_beta_30d", "relative_strength_30d",
        "market_breadth_30d", "market_regime",
        "funding_rate_mean_7d", "funding_rate_mean_30d", "funding_rate_zscore_90d",
        "premium_mean_7d", "premium_mean_30d", "premium_zscore_90d",
        "futures_volume_zscore_30d", "futures_taker_buy_ratio_7d",
        "open_interest_change_7d", "open_interest_change_30d", "open_interest_zscore_90d",
        "futures_long_short_ratio_7d", "futures_taker_long_short_ratio_7d", "derivatives_available"
    ];
}

public sealed record MarketObservation(
    DateTimeOffset Time,
    double Open,
    double High,
    double Low,
    double Close,
    double Volume,
    double QuoteVolume,
    double TradeCount,
    double TakerBuyBaseVolume);

public sealed record DerivativeObservation(
    DateTimeOffset Time,
    double FundingRate,
    double Premium,
    double FuturesQuoteVolume,
    double FuturesTakerBuyRatio,
    double OpenInterestValue,
    double LongShortRatio,
    double TakerLongShortRatio);

public sealed record FeatureVector(
    DateTimeOffset SnapshotTime,
    string FeatureSetVersion,
    IReadOnlyDictionary<string, double> Values)
{
    public float[] ToModelInput() => FeatureSchema.Names.Select(name => (float)Values[name]).ToArray();
}
