using Microsoft.Extensions.Options;
using Probora.Infrastructure.Research;

namespace Probora.UnitTests;

public sealed class ResearchPipelineStatusReaderTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"probora-research-{Guid.NewGuid():N}");

    [Fact]
    public async Task GetAsync_CombinesBootstrapAndCoverageSnapshots()
    {
        Directory.CreateDirectory(_directory);
        string statePath = Path.Combine(_directory, "state.json");
        string coveragePath = Path.Combine(_directory, "coverage.json");
        await File.WriteAllTextAsync(statePath, """
            {
              "universe_size": 8,
              "batch_count": 2,
              "updated_at": "2026-07-20T12:00:00Z",
              "symbols": {
                "AAPL": { "status": "succeeded", "row_count": 10 },
                "MSFT": { "status": "succeeded", "row_count": 15 }
              }
            }
            """);
        await File.WriteAllTextAsync(coveragePath, """
            {
              "checked_at": "2026-07-20T12:01:00Z",
              "mean_daily_coverage": 0.25,
              "minimum_daily_coverage": 0.20,
              "latest_daily_coverage": 0.30,
              "minimum_required_daily_coverage": 0.95,
              "coverage_ready": false,
              "membership_last_snapshot_date": "2026-07-20",
              "membership_freshness_days": 0,
              "membership_fresh": true
            }
            """);
        ResearchPipelineStatusReader reader = CreateReader(statePath, coveragePath);

        var result = await reader.GetAsync(CancellationToken.None);

        Assert.Equal("collecting", result.State);
        Assert.Equal(2, result.ProcessedSymbols);
        Assert.Equal(25, result.DownloadedBars);
        Assert.Equal(50, result.BatchProgressPercent);
        Assert.Equal(20, result.OverallProgressPercent);
        Assert.Equal(0.25, result.MeanDailyCoverage);
        Assert.True(result.MembershipFresh);
        Assert.False(result.CoverageReady);
    }

    [Fact]
    public async Task GetAsync_ReturnsNoDataWhenSnapshotsAreMissing()
    {
        ResearchPipelineStatusReader reader = CreateReader(
            Path.Combine(_directory, "missing-state.json"),
            Path.Combine(_directory, "missing-coverage.json"));

        var result = await reader.GetAsync(CancellationToken.None);

        Assert.Equal("no_data", result.State);
        Assert.Equal(0, result.ProcessedSymbols);
        Assert.Equal(0, result.DownloadedBars);
    }

    [Fact]
    public async Task GetAsync_ShowsCompletedBatchWhileWaitingForNextQuotaWindow()
    {
        Directory.CreateDirectory(_directory);
        string statePath = Path.Combine(_directory, "batch-boundary.json");
        await File.WriteAllTextAsync(statePath, """
            {
              "universe_size": 8,
              "batch_count": 2,
              "symbols": {
                "A": { "status": "succeeded", "row_count": 1 },
                "B": { "status": "succeeded", "row_count": 1 },
                "C": { "status": "succeeded", "row_count": 1 },
                "D": { "status": "succeeded", "row_count": 1 }
              }
            }
            """);
        ResearchPipelineStatusReader reader = CreateReader(statePath, Path.Combine(_directory, "missing.json"));

        var result = await reader.GetAsync(CancellationToken.None);

        Assert.Equal("waiting_next_batch", result.State);
        Assert.Equal(1, result.BatchNumber);
        Assert.Equal(4, result.BatchProcessedSymbols);
        Assert.Equal(100, result.BatchProgressPercent);
    }

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }

        GC.SuppressFinalize(this);
    }

    private static ResearchPipelineStatusReader CreateReader(string statePath, string coveragePath) =>
        new(Options.Create(new ResearchPipelineOptions
        {
            StatePath = statePath,
            CoveragePath = coveragePath,
            FrozenUniverseSize = 8,
            CurrentUniverseSize = 10,
            BatchSize = 4,
            BatchCount = 2
        }));
}
