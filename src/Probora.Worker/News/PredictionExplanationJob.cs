using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Domain.Analysis;
using Probora.Domain.News;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.News;

[DisallowConcurrentExecution]
public sealed class PredictionExplanationJob(
    ProboraDbContext dbContext,
    ILlmExplanationClient llmClient,
    IOptions<LlmExplanationOptions> options,
    TimeProvider timeProvider,
    ILogger<PredictionExplanationJob> logger) : IJob
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly LlmExplanationOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.Enabled)
        {
            return;
        }
        if (string.IsNullOrWhiteSpace(_options.ApiKey))
        {
            logger.LogWarning("LLM explanations are enabled but LlmExplanations:ApiKey is empty; job skipped.");
            return;
        }

        DateTimeOffset now = timeProvider.GetUtcNow();
        DateTimeOffset retryBefore = now.AddHours(-Math.Max(1, _options.RetryFailedAfterHours));
        int scanLimit = Math.Clamp(_options.MaxPredictionsPerRun, 1, 50) * 4;
        var rows = await (
            from prediction in dbContext.Predictions.AsNoTracking()
            join asset in dbContext.Assets.AsNoTracking() on prediction.AssetId equals asset.Id
            join model in dbContext.ModelVersions.AsNoTracking() on prediction.ModelVersionId equals model.Id
            join feature in dbContext.FeatureSnapshots.AsNoTracking() on prediction.FeatureSnapshotId equals feature.Id
            where prediction.CreatedAt >= now.AddDays(-7) &&
                  !dbContext.PredictionExplanations.Any(explanation =>
                      explanation.PredictionId == prediction.Id &&
                      explanation.Provider == _options.Provider &&
                      explanation.Model == _options.Model &&
                      explanation.PromptVersion == _options.PromptVersion &&
                      explanation.Status == "succeeded")
            orderby prediction.CreatedAt descending, prediction.Id descending
            select new { prediction, asset, model, feature })
            .Take(scanLimit)
            .ToListAsync(context.CancellationToken);

        int completed = 0;
        foreach (var row in rows)
        {
            if (completed >= Math.Clamp(_options.MaxPredictionsPerRun, 1, 50))
            {
                break;
            }

            PredictionExplanation? explanation = await dbContext.PredictionExplanations
                .SingleOrDefaultAsync(item =>
                    item.PredictionId == row.prediction.Id &&
                    item.Provider == _options.Provider &&
                    item.Model == _options.Model &&
                    item.PromptVersion == _options.PromptVersion,
                    context.CancellationToken);
            if (explanation is { Status: "failed", CompletedAt: { } failedAt } && failedAt > retryBefore)
            {
                continue;
            }

            List<NewsArticle> news = await dbContext.NewsArticles.AsNoTracking()
                .Where(article => article.AssetId == row.asset.Id &&
                                  article.AvailableAt <= row.prediction.AnalysisTime &&
                                  article.PublishedAt <= row.prediction.AnalysisTime &&
                                  article.AvailableAt >= row.prediction.AnalysisTime.AddHours(
                                      -Math.Clamp(_options.NewsLookbackHours, 1, 24 * 14)))
                .OrderByDescending(article => article.SourceReliabilityScore * article.RelevanceScore)
                .ThenByDescending(article => article.PublishedAt)
                .Take(Math.Clamp(_options.MaxNewsArticles, 0, 20))
                .ToListAsync(context.CancellationToken);
            PredictionExplanationContract contract = BuildContract(row.prediction, row.asset.Symbol,
                row.asset.AssetClass, row.model, row.feature, news);
            string inputJson = JsonSerializer.Serialize(contract, JsonOptions);
            string inputSha256 = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(inputJson)))
                .ToLowerInvariant();

            explanation ??= new PredictionExplanation
            {
                PredictionId = row.prediction.Id,
                Provider = _options.Provider,
                Model = _options.Model,
                PromptVersion = _options.PromptVersion
            };
            if (explanation.Id == 0)
            {
                dbContext.PredictionExplanations.Add(explanation);
            }
            explanation.InputJson = inputJson;
            explanation.InputSha256 = inputSha256;
            explanation.OutputJson = "{}";
            explanation.Status = "pending";
            explanation.FailureReason = null;
            explanation.CreatedAt = now;
            explanation.CompletedAt = null;
            await dbContext.SaveChangesAsync(context.CancellationToken);

            try
            {
                HashSet<string> allowedUrls = news.Select(article => article.SourceUrl).ToHashSet(StringComparer.Ordinal);
                PredictionExplanationOutput output = await llmClient.ExplainAsync(
                    inputJson,
                    allowedUrls,
                    context.CancellationToken);
                explanation.OutputJson = JsonSerializer.Serialize(output, JsonOptions);
                explanation.Status = "succeeded";
                explanation.CompletedAt = timeProvider.GetUtcNow();
                completed++;
            }
            catch (Exception exception)
            {
                explanation.Status = "failed";
                explanation.FailureReason = SafeFailure(exception.Message);
                explanation.CompletedAt = timeProvider.GetUtcNow();
                logger.LogWarning(exception, "LLM explanation failed for prediction {PredictionId}.", row.prediction.Id);
            }

            await dbContext.SaveChangesAsync(context.CancellationToken);
        }

        logger.LogInformation(
            "Prediction explanation run completed; {Completed} explanations succeeded with {Provider}/{Model}.",
            completed,
            _options.Provider,
            _options.Model);
    }

    private static PredictionExplanationContract BuildContract(
        PredictionRecord prediction,
        string symbol,
        string assetClass,
        ModelVersion model,
        FeatureSnapshot feature,
        IReadOnlyCollection<NewsArticle> news)
    {
        Dictionary<string, double> features = JsonSerializer.Deserialize<Dictionary<string, double>>(
            feature.FeaturesJson,
            JsonOptions) ?? [];
        SortedDictionary<string, double> finiteFeatures = new(StringComparer.Ordinal);
        foreach ((string name, double value) in features.Where(item => double.IsFinite(item.Value)))
        {
            finiteFeatures[name] = value;
        }

        ExplanationProbabilityContract? baseline =
            prediction.BaselineDownProbability.HasValue &&
            prediction.BaselineNeutralProbability.HasValue &&
            prediction.BaselineUpProbability.HasValue
                ? new ExplanationProbabilityContract(
                    prediction.BaselineDownProbability.Value,
                    prediction.BaselineNeutralProbability.Value,
                    prediction.BaselineUpProbability.Value)
                : null;
        return new PredictionExplanationContract(
            prediction.Id,
            symbol,
            assetClass,
            prediction.AnalysisTime,
            prediction.HorizonDays,
            new ExplanationProbabilityContract(
                prediction.DownProbability,
                prediction.NeutralProbability,
                prediction.UpProbability),
            baseline,
            new ExplanationReturnContract(prediction.ReturnP10, prediction.ReturnP50, prediction.ReturnP90),
            prediction.RiskScore,
            prediction.RiskLevel.ToString(),
            prediction.ConfidenceScore,
            prediction.Status.ToString(),
            DeserializeList(prediction.PositiveFactorsJson),
            DeserializeList(prediction.NegativeFactorsJson),
            DeserializeList(prediction.LimitationsJson),
            finiteFeatures,
            feature.SnapshotTime,
            news.Count == 0 ? null : news.Max(article => article.AvailableAt),
            news.Select(article => new ExplanationNewsContract(
                article.Title,
                article.SourceName,
                article.SourceUrl,
                article.Provider,
                article.PublishedAt,
                article.AvailableAt,
                article.EventType,
                article.SourceReliabilityScore,
                article.RelevanceScore)).ToArray(),
            model.Version,
            model.FeatureSetVersion,
            prediction.ArtifactSha256);
    }

    private static IReadOnlyList<string> DeserializeList(string json) =>
        JsonSerializer.Deserialize<List<string>>(json, JsonOptions) ?? [];

    private static string SafeFailure(string message) => message.Length <= 1_000 ? message : message[..1_000];
}
