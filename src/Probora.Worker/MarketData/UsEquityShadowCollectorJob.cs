using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Application.Abstractions;
using Probora.Domain.Markets;
using Probora.Domain.Operations;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.MarketData;

[DisallowConcurrentExecution]
public sealed class UsEquityShadowCollectorJob(
    TwelveDataMarketDataClient client,
    IPriceBarWriter writer,
    ProboraDbContext dbContext,
    IOptions<TwelveDataOptions> options,
    TimeProvider timeProvider,
    ILogger<UsEquityShadowCollectorJob> logger) : IJob
{
    private readonly TwelveDataOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        if (!_options.IsConfigured)
        {
            logger.LogInformation("US equity shadow collector is disabled or Twelve Data credentials are missing.");
            return;
        }

        CancellationToken cancellationToken = context.CancellationToken;
        List<Asset> assets = await dbContext.Assets
            .Where(x => x.AssetClass == AssetClasses.UsEquity && x.IsShadowEnabled)
            .OrderBy(x => x.Symbol)
            .ToListAsync(cancellationToken);
        if (assets.Count == 0)
        {
            return;
        }

        string source = TwelveDataOptions.Source;
        DateTimeOffset? latest = await dbContext.PriceBars
            .Where(x => x.Source == source && assets.Select(a => a.Id).Contains(x.AssetId))
            .MaxAsync(x => (DateTimeOffset?)x.OpenTime, cancellationToken);
        DateOnly start = latest is null
            ? _options.HistoryStart
            : DateOnly.FromDateTime(latest.Value.UtcDateTime).AddDays(-7);
        IngestionRun run = new()
        {
            Id = Guid.NewGuid(),
            Source = source,
            Dataset = "us_equity_daily_shadow",
            StartedAt = timeProvider.GetUtcNow()
        };
        dbContext.IngestionRuns.Add(run);
        await dbContext.SaveChangesAsync(cancellationToken);

        try
        {
            IReadOnlyList<PriceBarCandidate> bars = await client.GetDailyBarsAsync(
                assets.Select(x => x.Symbol).ToArray(),
                start,
                DateOnly.FromDateTime(timeProvider.GetUtcNow().UtcDateTime),
                cancellationToken);
            if (bars.Count == 0)
            {
                throw new InvalidOperationException("Twelve Data returned no US equity EOD bars.");
            }
            run.RecordsRead = bars.Count;
            run.RecordsWritten = await writer.UpsertAsync(bars, cancellationToken);
            DateTimeOffset expectedSession = bars
                .Where(x => string.Equals(x.Symbol, "SPY", StringComparison.OrdinalIgnoreCase))
                .Select(x => x.OpenTime)
                .DefaultIfEmpty(bars.Max(x => x.OpenTime))
                .Max();
            string[] received = bars
                .Where(x => x.OpenTime == expectedSession)
                .Select(x => x.Symbol)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            string[] missing = assets.Select(x => x.Symbol)
                .Except(received, StringComparer.OrdinalIgnoreCase)
                .ToArray();
            if (missing.Length > 0)
            {
                dbContext.DataQualityIssues.Add(new DataQualityIssue
                {
                    Code = "US_EQUITY_SESSION_INCOMPLETE",
                    Severity = "error",
                    Description = $"Missing total-return adjusted EOD bar for: {string.Join(", ", missing)}",
                    DataTime = expectedSession,
                    DetectedAt = timeProvider.GetUtcNow(),
                    IsResolved = false
                });
                run.Status = "degraded";
                run.Error = $"{missing.Length} pilot assets are missing the completed session.";
            }
            else
            {
                run.Status = "succeeded";
            }
            run.CompletedAt = timeProvider.GetUtcNow();
            await dbContext.SaveChangesAsync(cancellationToken);
        }
        catch (Exception exception)
        {
            run.Status = "failed";
            run.Error = exception.Message;
            run.CompletedAt = timeProvider.GetUtcNow();
            await dbContext.SaveChangesAsync(CancellationToken.None);
            logger.LogError(exception, "US equity shadow collection failed.");
            throw;
        }
    }
}
