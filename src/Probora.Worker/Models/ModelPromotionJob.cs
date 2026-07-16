using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Domain.Analysis;
using Probora.Infrastructure.Persistence;
using Probora.ML.Runtime.Inference;
using Quartz;

namespace Probora.Worker.Models;

[DisallowConcurrentExecution]
public sealed class ModelPromotionJob(
    ProboraDbContext dbContext,
    IOptions<ModelOptions> options,
    ILogger<ModelPromotionJob> logger) : IJob
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly ModelOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        string root = Path.GetFullPath(_options.Root);
        if (!Directory.Exists(root))
        {
            logger.LogInformation("Model directory {Root} does not exist yet.", root);
            return;
        }

        // Process oldest first so the newest newly discovered shadow bundle wins
        // deterministically when several artifacts are copied in one deployment.
        foreach (string manifestPath in Directory
                     .EnumerateFiles(root, "manifest.json", SearchOption.AllDirectories)
                     .OrderBy(File.GetLastWriteTimeUtc)
                     .ThenBy(x => x, StringComparer.Ordinal))
        {
            ModelManifest manifest = JsonSerializer.Deserialize<ModelManifest>(
                await File.ReadAllTextAsync(manifestPath, context.CancellationToken),
                JsonOptions) ?? throw new InvalidDataException($"Invalid manifest: {manifestPath}");
            string directory = Path.GetDirectoryName(manifestPath)!;
            string actualSha = ComputeArtifactSha(directory);
            if (!CryptographicOperations.FixedTimeEquals(
                    Convert.FromHexString(actualSha),
                    Convert.FromHexString(manifest.ArtifactSha256)))
            {
                throw new InvalidDataException($"Artifact checksum mismatch for {manifest.Version}.");
            }

            ModelVersion? existing = await dbContext.ModelVersions.SingleOrDefaultAsync(
                x => x.Version == manifest.Version,
                context.CancellationToken);
            if (existing is null)
            {
                existing = new ModelVersion
                {
                    Id = Guid.NewGuid(),
                    Version = manifest.Version,
                    HorizonDays = manifest.HorizonDays,
                    AssetClass = manifest.AssetClass,
                    FeatureSetVersion = manifest.FeatureSetVersion,
                    DatasetVersion = manifest.DatasetVersion,
                    ArtifactPath = directory,
                    ArtifactSha256 = actualSha,
                    MetricsJson = await ReadMetricsSummaryAsync(directory, context.CancellationToken),
                    TrainedAt = File.GetLastWriteTimeUtc(manifestPath),
                    IsProduction = false,
                    IsShadowCandidate = false,
                    DirectionEligible = manifest.DirectionEligible,
                    ScenarioEligible = manifest.ScenarioEligible
                };
                dbContext.ModelVersions.Add(existing);
                logger.LogInformation(
                    "Registered model {Version} for {Horizon} days.",
                    manifest.Version,
                    manifest.HorizonDays);
            }
            existing.DirectionEligible = manifest.DirectionEligible;
            existing.ScenarioEligible = manifest.ScenarioEligible;

            if (manifest.ProductionEligible && !existing.IsProduction)
            {
                await dbContext.ModelVersions
                    .Where(x => x.AssetClass == manifest.AssetClass &&
                                x.HorizonDays == manifest.HorizonDays && x.IsProduction)
                    .ExecuteUpdateAsync(
                        setters => setters.SetProperty(x => x.IsProduction, false),
                        context.CancellationToken);
                existing.IsProduction = true;
                existing.IsShadowCandidate = false;
                logger.LogInformation("Promoted model {Version} for {Horizon} days.", manifest.Version, manifest.HorizonDays);
            }
        }

        await dbContext.SaveChangesAsync(context.CancellationToken);

        // New models are inserted in one unit of work. Normalize candidates only
        // after those inserts are visible, otherwise two new bundles in the same
        // group can both retain IsShadowCandidate=true.
        List<ModelVersion> shadowModels = await dbContext.ModelVersions
            .Where(x => !x.IsProduction)
            .ToListAsync(context.CancellationToken);
        foreach (IGrouping<(string AssetClass, int HorizonDays), ModelVersion> group in shadowModels
                     .GroupBy(x => (x.AssetClass, x.HorizonDays)))
        {
            ModelVersion winner = group
                .OrderByDescending(x => x.TrainedAt)
                .ThenByDescending(x => x.Version, StringComparer.Ordinal)
                .First();
            foreach (ModelVersion model in group)
            {
                model.IsShadowCandidate = model.Id == winner.Id;
            }
            logger.LogInformation(
                "Shadow candidate for {AssetClass} {Horizon} days is {Version}.",
                group.Key.AssetClass,
                group.Key.HorizonDays,
                winner.Version);
        }
        await dbContext.SaveChangesAsync(context.CancellationToken);
    }

    private static string ComputeArtifactSha(string directory)
    {
        using IncrementalHash hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        foreach (string path in Directory.EnumerateFiles(directory, "*.onnx")
                     .OrderBy(x => Path.GetFileName(x), StringComparer.Ordinal))
        {
            hash.AppendData(System.Text.Encoding.UTF8.GetBytes(Path.GetFileName(path)));
            hash.AppendData(File.ReadAllBytes(path));
        }
        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private static async Task<string> ReadMetricsSummaryAsync(string directory, CancellationToken cancellationToken)
    {
        string path = Path.Combine(directory, "metrics.json");
        if (!File.Exists(path))
        {
            return "{}";
        }
        using JsonDocument document = JsonDocument.Parse(await File.ReadAllTextAsync(path, cancellationToken));
        JsonElement[] folds = document.RootElement.EnumerateArray().ToArray();
        if (folds.Length == 0)
        {
            return "{}";
        }
        double Average(string name) => folds.Average(x => x.GetProperty(name).GetDouble());
        double AverageOrNaN(string name) => folds.All(x => x.TryGetProperty(name, out _))
            ? Average(name)
            : double.NaN;
        int samples = folds.Sum(x => x.GetProperty("sample_count").GetInt32());
        Dictionary<string, double> metrics = new()
        {
            ["brier_score"] = Average("brier"),
            ["baseline_brier_score"] = Average("baseline_brier"),
            ["ece"] = Average("ece"),
            ["directional_accuracy"] = Average("accuracy"),
            ["interval_coverage"] = Average("coverage"),
            ["sample_count"] = samples
        };
        foreach ((string output, string source) in new[]
                 {
                     ("brier_skill_score", "brier_skill_score"),
                     ("brier_reliability", "brier_reliability"),
                     ("brier_resolution", "brier_resolution"),
                     ("brier_uncertainty", "brier_uncertainty"),
                     ("classwise_ece", "classwise_ece"),
                     ("quantile_pinball", "quantile_pinball"),
                     ("baseline_quantile_pinball", "baseline_quantile_pinball"),
                     ("interval_score", "interval_score"),
                     ("baseline_interval_score", "baseline_interval_score"),
                     ("risk_mae", "risk_mae"),
                     ("baseline_risk_mae", "baseline_risk_mae")
                 })
        {
            double value = AverageOrNaN(source);
            if (!double.IsNaN(value))
            {
                metrics[output] = value;
            }
        }
        return JsonSerializer.Serialize(metrics, JsonOptions);
    }
}
