using Probora.Worker.MarketData;

namespace Probora.UnitTests;

public sealed class DerivativeSnapshotAssemblerTests
{
    private static readonly DateTimeOffset Cutoff = new(2026, 7, 14, 0, 0, 0, TimeSpan.Zero);

    [Fact]
    public void Assemble_RequiresCompleteUtcGridsAndMatchesTrainingAggregation()
    {
        DateTimeOffset start = Cutoff.AddDays(-1);
        FuturesKlinePoint[] futures = Enumerable.Range(0, 24)
            .Select(index => new FuturesKlinePoint(
                start.AddHours(index),
                start.AddHours(index + 1).AddMilliseconds(-1),
                100,
                1_000,
                40))
            .ToArray();
        TimedKlineValue[] premium = Enumerable.Range(0, 24)
            .Select(index => new TimedKlineValue(
                start.AddHours(index),
                start.AddHours(index + 1).AddMilliseconds(-1),
                index / 1_000d))
            .ToArray();
        TimedValue[] funding = Enumerable.Range(0, 3)
            .Select(index => new TimedValue(start.AddHours(index * 8), (index + 1) / 10_000d))
            .ToArray();
        TimedValue[] openInterest = FiveMinutePoints(start, index => 1_000_000 + index);
        TimedValue[] longShort = FiveMinutePoints(start, _ => 1.2);
        TimedValue[] takerLongShort = FiveMinutePoints(start, _ => 0.9);

        DerivativeSnapshotValues result = DerivativeSnapshotAssembler.Assemble(
            Cutoff,
            futures,
            premium,
            funding,
            openInterest,
            longShort,
            takerLongShort);

        Assert.Equal(Cutoff, result.SnapshotTime);
        Assert.Equal(24_000, result.FuturesQuoteVolume);
        Assert.Equal(0.4, result.FuturesTakerBuyRatio, 12);
        Assert.Equal(0.023, result.Premium, 12);
        Assert.Equal(0.0002, result.FundingRate, 12);
        Assert.Equal(1_000_287, result.OpenInterestValue);
        Assert.Equal(288, result.OpenInterestPointCount);
        Assert.Equal(64, result.SourceChecksum.Length);
        Assert.True(result.SourceMaxEventTime < result.SnapshotTime);
    }

    [Fact]
    public void Assemble_RejectsOneMissingFiveMinuteBucket()
    {
        DateTimeOffset start = Cutoff.AddDays(-1);
        TimedValue[] incomplete = FiveMinutePoints(start, index => 1_000_000 + index).Skip(1).ToArray();

        InvalidDataException exception = Assert.Throws<InvalidDataException>(() =>
            DerivativeSnapshotAssembler.Assemble(
                Cutoff,
                Enumerable.Range(0, 24).Select(index => new FuturesKlinePoint(
                    start.AddHours(index),
                    start.AddHours(index + 1).AddMilliseconds(-1),
                    100,
                    1_000,
                    40)).ToArray(),
                Enumerable.Range(0, 24).Select(index => new TimedKlineValue(
                    start.AddHours(index),
                    start.AddHours(index + 1).AddMilliseconds(-1),
                    0.001)).ToArray(),
                [new TimedValue(start, 0.0001)],
                incomplete,
                FiveMinutePoints(start, _ => 1.2),
                FiveMinutePoints(start, _ => 0.9)));

        Assert.Contains("expected 288", exception.Message, StringComparison.Ordinal);
    }

    private static TimedValue[] FiveMinutePoints(DateTimeOffset start, Func<int, double> value) =>
        Enumerable.Range(0, 288)
            .Select(index => new TimedValue(start.AddMinutes(index * 5), value(index)))
            .ToArray();
}
