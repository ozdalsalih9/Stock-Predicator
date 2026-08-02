using System.Text.Json;
using Probora.Domain.Markets;
using Probora.Worker.News;

namespace Probora.UnitTests;

public sealed class FinnhubNewsJobTests
{
    [Fact]
    public void IsRelevantCryptoArticle_MatchesWholeAliasesAndRejectsSubstringNoise()
    {
        using JsonDocument relevant = JsonDocument.Parse(
            """{"headline":"Solana network activity rises","summary":"","related":"SOL"}""");
        using JsonDocument noise = JsonDocument.Parse(
            """{"headline":"A new enterprise solution launches","summary":"","related":""}""");
        Asset solana = new()
        {
            Symbol = "SOLUSDT",
            BaseAsset = "SOL",
            DisplayName = "Solana",
            AssetClass = AssetClasses.Crypto
        };

        Assert.True(FinnhubNewsJob.IsRelevantCryptoArticle(relevant.RootElement, solana));
        Assert.False(FinnhubNewsJob.IsRelevantCryptoArticle(noise.RootElement, solana));
    }
}
