using Probora.Application.Analysis;
using Probora.Domain.Analysis;

namespace Probora.UnitTests;

public sealed class ConfidenceGateTests
{
    [Fact]
    public void Evaluate_RejectsStaleData()
    {
        ConfidenceDecision result = ConfidenceGate.Evaluate(new(0.8, 0.1, 0.1, 0.2, 0.2, false, true));

        Assert.Equal(AnalysisStatus.StaleData, result.Status);
    }

    [Fact]
    public void Evaluate_RejectsDirectionReturnConflict()
    {
        ConfidenceDecision result = ConfidenceGate.Evaluate(new(0.75, 0.15, 0.10, -0.05, 0.2, true, true));

        Assert.Equal(AnalysisStatus.InsufficientConfidence, result.Status);
    }

    [Fact]
    public void Evaluate_AllowsClearConsistentSignal()
    {
        ConfidenceDecision result = ConfidenceGate.Evaluate(new(0.75, 0.15, 0.10, 0.12, 0.2, true, true));

        Assert.Equal(AnalysisStatus.Signal, result.Status);
    }
}
