using Probora.Domain.Analysis;
using Probora.Domain.Markets;
using Probora.Infrastructure.Queries;

namespace Probora.UnitTests;

public sealed class ShadowPredictionProgressTests
{
    [Fact]
    public void BuildShadowProgress_WaitsBeforeFirstPrediction()
    {
        ModelVersion model = new() { Version = "candidate-30d", HorizonDays = 30 };
        DateTimeOffset now = new(2026, 7, 14, 12, 0, 0, TimeSpan.Zero);

        var result = ProboraQueryService.BuildShadowProgress(model, [], 8, now);

        Assert.Equal("waiting", result.State);
        Assert.Equal(30, result.RemainingCalendarDays);
        Assert.Equal(0, result.PredictionCount);
        Assert.Equal(0, result.CoveragePercent);
    }

    [Fact]
    public void BuildShadowProgress_TracksCalendarAndAssetCoverage()
    {
        ModelVersion model = new() { Version = "candidate-30d", HorizonDays = 30 };
        DateTimeOffset start = new(2026, 7, 14, 0, 0, 0, TimeSpan.Zero);
        Guid first = Guid.NewGuid();
        Guid second = Guid.NewGuid();
        (Guid AssetId, DateTimeOffset AnalysisTime)[] points =
        [
            (first, start),
            (second, start),
            (first, start.AddDays(1)),
            (second, start.AddDays(1))
        ];

        var result = ProboraQueryService.BuildShadowProgress(model, points, 2, start.AddDays(10));

        Assert.Equal("collecting", result.State);
        Assert.Equal(10, result.CalendarDaysElapsed);
        Assert.Equal(20, result.RemainingCalendarDays);
        Assert.Equal(2, result.PredictionDays);
        Assert.Equal(4, result.PredictionCount);
        Assert.Equal(1, result.CoveragePercent);
    }

    [Fact]
    public void BuildShadowProgress_BecomesEvaluableWhenHorizonMatures()
    {
        ModelVersion model = new() { Version = "candidate-30d", HorizonDays = 30 };
        DateTimeOffset start = new(2026, 7, 14, 0, 0, 0, TimeSpan.Zero);
        (Guid AssetId, DateTimeOffset AnalysisTime)[] points = [(Guid.NewGuid(), start)];

        var result = ProboraQueryService.BuildShadowProgress(model, points, 8, start.AddDays(30));

        Assert.Equal("evaluable", result.State);
        Assert.Equal(0, result.RemainingCalendarDays);
        Assert.Equal(1, result.MaturedPredictionCount);
    }

    [Fact]
    public void BuildShadowProgress_UsesCompletedSessionsForEquities()
    {
        ModelVersion model = new()
        {
            Version = "equity-candidate-30s",
            AssetClass = AssetClasses.UsEquity,
            HorizonDays = 30
        };
        DateTimeOffset start = new(2026, 7, 13, 0, 0, 0, TimeSpan.Zero);
        Guid asset = Guid.NewGuid();
        (Guid AssetId, DateTimeOffset AnalysisTime)[] points = Enumerable.Range(0, 31)
            .Select(index => (asset, start.AddDays(index)))
            .ToArray();

        var result = ProboraQueryService.BuildShadowProgress(model, points, 20, start.AddDays(45));

        Assert.Equal("trading_sessions", result.HorizonUnit);
        Assert.Equal(30, result.CalendarDaysElapsed);
        Assert.Equal(0, result.RemainingCalendarDays);
        Assert.Equal(1, result.MaturedPredictionCount);
        Assert.Equal("evaluable", result.State);
    }
}
