namespace Probora.Infrastructure.Research;

public sealed class ResearchPipelineOptions
{
    public const string SectionName = "ResearchPipeline";

    public string StatePath { get; set; } = "data/raw-equity/sp500-pit/bootstrap-state.json";
    public string CoveragePath { get; set; } = "artifacts/reports/sp500-pit-coverage.json";
    public int FrozenUniverseSize { get; set; } = 734;
    public int CurrentUniverseSize { get; set; } = 758;
    public int BatchSize { get; set; } = 367;
    public int BatchCount { get; set; } = 2;
    public double RequiredDailyCoverage { get; set; } = 0.95;
}
