namespace Probora.ML.Runtime.Inference;

public static class ConformalIntervalCalibration
{
    public static double ResolveAdjustment(
        ModelManifest manifest,
        IReadOnlyDictionary<string, double> features)
    {
        if (!string.Equals(manifest.ConformalMode, "volatility_scaled", StringComparison.Ordinal) ||
            manifest.ConformalScaleFeature is null ||
            !features.TryGetValue(manifest.ConformalScaleFeature, out double annualizedVolatility))
        {
            return Math.Max(0, manifest.ConformalAdjustment);
        }

        double periods = Math.Max(1, manifest.ConformalPeriodsPerYear);
        double scale = Math.Max(annualizedVolatility, 0) * Math.Sqrt(manifest.HorizonDays / periods);
        return Math.Max(0, manifest.ConformalMultiplier) * Math.Max(scale, 1e-4);
    }
}
