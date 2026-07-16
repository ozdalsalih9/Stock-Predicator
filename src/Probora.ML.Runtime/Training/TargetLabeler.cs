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
    {
        if (currentClose <= 0 || futureClose <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(currentClose), "Prices must be positive.");
        }
        if (horizonDays is not (30 or 90))
        {
            throw new ArgumentOutOfRangeException(nameof(horizonDays), "Only 30 and 90 day horizons are supported.");
        }

        double forwardReturn = Math.Log(futureClose / currentClose);
        double threshold = 0.5 * annualizedVolatility30 * Math.Sqrt(horizonDays / 365d);
        if (forwardReturn > threshold)
        {
            return DirectionLabel.Up;
        }
        return forwardReturn < -threshold ? DirectionLabel.Down : DirectionLabel.Neutral;
    }
}
