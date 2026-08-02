using Probora.Domain.Markets;
using Probora.Worker.News;

namespace Probora.UnitTests;

public sealed class GdeltNewsJobTests
{
    [Fact]
    public void BuildQuery_CoversCryptoAndUsEquityWithoutTickerAmbiguity()
    {
        Asset crypto = new() { Symbol = "BTCUSDT", DisplayName = "Bitcoin", AssetClass = AssetClasses.Crypto };
        Asset equity = new() { Symbol = "V", DisplayName = "Visa", AssetClass = AssetClasses.UsEquity };

        Assert.Contains("Bitcoin", GdeltNewsJob.BuildQuery(crypto));
        string equityQuery = GdeltNewsJob.BuildQuery(equity);
        Assert.Contains("\"Visa\"", equityQuery);
        Assert.DoesNotContain(" OR \"V\"", equityQuery);
    }

    [Theory]
    [InlineData("Apple raises earnings guidance", "earnings_guidance")]
    [InlineData("Regulator opens antitrust lawsuit", "legal_regulatory")]
    [InlineData("Exchange reports cyber breach", "cyber_security")]
    [InlineData("Federal Reserve signals rate cut", "macro_policy")]
    [InlineData("Daily market update", "market_news")]
    public void ClassifyEvent_UsesTransparentRules(string title, string expected)
    {
        Assert.Equal(expected, GdeltNewsJob.ClassifyEvent(title));
    }
}
