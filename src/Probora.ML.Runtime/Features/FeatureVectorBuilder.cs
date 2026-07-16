namespace Probora.ML.Runtime.Features;

public static class FeatureVectorBuilder
{
    private const int MinimumHistoryDays = 365;

    public static FeatureVector Build(
        IReadOnlyList<MarketObservation> asset,
        IReadOnlyList<MarketObservation> bitcoin,
        double marketBreadth30Days,
        IReadOnlyList<DerivativeObservation>? derivatives = null)
    {
        if (asset.Count < MinimumHistoryDays)
        {
            throw new ArgumentException($"At least {MinimumHistoryDays} daily observations are required.", nameof(asset));
        }

        MarketObservation[] ordered = asset.OrderBy(x => x.Time).ToArray();
        MarketObservation[] btcOrdered = bitcoin.OrderBy(x => x.Time).ToArray();
        double[] close = ordered.Select(x => x.Close).ToArray();
        double[] logReturns = LogReturns(close);
        double[] btcReturns = btcOrdered.Length >= 91
            ? LogReturns(btcOrdered.Select(x => x.Close).ToArray())
            : [];

        Dictionary<string, double> values = new(StringComparer.Ordinal)
        {
            ["return_1d"] = Return(close, 1),
            ["return_3d"] = Return(close, 3),
            ["return_7d"] = Return(close, 7),
            ["return_14d"] = Return(close, 14),
            ["return_30d"] = Return(close, 30),
            ["return_60d"] = Return(close, 60),
            ["return_90d"] = Return(close, 90),
            ["volatility_7d"] = AnnualizedVolatility(logReturns, 7),
            ["volatility_30d"] = AnnualizedVolatility(logReturns, 30),
            ["volatility_90d"] = AnnualizedVolatility(logReturns, 90),
            ["rsi_14"] = Rsi(close, 14) / 100,
            ["macd_normalized"] = Macd(close) / close[^1],
            ["atr_14_normalized"] = Atr(ordered, 14) / close[^1],
            ["bollinger_width_20"] = BollingerWidth(close, 20),
            ["ma_ratio_7d"] = close[^1] / Mean(close, 7) - 1,
            ["ma_ratio_30d"] = close[^1] / Mean(close, 30) - 1,
            ["ma_ratio_90d"] = close[^1] / Mean(close, 90) - 1,
            ["ma_ratio_200d"] = close[^1] / Mean(close, 200) - 1,
            ["ma_slope_30d"] = Mean(close, 7) / Mean(close.SkipLast(7).ToArray(), 30) - 1,
            ["volume_zscore_30d"] = ZScore(ordered.Select(x => x.Volume).ToArray(), 30),
            ["trade_count_zscore_30d"] = ZScore(ordered.Select(x => x.TradeCount).ToArray(), 30),
            ["taker_buy_ratio_7d"] = TakerBuyRatio(ordered, 7),
            ["btc_correlation_30d"] = Correlation(logReturns, btcReturns, 30),
            ["btc_correlation_90d"] = Correlation(logReturns, btcReturns, 90),
            ["btc_beta_30d"] = Beta(logReturns, btcReturns, 30),
            ["relative_strength_30d"] = Return(close, 30) - (btcOrdered.Length >= 31 ? Return(btcOrdered.Select(x => x.Close).ToArray(), 30) : 0),
            ["market_breadth_30d"] = Math.Clamp(marketBreadth30Days, 0, 1),
            ["market_regime"] = Regime(close, logReturns)
        };

        AddDerivativeFeatures(values, derivatives);

        foreach ((string key, double value) in values.ToArray())
        {
            if (!double.IsFinite(value))
            {
                values[key] = 0;
            }
        }

        return new FeatureVector(ordered[^1].Time, FeatureSchema.Version, values);
    }

    private static double Return(double[] values, int days) => Math.Log(values[^1] / values[^(days + 1)]);

    private static double[] LogReturns(double[] values) => values.Skip(1)
        .Select((value, index) => Math.Log(value / values[index]))
        .ToArray();

