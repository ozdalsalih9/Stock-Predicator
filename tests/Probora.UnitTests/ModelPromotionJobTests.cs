using Probora.Domain.Analysis;
using Probora.Worker.Models;

namespace Probora.UnitTests;

public sealed class ModelPromotionJobTests
{
    [Fact]
    public void SelectShadowCandidate_DoesNotReplaceEligibleModelWithNewerRejectedArtifact()
    {
        ModelVersion eligible = Model("eligible", new DateTimeOffset(2026, 7, 20, 0, 0, 0, TimeSpan.Zero), true);
        ModelVersion rejected = Model("rejected", new DateTimeOffset(2026, 7, 21, 0, 0, 0, TimeSpan.Zero), false);

        Assert.Same(eligible, ModelPromotionJob.SelectShadowCandidate([eligible, rejected]));
    }

    [Fact]
    public void SelectShadowCandidate_UsesNewestEligibleArtifact()
    {
        ModelVersion old = Model("old", new DateTimeOffset(2026, 7, 20, 0, 0, 0, TimeSpan.Zero), true);
        ModelVersion current = Model("current", new DateTimeOffset(2026, 7, 21, 0, 0, 0, TimeSpan.Zero), true);

        Assert.Same(current, ModelPromotionJob.SelectShadowCandidate([old, current]));
    }

    private static ModelVersion Model(string version, DateTimeOffset trainedAt, bool eligible) => new()
    {
        Version = version,
        TrainedAt = trainedAt,
        DirectionEligible = eligible,
        ScenarioEligible = false
    };
}
