using Probora.Worker.MarketData;

namespace Probora.UnitTests;

public sealed class BinanceTimestampTests
{
    [Theory]
    [InlineData(1735689600000)]
    [InlineData(1735689600000000)]
    public void FromUnixTimestamp_NormalizesMillisecondsAndMicroseconds(long input)
    {
        DateTimeOffset result = BinanceRestClient.FromUnixTimestamp(input);

        Assert.Equal(new DateTimeOffset(2025, 1, 1, 0, 0, 0, TimeSpan.Zero), result);
    }
}