    private static double AnnualizedVolatility(double[] returns, int days) =>
        StandardDeviation(returns.TakeLast(days).ToArray()) * Math.Sqrt(365);

    private static double Mean(double[] values, int days) => values.TakeLast(days).Average();

    private static double StandardDeviation(double[] values)
    {
        if (values.Length < 2)
        {
            return 0;
        }

        double mean = values.Average();
        return Math.Sqrt(values.Sum(value => Math.Pow(value - mean, 2)) / (values.Length - 1));
    }

    private static double Rsi(double[] close, int period)
    {
        double[] changes = close.TakeLast(period + 1).Zip(close.TakeLast(period + 1).Skip(1), (a, b) => b - a).ToArray();
        double gains = changes.Where(x => x > 0).Sum() / period;
        double losses = -changes.Where(x => x < 0).Sum() / period;
        return losses == 0 ? 100 : 100 - (100 / (1 + (gains / losses)));
    }

    private static double ExponentialMovingAverage(double[] values, int period)
    {
        double alpha = 2d / (period + 1);
        double ema = values[0];
        foreach (double value in values.Skip(1))
        {
            ema = (alpha * value) + ((1 - alpha) * ema);
        }
        return ema;
    }

    private static double Macd(double[] close) =>
        ExponentialMovingAverage(close.TakeLast(120).ToArray(), 12) - ExponentialMovingAverage(close.TakeLast(120).ToArray(), 26);

    private static double Atr(MarketObservation[] observations, int period)
    {
        MarketObservation[] tail = observations.TakeLast(period + 1).ToArray();
        List<double> ranges = [];
        for (int index = 1; index < tail.Length; index++)
        {
            ranges.Add(Math.Max(
                tail[index].High - tail[index].Low,
                Math.Max(Math.Abs(tail[index].High - tail[index - 1].Close), Math.Abs(tail[index].Low - tail[index - 1].Close))));
        }
        return ranges.Average();
    }

    private static double BollingerWidth(double[] close, int period)
    {
        double[] tail = close.TakeLast(period).ToArray();
        double mean = tail.Average();
        return mean == 0 ? 0 : (4 * StandardDeviation(tail)) / mean;
    }

    private static double ZScore(double[] values, int period)
    {
        double[] tail = values.TakeLast(period).ToArray();
        double standardDeviation = StandardDeviation(tail);
        return standardDeviation == 0 ? 0 : (tail[^1] - tail.Average()) / standardDeviation;
    }

    private static double TakerBuyRatio(MarketObservation[] observations, int period)
    {
        MarketObservation[] tail = observations.TakeLast(period).ToArray();
        double totalVolume = tail.Sum(x => x.Volume);
        return totalVolume == 0 ? 0.5 : tail.Sum(x => x.TakerBuyBaseVolume) / totalVolume;
    }

    private static double Correlation(double[] left, double[] right, int period)
    {
        if (left.Length < period || right.Length < period)
        {
            return 0;
        }

        double[] x = left.TakeLast(period).ToArray();
        double[] y = right.TakeLast(period).ToArray();
        double xStd = StandardDeviation(x);
        double yStd = StandardDeviation(y);
        if (xStd == 0 || yStd == 0)
        {
            return 0;
        }
        double covariance = x.Zip(y, (a, b) => (a - x.Average()) * (b - y.Average())).Sum() / (period - 1);
        return covariance / (xStd * yStd);
    }

    private static double Beta(double[] asset, double[] benchmark, int period)
    {
        if (asset.Length < period || benchmark.Length < period)
        {
            return 0;
        }
        double[] x = asset.TakeLast(period).ToArray();
        double[] y = benchmark.TakeLast(period).ToArray();
        double variance = Math.Pow(StandardDeviation(y), 2);
        if (variance == 0)
        {
            return 0;
        }
        double covariance = x.Zip(y, (a, b) => (a - x.Average()) * (b - y.Average())).Sum() / (period - 1);
        return covariance / variance;
    }

