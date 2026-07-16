using Probora.Domain.Markets;

namespace Probora.UnitTests;

public sealed class AssetUniverseTests
{
    [Fact]
    public void PilotUniverse_IsSeparatedFromCryptoCollectors()
    {
        Assert.Equal(8, AssetCatalog.Crypto.Count);
        Assert.Equal(20, AssetCatalog.UsEquityPilot.Count);
        Assert.All(AssetCatalog.Crypto, asset => Assert.Equal(AssetClasses.Crypto, asset.AssetClass));
        Assert.All(
            AssetCatalog.UsEquityPilot,
            asset => Assert.Equal(AssetClasses.UsEquity, asset.AssetClass));
        Assert.Equal(
            AssetCatalog.All.Count,
            AssetCatalog.All.Select(x => x.Symbol).Distinct(StringComparer.OrdinalIgnoreCase).Count());
    }
}
