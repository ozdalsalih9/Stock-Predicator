namespace Probora.ML.Runtime.Features;

public static class EquityFeatureSchema
{
    public const string Version = "us-equity-daily-v1";

    public static readonly IReadOnlyList<string> Names =
    [
        "return_1s", "return_3s", "return_5s", "return_10s", "return_20s", "return_60s", "return_120s",
        "volatility_5s", "volatility_20s", "volatility_60s",
        "downside_volatility_20s", "rsi_14", "macd_normalized", "atr_14_normalized",
        "bollinger_width_20", "ma_ratio_5s", "ma_ratio_20s", "ma_ratio_60s", "ma_ratio_200s",
        "ma_slope_20s", "volume_zscore_20s", "dollar_volume_zscore_20s",
        "overnight_gap_1s", "intraday_return_1s",
        "benchmark_correlation_20s", "benchmark_correlation_60s", "benchmark_beta_20s",
        "relative_strength_20s", "market_breadth_20s", "market_regime",
        "momentum_rank_20s", "momentum_rank_60s", "volatility_rank_20s"
    ];
}

public static class EquityFeatureVectorBuilder
{
    private const int MinimumHistorySessions = 252;
    private const double AnnualizationSessions = 252;

    public static FeatureVector Build(
        IReadOnlyList<MarketObservation> asset,
        IReadOnlyList<MarketObservation> benchmark,
        double marketBreadth20Sessions,
        double momentumRank20Sessions,
        double momentumRank60Sessions,
        double volatilityRank20Sessions)
    {
        if (asset.Count < MinimumHistorySessions)
        {
            throw new ArgumentException(
                $"At least {MinimumHistorySessions} completed sessions are required.", nameof(asset));
        }

        MarketObservation[] ordered = asset.OrderBy(x => x.Time).ToArray();
        MarketObservation[] benchmarkOrdered = benchmark.OrderBy(x => x.Time).ToArray();
        double[] close = ordered.Select(x => x.Close).ToArray();
        double[] returns = LogReturns(close);
        double[] benchmarkClose = benchmarkOrdered.Select(x => x.Close).ToArray();
        double[] benchmarkReturns = benchmarkClose.Length >= 61 ? LogReturns(benchmarkClose) : [];
        double[] volume = ordered.Select(x => x.Volume).ToArray();
        double[] dollarVolume = ordered.Select(x => x.Volume * x.Close).ToArray();
        double downsideVolatility = StandardDeviation(returns.TakeLast(20).Where(x => x < 0).ToArray()) *
            Math.Sqrt(AnnualizationSessions);

        Dictionary<string, double> values = new(StringComparer.Ordinal)
        {
            ["return_1s"] = Return(close, 1),
            ["return_3s"] = Return(close, 3),
            ["return_5s"] = Return(close, 5),
            ["return_10s"] = Return(close, 10),
            ["return_20s"] = Return(close, 20),
            ["return_60s"] = Return(close, 60),
            ["return_120s"] = Return(close, 120),
            ["volatility_5s"] = AnnualizedVolatility(returns, 5),
            ["volatility_20s"] = AnnualizedVolatility(returns, 20),
            ["volatility_60s"] = AnnualizedVolatility(returns, 60),
            ["downside_volatility_20s"] = downsideVolatility,
            ["rsi_14"] = Rsi(close, 14) / 100,
            ["macd_normalized"] = Macd(close) / close[^1],
            ["atr_14_normalized"] = Atr(ordered, 14) / close[^1],
            ["bollinger_width_20"] = BollingerWidth(close, 20),
            ["ma_ratio_5s"] = close[^1] / Mean(close, 5) - 1,
            ["ma_ratio_20s"] = close[^1] / Mean(close, 20) - 1,
            ["ma_ratio_60s"] = close[^1] / Mean(close, 60) - 1,
            ["ma_ratio_200s"] = close[^1] / Mean(close, 200) - 1,
            ["ma_slope_20s"] = Mean(close, 5) / Mean(close.SkipLast(5).ToArray(), 20) - 1,
            ["volume_zscore_20s"] = ZScore(volume, 20),
            ["dollar_volume_zscore_20s"] = ZScore(dollarVolume, 20),
            ["overnight_gap_1s"] = ordered[^2].Close == 0 ? 0 : Math.Log(ordered[^1].Open / ordered[^2].Close),
            ["intraday_return_1s"] = ordered[^1].Open == 0 ? 0 : Math.Log(ordered[^1].Close / ordered[^1].Open),
            ["benchmark_correlation_20s"] = Correlation(returns, benchmarkReturns, 20),
            ["benchmark_correlation_60s"] = Correlation(returns, benchmarkReturns, 60),
            ["benchmark_beta_20s"] = Beta(returns, benchmarkReturns, 20),
            ["relative_strength_20s"] = Return(close, 20) -
                (benchmarkClose.Length >= 21 ? Return(benchmarkClose, 20) : 0),
            ["market_breadth_20s"] = Math.Clamp(marketBreadth20Sessions, 0, 1),
            ["market_regime"] = Regime(close, returns),
            ["momentum_rank_20s"] = Math.Clamp(momentumRank20Sessions, 0, 1),
            ["momentum_rank_60s"] = Math.Clamp(momentumRank60Sessions, 0, 1),
            ["volatility_rank_20s"] = Math.Clamp(volatilityRank20Sessions, 0, 1)
        };

        foreach ((string key, double value) in values.ToArray())
        {
            if (!double.IsFinite(value))
            {
                values[key] = 0;
            }
        }

        return new FeatureVector(ordered[^1].Time, EquityFeatureSchema.Version, values);
    }

