using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Application.Analysis;
using Probora.Domain.Analysis;
using Probora.Domain.Markets;
using Probora.Infrastructure.Persistence;
using Probora.ML.Runtime.Features;
using Probora.ML.Runtime.Inference;
using Probora.Worker.MarketData;
using Quartz;

namespace Probora.Worker.Models;

[DisallowConcurrentExecution]
public sealed class DailyPredictionJob(
    ProboraDbContext dbContext,
    IOptions<BinanceFuturesOptions> futuresOptions,
    TimeProvider timeProvider,
    ILogger<DailyPredictionJob> logger) : IJob
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly BinanceFuturesOptions _futuresOptions = futuresOptions.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        DateTimeOffset inferenceTime = timeProvider.GetUtcNow();
        DateTimeOffset targetCutoff = new(
            inferenceTime.Year,
            inferenceTime.Month,
            inferenceTime.Day,
            0,
            0,
            0,
            TimeSpan.Zero);
        await ExecuteCryptoAsync(context, inferenceTime, targetCutoff);
        await ExecuteEquityAsync(context, inferenceTime);
    }

    private async Task ExecuteCryptoAsync(
        IJobExecutionContext context,
        DateTimeOffset inferenceTime,
        DateTimeOffset targetCutoff)
    {
        List<ModelVersion> models = await dbContext.ModelVersions
            .Where(x => x.AssetClass == AssetClasses.Crypto && (x.IsProduction || x.IsShadowCandidate) &&
                        (x.HorizonDays == 30 || x.HorizonDays == 90))
            .ToListAsync(context.CancellationToken);
        if (models.Count == 0)
        {
            logger.LogInformation("No production or shadow-candidate model is registered; daily inference is safely skipped.");
            return;
        }

        int shadowPredictionsWritten = 0;
        int productionPredictionsWritten = 0;

        List<Asset> assets = await dbContext.Assets
            .Where(x => x.IsActive && x.AssetClass == AssetClasses.Crypto)
            .ToListAsync(context.CancellationToken);
        Dictionary<Guid, MarketObservation[]> observations = new();
        foreach (Asset asset in assets)
        {
            DateTimeOffset since = targetCutoff.AddDays(-410);
            List<PriceBar> bars = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.Interval == "1h" && x.IsFinal &&
                            x.OpenTime >= since && x.OpenTime < targetCutoff)
                .OrderBy(x => x.OpenTime)
                .ToListAsync(context.CancellationToken);
            observations[asset.Id] = AggregateDaily(bars);
        }

        Asset? bitcoin = assets.SingleOrDefault(x => x.Symbol == "BTCUSDT");
        if (bitcoin is null || observations[bitcoin.Id].Length < 365 ||
            observations[bitcoin.Id][^1].Time != targetCutoff)
        {
            logger.LogWarning("BTC spot history is not complete at UTC cutoff {Cutoff}; inference is deferred.", targetCutoff);
            return;
        }

        foreach (Asset asset in assets)
        {
            MarketObservation[] history = observations[asset.Id];
            if (history.Length < 365 || history[^1].Time != targetCutoff)
            {
                logger.LogWarning("Spot history for {Symbol} is not complete at UTC cutoff {Cutoff}.", asset.Symbol, targetCutoff);
                continue;
            }
            List<DerivativeDailySnapshot> derivativeSnapshots = await dbContext.DerivativeDailySnapshots.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.Source.StartsWith("binance-usdm") &&
                            x.SnapshotTime <= targetCutoff &&
                            x.SnapshotTime >= targetCutoff.AddDays(-_futuresOptions.RequiredHistoryDays - 7))
                .OrderBy(x => x.SnapshotTime)
                .ToListAsync(context.CancellationToken);
            if (!DerivativeHistoryReadiness.TryCreate(
                    derivativeSnapshots,
                    targetCutoff,
                    inferenceTime,
                    _futuresOptions.RequiredHistoryDays,
                    out DerivativeObservation[] derivativeHistory,
                    out string readinessReason))
            {
                logger.LogWarning(
                    "Derivative history for {Symbol} is not ready at {Cutoff}: {Reason}",
                    asset.Symbol,
                    targetCutoff,
                    readinessReason);
                continue;
            }
            double breadth = CalculateBreadth(observations.Values);
            FeatureVector vector = FeatureVectorBuilder.Build(
                history,
                observations[bitcoin.Id],
                breadth,
                derivativeHistory);
            FeatureSnapshot snapshot = await GetOrCreateSnapshotAsync(
                asset,
                vector,
                history,
                derivativeHistory,
                context.CancellationToken);

            foreach (ModelVersion model in models)
            {
                bool alreadyExists = await dbContext.Predictions.AnyAsync(
                    x => x.AssetId == asset.Id && x.ModelVersionId == model.Id &&
                         x.HorizonDays == model.HorizonDays &&
                         x.AnalysisTime == vector.SnapshotTime,
                    context.CancellationToken);
                if (alreadyExists)
                {
                    continue;
                }

                using OnnxModelBundle bundle = OnnxModelBundle.Load(model.ArtifactPath);
                RuntimePrediction prediction = bundle.Predict(vector);
                bool isFresh = vector.SnapshotTime == targetCutoff &&
                    inferenceTime - history[^1].Time <= TimeSpan.FromHours(26);
                bool featuresComplete = vector.Values["derivatives_available"] >= 0.5;
                ConfidenceDecision confidence = ConfidenceGate.Evaluate(new ConfidenceInput(
                    prediction.Up,
                    prediction.Neutral,
                    prediction.Down,
                    prediction.P50,
                    prediction.P90 - prediction.P10,
                    isFresh,
                    featuresComplete,
                    bundle.Manifest.MinimumProbability,
                    bundle.Manifest.MinimumMargin));
                if (!bundle.Manifest.DirectionEligible)
                {
                    confidence = confidence with
                    {
                        Status = AnalysisStatus.InsufficientConfidence,
                        Score = Math.Min(confidence.Score, 0.49),
                        Level = "ResearchOnly"
                    };
                }
                (IReadOnlyList<string> positive, IReadOnlyList<string> negative) =
                    bundle.Manifest.DirectionEligible
                        ? Explain(bundle, vector, prediction)
                        : (Array.Empty<string>(), Array.Empty<string>());
                dbContext.Predictions.Add(new PredictionRecord
                {
                    AssetId = asset.Id,
                    ModelVersionId = model.Id,
                    FeatureSnapshotId = snapshot.Id,
                    AnalysisTime = vector.SnapshotTime,
                    HorizonDays = model.HorizonDays,
                    UpProbability = prediction.Up,
                    NeutralProbability = prediction.Neutral,
                    DownProbability = prediction.Down,
                    ReturnP10 = prediction.P10,
                    ReturnP50 = prediction.P50,
                    ReturnP90 = prediction.P90,
                    RiskScore = prediction.RiskScore,
                    RiskLevel = ToRiskLevel(prediction.RiskScore),
                    ConfidenceScore = confidence.Score,
                    Status = confidence.Status,
                    PositiveFactorsJson = JsonSerializer.Serialize(positive, JsonOptions),
                    NegativeFactorsJson = JsonSerializer.Serialize(negative, JsonOptions),
                    LimitationsJson = JsonSerializer.Serialize(
                        BuildLimitations(bundle.Manifest, isEquity: false), JsonOptions),
                    ArtifactSha256 = model.ArtifactSha256,
                    IsShadow = !model.IsProduction,
                    CreatedAt = timeProvider.GetUtcNow()
                });
                if (model.IsProduction)
                {
                    productionPredictionsWritten++;
                }
                else
                {
                    shadowPredictionsWritten++;
                }
            }
        }

        await dbContext.SaveChangesAsync(context.CancellationToken);
        logger.LogInformation(
            "Daily inference for cutoff {Cutoff} wrote {ShadowCount} shadow and {ProductionCount} production predictions.",
            targetCutoff,
            shadowPredictionsWritten,
            productionPredictionsWritten);
    }

    private async Task ExecuteEquityAsync(IJobExecutionContext context, DateTimeOffset inferenceTime)
    {
        CancellationToken cancellationToken = context.CancellationToken;
        List<ModelVersion> models = await dbContext.ModelVersions
            .Where(x => x.AssetClass == AssetClasses.UsEquity && x.IsShadowCandidate && !x.IsProduction &&
                        (x.HorizonDays == 30 || x.HorizonDays == 90))
            .ToListAsync(cancellationToken);
        if (models.Count == 0)
        {
            logger.LogInformation("No US-equity shadow candidate is registered; EOD inference is safely skipped.");
            return;
        }

        List<Asset> assets = await dbContext.Assets
            .Where(x => x.AssetClass == AssetClasses.UsEquity && x.IsShadowEnabled)
            .OrderBy(x => x.Symbol)
            .ToListAsync(cancellationToken);
        Dictionary<Guid, MarketObservation[]> observations = new();
        foreach (Asset asset in assets)
        {
            List<PriceBar> bars = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.Interval == "1d" && x.IsFinal &&
                            x.Source == TwelveDataOptions.Source)
                .OrderByDescending(x => x.OpenTime)
                .Take(420)
                .OrderBy(x => x.OpenTime)
                .ToListAsync(cancellationToken);
            observations[asset.Id] = bars.Select(x => new MarketObservation(
                x.OpenTime.AddDays(1),
                (double)x.Open,
                (double)x.High,
                (double)x.Low,
                (double)x.Close,
                (double)x.Volume,
                (double)x.QuoteVolume,
                x.TradeCount,
                (double)x.TakerBuyBaseVolume)).ToArray();
        }

        Asset? benchmark = assets.SingleOrDefault(x => x.Symbol == "SPY");
        if (benchmark is null || observations[benchmark.Id].Length < 252)
        {
            logger.LogWarning("SPY EOD history is not ready; US-equity shadow inference is deferred.");
            return;
        }
        DateTimeOffset latestSessionCutoff = observations[benchmark.Id][^1].Time;
        if (latestSessionCutoff > inferenceTime || inferenceTime - latestSessionCutoff > TimeSpan.FromDays(5))
        {
            logger.LogWarning(
                "SPY EOD cutoff {Cutoff} is stale or unavailable; US-equity shadow inference is deferred.",
                latestSessionCutoff);
            return;
        }

        int written = 0;
        foreach (Asset asset in assets)
        {
            MarketObservation[] history = observations[asset.Id];
            if (history.Length < 252 || history[^1].Time != latestSessionCutoff)
            {
                logger.LogWarning(
                    "EOD history for {Symbol} does not match SPY cutoff {Cutoff}.",
                    asset.Symbol,
                    latestSessionCutoff);
                continue;
            }

            (double breadth, double momentum20, double momentum60, double volatility20) =
                CalculateEquityCrossSection(asset.Id, observations, latestSessionCutoff);
            FeatureVector vector = EquityFeatureVectorBuilder.Build(
                history,
                observations[benchmark.Id],
                breadth,
                momentum20,
                momentum60,
                volatility20);
            FeatureSnapshot snapshot = await GetOrCreateSnapshotAsync(
                asset,
                vector,
                history,
                [],
                cancellationToken);

            foreach (ModelVersion model in models)
            {
                bool alreadyExists = await dbContext.Predictions.AnyAsync(
                    x => x.AssetId == asset.Id && x.ModelVersionId == model.Id &&
                         x.HorizonDays == model.HorizonDays && x.AnalysisTime == vector.SnapshotTime,
                    cancellationToken);
                if (alreadyExists)
                {
                    continue;
                }

                using OnnxModelBundle bundle = OnnxModelBundle.Load(model.ArtifactPath);
                RuntimePrediction prediction = bundle.Predict(vector);
                ConfidenceDecision confidence = ConfidenceGate.Evaluate(new ConfidenceInput(
                    prediction.Up,
                    prediction.Neutral,
                    prediction.Down,
                    prediction.P50,
                    prediction.P90 - prediction.P10,
                    true,
                    true,
                    bundle.Manifest.MinimumProbability,
                    bundle.Manifest.MinimumMargin));
                if (!bundle.Manifest.DirectionEligible)
                {
                    confidence = confidence with
                    {
                        Status = AnalysisStatus.InsufficientConfidence,
                        Score = Math.Min(confidence.Score, 0.49),
                        Level = "ResearchOnly"
                    };
                }
                (IReadOnlyList<string> positive, IReadOnlyList<string> negative) =
                    bundle.Manifest.DirectionEligible
                        ? Explain(bundle, vector, prediction)
                        : (Array.Empty<string>(), Array.Empty<string>());
                dbContext.Predictions.Add(new PredictionRecord
                {
                    AssetId = asset.Id,
                    ModelVersionId = model.Id,
                    FeatureSnapshotId = snapshot.Id,
                    AnalysisTime = vector.SnapshotTime,
                    HorizonDays = model.HorizonDays,
                    UpProbability = prediction.Up,
                    NeutralProbability = prediction.Neutral,
                    DownProbability = prediction.Down,
                    ReturnP10 = prediction.P10,
                    ReturnP50 = prediction.P50,
                    ReturnP90 = prediction.P90,
                    RiskScore = prediction.RiskScore,
                    RiskLevel = ToRiskLevel(prediction.RiskScore),
                    ConfidenceScore = confidence.Score,
                    Status = confidence.Status,
                    PositiveFactorsJson = JsonSerializer.Serialize(positive, JsonOptions),
                    NegativeFactorsJson = JsonSerializer.Serialize(negative, JsonOptions),
                    LimitationsJson = JsonSerializer.Serialize(
                        BuildLimitations(bundle.Manifest, isEquity: true), JsonOptions),
                    ArtifactSha256 = model.ArtifactSha256,
                    IsShadow = true,
                    CreatedAt = timeProvider.GetUtcNow()
                });
                written++;
            }
        }

        await dbContext.SaveChangesAsync(cancellationToken);
        logger.LogInformation(
            "US-equity EOD inference for cutoff {Cutoff} wrote {Count} shadow predictions.",
            latestSessionCutoff,
            written);
    }

    private async Task<FeatureSnapshot> GetOrCreateSnapshotAsync(
        Asset asset,
        FeatureVector vector,
        MarketObservation[] history,
        DerivativeObservation[] derivatives,
        CancellationToken cancellationToken)
    {
        FeatureSnapshot? existing = await dbContext.FeatureSnapshots.SingleOrDefaultAsync(
            x => x.AssetId == asset.Id && x.SnapshotTime == vector.SnapshotTime &&
                 x.FeatureSetVersion == vector.FeatureSetVersion,
            cancellationToken);
        if (existing is not null)
        {
            return existing;
        }
        string dataIdentity = string.Join('|', history.TakeLast(200)
            .Select(x => $"{x.Time:O}:{x.Close:R}:{x.Volume:R}")) + "|" +
            string.Join('|', derivatives.Select(x =>
                $"{x.Time:O}:{x.FundingRate:R}:{x.Premium:R}:{x.OpenInterestValue:R}"));
        FeatureSnapshot snapshot = new()
        {
            Id = Guid.NewGuid(),
            AssetId = asset.Id,
            SnapshotTime = vector.SnapshotTime,
            FeatureSetVersion = vector.FeatureSetVersion,
            FeaturesJson = JsonSerializer.Serialize(vector.Values, JsonOptions),
            InputDataSha256 = Convert.ToHexString(
                SHA256.HashData(Encoding.UTF8.GetBytes(dataIdentity))).ToLowerInvariant(),
            CreatedAt = timeProvider.GetUtcNow()
        };
        dbContext.FeatureSnapshots.Add(snapshot);
        return snapshot;
    }

    private static MarketObservation[] AggregateDaily(IReadOnlyCollection<PriceBar> bars) => bars
        .GroupBy(x => new DateTimeOffset(
            x.OpenTime.Year,
            x.OpenTime.Month,
            x.OpenTime.Day,
            0,
            0,
            0,
            TimeSpan.Zero))
        .OrderBy(x => x.Key)
        .Where(group => IsCompleteUtcDay(group.Key, group.OrderBy(x => x.OpenTime).ToArray()))
        .Select(group => new MarketObservation(
            group.Key.AddDays(1),
            (double)group.First().Open,
            (double)group.Max(x => x.High),
            (double)group.Min(x => x.Low),
            (double)group.Last().Close,
            (double)group.Sum(x => x.Volume),
            (double)group.Sum(x => x.QuoteVolume),
            group.Sum(x => (double)x.TradeCount),
            (double)group.Sum(x => x.TakerBuyBaseVolume)))
        .ToArray();

    private static bool IsCompleteUtcDay(DateTimeOffset day, IReadOnlyList<PriceBar> bars)
    {
        if (bars.Count != 24)
        {
            return false;
        }
        for (int hour = 0; hour < 24; hour++)
        {
            if (bars[hour].OpenTime != day.AddHours(hour) || bars[hour].CloseTime >= day.AddDays(1))
            {
                return false;
            }
        }
        return true;
    }

    private static double CalculateBreadth(IEnumerable<MarketObservation[]> all) =>
        all.Where(x => x.Length >= 31)
            .Select(x => Math.Log(x[^1].Close / x[^31].Close) > 0 ? 1d : 0d)
            .DefaultIfEmpty(0.5)
        .Average();

    private static (double Breadth, double Momentum20, double Momentum60, double Volatility20)
        CalculateEquityCrossSection(
            Guid assetId,
            IReadOnlyDictionary<Guid, MarketObservation[]> all,
            DateTimeOffset cutoff)
    {
        static double Return(MarketObservation[] values, int sessions) =>
            Math.Log(values[^1].Close / values[^(sessions + 1)].Close);
        static double Volatility(MarketObservation[] values, int sessions)
        {
            MarketObservation[] tail = values.TakeLast(sessions + 1).ToArray();
            double[] returns = tail.Skip(1)
                .Select((value, index) => Math.Log(value.Close / tail[index].Close))
                .ToArray();
            if (returns.Length < 2)
            {
                return 0;
            }
            double mean = returns.Average();
            return Math.Sqrt(returns.Sum(x => Math.Pow(x - mean, 2)) / (returns.Length - 1)) * Math.Sqrt(252);
        }
        static double Rank(double value, IReadOnlyCollection<double> peers) =>
            peers.Count == 0 ? 0.5 : peers.Count(x => x <= value) / (double)peers.Count;

        Dictionary<Guid, MarketObservation[]> eligible = all
            .Where(x => x.Value.Length >= 61 && x.Value[^1].Time == cutoff)
            .ToDictionary();
        double[] momentum20 = eligible.Values.Select(x => Return(x, 20)).ToArray();
        double[] momentum60 = eligible.Values.Select(x => Return(x, 60)).ToArray();
        double[] volatility20 = eligible.Values.Select(x => Volatility(x, 20)).ToArray();
        MarketObservation[] current = eligible[assetId];
        return (
            momentum20.Count(x => x > 0) / (double)Math.Max(1, momentum20.Length),
            Rank(Return(current, 20), momentum20),
            Rank(Return(current, 60), momentum60),
            Rank(Volatility(current, 20), volatility20));
    }

    private static (IReadOnlyList<string> Positive, IReadOnlyList<string> Negative) Explain(
        OnnxModelBundle bundle,
        FeatureVector vector,
        RuntimePrediction baseline)
    {
        double baselineScore = baseline.Up - baseline.Down;
        List<(string Name, double Delta, double Current, double Reference)> impacts = [];
        foreach (string feature in bundle.FeatureNames)
        {
            double current = vector.Values[feature];
            double reference = DefaultFeatureReference(feature, current);
            if (bundle.Manifest.FeatureReference is not null &&
                bundle.Manifest.FeatureReference.TryGetValue(feature, out double learnedReference) &&
                double.IsFinite(learnedReference))
            {
                reference = learnedReference;
            }
            if (Math.Abs(current - reference) < 1e-12)
            {
                continue;
            }
            Dictionary<string, double> perturbed = new(vector.Values, StringComparer.Ordinal)
            {
                [feature] = reference
            };
            RuntimePrediction result = bundle.Predict(
                new FeatureVector(vector.SnapshotTime, vector.FeatureSetVersion, perturbed));
            impacts.Add((feature, baselineScore - (result.Up - result.Down), current, reference));
        }
        string Describe((string Name, double Delta, double Current, double Reference) item)
        {
            string position = item.Current >= item.Reference
                ? "eğitim referansının üzerinde"
                : "eğitim referansının altında";
            string sign = item.Delta >= 0 ? "+" : "−";
            return $"{FeatureLabel(item.Name)} {position}: {sign}{Math.Abs(item.Delta) * 100:0.0} olasılık puanı";
        }
        return (
            impacts.Where(x => x.Delta > 0).OrderByDescending(x => x.Delta).Take(3).Select(Describe).ToArray(),
            impacts.Where(x => x.Delta < 0).OrderBy(x => x.Delta).Take(3).Select(Describe).ToArray());
    }

    private static IReadOnlyList<string> BuildLimitations(ModelManifest manifest, bool isEquity)
    {
        List<string> limitations = [];
        if (!manifest.DirectionEligible)
        {
            limitations.Add("Yön modeli doğrulama kapısını geçmedi; yön sinyali otomatik olarak bastırılmıştır.");
        }
        if (!manifest.ScenarioEligible)
        {
            limitations.Add("Getiri aralığı ve risk tahmini henüz senaryo doğrulama kapısını geçmemiştir.");
        }
        if (isEquity)
        {
            limitations.Add("ABD hissesi EOD shadow modelidir; kullanıcı sinyali değildir.");
            limitations.Add("Tahmin ufku işlem seansı cinsindendir.");
        }
        else
        {
            limitations.Add("Haber sinyali v2 tahminine dahil değildir.");
        }
        limitations.Add("Faktör katkıları nedensellik değil, model içi referans karşılaştırmasıdır.");
        limitations.Add("Bu analiz yatırım tavsiyesi değildir.");
        return limitations;
    }

    private static double DefaultFeatureReference(string name, double current) => name switch
    {
        "rsi_14" => 0.5,
        "market_breadth_20s" or "market_breadth_30d" => 0.5,
        "momentum_rank_20s" or "momentum_rank_30d" or
        "momentum_rank_60s" or "momentum_rank_90d" or
        "volatility_rank_20s" or "volatility_rank_30d" => 0.5,
        "benchmark_beta_20s" or "btc_beta_30d" => 1,
        "derivatives_available" => current,
        _ => 0
    };

    private static string FeatureLabel(string name) => name switch
    {
        "return_30d" => "30 günlük momentum",
        "return_90d" => "90 günlük momentum",
        "return_5s" => "5 seanslık momentum",
        "return_20s" => "20 seanslık momentum",
        "return_60s" => "60 seanslık momentum",
        "return_120s" => "120 seanslık momentum",
        "volatility_30d" => "30 günlük oynaklık",
        "volatility_20s" => "20 seanslık oynaklık",
        "volatility_60s" => "60 seanslık oynaklık",
        "downside_volatility_20s" => "aşağı yönlü oynaklık",
        "rsi_14" => "RSI dengesi",
        "macd_normalized" => "MACD eğilimi",
        "volume_zscore_30d" => "olağandışı hacim",
        "volume_zscore_20s" => "olağandışı işlem hacmi",
        "dollar_volume_zscore_20s" => "olağandışı dolar hacmi",
        "overnight_gap_1s" => "gece fiyat boşluğu",
        "intraday_return_1s" => "seans içi hareket",
        "relative_strength_30d" => "BTC'ye göre göreceli güç",
        "relative_strength_20s" => "SPY'a göre göreceli güç",
        "benchmark_correlation_60s" => "SPY korelasyonu",
        "benchmark_beta_20s" => "SPY beta duyarlılığı",
        "market_breadth_20s" => "piyasa genişliği",
        "momentum_rank_20s" => "kısa dönem momentum sırası",
        "momentum_rank_60s" => "orta dönem momentum sırası",
        "volatility_rank_20s" => "oynaklık sırası",
        "market_regime" => "piyasa rejimi",
        _ => name.Replace('_', ' ')
    };

    private static RiskLevel ToRiskLevel(double score) => score switch
    {
        < 0.25 => RiskLevel.Low,
        < 0.50 => RiskLevel.Medium,
        < 0.75 => RiskLevel.High,
        _ => RiskLevel.VeryHigh
    };
}
