using Probora.Domain.Markets;
using Probora.Worker.Models;

namespace Probora.UnitTests;

public sealed class DerivativeHistoryReadinessTests
{
    [Fact]
    public void TryCreate_AcceptsOnlyConsecutiveAvailableAsOfHistory()
    {
        DateTimeOffset cutoff = new(2026, 7, 14, 0, 0, 0, TimeSpan.Zero);
        DerivativeDailySnapshot[] snapshots = Enumerable.Range(0, 90)
            .Select(index => Snapshot(cutoff.AddDays(index - 89)))
            .ToArray();

        bool ready = DerivativeHistoryReadiness.TryCreate(
            snapshots,
            cutoff,
            cutoff.AddMinutes(10),
            90,
            out var observations,
            out string reason);

        Assert.True(ready, reason);
        Assert.Equal(90, observations.Length);
        Assert.Equal(cutoff, observations[^1].Time);
    }

    [Fact]
    public void TryCreate_RejectsGapInsteadOfSilentlyShorteningRollingWindow()
    {
        DateTimeOffset cutoff = new(2026, 7, 14, 0, 0, 0, TimeSpan.Zero);
        DerivativeDailySnapshot[] snapshots = Enumerable.Range(0, 90)
            .Where(index => index != 45)
            .Select(index => Snapshot(cutoff.AddDays(index - 89)))
            .ToArray();

        bool ready = DerivativeHistoryReadiness.TryCreate(
            snapshots,
            cutoff,
            cutoff.AddMinutes(10),
            90,
            out var observations,
            out string reason);

        Assert.False(ready);
        Assert.Empty(observations);
        Assert.Contains("89/90", reason, StringComparison.Ordinal);
    }

    private static DerivativeDailySnapshot Snapshot(DateTimeOffset time) => new()
    {
        SnapshotTime = time,
        FundingRate = 0.0001,
        Premium = 0.0002,
        FuturesQuoteVolume = 1_000,
        FuturesTakerBuyRatio = 0.5,
        OpenInterestValue = 1_000_000,
        LongShortRatio = 1.1,
        TakerLongShortRatio = 0.9,
        IsComplete = true,
        SourceMaxEventTime = time.AddMilliseconds(-1),
        AvailableAt = time.AddMinutes(5)
    };
}