    private static double Return(double[] values, int sessions) => Math.Log(values[^1] / values[^(sessions + 1)]);

    private static double[] LogReturns(double[] values) => values.Skip(1)
        .Select((value, index) => Math.Log(value / values[index]))
        .ToArray();

    private static double AnnualizedVolatility(double[] returns, int sessions) =>
        StandardDeviation(returns.TakeLast(sessions).ToArray()) * Math.Sqrt(AnnualizationSessions);

    private static double Mean(double[] values, int sessions) => values.TakeLast(sessions).Average();

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
        double[] tail = close.TakeLast(period + 1).ToArray();
        double[] changes = tail.Skip(1).Select((value, index) => value - tail[index]).ToArray();
        double gains = changes.Where(x => x > 0).Sum() / period;
        double losses = -changes.Where(x => x < 0).Sum() / period;
        return losses == 0 ? 100 : 100 - (100 / (1 + gains / losses));
    }

    private static double ExponentialMovingAverage(double[] values, int period)
    {
        double alpha = 2d / (period + 1);
        double ema = values[0];
        foreach (double value in values.Skip(1))
        {
            ema = alpha * value + (1 - alpha) * ema;
        }
        return ema;
    }

    private static double Macd(double[] close) =>
        ExponentialMovingAverage(close.TakeLast(120).ToArray(), 12) -
        ExponentialMovingAverage(close.TakeLast(120).ToArray(), 26);

    private static double Atr(MarketObservation[] observations, int period)
    {
        MarketObservation[] tail = observations.TakeLast(period + 1).ToArray();
        return tail.Skip(1).Select((value, index) => Math.Max(
            value.High - value.Low,
            Math.Max(Math.Abs(value.High - tail[index].Close), Math.Abs(value.Low - tail[index].Close))))
            .Average();
    }

    private static double BollingerWidth(double[] close, int period)
    {
        double[] tail = close.TakeLast(period).ToArray();
        double mean = tail.Average();
        return mean == 0 ? 0 : 4 * StandardDeviation(tail) / mean;
    }

    private static double ZScore(double[] values, int period)
    {
        double[] tail = values.TakeLast(period).ToArray();
        double standardDeviation = StandardDeviation(tail);
        return standardDeviation == 0 ? 0 : (tail[^1] - tail.Average()) / standardDeviation;
    }

    private static double Correlation(double[] left, double[] right, int period)
    {
        if (left.Length < period || right.Length < period)
        {
            return 0;
        }
        double[] x = left.TakeLast(period).ToArray();
        double[] y = right.TakeLast(period).ToArray();
        double xMean = x.Average();
        double yMean = y.Average();
        double denominator = StandardDeviation(x) * StandardDeviation(y);
        return denominator == 0
            ? 0
            : x.Zip(y, (a, b) => (a - xMean) * (b - yMean)).Sum() / (period - 1) / denominator;
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
        double xMean = x.Average();
        double yMean = y.Average();
        return x.Zip(y, (a, b) => (a - xMean) * (b - yMean)).Sum() / (period - 1) / variance;
    }

    private static double Regime(double[] close, double[] returns)
    {
        double trend = close[^1] / Mean(close, 60) - 1;
        double volatility = AnnualizedVolatility(returns, 20);
        if (Math.Abs(trend) < 0.03)
        {
            return 0;
        }
        if (trend > 0)
        {
            return volatility < 0.35 ? 1 : 2;
        }
        return volatility < 0.35 ? -1 : -2;
    }
}
