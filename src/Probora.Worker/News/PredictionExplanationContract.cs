namespace Probora.Worker.News;

public sealed record ExplanationProbabilityContract(double Down, double Neutral, double Up);

public sealed record ExplanationReturnContract(double P10, double P50, double P90);

public sealed record ExplanationNewsContract(
    string Title,
    string SourceName,
    string SourceUrl,
    string Provider,
    DateTimeOffset PublishedAt,
    DateTimeOffset AvailableAt,
    string EventType,
    double SourceReliability,
    double Relevance);

public sealed record PredictionExplanationContract(
    long PredictionId,
    string Asset,
    string AssetClass,
    DateTimeOffset Cutoff,
    int HorizonDays,
    ExplanationProbabilityContract Probabilities,
    ExplanationProbabilityContract? BaselineProbabilities,
    ExplanationReturnContract ReturnInterval,
    double RiskScore,
    string RiskLevel,
    double ConfidenceScore,
    string Status,
    IReadOnlyList<string> PositiveFactors,
    IReadOnlyList<string> NegativeFactors,
    IReadOnlyList<string> Limitations,
    IReadOnlyDictionary<string, double> NumericFeatures,
    DateTimeOffset FeatureDataAt,
    DateTimeOffset? LatestNewsAvailableAt,
    IReadOnlyList<ExplanationNewsContract> RelevantNews,
    string ModelVersion,
    string FeatureSetVersion,
    string ArtifactSha256);

public sealed class PredictionExplanationOutput
{
    public string Summary { get; init; } = string.Empty;
    public IReadOnlyList<string> SupportingFactors { get; init; } = [];
    public IReadOnlyList<string> RiskFactors { get; init; } = [];
    public IReadOnlyList<string> Contradictions { get; init; } = [];
    public IReadOnlyList<string> UncertaintyNotes { get; init; } = [];
    public IReadOnlyList<PredictionNewsAssessment> NewsAssessment { get; init; } = [];
    public string Disclaimer { get; init; } = string.Empty;
}

public sealed class PredictionNewsAssessment
{
    public string SourceUrl { get; init; } = string.Empty;
    public string Impact { get; init; } = "neutral";
    public string Rationale { get; init; } = string.Empty;
}
