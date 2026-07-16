namespace Probora.ML.Runtime.Inference;

public sealed record ModelManifest(
    string Version,
    int HorizonDays,
    string FeatureSetVersion,
    string DatasetVersion,
    string ArtifactSha256,
    double Temperature,
    double MinimumProbability,
    double MinimumMargin,
    IReadOnlyList<string> DirectionModels,
    IReadOnlyDictionary<string, string> QuantileModels,
    string RiskModel,
    double ConformalAdjustment = 0,
    string ConformalMode = "absolute",
    string? ConformalScaleFeature = null,
    double ConformalMultiplier = 0,
    int ConformalPeriodsPerYear = 365,
    string InputName = "features",
    string OutputName = "probabilities",
    bool ProductionEligible = false,
    double ProbabilityBlendWeight = 1,
    IReadOnlyList<double>? ClassPrior = null,
    string AssetClass = "crypto",
    bool DirectionEligible = true,
    bool ScenarioEligible = true,
    IReadOnlyDictionary<string, double>? FeatureReference = null);

public sealed record RuntimePrediction(
    double Up,
    double Neutral,
    double Down,
    double P10,
    double P50,
    double P90,
    double RiskScore);
