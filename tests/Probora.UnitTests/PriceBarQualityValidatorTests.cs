using Probora.Application.MarketData;
using Probora.Domain.Markets;

namespace Probora.UnitTests;

public sealed class PriceBarQualityValidatorTests
{
    [Fact]
    public void Validate_AcceptsConsistentUtcBar()
    {
        PriceBarCandidate bar = ValidBar();

        IReadOnlyList<QualityViolation> result = PriceBarQualityValidator.Validate(bar);

        Assert.Empty(result);
    }

    [Fact]
    public void Validate_RejectsInvalidHighAndLow()
    {
        PriceBarCandidate bar = ValidBar() with { High = 90, Low = 110 };

        IReadOnlyList<QualityViolation> result = PriceBarQualityValidator.Validate(bar);

        Assert.Contains(result, issue => issue.Code == "invalid_ohlc");
    }

    private static PriceBarCandidate ValidBar() => new(
        "BTCUSDT",
        new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero),
        new DateTimeOffset(2026, 1, 1, 0, 59, 59, TimeSpan.Zero),
        "1h",
        100,
        110,
        90,
        105,
        12,
        1_230,
        42,
        6,
        620,
        true,
        new DateTimeOffset(2026, 1, 1, 1, 0, 0, TimeSpan.Zero));
}
