using Probora.ML.Runtime.Training;

namespace Probora.UnitTests;

public sealed class OutcomeScoringTests
{
    [Fact]
    public void MulticlassBrier_MatchesPythonDefinition()
    {
        double result = OutcomeScoring.MulticlassBrier(0.2, 0.3, 0.5, DirectionLabel.Up);

        Assert.Equal(0.38, result, 12);
    }

    [Fact]
    public void MeanQuantilePinball_MatchesReferenceCalculation()
    {
        double result = OutcomeScoring.MeanQuantilePinball(0.2, -0.1, 0.1, 0.3);

        Assert.Equal((0.03 + 0.05 + 0.01) / 3, result, 12);
    }

    [Fact]
    public void AnnualizedVolatility_UsesFutureClosesAndSampleStandardDeviation()
    {
        double[] closes = [100, 110, 99];
        double result = OutcomeScoring.AnnualizedVolatility(closes, 252);
        double[] returns = [Math.Log(1.1), Math.Log(0.9)];
        double mean = returns.Average();
        double expected = Math.Sqrt(returns.Sum(value => Math.Pow(value - mean, 2))) * Math.Sqrt(252);

        Assert.Equal(expected, result, 12);
    }

    [Fact]
    public void RiskTarget_MatchesTrainingFormula()
    {
        Assert.Equal(1 - Math.Exp(-0.4), OutcomeScoring.RiskTarget(0.4), 12);
    }
}
