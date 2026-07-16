using Probora.ML.Runtime.Inference;

namespace Probora.UnitTests;

public sealed class ConformalIntervalCalibrationTests
{
    [Fact]
    public void VolatilityScaledAdjustmentMatchesTrainingFormula()
    {
        ModelManifest manifest = Manifest() with
        {
            HorizonDays = 90,
            ConformalMode = "volatility_scaled",
            ConformalScaleFeature = "volatility_60s",
            ConformalMultiplier = 0.5,
            ConformalPeriodsPerYear = 252
        };

        double adjustment = ConformalIntervalCalibration.ResolveAdjustment(
            manifest, new Dictionary<string, double> { ["volatility_60s"] = 0.4 });

        Assert.Equal(0.5 * 0.4 * Math.Sqrt(90d / 252d), adjustment, 12);
    }

    [Fact]
    public void LegacyManifestUsesAbsoluteAdjustment()
    {
        ModelManifest manifest = Manifest() with { ConformalAdjustment = 0.07 };

        double adjustment = ConformalIntervalCalibration.ResolveAdjustment(
            manifest, new Dictionary<string, double>());

        Assert.Equal(0.07, adjustment);
    }

    private static ModelManifest Manifest() => new(
        "test",
        30,
        "features",
        "dataset",
        new string('0', 64),
        1,
        0.55,
        0.15,
        ["direction.onnx"],
        new Dictionary<string, string>
        {
            ["p10"] = "p10.onnx",
            ["p50"] = "p50.onnx",
            ["p90"] = "p90.onnx"
        },
        "risk.onnx");
}