    private static double Regime(double[] close, double[] returns)
    {
        double trend = close[^1] / Mean(close, 90) - 1;
        double volatility = AnnualizedVolatility(returns, 30);
        if (Math.Abs(trend) < 0.05)
        {
            return 0;
        }
        if (trend > 0)
        {
            return volatility < 0.65 ? 1 : 2;
        }
        return volatility < 0.65 ? -1 : -2;
    }

    private static void AddDerivativeFeatures(
        IDictionary<string, double> values,
        IReadOnlyList<DerivativeObservation>? derivatives)
    {
        string[] names =
        [
            "funding_rate_mean_7d", "funding_rate_mean_30d", "funding_rate_zscore_90d",
            "premium_mean_7d", "premium_mean_30d", "premium_zscore_90d",
            "futures_volume_zscore_30d", "futures_taker_buy_ratio_7d",
            "open_interest_change_7d", "open_interest_change_30d", "open_interest_zscore_90d",
            "futures_long_short_ratio_7d", "futures_taker_long_short_ratio_7d", "derivatives_available"
        ];
        foreach (string name in names)
        {
            values[name] = 0;
        }
        if (derivatives is null || derivatives.Count == 0)
        {
            return;
        }

        DerivativeObservation[] ordered = derivatives.OrderBy(x => x.Time).ToArray();
        values["funding_rate_mean_7d"] = TailMean(ordered.Select(x => x.FundingRate), 7);
        values["funding_rate_mean_30d"] = TailMean(ordered.Select(x => x.FundingRate), 30);
        values["funding_rate_zscore_90d"] = TailZScore(ordered.Select(x => x.FundingRate), 90);
        values["premium_mean_7d"] = TailMean(ordered.Select(x => x.Premium), 7);
        values["premium_mean_30d"] = TailMean(ordered.Select(x => x.Premium), 30);
        values["premium_zscore_90d"] = TailZScore(ordered.Select(x => x.Premium), 90);
        values["futures_volume_zscore_30d"] = TailZScore(ordered.Select(x => x.FuturesQuoteVolume), 30);
        values["futures_taker_buy_ratio_7d"] = TailMean(ordered.Select(x => x.FuturesTakerBuyRatio), 7);
        values["open_interest_change_7d"] = LogChange(ordered.Select(x => x.OpenInterestValue), 7);
        values["open_interest_change_30d"] = LogChange(ordered.Select(x => x.OpenInterestValue), 30);
        values["open_interest_zscore_90d"] = TailZScore(ordered.Select(x => x.OpenInterestValue), 90);
        values["futures_long_short_ratio_7d"] = TailMean(ordered.Select(x => x.LongShortRatio), 7);
        values["futures_taker_long_short_ratio_7d"] = TailMean(ordered.Select(x => x.TakerLongShortRatio), 7);
        values["derivatives_available"] = ordered.Length >= 30 &&
            ordered[^1].Time - ordered[^30].Time >= TimeSpan.FromDays(29) ? 1 : 0;
    }

    private static double TailMean(IEnumerable<double> values, int days)
    {
        double[] tail = values.Where(double.IsFinite).TakeLast(days).ToArray();
        return tail.Length == 0 ? 0 : tail.Average();
    }

    private static double TailZScore(IEnumerable<double> values, int days)
    {
        double[] tail = values.Where(double.IsFinite).TakeLast(days).ToArray();
        if (tail.Length < 10)
        {
            return 0;
        }
        double standardDeviation = StandardDeviation(tail);
        return standardDeviation == 0 ? 0 : (tail[^1] - tail.Average()) / standardDeviation;
    }

    private static double LogChange(IEnumerable<double> values, int days)
    {
        double[] valid = values.Where(value => double.IsFinite(value) && value > 0).ToArray();
        return valid.Length <= days ? 0 : Math.Log(valid[^1] / valid[^(days + 1)]);
    }
}
