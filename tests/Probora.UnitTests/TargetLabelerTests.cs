using Probora.ML.Runtime.Training;

namespace Probora.UnitTests;

public sealed class TargetLabelerTests
{
    [Theory]
    [InlineData(100, 130, DirectionLabel.Up)]
    [InlineData(100, 70, DirectionLabel.Down)]
    [InlineData(100, 101, DirectionLabel.Neutral)]
    public void Label_UsesVolatilityAdjustedThreshold(double current, double future, DirectionLabel expected)
    {
        DirectionLabel actual = TargetLabeler.Label(current, future, 0.50, 30);

        Assert.Equal(expected, actual);
    }

    [Theory]
    [InlineData(0.42, 30, 0.61, 365, 0.07093721901157311)]
    [InlineData(0.42, 90, 0.61, 365, 0.12286686747568552)]
    [InlineData(0.18, 30, 0.22, 252, 0.03450327796711771)]
    [InlineData(2.00, 90, 1.80, 252, 0.31176914536239786)]
    public void NeutralBandThreshold_MatchesPythonReference(
        double shortVolatility,
        int horizon,
        double longVolatility,
        int periodsPerYear,
        double expected)
    {
        double actual = TargetLabeler.NeutralBandThreshold(
            shortVolatility,
            horizon,
            longVolatility,
            periodsPerYear);

        Assert.Equal(expected, actual, 14);
    }
}
