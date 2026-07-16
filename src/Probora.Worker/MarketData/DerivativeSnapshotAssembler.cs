using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace Probora.Worker.MarketData;

public sealed record FuturesKlinePoint(
    DateTimeOffset OpenTime,
    DateTimeOffset CloseTime,
    double Volume,
    double QuoteVolume,
    double TakerBuyBaseVolume);

public sealed record TimedValue(DateTimeOffset Time, double Value);

public sealed record TimedKlineValue(DateTimeOffset OpenTime, DateTimeOffset CloseTime, double Value);

public sealed record DerivativeSnapshotValues(
    DateTimeOffset SnapshotTime,
    double FundingRate,
    double Premium,
    double FuturesQuoteVolume,
    double FuturesTakerBuyRatio,
    double OpenInterestValue,
    double LongShortRatio,
    double TakerLongShortRatio,
    int FuturesKlineCount,
    int PremiumKlineCount,
    int FundingPointCount,
    int OpenInterestPointCount,
    int LongShortPointCount,
    int TakerLongShortPointCount,
    DateTimeOffset SourceMaxEventTime,
    string SourceChecksum);

public static class DerivativeSnapshotAssembler
{
    private const int ExpectedHourlyPoints = 24;
    private const int ExpectedFiveMinutePoints = 288;

