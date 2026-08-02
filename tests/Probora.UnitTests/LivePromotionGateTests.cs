using Probora.Application.Analysis;

namespace Probora.UnitTests;

public sealed class LivePromotionGateTests
{
    [Fact]
    public void Evaluate_RequiresEveryLiveEvidenceGate()
    {
        LivePromotionVerdict result = LivePromotionGate.Evaluate(new LivePromotionEvidence(
            99, 19, 9, 40, 50, 0.049, 0.051, 0.91));

        Assert.Equal("collecting_evidence", result.State);
        Assert.Equal(6, result.Blockers.Count);
    }

    [Fact]
    public void Evaluate_NeverAutoPromotesPassingModel()
    {
        LivePromotionVerdict result = LivePromotionGate.Evaluate(new LivePromotionEvidence(
            120, 25, 30, 40, 50, 0.08, 0.04, 0.82));

        Assert.Equal("eligible_for_manual_review", result.State);
        Assert.Empty(result.Blockers);
    }
}
