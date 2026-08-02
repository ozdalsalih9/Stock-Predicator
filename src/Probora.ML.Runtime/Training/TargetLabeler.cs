namespace Probora.ML.Runtime.Training;

public enum DirectionLabel
{
    Down = 0,
    Neutral = 1,
    Up = 2
}

public static class TargetLabeler
{
    public static DirectionLabel Label(double currentClose, double futureClose, double annualizedVolatility30, int horizonDays)
        => Label(
            currentClose,
            futureClose,
            NeutralBandThreshold(annualizedVolatility30, horizonDays, annualizedVolatility30));

    public static DirectionLabel Label(double currentClose, double futureClose, double neutralBandThreshold)
    {
        if (currentClose <= 0 || futureClose <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(currentClose), "Prices must be positive.");
        }
        double forwardReturn = Math.Log(futureClose / currentClose);
        if (!double.IsFinite(neutralBandThreshold) || neutralBandThreshold <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(neutralBandThreshold), "Neutral band must be positive and finite.");
        }
        if (forwardReturn > neutralBandThreshold)
        {
            return DirectionLabel.Up;
        }
        return forwardReturn < -neutralBandThreshold ? DirectionLabel.Down : DirectionLabel.Neutral;
    }

    public static double NeutralBandThreshold(
        double annualizedVolatilityShort,
        int horizonDays,
        double? annualizedVolatilityLong = null,
        int periodsPerYear = 365)
    {
        if (horizonDays is not (30 or 90))
        {
            throw new ArgumentOutOfRangeException(nameof(horizonDays), "Only 30 and 90 day horizons are supported.");
        }
        double longTerm = annualizedVolatilityLong ?? annualizedVolatilityShort;
        if (!double.IsFinite(annualizedVolatilityShort) || !double.IsFinite(longTerm))
        {
            throw new ArgumentOutOfRangeException(nameof(annualizedVolatilityShort), "Volatility must be finite.");
        }
        if (periodsPerYear <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(periodsPerYear));
        }

        const double longTermWeight = 0.35;
        double blended = Math.Sqrt(
            (1 - longTermWeight) * Math.Pow(annualizedVolatilityShort, 2) +
            longTermWeight * Math.Pow(longTerm, 2));
        double robustVolatility = Math.Clamp(blended, 0.20, 1.50);
        double horizonScale = Math.Sqrt(horizonDays / 30d);
        double rawThreshold = 0.5 * robustVolatility * Math.Sqrt(horizonDays / (double)periodsPerYear);
        return Math.Clamp(rawThreshold, 0.025 * horizonScale, 0.18 * horizonScale);
    }
}
