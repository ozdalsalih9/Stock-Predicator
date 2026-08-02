using Probora.Domain.Markets;
using Probora.Infrastructure.Queries;

namespace Probora.UnitTests;

public sealed class PriceFreshnessWindowTests
{
    [Fact]
    public void UsesIntradayWindowForCrypto()
    {
        Assert.Equal(TimeSpan.FromHours(2), ProboraQueryService.PriceFreshnessWindow(AssetClasses.Crypto));
    }

    [Fact]
    public void UsesCompletedSessionWindowForUsEquities()
    {
        Assert.Equal(TimeSpan.FromDays(5), ProboraQueryService.PriceFreshnessWindow(AssetClasses.UsEquity));
    }
}
