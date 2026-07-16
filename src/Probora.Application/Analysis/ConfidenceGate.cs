using Probora.Domain.Analysis;

namespace Probora.Application.Analysis;

public sealed record ConfidenceInput(
    double Up,
    double Neutral,
    double Down,
    double ReturnP50,
    double IntervalWidth,
    bool IsDataFresh,
    bool IsFeatureComplete,
    double MinimumProbability = 0.55,
    double MinimumMargin = 0.15);

public sealed record ConfidenceDecision(AnalysisStatus Status, double Score, string Level);

public static class ConfidenceGate
{
    public static ConfidenceDecision Evaluate(ConfidenceInput input)
    {
        if (!input.IsDataFresh || !input.IsFeatureComplete)
        {
            return new(AnalysisStatus.StaleData, 0, "Unavailable");
        }

        double[] probabilities = [input.Up, input.Neutral, input.Down];
        Array.Sort(probabilities);
        Array.Reverse(probabilities);
        double top = probabilities[0];
        double margin = top - probabilities[1];
        double agreementPenalty = HasDirectionConflict(input) ? 0.25 : 0;
        double widthPenalty = Math.Clamp(input.IntervalWidth / 2, 0, 0.25);
        double score = Math.Clamp((top * 0.65) + (margin * 0.35) - agreementPenalty - widthPenalty, 0, 1);

        AnalysisStatus status = top >= input.MinimumProbability &&
                                margin >= input.MinimumMargin &&
                                !HasDirectionConflict(input)
            ? AnalysisStatus.Signal
            : AnalysisStatus.InsufficientConfidence;

        string level = score switch
        {
            >= 0.70 => "High",
            >= 0.50 => "Medium",
            _ => "Low"
        };

        return new(status, score, level);
    }

    private static bool HasDirectionConflict(ConfidenceInput input)
    {
        bool predictsUp = input.Up > input.Down && input.Up > input.Neutral;
        bool predictsDown = input.Down > input.Up && input.Down > input.Neutral;
        return (predictsUp && input.ReturnP50 < 0) || (predictsDown && input.ReturnP50 > 0);
    }
}
