using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using Probora.Application.Abstractions;
using Probora.Domain.Markets;
using Probora.Domain.Operations;
using Probora.Infrastructure.Persistence;
using Quartz;

namespace Probora.Worker.MarketData;

[DisallowConcurrentExecution]
public sealed class BinanceSyncJob(
    BinanceRestClient client,
    IPriceBarWriter writer,
    ProboraDbContext dbContext,
    IOptions<BinanceOptions> options,
    ILogger<BinanceSyncJob> logger) : IJob
{
    private readonly BinanceOptions _options = options.Value;

    public async Task Execute(IJobExecutionContext context)
    {
        CancellationToken cancellationToken = context.CancellationToken;
        IngestionRun run = new()
        {
            Id = Guid.NewGuid(),
            Source = "binance",
            Dataset = "spot_klines_1h",
            StartedAt = DateTimeOffset.UtcNow
        };
        dbContext.IngestionRuns.Add(run);
        await dbContext.SaveChangesAsync(cancellationToken);

        try
        {
            int written = 0;
            foreach (AssetDefinition asset in AssetCatalog.Crypto)
            {
                written += await BackfillInferenceHistoryAsync(asset, run, cancellationToken);
                IReadOnlyList<PriceBarCandidate> bars = await client.GetKlinesAsync(
                    asset.Symbol,
                    "1h",
                    _options.BackfillLimit,
                    cancellationToken);
                run.RecordsRead += bars.Count;
                written += await writer.UpsertAsync(bars, cancellationToken);
            }

            run.RecordsWritten = written;
            run.Status = "succeeded";
            run.CompletedAt = DateTimeOffset.UtcNow;
            await dbContext.SaveChangesAsync(cancellationToken);
            logger.LogInformation("Binance sync completed. Read {Read}, affected {Written} bars.", run.RecordsRead, written);
        }
        catch (Exception exception)
        {
            run.Status = "failed";
            run.CompletedAt = DateTimeOffset.UtcNow;
            run.Error = exception.Message;
            await dbContext.SaveChangesAsync(CancellationToken.None);
            logger.LogError(exception, "Binance synchronization failed.");
            throw;
        }
    }

    private async Task<int> BackfillInferenceHistoryAsync(
        AssetDefinition definition,
        IngestionRun run,
        CancellationToken cancellationToken)
    {
        Asset asset = await dbContext.Assets.SingleAsync(
            x => x.Symbol == definition.Symbol,
            cancellationToken);
        DateTimeOffset desiredStart = new DateTimeOffset(DateTime.UtcNow.Date, TimeSpan.Zero)
            .AddDays(-_options.BackfillDays);
        DateTimeOffset? earliest = await dbContext.PriceBars.AsNoTracking()
            .Where(x => x.AssetId == asset.Id && x.Interval == "1h" && x.Source == "binance" &&
                        x.OpenTime >= desiredStart)
            .MinAsync(x => (DateTimeOffset?)x.OpenTime, cancellationToken);
        if (earliest.HasValue && earliest.Value <= desiredStart.AddHours(1))
        {
            return 0;
        }

        DateTimeOffset stopBefore = earliest ?? DateTimeOffset.UtcNow;
        DateTimeOffset cursor = desiredStart;
        int written = 0;
        logger.LogInformation(
            "Backfilling {Symbol} spot history from {Start} to {End} for inference readiness.",
            definition.Symbol,
            cursor,
            stopBefore);

        while (cursor < stopBefore)
        {
            IReadOnlyList<PriceBarCandidate> page = await client.GetKlinesAsync(
                definition.Symbol,
                "1h",
                _options.BackfillLimit,
                cursor,
                stopBefore.AddMilliseconds(-1),
                cancellationToken);
            if (page.Count == 0)
            {
                break;
            }

            run.RecordsRead += page.Count;
            written += await writer.UpsertAsync(page, cancellationToken);
            DateTimeOffset next = page.Max(x => x.OpenTime).AddHours(1);
            if (next <= cursor)
            {
                throw new InvalidDataException($"Binance backfill cursor did not advance for {definition.Symbol}.");
            }
            cursor = next;
            if (_options.BackfillPageDelayMilliseconds > 0)
            {
                await Task.Delay(_options.BackfillPageDelayMilliseconds, cancellationToken);
            }
        }

        return written;
    }
}
