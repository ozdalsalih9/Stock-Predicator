using Probora.Infrastructure.Queries;

namespace Probora.UnitTests;

public sealed class ShadowCollectorDashboardTests
{
    [Fact]
    public void CountConsecutiveDays_ReturnsOnlyTrailingUnbrokenWindow()
    {
        DateTimeOffset start = new(2026, 7, 1, 0, 0, 0, TimeSpan.Zero);
        DateTimeOffset[] days =
        [
            start,
            start.AddDays(1),
            start.AddDays(4),
            start.AddDays(5),
            start.AddDays(6)
        ];

        Assert.Equal(3, ProboraQueryService.CountConsecutiveDays(days));
    }

    [Fact]
    public void CountConsecutiveDays_IgnoresDuplicates()
    {
        DateTimeOffset start = new(2026, 7, 1, 0, 0, 0, TimeSpan.Zero);

        Assert.Equal(2, ProboraQueryService.CountConsecutiveDays([start, start, start.AddDays(1)]));
    }
}
