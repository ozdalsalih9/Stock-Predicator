using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Probora.Application.Abstractions;
using Probora.Contracts.Analysis;
using Probora.Contracts.Assets;
using Probora.Contracts.News;
using Probora.Contracts.System;
using Probora.Domain.Analysis;
using Probora.Domain.Markets;
using Probora.Domain.Operations;
using Probora.Infrastructure.Persistence;

namespace Probora.Infrastructure.Queries;

public sealed class ProboraQueryService(ProboraDbContext dbContext, TimeProvider timeProvider) : IProboraQueryService
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    public async Task<IReadOnlyList<AssetResponse>> GetAssetsAsync(CancellationToken cancellationToken)
    {
        List<Asset> assets = await dbContext.Assets.AsNoTracking()
            .Where(x => x.IsActive || x.IsShadowEnabled)
            .OrderBy(x => x.AssetClass)
            .ThenBy(x => x.Symbol)
            .ToListAsync(cancellationToken);
        List<AssetResponse> response = [];

        foreach (Asset asset in assets)
        {
            PriceBar? latest = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.IsFinal)
                .OrderByDescending(x => x.CloseTime)
                .FirstOrDefaultAsync(cancellationToken);

            response.Add(new AssetResponse(
                asset.Symbol,
                asset.BaseAsset,
                asset.QuoteAsset,
                asset.DisplayName,
                asset.AssetClass,
                asset.Exchange,
                asset.DataStartsAt,
                latest?.Close,
                latest?.CloseTime,
                FreshnessState(latest?.CloseTime, TimeSpan.FromHours(2))));
        }

        return response;
    }

    public async Task<IReadOnlyList<PriceBarResponse>?> GetBarsAsync(
        string symbol,
        string interval,
        DateTimeOffset? from,
        DateTimeOffset? to,
        int limit,
        CancellationToken cancellationToken)
    {
        Asset? asset = await dbContext.Assets.AsNoTracking()
            .SingleOrDefaultAsync(x => x.Symbol == symbol.ToUpper(), cancellationToken);
        if (asset is null)
        {
            return null;
        }

        IQueryable<PriceBar> query = dbContext.PriceBars.AsNoTracking()
            .Where(x => x.AssetId == asset.Id && x.Interval == interval);
        if (from.HasValue)
        {
            query = query.Where(x => x.OpenTime >= from.Value);
        }
        if (to.HasValue)
        {
            query = query.Where(x => x.OpenTime <= to.Value);
        }

        return await query.OrderByDescending(x => x.OpenTime).Take(limit).OrderBy(x => x.OpenTime)
            .Select(x => new PriceBarResponse(
                x.OpenTime,
                x.CloseTime,
                x.Interval,
                x.Open,
                x.High,
                x.Low,
                x.Close,
                x.Volume,
                x.TradeCount,
                x.IsFinal))
            .ToListAsync(cancellationToken);
    }

    public async Task<AnalysisResponse?> GetLatestAnalysisAsync(
        string symbol,
        int horizonDays,
        bool includeShadowPreview,
        CancellationToken cancellationToken)
    {
        var result = await (
            from prediction in dbContext.Predictions.AsNoTracking()
            join asset in dbContext.Assets.AsNoTracking() on prediction.AssetId equals asset.Id
            join model in dbContext.ModelVersions.AsNoTracking() on prediction.ModelVersionId equals model.Id
            join feature in dbContext.FeatureSnapshots.AsNoTracking() on prediction.FeatureSnapshotId equals feature.Id
            where asset.Symbol == symbol.ToUpper() && prediction.HorizonDays == horizonDays &&
                  ((model.IsProduction && !prediction.IsShadow) ||
                   (includeShadowPreview && model.IsShadowCandidate && prediction.IsShadow))
            orderby model.IsProduction descending, prediction.AnalysisTime descending
            select new { prediction, asset, model, feature })
            .FirstOrDefaultAsync(cancellationToken);

        if (result is null)
        {
            return null;
        }

        PriceBar? latestPrice = await dbContext.PriceBars.AsNoTracking()
            .Where(x => x.AssetId == result.asset.Id && x.IsFinal)
            .OrderByDescending(x => x.CloseTime)
            .FirstOrDefaultAsync(cancellationToken);
        DateTimeOffset? latestNews = await dbContext.NewsArticles.AsNoTracking()
            .Where(x => x.AssetId == result.asset.Id)
            .MaxAsync(x => (DateTimeOffset?)x.PublishedAt, cancellationToken);

        string freshnessState = FreshnessState(latestPrice?.CloseTime, TimeSpan.FromHours(26));
        return new AnalysisResponse(
            result.asset.Symbol,
            result.prediction.AnalysisTime,
            result.prediction.HorizonDays,
            new ProbabilityResponse(result.prediction.UpProbability, result.prediction.NeutralProbability, result.prediction.DownProbability),
            new ReturnRangeResponse(result.prediction.ReturnP10, result.prediction.ReturnP50, result.prediction.ReturnP90),
            result.prediction.RiskScore,
            result.prediction.RiskLevel.ToString(),
            result.prediction.ConfidenceScore,
            ConfidenceLevel(result.prediction.ConfidenceScore),
            ToContractStatus(result.prediction.Status),
            result.prediction.IsShadow,
            result.model.DirectionEligible,
            result.model.ScenarioEligible,
            DeserializeList(result.prediction.PositiveFactorsJson),
            DeserializeList(result.prediction.NegativeFactorsJson),
            new FreshnessResponse(latestPrice?.CloseTime, result.feature.SnapshotTime, latestNews, freshnessState),
            result.model.Version,
            result.model.FeatureSetVersion,
            result.model.DatasetVersion,
            DeserializeList(result.prediction.LimitationsJson));
    }

    public async Task<ModelCardResponse?> GetModelCardAsync(string version, CancellationToken cancellationToken)
    {
        ModelVersion? model = await dbContext.ModelVersions.AsNoTracking()
            .SingleOrDefaultAsync(x => x.Version == version, cancellationToken);
        if (model is null)
        {
            return null;
        }

        Dictionary<string, double> metrics = DeserializeDictionary(model.MetricsJson);
        return new ModelCardResponse(
            model.Version,
            model.HorizonDays,
            model.FeatureSetVersion,
            model.DatasetVersion,
            model.TrainedAt,
            model.IsProduction,
            model.DirectionEligible,
            model.ScenarioEligible,
            metrics,
            [
                "Kripto piyasaları yüksek oynaklığa sahiptir.",
                "Geçmiş performans gelecekteki sonuçları garanti etmez.",
                "Haber sinyali v1 modelinde aktif değildir."
            ]);
    }

    public async Task<PerformanceResponse?> GetPerformanceAsync(
        string? symbol,
        int horizonDays,
        CancellationToken cancellationToken)
    {
        ModelVersion? model = await dbContext.ModelVersions.AsNoTracking()
            .Where(x => x.AssetClass == AssetClasses.Crypto &&
                        x.HorizonDays == horizonDays && x.IsProduction)
            .OrderByDescending(x => x.TrainedAt)
            .FirstOrDefaultAsync(cancellationToken);
        if (model is null)
        {
            return null;
        }

        Dictionary<string, double> metrics = DeserializeDictionary(model.MetricsJson);
        return new PerformanceResponse(
            symbol?.ToUpperInvariant(),
            horizonDays,
            model.Version,
            GetMetric(metrics, "brier_score"),
            GetMetric(metrics, "baseline_brier_score"),
            GetMetric(metrics, "ece"),
            GetMetric(metrics, "directional_accuracy"),
            GetMetric(metrics, "interval_coverage"),
            (int)GetMetric(metrics, "sample_count"),
            model.TrainedAt);
    }

    public async Task<SystemFreshnessResponse> GetFreshnessAsync(CancellationToken cancellationToken)
    {
        List<DatasetFreshnessItem> items = [];
        List<Asset> assets = await dbContext.Assets.AsNoTracking().Where(x => x.IsActive).ToListAsync(cancellationToken);
        foreach (Asset asset in assets)
        {
            DateTimeOffset? latest = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.IsFinal)
                .MaxAsync(x => (DateTimeOffset?)x.CloseTime, cancellationToken);
            DateTimeOffset? ingestion = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id)
                .MaxAsync(x => (DateTimeOffset?)x.IngestedAt, cancellationToken);
            items.Add(new("price_bars", asset.Symbol, latest, ingestion, FreshnessState(latest, TimeSpan.FromHours(2))));
            DateTimeOffset? latestNews = await dbContext.NewsArticles.AsNoTracking()
                .Where(x => x.AssetId == asset.Id)
                .MaxAsync(x => (DateTimeOffset?)x.PublishedAt, cancellationToken);
            DateTimeOffset? newsIngestion = await dbContext.NewsArticles.AsNoTracking()
                .Where(x => x.AssetId == asset.Id)
                .MaxAsync(x => (DateTimeOffset?)x.RetrievedAt, cancellationToken);
            items.Add(new("news_shadow", asset.Symbol, latestNews, newsIngestion,
                FreshnessState(newsIngestion, TimeSpan.FromHours(2))));
        }

        return new SystemFreshnessResponse(timeProvider.GetUtcNow(), items);
    }

    public async Task<ShadowCollectorDashboardResponse> GetShadowCollectorDashboardAsync(
        CancellationToken cancellationToken)
    {
        const int requiredHistoryDays = 90;
        DateTimeOffset checkedAt = timeProvider.GetUtcNow();
        DateTimeOffset cutoff = new(
            checkedAt.Year,
            checkedAt.Month,
            checkedAt.Day,
            0,
            0,
            0,
            TimeSpan.Zero);
        DateTimeOffset sevenDaysAgo = checkedAt.AddDays(-7);
        List<Asset> assets = await dbContext.Assets.AsNoTracking()
            .Where(x => x.IsActive && x.AssetClass == AssetClasses.Crypto)
            .OrderBy(x => x.Symbol)
            .ToListAsync(cancellationToken);
        List<DerivativeDailySnapshot> snapshots = await dbContext.DerivativeDailySnapshots.AsNoTracking()
            .Where(x => x.IsComplete && x.SnapshotTime >= cutoff.AddDays(-requiredHistoryDays - 7))
            .OrderBy(x => x.SnapshotTime)
            .ToListAsync(cancellationToken);
        List<IngestionRun> runs = await dbContext.IngestionRuns.AsNoTracking()
            .Where(x => x.Source == "binance-usdm" && x.Dataset == "derivative_daily_shadow" &&
                        x.StartedAt >= sevenDaysAgo)
            .OrderByDescending(x => x.StartedAt)
            .ToListAsync(cancellationToken);
        int unresolvedIssues = await dbContext.DataQualityIssues.AsNoTracking()
            .CountAsync(x => x.Code == "DERIVATIVE_CUTOFF_INCOMPLETE" && !x.IsResolved, cancellationToken);

        List<ShadowCollectorAssetResponse> assetRows = [];
        foreach (Asset asset in assets)
        {
            DerivativeDailySnapshot[] history = snapshots.Where(x => x.AssetId == asset.Id)
                .OrderBy(x => x.SnapshotTime)
                .ToArray();
            DerivativeDailySnapshot? latest = history.LastOrDefault();
            int consecutiveDays = CountConsecutiveDays(history.Select(x => x.SnapshotTime));
            bool current = latest?.SnapshotTime == cutoff;
            string state = latest switch
            {
                null => "missing",
                _ when !current => "stale",
                _ when consecutiveDays >= requiredHistoryDays => "ready",
                _ => "warming"
            };
            assetRows.Add(new ShadowCollectorAssetResponse(
                asset.Symbol,
                latest?.SnapshotTime,
                latest?.AvailableAt,
                consecutiveDays,
                requiredHistoryDays,
                Math.Min(1, consecutiveDays / (double)requiredHistoryDays),
                latest is null ? null : (latest.AvailableAt - latest.SnapshotTime).TotalMinutes,
                state));
        }

        double[] sevenDayLatencies = snapshots
            .Where(x => x.SnapshotTime >= cutoff.AddDays(-6) && x.SnapshotTime <= cutoff)
            .Select(x => (x.AvailableAt - x.SnapshotTime).TotalMinutes)
            .Where(x => double.IsFinite(x) && x >= 0)
            .Order()
            .ToArray();
        int successfulRuns = runs.Count(x => x.Status == "succeeded");
        int cutoffComplete = assetRows.Count(x => x.LatestSnapshotAt == cutoff);
        int modelReady = assetRows.Count(x => x.State == "ready");
        string overallState = (cutoffComplete, modelReady, unresolvedIssues) switch
        {
            (_, _, > 0) => "degraded",
            var (complete, ready, _) when complete == assets.Count && ready == assets.Count => "healthy",
            var (complete, _, _) when complete == assets.Count => "warming",
            (0, 0, _) => "no_data",
            _ => "degraded"
        };

        return new ShadowCollectorDashboardResponse(
            checkedAt,
            cutoff,
            overallState,
            assets.Count,
            cutoffComplete,
            modelReady,
            requiredHistoryDays,
            unresolvedIssues,
            runs.Count,
            runs.Count == 0 ? null : successfulRuns / (double)runs.Count,
            sevenDayLatencies.Length == 0 ? null : sevenDayLatencies.Count(x => x <= 45) / (double)sevenDayLatencies.Length,
            sevenDayLatencies.Length == 0 ? null : sevenDayLatencies.Average(),
            Percentile95(sevenDayLatencies),
            assetRows,
            runs.Take(10).Select(x => new ShadowCollectorRunResponse(
                x.StartedAt,
                x.CompletedAt,
                x.Status,
                x.RecordsRead,
                x.RecordsWritten,
                x.CompletedAt.HasValue ? (x.CompletedAt.Value - x.StartedAt).TotalSeconds : null,
                x.Error)).ToArray());
    }

    public async Task<UsEquityShadowDashboardResponse> GetUsEquityShadowDashboardAsync(
        CancellationToken cancellationToken)
    {
        const string source = "twelvedata-us-eod-total-return";
        const int requiredHistoryBars = 90;
        DateTimeOffset checkedAt = timeProvider.GetUtcNow();
        List<Asset> assets = await dbContext.Assets.AsNoTracking()
            .Where(x => x.AssetClass == AssetClasses.UsEquity && x.IsShadowEnabled)
            .OrderBy(x => x.Symbol)
            .ToListAsync(cancellationToken);
        Guid[] assetIds = assets.Select(x => x.Id).ToArray();
        var summaries = await dbContext.PriceBars.AsNoTracking()
            .Where(x => assetIds.Contains(x.AssetId) && x.Source == source && x.Interval == "1d" && x.IsFinal)
            .GroupBy(x => x.AssetId)
            .Select(group => new
            {
                AssetId = group.Key,
                BarCount = group.LongCount(),
                FirstBarAt = (DateTimeOffset?)group.Min(x => x.OpenTime),
                LatestBarAt = (DateTimeOffset?)group.Max(x => x.OpenTime),
                LastIngestedAt = (DateTimeOffset?)group.Max(x => x.IngestedAt)
            })
            .ToListAsync(cancellationToken);
        var summariesByAsset = summaries.ToDictionary(x => x.AssetId);
        Asset? referenceAsset = assets.FirstOrDefault(x => x.Symbol == "SPY");
        DateTimeOffset? latestSessionAt = referenceAsset is not null &&
            summariesByAsset.TryGetValue(referenceAsset.Id, out var referenceSummary)
                ? referenceSummary.LatestBarAt
                : summaries.Select(x => x.LatestBarAt).Max();

        List<UsEquityShadowAssetResponse> rows = [];
        foreach (Asset asset in assets)
        {
            if (!summariesByAsset.TryGetValue(asset.Id, out var summary))
            {
                rows.Add(new UsEquityShadowAssetResponse(
                    asset.Symbol,
                    asset.DisplayName,
                    asset.Exchange,
                    0,
                    null,
                    null,
                    null,
                    requiredHistoryBars,
                    0,
                    "missing"));
                continue;
            }

            string state = summary.LatestBarAt != latestSessionAt
                ? "stale"
                : summary.BarCount >= requiredHistoryBars ? "ready" : "warming";
            rows.Add(new UsEquityShadowAssetResponse(
                asset.Symbol,
                asset.DisplayName,
                asset.Exchange,
                summary.BarCount,
                summary.FirstBarAt,
                summary.LatestBarAt,
                summary.LastIngestedAt,
                requiredHistoryBars,
                Math.Min(1, summary.BarCount / (double)requiredHistoryBars),
                state));
        }

        IngestionRun? latestRun = await dbContext.IngestionRuns.AsNoTracking()
            .Where(x => x.Source == source && x.Dataset == "us_equity_daily_shadow")
            .OrderByDescending(x => x.StartedAt)
            .FirstOrDefaultAsync(cancellationToken);
        int unresolvedIssues = await dbContext.DataQualityIssues.AsNoTracking()
            .CountAsync(x => x.Code == "US_EQUITY_SESSION_INCOMPLETE" && !x.IsResolved, cancellationToken);
        int readyAssets = rows.Count(x => x.State == "ready");
        string overallState = (rows.Count, readyAssets, unresolvedIssues) switch
        {
            (0, _, _) => "no_data",
            (_, _, > 0) => "degraded",
            var (total, ready, _) when total == ready => "healthy",
            (_, 0, _) => "no_data",
            _ => "warming"
        };

        return new UsEquityShadowDashboardResponse(
            checkedAt,
            overallState,
            "Twelve Data Basic",
            source,
            rows.Count,
            readyAssets,
            rows.Sum(x => x.BarCount),
            requiredHistoryBars,
            rows.Select(x => x.FirstBarAt).Where(x => x.HasValue).Min(),
            latestSessionAt,
            unresolvedIssues,
            latestRun is null ? null : new ShadowCollectorRunResponse(
                latestRun.StartedAt,
                latestRun.CompletedAt,
                latestRun.Status,
                latestRun.RecordsRead,
                latestRun.RecordsWritten,
                latestRun.CompletedAt.HasValue ? (latestRun.CompletedAt.Value - latestRun.StartedAt).TotalSeconds : null,
                latestRun.Error),
            rows);
    }

    public async Task<ShadowPredictionDashboardResponse> GetShadowPredictionDashboardAsync(
        CancellationToken cancellationToken)
    {
        DateTimeOffset checkedAt = timeProvider.GetUtcNow();
        List<ModelVersion> candidates = await dbContext.ModelVersions.AsNoTracking()
            .Where(x => x.IsShadowCandidate && !x.IsProduction &&
                        (x.AssetClass == AssetClasses.Crypto || x.AssetClass == AssetClasses.UsEquity) &&
                        (x.HorizonDays == 30 || x.HorizonDays == 90))
            .OrderBy(x => x.AssetClass)
            .ThenBy(x => x.HorizonDays)
            .ThenByDescending(x => x.TrainedAt)
            .ToListAsync(cancellationToken);
        Dictionary<string, int> totalAssetsByClass = await dbContext.Assets.AsNoTracking()
            .Where(x => (x.AssetClass == AssetClasses.Crypto && x.IsActive) ||
                        (x.AssetClass == AssetClasses.UsEquity && x.IsShadowEnabled))
            .GroupBy(x => x.AssetClass)
            .ToDictionaryAsync(x => x.Key, x => x.Count(), cancellationToken);
        Guid[] candidateIds = candidates.Select(x => x.Id).ToArray();
        var predictionRows = await dbContext.Predictions.AsNoTracking()
            .Where(x => candidateIds.Contains(x.ModelVersionId) && x.IsShadow)
            .Select(x => new { x.ModelVersionId, x.AssetId, x.AnalysisTime })
            .ToListAsync(cancellationToken);

        List<ShadowPredictionModelResponse> models = [];
        foreach (ModelVersion candidate in candidates)
        {
            (Guid AssetId, DateTimeOffset AnalysisTime)[] points = predictionRows
                .Where(x => x.ModelVersionId == candidate.Id)
                .Select(x => (x.AssetId, x.AnalysisTime))
                .ToArray();
            int totalAssets = totalAssetsByClass.GetValueOrDefault(candidate.AssetClass);
            models.Add(BuildShadowProgress(candidate, points, totalAssets, checkedAt));
        }

        int totalPredictions = models.Sum(x => x.PredictionCount);
        int maturedPredictions = models.Sum(x => x.MaturedPredictionCount);
        string state = models.Count switch
        {
            0 => "no_candidate",
            _ when models.All(x => x.State == "waiting") => "waiting",
            _ when models.Any(x => x.State == "evaluable") => "evaluable",
            _ => "collecting"
        };
        return new ShadowPredictionDashboardResponse(
            checkedAt,
            state,
            models.Count,
            totalPredictions,
            maturedPredictions,
            models);
    }

    public static ShadowPredictionModelResponse BuildShadowProgress(
        ModelVersion model,
        IReadOnlyCollection<(Guid AssetId, DateTimeOffset AnalysisTime)> points,
        int totalAssets,
        DateTimeOffset checkedAt)
    {
        DateTimeOffset? startedAt = points.Count == 0 ? null : points.Min(x => x.AnalysisTime);
        DateTimeOffset? lastPredictionAt = points.Count == 0 ? null : points.Max(x => x.AnalysisTime);
        int predictionDays = points.Select(x => x.AnalysisTime.UtcDateTime.Date).Distinct().Count();
        bool isEquity = model.AssetClass == AssetClasses.UsEquity;
        DateTimeOffset? firstEvaluationAt = isEquity ? null : startedAt?.AddDays(model.HorizonDays);
        int elapsedDays = isEquity
            ? Math.Clamp(Math.Max(0, predictionDays - 1), 0, model.HorizonDays)
            : startedAt.HasValue
                ? Math.Clamp((int)Math.Floor((checkedAt - startedAt.Value).TotalDays), 0, model.HorizonDays)
                : 0;
        int remainingDays = Math.Max(0, model.HorizonDays - elapsedDays);
        int expectedPredictions = totalAssets * predictionDays;
        int maturedPredictions;
        if (isEquity)
        {
            DateTime[] predictionSessions = points.Select(x => x.AnalysisTime.UtcDateTime.Date)
                .Distinct()
                .OrderBy(x => x)
                .ToArray();
            maturedPredictions = predictionSessions.Length > model.HorizonDays
                ? points.Count(x => x.AnalysisTime.UtcDateTime.Date <=
                    predictionSessions[^(model.HorizonDays + 1)])
                : 0;
        }
        else
        {
            maturedPredictions = points.Count(x => x.AnalysisTime.AddDays(model.HorizonDays) <= checkedAt);
        }
        string state = points.Count switch
        {
            0 => "waiting",
            _ when maturedPredictions > 0 => "evaluable",
            _ => "collecting"
        };

        return new ShadowPredictionModelResponse(
            model.Version,
            model.AssetClass,
            isEquity ? "trading_sessions" : "calendar_days",
            model.HorizonDays,
            startedAt,
            lastPredictionAt,
            firstEvaluationAt,
            elapsedDays,
            model.HorizonDays,
            remainingDays,
            predictionDays,
            points.Count,
            maturedPredictions,
            points.Select(x => x.AssetId).Distinct().Count(),
            totalAssets,
            expectedPredictions == 0 ? 0 : Math.Min(1, points.Count / (double)expectedPredictions),
            state);
    }

    public async Task<IReadOnlyList<MarketPriceUpdate>> GetLatestPricesAsync(CancellationToken cancellationToken)
    {
        List<Asset> assets = await dbContext.Assets.AsNoTracking().Where(x => x.IsActive).ToListAsync(cancellationToken);
        List<MarketPriceUpdate> updates = [];
        foreach (Asset asset in assets)
        {
            List<PriceBar> bars = await dbContext.PriceBars.AsNoTracking()
                .Where(x => x.AssetId == asset.Id && x.IsFinal)
                .OrderByDescending(x => x.CloseTime)
                .Take(25)
                .ToListAsync(cancellationToken);
            if (bars.Count == 0)
            {
                continue;
            }

            decimal? change = bars.Count >= 24 && bars[^1].Close != 0
                ? ((bars[0].Close / bars[^1].Close) - 1) * 100
                : null;
            updates.Add(new(asset.Symbol, bars[0].Close, bars[0].CloseTime, change));
        }
        return updates;
    }

    public async Task<IReadOnlyList<NewsArticleResponse>?> GetNewsAsync(
        string symbol,
        int limit,
        CancellationToken cancellationToken)
    {
        Asset? asset = await dbContext.Assets.AsNoTracking()
            .SingleOrDefaultAsync(x => x.Symbol == symbol.ToUpper(), cancellationToken);
        if (asset is null)
        {
            return null;
        }

        return await dbContext.NewsArticles.AsNoTracking()
            .Where(x => x.AssetId == asset.Id)
            .OrderByDescending(x => x.PublishedAt)
            .Take(limit)
            .Select(x => new NewsArticleResponse(
                x.Id,
                asset.Symbol,
                x.Title,
                x.SourceName,
                x.SourceUrl,
                x.PublishedAt,
                x.RetrievedAt,
                x.Language,
                x.RelevanceScore,
                x.SentimentScore,
                x.EventType,
                x.NoveltyScore,
                x.ShadowOnly))
            .ToListAsync(cancellationToken);
    }

    private string FreshnessState(DateTimeOffset? dataTime, TimeSpan allowedAge) => dataTime switch
    {
        null => "missing",
        _ when timeProvider.GetUtcNow() - dataTime.Value <= allowedAge => "fresh",
        _ => "stale"
    };

    private static string ToContractStatus(AnalysisStatus status) => status switch
    {
        AnalysisStatus.Signal => "signal",
        AnalysisStatus.InsufficientConfidence => "insufficient_confidence",
        AnalysisStatus.StaleData => "stale_data",
        _ => "insufficient_confidence"
    };

    private static string ConfidenceLevel(double score) => score switch
    {
        >= 0.70 => "High",
        >= 0.50 => "Medium",
        _ => "Low"
    };

    private static IReadOnlyList<string> DeserializeList(string json) =>
        JsonSerializer.Deserialize<List<string>>(json, JsonOptions) ?? [];

    private static Dictionary<string, double> DeserializeDictionary(string json) =>
        JsonSerializer.Deserialize<Dictionary<string, double>>(json, JsonOptions) ?? [];

    private static double GetMetric(IReadOnlyDictionary<string, double> metrics, string name) =>
        metrics.TryGetValue(name, out double value) ? value : double.NaN;

    public static int CountConsecutiveDays(IEnumerable<DateTimeOffset> times)
    {
        DateTimeOffset[] ordered = times.Distinct().Order().ToArray();
        if (ordered.Length == 0)
        {
            return 0;
        }
        int count = 1;
        for (int index = ordered.Length - 1; index > 0; index--)
        {
            if (ordered[index] - ordered[index - 1] != TimeSpan.FromDays(1))
            {
                break;
            }
            count++;
        }
        return count;
    }

    private static double? Percentile95(IReadOnlyList<double> orderedValues)
    {
        if (orderedValues.Count == 0)
        {
            return null;
        }
        int index = Math.Clamp((int)Math.Ceiling(orderedValues.Count * 0.95) - 1, 0, orderedValues.Count - 1);
        return orderedValues[index];
    }
}
