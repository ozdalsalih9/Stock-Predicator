using Microsoft.EntityFrameworkCore;
using Probora.Application.Abstractions;
using Probora.Application.MarketData;
using Probora.Domain.Markets;

namespace Probora.Infrastructure.Persistence;

public sealed class PriceBarWriter(ProboraDbContext dbContext, TimeProvider timeProvider) : IPriceBarWriter
{
    public async Task<int> UpsertAsync(IReadOnlyCollection<PriceBarCandidate> bars, CancellationToken cancellationToken)
    {
        if (bars.Count == 0)
        {
            return 0;
        }

        foreach (PriceBarCandidate bar in bars)
        {
            IReadOnlyList<QualityViolation> violations = PriceBarQualityValidator.Validate(bar);
            if (violations.Count != 0)
            {
                throw new InvalidDataException(string.Join("; ", violations.Select(x => $"{x.Code}: {x.Message}")));
            }
        }

        Dictionary<string, Guid> assets = await dbContext.Assets
            .Where(asset => bars.Select(bar => bar.Symbol).Contains(asset.Symbol))
            .ToDictionaryAsync(x => x.Symbol, x => x.Id, StringComparer.OrdinalIgnoreCase, cancellationToken);

        int affected = 0;
        foreach (IGrouping<(string Symbol, string Interval, string Source), PriceBarCandidate> group in
                 bars.GroupBy(x => (x.Symbol.ToUpperInvariant(), x.Interval, x.Source)))
        {
            Guid assetId = assets[group.Key.Symbol];
            DateTimeOffset min = group.Min(x => x.OpenTime);
            DateTimeOffset max = group.Max(x => x.OpenTime);
            Dictionary<DateTimeOffset, PriceBar> existing = await dbContext.PriceBars
                .Where(x => x.AssetId == assetId && x.Interval == group.Key.Interval &&
                            x.Source == group.Key.Source && x.OpenTime >= min && x.OpenTime <= max)
                .ToDictionaryAsync(x => x.OpenTime, cancellationToken);

            foreach (PriceBarCandidate candidate in group)
            {
                if (existing.TryGetValue(candidate.OpenTime, out PriceBar? entity))
                {
                    if (!candidate.IsFinal && entity.IsFinal)
                    {
                        continue;
                    }

                    Apply(candidate, entity, timeProvider.GetUtcNow());
                }
                else
                {
                    entity = new PriceBar { AssetId = assetId };
                    Apply(candidate, entity, timeProvider.GetUtcNow());
                    dbContext.PriceBars.Add(entity);
                }

                affected++;
            }
        }

        await dbContext.SaveChangesAsync(cancellationToken);
        return affected;
    }

    private static void Apply(PriceBarCandidate source, PriceBar target, DateTimeOffset ingestedAt)
    {
        target.OpenTime = source.OpenTime;
        target.CloseTime = source.CloseTime;
        target.Interval = source.Interval;
        target.Open = source.Open;
        target.High = source.High;
        target.Low = source.Low;
        target.Close = source.Close;
        target.Volume = source.Volume;
        target.QuoteVolume = source.QuoteVolume;
        target.TradeCount = source.TradeCount;
        target.TakerBuyBaseVolume = source.TakerBuyBaseVolume;
        target.TakerBuyQuoteVolume = source.TakerBuyQuoteVolume;
        target.Source = source.Source;
        target.IsFinal = source.IsFinal;
        target.AvailableAt = source.AvailableAt;
        target.IngestedAt = ingestedAt;
        target.SourceChecksum = source.SourceChecksum;
    }
}
