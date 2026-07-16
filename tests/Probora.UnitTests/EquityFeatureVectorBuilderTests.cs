using Probora.ML.Runtime.Features;

namespace Probora.UnitTests;

public sealed class EquityFeatureVectorBuilderTests
{
    [Fact]
    public void Build_ProducesCompleteFiniteEquitySchema()
    {
        DateTimeOffset start = new(2025, 1, 2, 0, 0, 0, TimeSpan.Zero);
        MarketObservation[] benchmark = Enumerable.Range(0, 260)
            .Select(index => Observation(start.AddDays(index), 100 + index * 0.2, 1_000_000 + index))
            .ToArray();
        MarketObservation[] asset = Enumerable.Range(0, 260)
            .Select(index => Observation(start.AddDays(index), 50 + index * 0.15, 500_000 + index * 2))
            .ToArray();

        FeatureVector result = EquityFeatureVectorBuilder.Build(asset, benchmark, 0.65, 0.7, 0.6, 0.4);

        Assert.Equal(EquityFeatureSchema.Version, result.FeatureSetVersion);
        Assert.Equal(EquityFeatureSchema.Names.Count, result.Values.Count);
        Assert.All(EquityFeatureSchema.Names, name => Assert.True(result.Values.ContainsKey(name)));
        Assert.All(result.Values.Values, value => Assert.True(double.IsFinite(value)));
    }

    private static MarketObservation Observation(DateTimeOffset time, double close, double volume) =>
        new(time, close * 0.995, close * 1.01, close * 0.99, close, volume, close * volume, 0, 0);
}
