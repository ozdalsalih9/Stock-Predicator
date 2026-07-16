namespace Probora.Contracts.Analysis;

public sealed record ProbabilityResponse(double Up, double Neutral, double Down);

public sealed record ReturnRangeResponse(double P10, double P50, double P90);

public sealed record FreshnessResponse(
    DateTimeOffset? PriceDataAt,
    DateTimeOffset? FeatureDataAt,
    DateTimeOffset? NewsDataAt,
    string State);

public sealed record AnalysisResponse(
    string Symbol,
    DateTimeOffset AnalysisTime,
    int HorizonDays,
    ProbabilityResponse Direction,
    ReturnRangeResponse ExpectedReturn,
    double RiskScore,
    string RiskLevel,
    double ConfidenceScore,
    string ConfidenceLevel,
    string Status,
    bool IsShadow,
    bool DirectionEligible,
    bool ScenarioEligible,
    IReadOnlyList<string> PositiveFactors,
    IReadOnlyList<string> NegativeFactors,
    FreshnessResponse DataFreshness,
    string ModelVersion,
    string FeatureSetVersion,
    string DatasetVersion,
    IReadOnlyList<string> Limitations);

public sealed record ModelCardResponse(
    string Version,
    int HorizonDays,
    string FeatureSetVersion,
    string DatasetVersion,
    DateTimeOffset TrainedAt,
    bool IsProduction,
    bool DirectionEligible,
    bool ScenarioEligible,
    IReadOnlyDictionary<string, double> Metrics,
    IReadOnlyList<string> KnownLimitations);

public sealed record PerformanceResponse(
    string? Symbol,
    int HorizonDays,
    string ModelVersion,
    double BrierScore,
    double BaselineBrierScore,
    double ExpectedCalibrationError,
    double DirectionalAccuracy,
    double IntervalCoverage,
    int SampleCount,
    DateTimeOffset EvaluatedThrough);
