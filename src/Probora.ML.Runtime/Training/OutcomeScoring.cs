namespace Probora.ML.Runtime.Training;

public static class OutcomeScoring
{
    public static double MulticlassBrier(
        double downProbability,
        double neutralProbability,
        double upProbability,
        DirectionLabel realizedDirection)
    {
        ValidateProbabilities(downProbability, neutralProbability, upProbability);
        double downTarget = realizedDirection == DirectionLabel.Down ? 1 : 0;
        double neutralTarget = realizedDirection == DirectionLabel.Neutral ? 1 : 0;
        double upTarget = realizedDirection == DirectionLabel.Up ? 1 : 0;
        return Math.Pow(downProbability - downTarget, 2) +
               Math.Pow(neutralProbability - neutralTarget, 2) +
               Math.Pow(upProbability - upTarget, 2);
    }

    public static double MeanQuantilePinball(
        double realizedReturn,
        double p10,
        double p50,
        double p90) =>
        (Pinball(realizedReturn, p10, 0.1) +
         Pinball(realizedReturn, p50, 0.5) +
         Pinball(realizedReturn, p90, 0.9)) / 3;

    public static double AnnualizedVolatility(IReadOnlyList<double> futureCloses, int periodsPerYear)
    {
        if (futureCloses.Count < 3 || futureCloses.Any(value => value <= 0))
        {
            throw new ArgumentException("At least three positive future closes are required.", nameof(futureCloses));
        }
        double[] returns = futureCloses.Skip(1)
            .Select((close, index) => Math.Log(close / futureCloses[index]))
            .ToArray();
        double mean = returns.Average();
        double variance = returns.Sum(value => Math.Pow(value - mean, 2)) / (returns.Length - 1);
        return Math.Sqrt(variance) * Math.Sqrt(periodsPerYear);
    }

    public static double RiskTarget(double annualizedVolatility) =>
        1 - Math.Exp(-Math.Max(0, annualizedVolatility));

    private static double Pinball(double target, double prediction, double quantile)
    {
        double error = target - prediction;
        return error >= 0 ? quantile * error : (quantile - 1) * error;
    }

    private static void ValidateProbabilities(params double[] probabilities)
    {
        if (probabilities.Any(value => !double.IsFinite(value) || value < 0 || value > 1) ||
            Math.Abs(probabilities.Sum() - 1) > 1e-5)
        {
            throw new ArgumentException("Probabilities must be finite, within [0,1], and sum to one.");
        }
    }
}
