namespace Probora.Domain.Analysis;

public enum AnalysisStatus
{
    Signal,
    InsufficientConfidence,
    StaleData
}

public enum RiskLevel
{
    Low,
    Medium,
    High,
    VeryHigh
}

public sealed class PredictionRecord
{
    public long Id { get; set; }
    public Guid AssetId { get; set; }
    public Guid ModelVersionId { get; set; }
    public Guid FeatureSnapshotId { get; set; }
    public DateTimeOffset AnalysisTime { get; set; }
    public int HorizonDays { get; set; }
    public double UpProbability { get; set; }
    public double NeutralProbability { get; set; }
    public double DownProbability { get; set; }
    public double ReturnP10 { get; set; }
    public double ReturnP50 { get; set; }
    public double ReturnP90 { get; set; }
    public double RiskScore { get; set; }
    public RiskLevel RiskLevel { get; set; }
    public double ConfidenceScore { get; set; }
    public AnalysisStatus Status { get; set; }
    public string PositiveFactorsJson { get; set; } = "[]";
    public string NegativeFactorsJson { get; set; } = "[]";
    public string LimitationsJson { get; set; } = "[]";
    public string ArtifactSha256 { get; set; } = string.Empty;
    public bool IsShadow { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

public sealed class ModelVersion
{
    public Guid Id { get; set; }
    public string Version { get; set; } = string.Empty;
    public int HorizonDays { get; set; }
    public string AssetClass { get; set; } = "crypto";
    public string FeatureSetVersion { get; set; } = string.Empty;
    public string DatasetVersion { get; set; } = string.Empty;
    public string ArtifactPath { get; set; } = string.Empty;
    public string ArtifactSha256 { get; set; } = string.Empty;
    public string MetricsJson { get; set; } = "{}";
    public DateTimeOffset TrainedAt { get; set; }
    public bool IsProduction { get; set; }
    public bool IsShadowCandidate { get; set; }
    public bool DirectionEligible { get; set; }
    public bool ScenarioEligible { get; set; }
}

public sealed class FeatureSnapshot
{
    public Guid Id { get; set; }
    public Guid AssetId { get; set; }
    public DateTimeOffset SnapshotTime { get; set; }
    public string FeatureSetVersion { get; set; } = string.Empty;
    public string FeaturesJson { get; set; } = "{}";
    public string InputDataSha256 { get; set; } = string.Empty;
    public DateTimeOffset CreatedAt { get; set; }
}