    public static DerivativeSnapshotValues Assemble(
        DateTimeOffset cutoff,
        IReadOnlyList<FuturesKlinePoint> futures,
        IReadOnlyList<TimedKlineValue> premium,
        IReadOnlyList<TimedValue> funding,
        IReadOnlyList<TimedValue> openInterest,
        IReadOnlyList<TimedValue> longShort,
        IReadOnlyList<TimedValue> takerLongShort)
    {
        EnsureUtcMidnight(cutoff);
        DateTimeOffset start = cutoff.AddDays(-1);
        FuturesKlinePoint[] orderedFutures = futures.OrderBy(x => x.OpenTime).ToArray();
        TimedKlineValue[] orderedPremium = premium.OrderBy(x => x.OpenTime).ToArray();
        TimedValue[] orderedFunding = funding.OrderBy(x => x.Time).ToArray();
        TimedValue[] orderedOpenInterest = openInterest.OrderBy(x => x.Time).ToArray();
        TimedValue[] orderedLongShort = longShort.OrderBy(x => x.Time).ToArray();
        TimedValue[] orderedTakerLongShort = takerLongShort.OrderBy(x => x.Time).ToArray();

        EnsureGrid("futures klines", orderedFutures.Select(x => x.OpenTime), start, TimeSpan.FromHours(1), ExpectedHourlyPoints);
        EnsureGrid("premium klines", orderedPremium.Select(x => x.OpenTime), start, TimeSpan.FromHours(1), ExpectedHourlyPoints);
        EnsureGrid("open interest", orderedOpenInterest.Select(x => x.Time), start, TimeSpan.FromMinutes(5), ExpectedFiveMinutePoints);
        EnsureGrid("long/short ratio", orderedLongShort.Select(x => x.Time), start, TimeSpan.FromMinutes(5), ExpectedFiveMinutePoints);
        EnsureGrid("taker ratio", orderedTakerLongShort.Select(x => x.Time), start, TimeSpan.FromMinutes(5), ExpectedFiveMinutePoints);
        EnsureWindow("funding", orderedFunding.Select(x => x.Time), start, cutoff, requireAny: true);

        if (orderedFutures.Any(x => x.CloseTime >= cutoff) || orderedPremium.Any(x => x.CloseTime >= cutoff))
        {
            throw new InvalidDataException("A response includes a candle that was not final at the UTC cutoff.");
        }
        EnsureFinitePositive("futures volume", orderedFutures.Select(x => x.Volume), allowZero: true);
        EnsureFinitePositive("futures quote volume", orderedFutures.Select(x => x.QuoteVolume), allowZero: true);
        EnsureFinitePositive("futures taker buy volume", orderedFutures.Select(x => x.TakerBuyBaseVolume), allowZero: true);
        EnsureFinitePositive("open interest", orderedOpenInterest.Select(x => x.Value), allowZero: false);
        EnsureFinitePositive("long/short ratio", orderedLongShort.Select(x => x.Value), allowZero: false);
        EnsureFinitePositive("taker ratio", orderedTakerLongShort.Select(x => x.Value), allowZero: false);
        EnsureFinite("premium", orderedPremium.Select(x => x.Value));
        EnsureFinite("funding", orderedFunding.Select(x => x.Value));

        double volume = orderedFutures.Sum(x => x.Volume);
        double takerBuyRatio = volume == 0 ? 0.5 : orderedFutures.Sum(x => x.TakerBuyBaseVolume) / volume;
        if (!double.IsFinite(takerBuyRatio) || takerBuyRatio < 0 || takerBuyRatio > 1)
        {
            throw new InvalidDataException("Futures taker buy ratio is outside [0, 1].");
        }

        DateTimeOffset sourceMaxEventTime = new[]
        {
            orderedFutures.Max(x => x.CloseTime),
            orderedPremium.Max(x => x.CloseTime),
            orderedFunding.Max(x => x.Time),
            orderedOpenInterest.Max(x => x.Time),
            orderedLongShort.Max(x => x.Time),
            orderedTakerLongShort.Max(x => x.Time)
        }.Max();
        StringBuilder identity = new(cutoff.ToString("O", CultureInfo.InvariantCulture));
        foreach (FuturesKlinePoint point in orderedFutures)
        {
            identity.Append('|').Append(point.OpenTime.ToString("O", CultureInfo.InvariantCulture))
                .Append(':').Append(point.Volume.ToString("R", CultureInfo.InvariantCulture))
                .Append(':').Append(point.QuoteVolume.ToString("R", CultureInfo.InvariantCulture))
                .Append(':').Append(point.TakerBuyBaseVolume.ToString("R", CultureInfo.InvariantCulture));
        }
        Append(identity, orderedPremium.Select(x => new TimedValue(x.OpenTime, x.Value)));
        Append(identity, orderedFunding);
        Append(identity, orderedOpenInterest);
        Append(identity, orderedLongShort);
        Append(identity, orderedTakerLongShort);

        return new DerivativeSnapshotValues(
            cutoff,
            orderedFunding.Average(x => x.Value),
            orderedPremium[^1].Value,
            orderedFutures.Sum(x => x.QuoteVolume),
            takerBuyRatio,
            orderedOpenInterest[^1].Value,
            orderedLongShort.Average(x => x.Value),
            orderedTakerLongShort.Average(x => x.Value),
            orderedFutures.Length,
            orderedPremium.Length,
            orderedFunding.Length,
            orderedOpenInterest.Length,
            orderedLongShort.Length,
            orderedTakerLongShort.Length,
            sourceMaxEventTime,
            Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(identity.ToString()))).ToLowerInvariant());
    }

    private static void EnsureUtcMidnight(DateTimeOffset cutoff)
    {
        if (cutoff.Offset != TimeSpan.Zero || cutoff.TimeOfDay != TimeSpan.Zero)
        {
            throw new ArgumentException("Cutoff must be exactly 00:00 UTC.", nameof(cutoff));
        }
    }

    private static void Append(StringBuilder identity, IEnumerable<TimedValue> values)
    {
        foreach (TimedValue point in values)
        {
            identity.Append('|').Append(point.Time.ToString("O", CultureInfo.InvariantCulture))
                .Append(':').Append(point.Value.ToString("R", CultureInfo.InvariantCulture));
        }
    }

    private static void EnsureGrid(
        string name,
        IEnumerable<DateTimeOffset> times,
        DateTimeOffset start,
        TimeSpan interval,
        int expectedCount)
    {
        DateTimeOffset[] actual = times.Order().ToArray();
        if (actual.Length != expectedCount)
        {
            throw new InvalidDataException($"{name} contains {actual.Length} points; expected {expectedCount}.");
        }
        for (int index = 0; index < expectedCount; index++)
        {
            DateTimeOffset expected = start.AddTicks(interval.Ticks * index);
            if (actual[index] != expected)
            {
                throw new InvalidDataException($"{name} is not contiguous at {expected:O}.");
            }
        }
    }

    private static void EnsureWindow(
        string name,
        IEnumerable<DateTimeOffset> times,
        DateTimeOffset start,
        DateTimeOffset cutoff,
        bool requireAny)
    {
        DateTimeOffset[] actual = times.ToArray();
        if ((requireAny && actual.Length == 0) || actual.Any(x => x < start || x >= cutoff))
        {
            throw new InvalidDataException($"{name} is empty or contains a point outside [{start:O}, {cutoff:O}).");
        }
    }

    private static void EnsureFinite(string name, IEnumerable<double> values)
    {
        if (values.Any(x => !double.IsFinite(x)))
        {
            throw new InvalidDataException($"{name} contains a non-finite value.");
        }
    }

    private static void EnsureFinitePositive(string name, IEnumerable<double> values, bool allowZero)
    {
        if (values.Any(x => !double.IsFinite(x) || (allowZero ? x < 0 : x <= 0)))
        {
            throw new InvalidDataException($"{name} contains an invalid value.");
        }
    }
}
