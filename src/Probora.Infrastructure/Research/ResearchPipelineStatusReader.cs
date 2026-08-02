using System.Text.Json;
using Microsoft.Extensions.Options;
using Probora.Application.Abstractions;
using Probora.Contracts.System;

namespace Probora.Infrastructure.Research;

public sealed class ResearchPipelineStatusReader(IOptions<ResearchPipelineOptions> options)
    : IResearchPipelineStatusReader
{
    private readonly ResearchPipelineOptions _options = options.Value;

    public async Task<ResearchPipelineDashboardResponse> GetAsync(CancellationToken cancellationToken)
    {
        BootstrapSnapshot? bootstrap = await ReadBootstrapAsync(cancellationToken);
        CoverageSnapshot? coverage = await ReadCoverageAsync(cancellationToken);

        int frozenUniverse = bootstrap?.UniverseSize ?? _options.FrozenUniverseSize;
        int currentUniverse = Math.Max(coverage?.UniverseSize ?? _options.CurrentUniverseSize, frozenUniverse);
        int batchCount = Math.Max(1, bootstrap?.BatchCount ?? _options.BatchCount);
        int configuredBatchSize = Math.Max(1, _options.BatchSize);
        int processed = bootstrap?.ProcessedSymbols ?? 0;
        int processedInFrozenUniverse = Math.Min(processed, frozenUniverse);
        bool exactlyBetweenBatches = processedInFrozenUniverse > 0
            && processedInFrozenUniverse < frozenUniverse
            && processedInFrozenUniverse % configuredBatchSize == 0;
        int batchNumber = processedInFrozenUniverse >= frozenUniverse
            ? batchCount
            : exactlyBetweenBatches
                ? Math.Min(batchCount, processedInFrozenUniverse / configuredBatchSize)
                : Math.Min(batchCount, (processedInFrozenUniverse / configuredBatchSize) + 1);
        int currentBatchSize = batchNumber == batchCount
            ? Math.Max(1, frozenUniverse - (configuredBatchSize * (batchCount - 1)))
            : configuredBatchSize;
        int batchProcessed = processedInFrozenUniverse >= frozenUniverse || exactlyBetweenBatches
            ? currentBatchSize
            : Math.Min(currentBatchSize, processedInFrozenUniverse - (configuredBatchSize * (batchNumber - 1)));
        bool coverageReady = coverage is { CoverageReady: true, MembershipFresh: true };
        string state = ResolveState(processed, frozenUniverse, currentUniverse, configuredBatchSize, coverageReady);

        return new ResearchPipelineDashboardResponse(
            DateTimeOffset.UtcNow,
            bootstrap?.LastUpdatedAt ?? coverage?.CheckedAt,
            coverage?.CheckedAt,
            state,
            frozenUniverse,
            currentUniverse,
            batchNumber,
            batchCount,
            currentBatchSize,
            Math.Max(0, batchProcessed),
            processed,
            bootstrap?.SuccessfulSymbols ?? 0,
            bootstrap?.FailedSymbols ?? 0,
            bootstrap?.DownloadedBars ?? 0,
            Percent(processed, currentUniverse),
            Percent(Math.Max(0, batchProcessed), currentBatchSize),
            coverage?.MeanDailyCoverage,
            coverage?.MinimumDailyCoverage,
            coverage?.LatestDailyCoverage,
            coverage?.RequiredDailyCoverage ?? _options.RequiredDailyCoverage,
            coverageReady,
            coverage?.MembershipLastSnapshotDate,
            coverage?.MembershipFreshnessDays,
            coverage?.MembershipFresh ?? false,
            ResolveNextStep(processed, frozenUniverse, currentUniverse, configuredBatchSize, bootstrap?.FailedSymbols ?? 0, coverageReady),
            bootstrap?.Failures ?? []);
    }

    private async Task<BootstrapSnapshot?> ReadBootstrapAsync(CancellationToken cancellationToken)
    {
        JsonDocument? document = await TryReadJsonAsync(_options.StatePath, cancellationToken);
        if (document is null)
        {
            return null;
        }

        using (document)
        {
            JsonElement root = document.RootElement;
            if (!root.TryGetProperty("symbols", out JsonElement symbols) || symbols.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            int successful = 0;
            int failed = 0;
            long downloadedBars = 0;
            List<ResearchPipelineFailureResponse> failures = [];
            DateTimeOffset? latestFailureAt = null;

            foreach (JsonProperty property in symbols.EnumerateObject())
            {
                JsonElement item = property.Value;
                string status = GetString(item, "status") ?? string.Empty;
                if (string.Equals(status, "succeeded", StringComparison.OrdinalIgnoreCase))
                {
                    successful++;
                    downloadedBars += GetInt64(item, "row_count") ?? 0;
                    continue;
                }

                if (!string.Equals(status, "failed", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                failed++;
                DateTimeOffset? updatedAt = GetDateTimeOffset(item, "updated_at");
                if (failures.Count < 8 || updatedAt > latestFailureAt)
                {
                    failures.Add(new ResearchPipelineFailureResponse(
                        property.Name,
                        GetString(item, "error_type") ?? "unknown"));
                    latestFailureAt = updatedAt ?? latestFailureAt;
                }
            }

            return new BootstrapSnapshot(
                GetInt32(root, "universe_size") ?? _options.FrozenUniverseSize,
                GetInt32(root, "batch_count") ?? _options.BatchCount,
                successful + failed,
                successful,
                failed,
                downloadedBars,
                GetDateTimeOffset(root, "updated_at"),
                failures.TakeLast(8).Reverse().ToArray());
        }
    }

    private async Task<CoverageSnapshot?> ReadCoverageAsync(CancellationToken cancellationToken)
    {
        JsonDocument? document = await TryReadJsonAsync(_options.CoveragePath, cancellationToken);
        if (document is null)
        {
            return null;
        }

        using (document)
        {
            JsonElement root = document.RootElement;
            return new CoverageSnapshot(
                GetInt32(root, "universe_size") ?? _options.CurrentUniverseSize,
                GetDateTimeOffset(root, "checked_at"),
                GetDouble(root, "mean_daily_coverage"),
                GetDouble(root, "minimum_daily_coverage"),
                GetDouble(root, "latest_daily_coverage"),
                GetDouble(root, "minimum_required_daily_coverage") ?? _options.RequiredDailyCoverage,
                GetBoolean(root, "coverage_ready") ?? false,
                GetDateOnly(root, "membership_last_snapshot_date"),
                GetInt32(root, "membership_freshness_days"),
                GetBoolean(root, "membership_fresh") ?? false);
        }
    }

    private static async Task<JsonDocument?> TryReadJsonAsync(string path, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return null;
        }

        try
        {
            await using FileStream stream = File.OpenRead(path);
            return await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string ResolveState(
        int processed,
        int frozenUniverse,
        int currentUniverse,
        int batchSize,
        bool coverageReady)
    {
        if (coverageReady)
        {
            return "ready";
        }

        if (processed == 0)
        {
            return "no_data";
        }

        if (processed < frozenUniverse && processed >= batchSize && processed % batchSize == 0)
        {
            return "waiting_next_batch";
        }

        return processed < currentUniverse ? "collecting" : "audit_required";
    }

    private static string ResolveNextStep(
        int processed,
        int frozenUniverse,
        int currentUniverse,
        int batchSize,
        int failed,
        bool coverageReady)
    {
        if (coverageReady)
        {
            return "V4.3 S&P breadth ablation ve GPU eğitimi";
        }

        if (processed < Math.Min(batchSize, frozenUniverse))
        {
            return "Birinci veri partisini tamamla";
        }

        if (processed < frozenUniverse)
        {
            return "İkinci veri partisini sonraki kota penceresinde indir";
        }

        if (processed < currentUniverse)
        {
            return "Güncel evrendeki yeni sembolleri indir";
        }

        if (failed > 0)
        {
            return "Delist sembolleri resmi eşleme ile yeniden dene";
        }

        return "Kapsama denetimini çalıştır ve yüzde 95 kapısını doğrula";
    }

    private static double Percent(int numerator, int denominator) =>
        denominator <= 0 ? 0 : Math.Round(Math.Clamp((double)numerator / denominator * 100, 0, 100), 2);

    private static string? GetString(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static int? GetInt32(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.TryGetInt32(out int result) ? result : null;

    private static long? GetInt64(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.TryGetInt64(out long result) ? result : null;

    private static double? GetDouble(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.TryGetDouble(out double result) ? result : null;

    private static bool? GetBoolean(JsonElement element, string name) =>
        element.TryGetProperty(name, out JsonElement value) && value.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? value.GetBoolean()
            : null;

    private static DateTimeOffset? GetDateTimeOffset(JsonElement element, string name) =>
        DateTimeOffset.TryParse(GetString(element, name), out DateTimeOffset result) ? result : null;

    private static DateOnly? GetDateOnly(JsonElement element, string name) =>
        DateOnly.TryParse(GetString(element, name), out DateOnly result) ? result : null;

    private sealed record BootstrapSnapshot(
        int UniverseSize,
        int BatchCount,
        int ProcessedSymbols,
        int SuccessfulSymbols,
        int FailedSymbols,
        long DownloadedBars,
        DateTimeOffset? LastUpdatedAt,
        IReadOnlyList<ResearchPipelineFailureResponse> Failures);

    private sealed record CoverageSnapshot(
        int UniverseSize,
        DateTimeOffset? CheckedAt,
        double? MeanDailyCoverage,
        double? MinimumDailyCoverage,
        double? LatestDailyCoverage,
        double RequiredDailyCoverage,
        bool CoverageReady,
        DateOnly? MembershipLastSnapshotDate,
        int? MembershipFreshnessDays,
        bool MembershipFresh);
}
