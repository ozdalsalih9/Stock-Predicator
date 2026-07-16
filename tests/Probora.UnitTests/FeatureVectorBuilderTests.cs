using System.Text.Json;
using Probora.ML.Runtime.Features;

namespace Probora.UnitTests;

public sealed class FeatureVectorBuilderTests
{
    [Fact]
    public void Build_ReturnsFiniteValuesInCanonicalOrder()
    {
        MarketObservation[] observations = Enumerable.Range(0, 400)
            .Select(index => new MarketObservation(
                new DateTimeOffset(2025, 1, 1, 0, 0, 0, TimeSpan.Zero).AddDays(index),
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                1_000 + index,
                100_000 + index,
                500 + index,
                500 + index / 2d))
            .ToArray();

        FeatureVector result = FeatureVectorBuilder.Build(observations, observations, 0.75);

        Assert.Equal(FeatureSchema.Names.Count, result.Values.Count);
        Assert.All(result.Values.Values, value => Assert.True(double.IsFinite(value)));
        Assert.Equal(FeatureSchema.Names.Count, result.ToModelInput().Length);
    }

    [Fact]
    public void Build_MatchesSharedPythonGoldenFixture()
    {
        MarketObservation[] observations = Enumerable.Range(0, 400)
            .Select(index => new MarketObservation(
                new DateTimeOffset(2025, 1, 1, 0, 0, 0, TimeSpan.Zero).AddDays(index),
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                1_000 + index,
                100_000 + index,
                500 + index,
                500 + index / 2d))
            .ToArray();

        FeatureVector actual = FeatureVectorBuilder.Build(observations, observations, 0.75);
        string fixturePath = Path.Combine(FindRepositoryRoot(), "tests", "fixtures", "feature-parity-v2.json");
        Dictionary<string, double> expected = JsonSerializer.Deserialize<Dictionary<string, double>>(
            File.ReadAllText(fixturePath))!;

        Assert.Equal(FeatureSchema.Names.Order(), expected.Keys.Order());
        foreach (string name in FeatureSchema.Names)
        {
            Assert.Equal(expected[name], actual.Values[name], 10);
        }
    }

    private static string FindRepositoryRoot()
    {
        DirectoryInfo? current = new(AppContext.BaseDirectory);
        while (current is not null && !File.Exists(Path.Combine(current.FullName, "Probora.slnx")))
        {
            current = current.Parent;
        }

        return current?.FullName ?? throw new DirectoryNotFoundException("Repository root was not found.");
    }
}
