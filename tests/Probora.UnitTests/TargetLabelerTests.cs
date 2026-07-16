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
}
