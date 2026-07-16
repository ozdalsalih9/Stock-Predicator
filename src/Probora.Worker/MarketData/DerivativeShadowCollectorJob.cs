using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Domain.Markets;
using Probora.Domain.Operations;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.MarketData;

[DisallowConcurrentExecution]
public sealed class DerivativeShadowCollectorJob(
    BinanceFuturesRestClient client,
    ProboraDbContext dbContext,
    IOptions<BinanceFuturesOptions> options,
    TimeProvider timeProvider,
    ILogger<DerivativeShadowCollectorJob> logger) : IJob
{
    private readonly BinanceFuturesOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.EnableShadowCollector)
        {
            return;
        }

        CancellationToken cancellationToken = context.CancellationToken;
        DateTimeOffset now = timeProvider.GetUtcNow();
        DateTimeOffset cutoff = new(now.Year, now.Month, now.Day, 0, 0, 0, TimeSpan.Zero);
        DateTimeOffset opensAt = cutoff.AddMinutes(_options.CutoffDelayMinutes);
        DateTimeOffset closesAt = cutoff.AddMinutes(_options.CollectionWindowMinutes);
        if (now < opensAt || now > closesAt)
        {
            logger.LogDebug("Derivative shadow collection is outside its UTC readiness window.");
            return;
        }

        IngestionRun run = new()
        {
            Id = Guid.NewGuid(),
            Source = "binance-usdm",
            Dataset = "derivative_daily_shadow",
            StartedAt = now
        };
        dbContext.IngestionRuns.Add(run);
        await dbContext.SaveChangesAsync(cancellationToken);

        try
        {
            DateTimeOffset serverTime = await client.GetServerTimeAsync(cancellationToken);
            TimeSpan clockSkew = (serverTime - now).Duration();
            if (clockSkew > TimeSpan.FromSeconds(_options.MaximumClockSkewSeconds))
            {
                throw new InvalidOperationException(
                    $"Local/Binance clock skew {clockSkew.TotalSeconds:0.0}s exceeds the configured limit.");
            }
            if (serverTime < opensAt)
            {
                run.Status = "deferred";
                run.Error = $"Binance server time {serverTime:O} has not crossed the buffered cutoff {opensAt:O}.";
                run.CompletedAt = timeProvider.GetUtcNow();
                await dbContext.SaveChangesAsync(cancellationToken);
                return;
            }

            List<Asset> assets = await dbContext.Assets
                .Where(x => x.IsActive && x.AssetClass == AssetClasses.Crypto)
                .ToListAsync(cancellationToken);
            List<string> pending = [];
            foreach (Asset asset in assets)
            {
                bool exists = await dbContext.DerivativeDailySnapshots.AnyAsync(
                    x => x.AssetId == asset.Id && x.SnapshotTime == cutoff &&
                         x.Source == "binance-usdm" && x.IsComplete,
                    cancellationToken);
                if (exists)
                {
                    continue;
                }

                try
                {
                    DerivativeSnapshotValues values = await client.GetDailySnapshotAsync(
                        asset.Symbol,
                        cutoff,
                        cancellationToken);
                    DateTimeOffset availableAt = timeProvider.GetUtcNow();
                    dbContext.DerivativeDailySnapshots.Add(new DerivativeDailySnapshot
                    {
                        AssetId = asset.Id,
                        SnapshotTime = values.SnapshotTime,
                        FundingRate = values.FundingRate,
                        Premium = values.Premium,
                        FuturesQuoteVolume = values.FuturesQuoteVolume,
                        FuturesTakerBuyRatio = values.FuturesTakerBuyRatio,
                        OpenInterestValue = values.OpenInterestValue,
                        LongShortRatio = values.LongShortRatio,
                        TakerLongShortRatio = values.TakerLongShortRatio,
                        FuturesKlineCount = values.FuturesKlineCount,
                        PremiumKlineCount = values.PremiumKlineCount,
                        FundingPointCount = values.FundingPointCount,
                        OpenInterestPointCount = values.OpenInterestPointCount,
                        LongShortPointCount = values.LongShortPointCount,
                        TakerLongShortPointCount = values.TakerLongShortPointCount,
                        IsComplete = true,
                        SourceMaxEventTime = values.SourceMaxEventTime,
                        AvailableAt = availableAt,
                        IngestedAt = availableAt,
                        Source = "binance-usdm",
                        SourceChecksum = values.SourceChecksum
                    });
                    run.RecordsRead += values.FuturesKlineCount + values.PremiumKlineCount +
                        values.FundingPointCount + values.OpenInterestPointCount +
                        values.LongShortPointCount + values.TakerLongShortPointCount;
                    run.RecordsWritten++;
                    await dbContext.SaveChangesAsync(cancellationToken);
                }
                catch (Exception exception) when (exception is InvalidDataException or HttpRequestException)
                {
                    pending.Add($"{asset.Symbol}: {exception.Message}");
                    logger.LogWarning(exception, "Derivative cutoff {Cutoff} is not ready for {Symbol}.", cutoff, asset.Symbol);
                }
            }

            run.Status = pending.Count == 0 ? "succeeded" : "deferred";
            run.Error = pending.Count == 0 ? null : string.Join(" | ", pending);
            run.CompletedAt = timeProvider.GetUtcNow();
            if (pending.Count > 0 && serverTime >= closesAt)
            {
                await AddQualityIssuesAsync(assets, cutoff, pending, cancellationToken);
            }
            await dbContext.SaveChangesAsync(cancellationToken);
            logger.LogInformation(
                "Derivative shadow cutoff {Cutoff} finished with status {Status}; wrote {Written} snapshots.",
                cutoff,
                run.Status,
                run.RecordsWritten);
        }
        catch (Exception exception)
        {
            run.Status = "failed";
            run.CompletedAt = timeProvider.GetUtcNow();
            run.Error = exception.Message;
            await dbContext.SaveChangesAsync(CancellationToken.None);
            logger.LogError(exception, "Derivative shadow collection failed for cutoff {Cutoff}.", cutoff);
            throw;
        }
    }

    private async Task AddQualityIssuesAsync(
        IReadOnlyCollection<Asset> assets,
        DateTimeOffset cutoff,
        IReadOnlyCollection<string> pending,
        CancellationToken cancellationToken)
    {
        foreach (Asset asset in assets.Where(asset => pending.Any(x => x.StartsWith(asset.Symbol + ":", StringComparison.Ordinal))))
        {
            bool exists = await dbContext.DataQualityIssues.AnyAsync(
                x => x.AssetId == asset.Id && x.Code == "DERIVATIVE_CUTOFF_INCOMPLETE" &&
                     x.DataTime == cutoff && !x.IsResolved,
                cancellationToken);
            if (!exists)
            {
                dbContext.DataQualityIssues.Add(new DataQualityIssue
                {
                    AssetId = asset.Id,
                    Code = "DERIVATIVE_CUTOFF_INCOMPLETE",
                    Severity = "error",
                    Description = pending.Single(x => x.StartsWith(asset.Symbol + ":", StringComparison.Ordinal)),
                    DataTime = cutoff,
                    DetectedAt = timeProvider.GetUtcNow()
                });
            }
        }
    }
}
